from __future__ import annotations

import logging
from dataclasses import replace

from hermes_constants import get_hermes_home

from .citation_engine import CitationEngine
from .config import MemoryKernelConfig
from .context_builder import ContextBuilder
from .interfaces import KernelRequest, KernelResult, QueryRoute, RetrievalOutput
from .orchestrator import RetrievalOrchestrator
from .router import QueryRouter
from .session_document_scope import DocumentScopeDecision, ResolvedDocument, SessionDocumentScopeStore

logger = logging.getLogger(__name__)


class MemoryKernel:
    """Hermes-owned enterprise memory kernel.

    Phase 1.5 keeps this small: route, retrieve through the Hermes_memory
    adapter, normalize citations, and build an API-time context block.
    """

    def __init__(self, config: MemoryKernelConfig) -> None:
        self.config = config
        self.router = QueryRouter()
        self.retrieval = RetrievalOrchestrator(config)
        self.citations = CitationEngine()
        self.context_builder = ContextBuilder()
        self.document_scope = SessionDocumentScopeStore(
            get_hermes_home() / "state" / "session_document_scope.json"
        )

    def resolve_document_scope(
        self,
        *,
        session_id: str,
        query: str,
        filters: dict | None,
    ) -> DocumentScopeDecision:
        return self.document_scope.resolve(
            session_id=session_id,
            query=query,
            filters=filters,
            resolver=self.retrieval.resolve_document_titles,
        )

    def start_turn(self, request: KernelRequest) -> KernelResult:
        if not self.config.enabled:
            route = self.router.route(request.query)
            disabled_retrieval = RetrievalOutput(backend="disabled")
            return KernelResult(route=route, retrieval=disabled_retrieval, trace={"enabled": False})

        route = self.router.route(request.query)
        scope_decision = self._scope_decision_from_request(request)
        route = self._route_with_scope_requirement(route, scope_decision, request)
        scoped_request = replace(
            request,
            filters=scope_decision.filters,
            document_scope=scope_decision.trace,
            allowed_document_ids=scope_decision.allowed_document_ids,
            cross_document_allowed=scope_decision.cross_document_allowed,
        )
        retrieval = self._retrieve_with_document_scope(scoped_request, route, scope_decision)
        scope_decision = self.document_scope.finalize_pending_alias_binding(
            session_id=request.session_id,
            decision=scope_decision,
            documents=self._documents_from_retrieval(retrieval),
        )
        retrieval = self._filter_retrieval_by_document_scope(retrieval, scope_decision)
        citations = self.citations.normalize_citations(retrieval.citations, retrieval.items)
        trace = dict(retrieval.trace or {})
        trace = self._with_context_governance_trace(trace, retrieval, scope_decision)
        trace = self._with_facts_context_trace(trace, scoped_request, retrieval, scope_decision)
        retrieval = RetrievalOutput(
            items=retrieval.items,
            citations=citations,
            backend=retrieval.backend,
            dense_retrieval_status=retrieval.dense_retrieval_status,
            sparse_retrieval_status=retrieval.sparse_retrieval_status,
            retrieval_mode=retrieval.retrieval_mode,
            applied_filters=retrieval.applied_filters,
            ignored_filters=retrieval.ignored_filters,
            trace=trace,
        )
        context_block = self.context_builder.build(route, retrieval) if self.config.inject_context else ""
        scope_trace = scope_decision.trace or {}
        return KernelResult(
            route=route,
            retrieval=retrieval,
            context_block=context_block,
            trace={
                "enabled": True,
                "route_type": route.route_type,
                "needs_retrieval": route.needs_retrieval,
                "route_reason": route.reason,
                "retrieval_backend": retrieval.backend,
                "retrieval_mode": retrieval.retrieval_mode,
                "retrieval_items": len(retrieval.items),
                "citations": len(retrieval.citations),
                "dense_retrieval_status": retrieval.dense_retrieval_status,
                "sparse_retrieval_status": retrieval.sparse_retrieval_status,
                "applied_filters": retrieval.applied_filters,
                "ignored_filters": retrieval.ignored_filters,
                "document_scope": scope_trace,
                **scope_trace,
                **(retrieval.trace or {}),
            },
        )

    def finish_turn(self, request: KernelRequest, response: str, result: KernelResult) -> None:
        # TODO Phase 2: write retrieval/citation trace and safe memory writeback.
        return None

    def mark_history_memory_usage(self, result: KernelResult, used: bool) -> None:
        trace = result.trace
        trace["history_memory_used"] = bool(used)
        trace["history_memory_as_evidence"] = False
        context_scope = trace.setdefault("context_scope", {})
        context_scope["history_memory_used"] = bool(used)
        context_scope["history_memory_as_evidence"] = False
        context_scope["history_memory_role"] = "context_hint_only"
        trace["evidence_source_policy"] = {
            "retrieval_evidence_required_for_citations": True,
            "history_memory_can_cite": False,
            "history_memory_can_satisfy_document_scope": False,
        }

    def result_payload(self, result: KernelResult) -> dict:
        if result.trace:
            result.trace["history_memory_as_evidence"] = False
            result.trace.setdefault("context_scope", {})["history_memory_as_evidence"] = False
        return self.context_builder.result_to_payload(result)

    def _scope_decision_from_request(self, request: KernelRequest) -> DocumentScopeDecision:
        if request.document_scope:
            return DocumentScopeDecision(
                filters=dict(request.filters or {}),
                trace=dict(request.document_scope or {}),
                allowed_document_ids=list(request.allowed_document_ids or []),
                cross_document_allowed=bool(request.cross_document_allowed),
                suppress_retrieval=bool((request.document_scope or {}).get("suppress_retrieval", False)),
            )
        return self.resolve_document_scope(
            session_id=request.session_id,
            query=request.query,
            filters=request.filters,
        )

    def _route_with_scope_requirement(
        self,
        route: QueryRoute,
        scope_decision: DocumentScopeDecision,
        request: KernelRequest,
    ) -> QueryRoute:
        if route.needs_retrieval:
            return route
        scope_status = scope_decision.trace.get("scope_resolution_status")
        scope_source = scope_decision.trace.get("document_scope_source")
        requires_context = bool(
            scope_decision.allowed_document_ids
            or scope_decision.cross_document_allowed
            or scope_decision.suppress_retrieval
            or scope_decision.trace.get("alias_resolution")
            or scope_decision.trace.get("facts_context_requested")
            or self._facts_context_requested(request, scope_decision)
            or (
                scope_source not in {None, "none", "active_project_task"}
                and scope_status not in {None, "project_task_hint_active", "unscoped"}
            )
        )
        if not requires_context:
            return route
        return replace(
            route,
            route_type="enterprise_retrieval",
            needs_retrieval=True,
            reason=f"{route.reason}; document scope requires enterprise retrieval context",
            mode=request.retrieval_mode,
        )

    def _filter_retrieval_by_document_scope(
        self,
        retrieval: RetrievalOutput,
        scope_decision: DocumentScopeDecision,
    ) -> RetrievalOutput:
        allowed_ids = set(scope_decision.allowed_document_ids or [])
        if not allowed_ids:
            return retrieval

        filtered_items = [item for item in retrieval.items if item.document_id in allowed_ids]
        filtered_citations = [citation for citation in retrieval.citations if citation.document_id in allowed_ids]
        original_document_ids = self._returned_document_ids(retrieval.items, retrieval.citations)
        returned_document_ids = self._returned_document_ids(filtered_items, filtered_citations)
        filtered_out_document_ids = [document_id for document_id in original_document_ids if document_id not in allowed_ids]
        trace = dict(retrieval.trace or {})
        trace["returned_document_ids"] = returned_document_ids
        trace["compare_document_ids"] = list(scope_decision.allowed_document_ids or []) if scope_decision.cross_document_allowed else []
        trace["document_scope_filter"] = {
            "allowed_document_ids": list(scope_decision.allowed_document_ids or []),
            "cross_document_allowed": scope_decision.cross_document_allowed,
            "input_document_ids": original_document_ids,
            "filtered_out_document_ids": filtered_out_document_ids,
            "items_before": len(retrieval.items),
            "items_after": len(filtered_items),
            "citations_before": len(retrieval.citations),
            "citations_after": len(filtered_citations),
        }
        return RetrievalOutput(
            items=filtered_items,
            citations=filtered_citations,
            backend=retrieval.backend,
            dense_retrieval_status=retrieval.dense_retrieval_status,
            sparse_retrieval_status=retrieval.sparse_retrieval_status,
            retrieval_mode=retrieval.retrieval_mode,
            applied_filters=retrieval.applied_filters,
            ignored_filters=retrieval.ignored_filters,
            trace=trace,
        )

    def _with_context_governance_trace(
        self,
        trace: dict,
        retrieval: RetrievalOutput,
        scope_decision: DocumentScopeDecision,
    ) -> dict:
        enriched = dict(scope_decision.trace or {})
        enriched.update(trace or {})
        retrieval_trace = enriched.get("retrieval_trace")
        if isinstance(retrieval_trace, dict):
            for field in (
                "metadata_snapshot",
                "metadata_snapshot_used",
                "metadata_fields_matched",
                "metadata_source_chunk_ids",
                "evidence_required",
                "snapshot_as_answer",
                "meeting_transcript_used",
                "meeting_fields_matched",
                "speaker_detected",
                "timestamp_detected",
                "action_items_detected",
                "decisions_detected",
                "risks_detected",
                "meeting_source_chunk_ids",
                "transcript_as_fact",
                "version_scope",
                "version_policy",
            ):
                if field in retrieval_trace:
                    enriched[field] = retrieval_trace[field]
        self._merge_alias_version_trace(enriched)
        if enriched.get("metadata_snapshot_used") or enriched.get("metadata_snapshot"):
            enriched["evidence_required"] = True
            enriched["snapshot_as_answer"] = False
        if enriched.get("meeting_transcript_used") or "transcript_as_fact" in enriched:
            enriched["evidence_required"] = True
            enriched["transcript_as_fact"] = False
        evidence_document_ids = self._returned_document_ids(retrieval.items, retrieval.citations)
        enriched["retrieval_evidence_document_ids"] = evidence_document_ids
        enriched["history_memory_used"] = bool(scope_decision.trace.get("history_memory_used", False))
        enriched["history_memory_as_evidence"] = False
        context_scope = dict(enriched.get("context_scope") or {})
        context_scope["retrieval_evidence_present"] = bool(evidence_document_ids)
        context_scope["history_memory_used"] = enriched["history_memory_used"]
        context_scope["history_memory_as_evidence"] = False
        context_scope["history_memory_role"] = "context_hint_only"
        enriched["context_scope"] = context_scope
        enriched["evidence_source_policy"] = {
            "retrieval_evidence_required_for_citations": True,
            "history_memory_can_cite": False,
            "history_memory_can_satisfy_document_scope": False,
            "confirmed_facts_can_cite": False,
            "confirmed_facts_can_satisfy_retrieval": False,
        }
        enriched["contamination_flags"] = self._contamination_flags(
            trace=enriched,
            evidence_document_ids=evidence_document_ids,
            scope_decision=scope_decision,
        )
        return enriched

    def _with_facts_context_trace(
        self,
        trace: dict,
        request: KernelRequest,
        retrieval: RetrievalOutput,
        scope_decision: DocumentScopeDecision,
    ) -> dict:
        enriched = dict(trace or {})
        enriched["facts_as_answer"] = False
        enriched.setdefault("facts_context_used", False)
        enriched.setdefault("facts_context_fact_ids", [])
        enriched.setdefault("stale_fact_source_count", 0)

        context_scope = dict(enriched.get("context_scope") or {})
        context_scope["facts_as_answer"] = False
        context_scope.setdefault("facts_context_used", False)
        enriched["context_scope"] = context_scope

        if not self._facts_context_requested(request, scope_decision):
            return enriched

        evidence_document_ids = list(enriched.get("retrieval_evidence_document_ids") or [])
        stale_diagnostic = self._stale_fact_check_requested(request)
        document_ids = self._facts_context_document_ids(request, scope_decision, evidence_document_ids)
        if not evidence_document_ids:
            if stale_diagnostic:
                stale_facts = self.retrieval.search_stale_confirmed_facts(
                    requester_id=request.user_id or (request.filters or {}).get("requester_id") or "local_dev",
                    tenant_id=(request.filters or {}).get("tenant_id"),
                    role=(request.filters or {}).get("role"),
                    limit=6,
                )
                if stale_facts:
                    return self._apply_confirmed_facts_context(
                        enriched,
                        context_scope,
                        request,
                        stale_facts,
                        diagnostic_only=True,
                    )
            if not (stale_diagnostic and document_ids):
                enriched["facts_context_suppressed_reason"] = "no_current_retrieval_evidence"
                context_scope["facts_context_suppressed_reason"] = "no_current_retrieval_evidence"
                flags = list(enriched.get("contamination_flags") or [])
                if "no_current_retrieval_evidence" not in flags:
                    flags.append("no_current_retrieval_evidence")
                enriched["contamination_flags"] = flags
                return enriched
            enriched["facts_context_diagnostic_only"] = True

        if not document_ids:
            enriched["facts_context_suppressed_reason"] = "no_document_scope"
            context_scope["facts_context_suppressed_reason"] = "no_document_scope"
            return enriched

        if stale_diagnostic:
            stale_facts = self.retrieval.search_stale_confirmed_facts(
                requester_id=request.user_id or (request.filters or {}).get("requester_id") or "local_dev",
                tenant_id=(request.filters or {}).get("tenant_id"),
                role=(request.filters or {}).get("role"),
                limit=6,
            )
            if stale_facts:
                return self._apply_confirmed_facts_context(
                    enriched,
                    context_scope,
                    request,
                    stale_facts,
                    diagnostic_only=not bool(evidence_document_ids),
                )

        facts = self.retrieval.search_confirmed_facts(
            document_ids=document_ids,
            requester_id=request.user_id or (request.filters or {}).get("requester_id") or "local_dev",
            tenant_id=(request.filters or {}).get("tenant_id"),
            role=(request.filters or {}).get("role"),
            limit=6,
        )
        allowed_evidence_ids = set(evidence_document_ids or document_ids)
        confirmed_facts = [
            fact
            for fact in facts
            if fact
            and fact.get("verification_status") == "confirmed"
            and fact.get("source_document_id") in allowed_evidence_ids
            and fact.get("source_chunk_id")
            and fact.get("source_version_id")
        ]
        if not confirmed_facts:
            enriched["facts_context_suppressed_reason"] = "no_confirmed_facts"
            context_scope["facts_context_suppressed_reason"] = "no_confirmed_facts"
            return enriched

        return self._apply_confirmed_facts_context(
            enriched,
            context_scope,
            request,
            confirmed_facts,
            diagnostic_only=bool(enriched.get("facts_context_diagnostic_only")),
        )

    def _apply_confirmed_facts_context(
        self,
        enriched: dict,
        context_scope: dict,
        request: KernelRequest,
        confirmed_facts: list[dict],
        *,
        diagnostic_only: bool = False,
    ) -> dict:
        fact_ids = [str(fact["fact_id"]) for fact in confirmed_facts if fact.get("fact_id")]
        stale_count = sum(1 for fact in confirmed_facts if fact.get("stale_source_version"))
        enriched["facts_context_used"] = True
        enriched["facts_context"] = confirmed_facts
        enriched["facts_context_fact_ids"] = fact_ids
        enriched["stale_fact_source_count"] = stale_count
        enriched["facts_as_answer"] = False
        if diagnostic_only:
            enriched["facts_context_diagnostic_only"] = True
        enriched["facts_context_audit"] = {
            "session_id": request.session_id,
            "requester_id": request.user_id or "local_dev",
            "query": request.query,
            "facts_context_fact_ids": fact_ids,
        }
        context_scope["facts_context_used"] = True
        context_scope["facts_context_fact_ids"] = fact_ids
        context_scope["stale_fact_source_count"] = stale_count
        context_scope["facts_as_answer"] = False
        if diagnostic_only or enriched.get("facts_context_diagnostic_only"):
            context_scope["facts_context_diagnostic_only"] = True
        enriched["context_scope"] = context_scope
        policy = dict(enriched.get("evidence_source_policy") or {})
        policy["confirmed_facts_can_cite"] = False
        policy["confirmed_facts_can_satisfy_retrieval"] = False
        policy["facts_as_answer"] = False
        enriched["evidence_source_policy"] = policy
        return enriched

    def _facts_context_requested(self, request: KernelRequest, scope_decision: DocumentScopeDecision) -> bool:
        scope = request.document_scope or scope_decision.trace or {}
        if scope.get("facts_context_requested") or scope.get("use_facts_context"):
            return True
        query = (request.query or "").lower()
        return any(
            hint in query
            for hint in (
                "confirmed fact",
                "confirmed facts",
                "fact context",
                "facts context",
                "已确认事实",
                "确认事实",
                "事实卡片",
                "事实上下文",
                "事实来源",
                "过期事实",
                "历史事实",
                "stale fact",
                "stale source",
                "fact source",
            )
        )

    def _stale_fact_check_requested(self, request: KernelRequest) -> bool:
        query = (request.query or "").lower()
        return any(
            hint in query
            for hint in (
                "stale fact",
                "stale source",
                "fact source",
                "过期事实",
                "历史事实",
                "事实来源",
                "旧版本事实",
            )
        )

    def _fact_answer_policy_query(self, request: KernelRequest) -> bool:
        query = (request.query or "").lower()
        return (
            ("facts" in query and ("answer" in query or "final answer" in query))
            or ("事实" in query and ("最终答案" in query or "直接作为" in query or "直接回答" in query or "答案来源" in query))
        )

    def _has_explicit_document_scope(self, request: KernelRequest, scope_decision: DocumentScopeDecision) -> bool:
        filters = request.filters or {}
        trace = scope_decision.trace or {}
        return bool(
            scope_decision.allowed_document_ids
            or filters.get("document_id")
            or trace.get("active_document_id")
            or trace.get("alias_resolution")
        )

    def _facts_context_document_ids(
        self,
        request: KernelRequest,
        scope_decision: DocumentScopeDecision,
        evidence_document_ids: list[str],
    ) -> list[str]:
        candidates: list[str] = []
        candidates.extend(scope_decision.allowed_document_ids or [])
        if (request.filters or {}).get("document_id"):
            candidates.append(str((request.filters or {})["document_id"]))
        trace = scope_decision.trace or {}
        if trace.get("active_document_id"):
            candidates.append(str(trace["active_document_id"]))
        if isinstance(trace.get("compare_document_ids"), list):
            candidates.extend(str(document_id) for document_id in trace["compare_document_ids"] if document_id)
        candidates.extend(evidence_document_ids)
        return list(dict.fromkeys(document_id for document_id in candidates if document_id))

    def _contamination_flags(
        self,
        *,
        trace: dict,
        evidence_document_ids: list[str],
        scope_decision: DocumentScopeDecision,
    ) -> list[str]:
        flags: list[str] = []
        allowed_ids = set(scope_decision.allowed_document_ids or [])
        if allowed_ids and not evidence_document_ids:
            flags.append("no_current_retrieval_evidence")
        unexpected_ids = [document_id for document_id in evidence_document_ids if document_id not in allowed_ids]
        trace["third_document_mixed"] = bool(unexpected_ids)
        trace["third_document_mixed_document_ids"] = unexpected_ids
        if scope_decision.cross_document_allowed:
            trace["compare_scope_document_ids"] = list(scope_decision.allowed_document_ids or [])
            trace["compare_evidence_document_ids_within_scope"] = bool(allowed_ids) and not unexpected_ids
        if allowed_ids and unexpected_ids:
            flags.append("unexpected_document_id")
        scope_filter = trace.get("document_scope_filter") or {}
        if scope_filter.get("filtered_out_document_ids"):
            trace["out_of_scope_document_ids_filtered"] = list(scope_filter.get("filtered_out_document_ids") or [])
        if scope_decision.cross_document_allowed and allowed_ids and set(evidence_document_ids) != allowed_ids:
            flags.append("compare_scope_partial_evidence")
        return flags

    def _merge_alias_version_trace(self, trace: dict) -> None:
        alias_resolution = trace.get("alias_resolution")
        if not isinstance(alias_resolution, dict):
            return

        version_scope = trace.get("version_scope")
        if isinstance(version_scope, dict) and "stale_version" in version_scope:
            stale = bool(version_scope.get("stale_version"))
            trace["alias_stale_version"] = stale
            alias_resolution["alias_stale_version"] = stale
            for field in ("latest_version_id", "superseded_by_version_id", "version_id", "version_policy"):
                if version_scope.get(field) is not None:
                    trace[field] = version_scope.get(field)
                    alias_resolution[field] = version_scope.get(field)

        multi_document = trace.get("multi_document_retrieval")
        if not isinstance(multi_document, dict):
            return
        per_document = multi_document.get("per_document")
        if not isinstance(per_document, list):
            return
        stale_entries = [
            {
                "alias": entry.get("alias"),
                "document_id": entry.get("document_id"),
                "alias_version_id": entry.get("alias_version_id"),
                "latest_version_id": entry.get("latest_version_id"),
                "superseded_by_version_id": entry.get("superseded_by_version_id"),
            }
            for entry in per_document
            if isinstance(entry, dict) and entry.get("alias_stale_version")
        ]
        if stale_entries:
            trace["alias_stale_version"] = True
            trace["compare_alias_stale_versions"] = stale_entries
            alias_resolution["alias_stale_version"] = True
            alias_resolution["compare_alias_stale_versions"] = stale_entries

    def _retrieve_with_document_scope(
        self,
        request: KernelRequest,
        route,
        scope_decision: DocumentScopeDecision,
    ) -> RetrievalOutput:
        if (
            self._fact_answer_policy_query(request)
            or self._stale_fact_check_requested(request)
        ) and not self._has_explicit_document_scope(request, scope_decision):
            return RetrievalOutput(
                backend="facts_policy_suppressed",
                trace={
                    "scope_retrieval_suppressed": True,
                    "facts_context_requested": True,
                    "facts_answer_policy_query": self._fact_answer_policy_query(request),
                    "facts_stale_policy_query": self._stale_fact_check_requested(request),
                    "facts_context_suppressed_reason": "no_current_retrieval_evidence",
                    "no_current_retrieval_evidence": True,
                },
            )
        if scope_decision.suppress_retrieval:
            return RetrievalOutput(
                backend="document_scope_suppressed",
                trace={
                    "scope_retrieval_suppressed": True,
                    "scope_resolution_status": scope_decision.trace.get("scope_resolution_status"),
                },
            )
        if scope_decision.cross_document_allowed and len(scope_decision.allowed_document_ids or []) >= 2:
            return self._retrieve_multi_document_scope(request, route, scope_decision)
        return self.retrieval.retrieve(request, route)

    def _retrieve_multi_document_scope(
        self,
        request: KernelRequest,
        route,
        scope_decision: DocumentScopeDecision,
    ) -> RetrievalOutput:
        document_ids = list(scope_decision.allowed_document_ids or [])
        version_by_document, alias_by_document = self._compare_version_scope(scope_decision)
        top_k_allocations = self._allocate_top_k(request.top_k, len(document_ids))
        per_document_outputs: list[tuple[str, RetrievalOutput]] = []

        for document_id, top_k in zip(document_ids, top_k_allocations):
            scoped_filters = {**(request.filters or {}), "document_id": document_id}
            if version_by_document.get(document_id):
                scoped_filters["version_id"] = version_by_document[document_id]
            per_document_request = replace(
                request,
                top_k=top_k,
                filters=scoped_filters,
                allowed_document_ids=[document_id],
                cross_document_allowed=False,
            )
            per_document_outputs.append((document_id, self.retrieval.retrieve(per_document_request, route)))

        items = []
        citations = []
        per_document_trace = []
        applied_filters = {**(request.filters or {}), "document_ids": document_ids}
        ignored_filters = {}
        for document_id, output in per_document_outputs:
            items.extend(output.items)
            citations.extend(output.citations)
            ignored_filters.update(output.ignored_filters or {})
            version_scope = self._version_scope_from_output(output)
            alias = alias_by_document.get(document_id, {}).get("alias")
            alias_version_id = alias_by_document.get(document_id, {}).get("version_id")
            entry = {
                "document_id": document_id,
                "backend": output.backend,
                "items": len(output.items),
                "citations": len(output.citations),
                "dense_retrieval_status": output.dense_retrieval_status,
                "sparse_retrieval_status": output.sparse_retrieval_status,
            }
            if alias:
                entry["alias"] = alias
            if alias_version_id:
                entry["alias_version_id"] = alias_version_id
            if version_scope:
                entry["version_scope"] = version_scope
                entry["alias_stale_version"] = bool(version_scope.get("stale_version"))
                if version_scope.get("latest_version_id"):
                    entry["latest_version_id"] = version_scope.get("latest_version_id")
                if version_scope.get("superseded_by_version_id"):
                    entry["superseded_by_version_id"] = version_scope.get("superseded_by_version_id")
            per_document_trace.append(
                entry
            )

        returned_document_ids = self._returned_document_ids(items, citations)
        trace = {
            "multi_document_retrieval": {
                "requested_document_ids": document_ids,
                "returned_document_ids": returned_document_ids,
                "per_document": per_document_trace,
            },
            "compare_document_ids": document_ids,
            "returned_document_ids": returned_document_ids,
        }
        return RetrievalOutput(
            items=items,
            citations=citations,
            backend="multi_document_scoped",
            dense_retrieval_status=self._aggregate_status(
                [output.dense_retrieval_status for _, output in per_document_outputs]
            ),
            sparse_retrieval_status=self._aggregate_status(
                [output.sparse_retrieval_status for _, output in per_document_outputs]
            ),
            retrieval_mode=request.retrieval_mode,
            applied_filters=applied_filters,
            ignored_filters=ignored_filters,
            trace=trace,
        )

    def _compare_version_scope(
        self,
        scope_decision: DocumentScopeDecision,
    ) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
        version_by_document: dict[str, str] = {}
        alias_by_document: dict[str, dict[str, str]] = {}
        compare_versions = scope_decision.trace.get("compare_document_versions") or []
        if not isinstance(compare_versions, list):
            return version_by_document, alias_by_document
        for entry in compare_versions:
            if not isinstance(entry, dict):
                continue
            document_id = entry.get("document_id")
            if not document_id:
                continue
            document_id = str(document_id)
            alias_by_document[document_id] = {
                key: str(value)
                for key, value in {
                    "alias": entry.get("alias"),
                    "version_id": entry.get("version_id"),
                }.items()
                if value
            }
            if entry.get("version_id"):
                version_by_document[document_id] = str(entry["version_id"])
        return version_by_document, alias_by_document

    def _version_scope_from_output(self, output: RetrievalOutput) -> dict:
        trace = output.trace or {}
        version_scope = trace.get("version_scope")
        if isinstance(version_scope, dict):
            return version_scope
        retrieval_trace = trace.get("retrieval_trace")
        if isinstance(retrieval_trace, dict) and isinstance(retrieval_trace.get("version_scope"), dict):
            return retrieval_trace["version_scope"]
        return {}

    def _allocate_top_k(self, top_k: int, bucket_count: int) -> list[int]:
        if bucket_count <= 0:
            return []
        total = max(1, int(top_k or bucket_count))
        base = max(1, total // bucket_count)
        allocations = [base for _ in range(bucket_count)]
        for index in range(total - (base * bucket_count)):
            allocations[index % bucket_count] += 1
        return allocations

    def _aggregate_status(self, statuses: list[str]) -> str:
        cleaned = [status for status in statuses if status]
        if not cleaned:
            return "not_executed"
        unique = list(dict.fromkeys(cleaned))
        return unique[0] if len(unique) == 1 else "mixed"

    def _returned_document_ids(self, items, citations) -> list[str]:
        ids = [item.document_id for item in items if item.document_id]
        ids.extend(citation.document_id for citation in citations if citation.document_id)
        return list(dict.fromkeys(ids))

    def _documents_from_retrieval(self, retrieval: RetrievalOutput) -> list[ResolvedDocument]:
        by_id: dict[str, ResolvedDocument] = {}
        for item in retrieval.items or []:
            if item.document_id and item.document_id not in by_id:
                by_id[item.document_id] = ResolvedDocument(
                    document_id=item.document_id,
                    title=item.source_name or item.document_id,
                    version_id=item.version_id or None,
                    source_name=item.source_name,
                )
        for citation in retrieval.citations or []:
            if citation.document_id and citation.document_id not in by_id:
                by_id[citation.document_id] = ResolvedDocument(
                    document_id=citation.document_id,
                    title=citation.source_name or citation.document_id,
                    version_id=citation.version_id or None,
                    source_name=citation.source_name,
                )
        return list(by_id.values())
