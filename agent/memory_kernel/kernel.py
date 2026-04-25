from __future__ import annotations

import logging
from dataclasses import replace

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
        self.document_scope = SessionDocumentScopeStore()

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
        retrieval = RetrievalOutput(
            items=retrieval.items,
            citations=citations,
            backend=retrieval.backend,
            dense_retrieval_status=retrieval.dense_retrieval_status,
            sparse_retrieval_status=retrieval.sparse_retrieval_status,
            retrieval_mode=retrieval.retrieval_mode,
            applied_filters=retrieval.applied_filters,
            ignored_filters=retrieval.ignored_filters,
            trace=self._with_context_governance_trace(trace, retrieval, scope_decision),
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
        returned_document_ids = self._returned_document_ids(filtered_items, filtered_citations)
        trace = dict(retrieval.trace or {})
        trace["returned_document_ids"] = returned_document_ids
        trace["compare_document_ids"] = list(scope_decision.allowed_document_ids or []) if scope_decision.cross_document_allowed else []
        trace["document_scope_filter"] = {
            "allowed_document_ids": list(scope_decision.allowed_document_ids or []),
            "cross_document_allowed": scope_decision.cross_document_allowed,
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
            ):
                if field in retrieval_trace:
                    enriched[field] = retrieval_trace[field]
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
        }
        enriched["contamination_flags"] = self._contamination_flags(
            trace=enriched,
            evidence_document_ids=evidence_document_ids,
            scope_decision=scope_decision,
        )
        return enriched

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
        if allowed_ids and unexpected_ids:
            flags.append("unexpected_document_id")
        scope_filter = trace.get("document_scope_filter") or {}
        if (
            scope_filter.get("items_before", 0) > scope_filter.get("items_after", 0)
            or scope_filter.get("citations_before", 0) > scope_filter.get("citations_after", 0)
        ):
            flags.append("out_of_scope_evidence_filtered")
        if scope_decision.cross_document_allowed and allowed_ids and set(evidence_document_ids) != allowed_ids:
            flags.append("compare_scope_partial_evidence")
        return flags

    def _retrieve_with_document_scope(
        self,
        request: KernelRequest,
        route,
        scope_decision: DocumentScopeDecision,
    ) -> RetrievalOutput:
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
        top_k_allocations = self._allocate_top_k(request.top_k, len(document_ids))
        per_document_outputs: list[tuple[str, RetrievalOutput]] = []

        for document_id, top_k in zip(document_ids, top_k_allocations):
            scoped_filters = {**(request.filters or {}), "document_id": document_id}
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
            per_document_trace.append(
                {
                    "document_id": document_id,
                    "backend": output.backend,
                    "items": len(output.items),
                    "citations": len(output.citations),
                    "dense_retrieval_status": output.dense_retrieval_status,
                    "sparse_retrieval_status": output.sparse_retrieval_status,
                }
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
