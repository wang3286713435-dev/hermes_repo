from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class DocumentScopeState:
    active_document_id: str | None = None
    active_document_title: str | None = None
    active_document_version_id: str | None = None
    active_project: str | None = None
    active_task: str | None = None
    scope_source: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ResolvedDocument:
    document_id: str
    title: str
    version_id: str | None = None
    source_name: str | None = None


@dataclass(frozen=True)
class FileAliasBinding:
    alias: str
    document_id: str
    title: str
    version_id: str | None = None
    source_name: str | None = None
    alias_scope: str = "session"
    scope_source: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class DocumentScopeDecision:
    filters: dict[str, Any]
    trace: dict[str, Any]
    allowed_document_ids: list[str] = field(default_factory=list)
    cross_document_allowed: bool = False
    suppress_retrieval: bool = False


DocumentTitleResolver = Callable[[list[str], dict[str, Any]], list[ResolvedDocument | dict[str, Any]]]


class SessionDocumentScopeStore:
    """In-process active document scope store keyed by Hermes session id."""

    _QUOTED_TITLE_RE = re.compile(r"[《「『\"]([^》」』\"]+)[》」』\"]")
    _ALIAS_RE = re.compile(r"@([A-Za-z0-9_\-\u4e00-\u9fff]+)")
    _ALIAS_BIND_RE = re.compile(r"(?:设为|命名为|取名为|叫做|叫)\s*@([A-Za-z0-9_\-\u4e00-\u9fff]+)")
    _ALIAS_BIND_TITLE_RE = re.compile(
        r"(?:把|将)\s*(.+?)\s*(?:设为|命名为|取名为|叫做|叫)\s*@([A-Za-z0-9_\-\u4e00-\u9fff]+)"
    )
    _SWITCH_TITLE_RE = re.compile(
        r"(?:围绕|切到|切换到|切回|回到)\s*(.+?)(?:文件|文档|资料)?(?:回答|继续|$|[，。！？\n])"
    )
    _CURRENT_DOC_RE = re.compile(r"(刚才那份文件|刚才的文件|当前文件|当前文档|当前主标书|当前标书|这份文件|这个文件)")
    _COMPARE_RE = re.compile(r"(对比|比较|比对)")
    _DIFFERENCE_RE = re.compile(r"(区别|差异|不同)")
    _PROJECT_RE = re.compile(r"(?:项目|project)\s*[：:]\s*(.+?)(?=\s*(?:任务|task)\s*[：:]|[，。！？\n]|$)", re.IGNORECASE)
    _TASK_RE = re.compile(r"(?:任务|task)\s*[：:]\s*(.+?)(?=[，。！？\n]|$)", re.IGNORECASE)

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._storage_path = Path(storage_path) if storage_path else None
        self._states: dict[str, DocumentScopeState] = {}
        self._aliases: dict[str, dict[str, FileAliasBinding]] = {}
        self._load()

    def get(self, session_id: str) -> DocumentScopeState:
        return self._states.get(session_id or "", DocumentScopeState())

    def resolve(
        self,
        *,
        session_id: str,
        query: str,
        filters: dict[str, Any] | None,
        resolver: DocumentTitleResolver,
    ) -> DocumentScopeDecision:
        session_key = session_id or ""
        incoming_filters = dict(filters or {})
        state = self.get(session_key)
        state = self._state_with_context_hints(
            state=state,
            query=query or "",
            filters=incoming_filters,
            session_key=session_key,
        )

        if incoming_filters.get("document_id"):
            document_id = str(incoming_filters["document_id"])
            return self._decision(
                filters=incoming_filters,
                state=state,
                source="explicit_document_id",
                status="explicit_document_id",
                changed=False,
                allowed_document_ids=[document_id],
                cross_document_allowed=False,
            )

        alias_binding = self._extract_alias_binding(query or "")
        if alias_binding:
            return self._resolve_alias_binding(
                session_key=session_key,
                query=query or "",
                filters=incoming_filters,
                resolver=resolver,
                state=state,
                alias=alias_binding,
            )

        aliases = self._extract_aliases(query or "")
        is_alias_compare = bool(len(aliases) >= 2 and self._is_compare_query(query or ""))
        if is_alias_compare:
            return self._resolve_alias_compare(
                session_key=session_key,
                filters=incoming_filters,
                state=state,
                aliases=aliases[:2],
            )
        if aliases:
            return self._resolve_single_alias_reference(
                session_key=session_key,
                filters=incoming_filters,
                state=state,
                alias=aliases[0],
            )

        titles = self._extract_title_candidates(query or "")
        is_compare = bool(
            len(titles) >= 2
            and self._is_compare_query(query or "")
        )
        if is_compare:
            documents = self._resolve_titles(titles[:2], incoming_filters, resolver)
            if len(documents) >= 2:
                allowed_ids = self._unique([doc.document_id for doc in documents[:2]])
                return self._decision(
                    filters=incoming_filters,
                    state=state,
                    source="query_compare_titles",
                    status="multi_document_resolved",
                    changed=False,
                    allowed_document_ids=allowed_ids,
                    cross_document_allowed=True,
                )
            return self._decision(
                filters=incoming_filters,
                state=state,
                source="query_compare_titles",
                status="scope_resolution_failed",
                changed=False,
                allowed_document_ids=[],
                cross_document_allowed=True,
            )

        if titles:
            documents = self._resolve_titles([titles[0]], incoming_filters, resolver)
            if documents:
                document = documents[0]
                new_state = DocumentScopeState(
                    active_document_id=document.document_id,
                    active_document_title=document.title,
                    active_document_version_id=document.version_id,
                    active_project=state.active_project,
                    active_task=state.active_task,
                    scope_source="query_title",
                    updated_at=self._now(),
                )
                self._states[session_key] = new_state
                self._save()
                scoped_filters = self._scoped_filters(incoming_filters, document.document_id, document.version_id)
                return self._decision(
                    filters=scoped_filters,
                    state=new_state,
                    source="query_title",
                    status="resolved_from_query_title",
                    changed=state.active_document_id != document.document_id,
                    allowed_document_ids=[document.document_id],
                    cross_document_allowed=False,
                )
            return self._decision(
                filters=incoming_filters,
                state=state,
                source="query_title",
                status="scope_resolution_failed",
                changed=False,
                allowed_document_ids=[],
                cross_document_allowed=False,
            )

        if self._CURRENT_DOC_RE.search(query or ""):
            if state.active_document_id:
                scoped_filters = self._scoped_filters(
                    incoming_filters,
                    state.active_document_id,
                    state.active_document_version_id,
                )
                return self._decision(
                    filters=scoped_filters,
                    state=state,
                    source="current_document_reference",
                    status="active_document_reused",
                    changed=False,
                    allowed_document_ids=[state.active_document_id],
                    cross_document_allowed=False,
                )
            return self._decision(
                filters=incoming_filters,
                state=state,
                source="current_document_reference",
                status="scope_resolution_failed",
                changed=False,
                allowed_document_ids=[],
                cross_document_allowed=False,
            )

        if state.active_document_id:
            scoped_filters = self._scoped_filters(
                incoming_filters,
                state.active_document_id,
                state.active_document_version_id,
            )
            return self._decision(
                filters=scoped_filters,
                state=state,
                source="active_document",
                status="active_document_applied",
                changed=False,
                allowed_document_ids=[state.active_document_id],
                cross_document_allowed=False,
            )

        if state.active_project or state.active_task:
            return self._decision(
                filters=incoming_filters,
                state=state,
                source="active_project_task",
                status="project_task_hint_active",
                changed=False,
                allowed_document_ids=[],
                cross_document_allowed=False,
            )

        return self._decision(
            filters=incoming_filters,
            state=state,
            source="none",
            status="unscoped",
            changed=False,
            allowed_document_ids=[],
            cross_document_allowed=False,
        )

    def _extract_title_candidates(self, query: str) -> list[str]:
        quoted = [self._clean_title(match.group(1)) for match in self._QUOTED_TITLE_RE.finditer(query)]
        titles = [title for title in quoted if title]
        if titles:
            return self._unique(titles)

        compare_titles = self._extract_unquoted_compare_titles(query)
        if compare_titles:
            return compare_titles

        switch_match = self._SWITCH_TITLE_RE.search(query)
        if switch_match:
            title = self._clean_title(switch_match.group(1))
            return [title] if title else []
        return []

    def _extract_unquoted_compare_titles(self, query: str) -> list[str]:
        compare_match = re.search(r"(?:对比|比较|比对)\s*(.+)", query)
        difference_match = re.search(r"(.+?)(?:和|与|/|、)(.+?)(?:的)?(?:区别|差异|不同)", query)
        segment = ""
        if compare_match:
            segment = compare_match.group(1)
        elif difference_match:
            segment = f"{difference_match.group(1)}和{difference_match.group(2)}"
        if not segment:
            return []
        segment = re.sub(r"(有什么|有哪些|的)?(?:区别|差异|不同).*$", "", segment).strip()
        parts = re.split(r"(?:和|与|/|、)", segment, maxsplit=1)
        if len(parts) < 2:
            return []
        return self._unique([title for title in (self._clean_title(part) for part in parts[:2]) if title])

    def _resolve_titles(
        self,
        titles: list[str],
        filters: dict[str, Any],
        resolver: DocumentTitleResolver,
    ) -> list[ResolvedDocument]:
        try:
            raw_documents = resolver(titles, filters) or []
        except Exception:
            return []
        documents: list[ResolvedDocument] = []
        for raw in raw_documents:
            document = self._coerce_document(raw)
            if document:
                documents.append(document)
        return documents

    def _coerce_document(self, raw: ResolvedDocument | dict[str, Any]) -> ResolvedDocument | None:
        if isinstance(raw, ResolvedDocument):
            return raw
        if isinstance(raw, dict):
            document_id = raw.get("document_id") or raw.get("id")
            title = raw.get("title") or raw.get("source_name")
            if document_id and title:
                return ResolvedDocument(
                    document_id=str(document_id),
                    title=str(title),
                    version_id=str(raw["version_id"]) if raw.get("version_id") else None,
                    source_name=str(raw["source_name"]) if raw.get("source_name") else None,
                )
        return None

    def _extract_alias_binding(self, query: str) -> str | None:
        match = self._ALIAS_BIND_RE.search(query or "")
        return self._normalize_alias(match.group(1)) if match else None

    def _extract_alias_bind_title_candidate(self, query: str, alias: str) -> str | None:
        match = self._ALIAS_BIND_TITLE_RE.search(query or "")
        if not match:
            return None
        matched_alias = self._normalize_alias(match.group(2))
        if matched_alias != self._normalize_alias(alias):
            return None
        raw_title = match.group(1) or ""
        if "@" in raw_title or self._CURRENT_DOC_RE.search(raw_title):
            return None
        title = self._clean_alias_bind_title(raw_title)
        return title or None

    def _extract_aliases(self, query: str) -> list[str]:
        return self._unique([self._normalize_alias(match.group(1)) for match in self._ALIAS_RE.finditer(query or "")])

    def _normalize_alias(self, alias: str) -> str:
        return (alias or "").strip().lstrip("@")

    def _session_aliases(self, session_key: str) -> dict[str, FileAliasBinding]:
        return self._aliases.setdefault(session_key, {})

    def _get_alias(self, session_key: str, alias: str) -> FileAliasBinding | None:
        return self._session_aliases(session_key).get(self._normalize_alias(alias))

    def _resolve_alias_binding(
        self,
        *,
        session_key: str,
        query: str,
        filters: dict[str, Any],
        resolver: DocumentTitleResolver,
        state: DocumentScopeState,
        alias: str,
    ) -> DocumentScopeDecision:
        normalized_alias = self._normalize_alias(alias)
        titles = self._extract_title_candidates(query)
        if not titles:
            alias_bind_title = self._extract_alias_bind_title_candidate(query, normalized_alias)
            titles = [alias_bind_title] if alias_bind_title else []
        documents = self._resolve_titles([titles[0]], filters, resolver) if titles else []
        document: ResolvedDocument | None = documents[0] if documents else None
        source = "alias_bind_title"

        is_current_document_binding = bool(self._CURRENT_DOC_RE.search(query or ""))
        if document is None and is_current_document_binding:
            if state.active_document_id:
                document = ResolvedDocument(
                    document_id=state.active_document_id,
                    title=state.active_document_title or state.active_document_id,
                    version_id=state.active_document_version_id,
                )
                source = "alias_bind_current_document"
            else:
                return self._decision(
                    filters=filters,
                    state=state,
                    source="file_alias",
                    status="alias_bind_pending_current_retrieval",
                    changed=False,
                    allowed_document_ids=[],
                    cross_document_allowed=False,
                    alias_trace=self._alias_trace(
                        status="alias_bind_pending_current_retrieval",
                        alias=normalized_alias,
                        alias_missing=False,
                        alias_conflict=False,
                        bind_failure_reason=None,
                    ),
                )

        if document is None and titles:
            return self._decision(
                filters=filters,
                state=state,
                source="file_alias",
                status="alias_bind_pending_title_retrieval",
                changed=False,
                allowed_document_ids=[],
                cross_document_allowed=False,
                alias_trace=self._alias_trace(
                    status="alias_bind_pending_title_retrieval",
                    alias=normalized_alias,
                    alias_missing=False,
                    alias_conflict=False,
                    bind_failure_reason=None,
                ),
            )

        existing = self._get_alias(session_key, normalized_alias)
        alias_conflict = bool(existing and document and existing.document_id != document.document_id)
        if document is None:
            return self._decision(
                filters=filters,
                state=state,
                source="file_alias",
                status="alias_bind_failed",
                changed=False,
                allowed_document_ids=[],
                cross_document_allowed=False,
                alias_trace=self._alias_trace(
                    status="alias_bind_failed",
                    alias=normalized_alias,
                    alias_missing=False,
                    alias_conflict=False,
                    bind_failure_reason="no_active_document",
                ),
                suppress_retrieval=True,
            )

        binding = FileAliasBinding(
            alias=normalized_alias,
            document_id=document.document_id,
            title=document.title,
            version_id=document.version_id,
            source_name=document.source_name,
            alias_scope="session",
            scope_source=source,
            updated_at=self._now(),
        )
        self._session_aliases(session_key)[normalized_alias] = binding
        new_state = DocumentScopeState(
            active_document_id=document.document_id,
            active_document_title=document.title,
            active_document_version_id=document.version_id,
            active_project=state.active_project,
            active_task=state.active_task,
            scope_source="file_alias",
            updated_at=self._now(),
        )
        self._states[session_key] = new_state
        self._save()
        scoped_filters = self._scoped_filters(filters, document.document_id, document.version_id)
        return self._decision(
            filters=scoped_filters,
            state=new_state,
            source="file_alias",
            status="alias_bound",
            changed=state.active_document_id != document.document_id,
            allowed_document_ids=[document.document_id],
            cross_document_allowed=False,
            alias_trace=self._alias_trace(
                status="alias_bound",
                alias=normalized_alias,
                binding=binding,
                alias_conflict=alias_conflict,
            ),
        )

    def _resolve_single_alias_reference(
        self,
        *,
        session_key: str,
        filters: dict[str, Any],
        state: DocumentScopeState,
        alias: str,
    ) -> DocumentScopeDecision:
        normalized_alias = self._normalize_alias(alias)
        binding = self._get_alias(session_key, normalized_alias)
        if binding is None:
            return self._decision(
                filters=filters,
                state=state,
                source="file_alias",
                status="alias_missing",
                changed=False,
                allowed_document_ids=[],
                cross_document_allowed=False,
                alias_trace=self._alias_trace(
                    status="alias_missing",
                    alias=normalized_alias,
                    alias_missing=True,
                ),
                suppress_retrieval=True,
            )

        new_state = DocumentScopeState(
            active_document_id=binding.document_id,
            active_document_title=binding.title,
            active_document_version_id=binding.version_id,
            active_project=state.active_project,
            active_task=state.active_task,
            scope_source="file_alias",
            updated_at=self._now(),
        )
        self._states[session_key] = new_state
        self._save()
        scoped_filters = self._scoped_filters(filters, binding.document_id, binding.version_id)
        return self._decision(
            filters=scoped_filters,
            state=new_state,
            source="file_alias",
            status="alias_resolved",
            changed=state.active_document_id != binding.document_id,
            allowed_document_ids=[binding.document_id],
            cross_document_allowed=False,
            alias_trace=self._alias_trace(
                status="alias_resolved",
                alias=normalized_alias,
                binding=binding,
            ),
        )

    def _resolve_alias_compare(
        self,
        *,
        session_key: str,
        filters: dict[str, Any],
        state: DocumentScopeState,
        aliases: list[str],
    ) -> DocumentScopeDecision:
        normalized_aliases = [self._normalize_alias(alias) for alias in aliases]
        bindings = [self._get_alias(session_key, alias) for alias in normalized_aliases]
        missing_aliases = [alias for alias, binding in zip(normalized_aliases, bindings) if binding is None]
        if missing_aliases:
            return self._decision(
                filters=filters,
                state=state,
                source="file_alias_compare",
                status="alias_compare_partial_resolution",
                changed=False,
                allowed_document_ids=[],
                cross_document_allowed=True,
                alias_trace=self._alias_trace(
                    status="alias_compare_partial_resolution",
                    alias=normalized_aliases,
                    alias_missing=True,
                    compare_aliases=normalized_aliases,
                    missing_aliases=missing_aliases,
                ),
                suppress_retrieval=True,
            )

        resolved_bindings = [binding for binding in bindings if binding is not None]
        allowed_ids = self._unique([binding.document_id for binding in resolved_bindings])
        return self._decision(
            filters=filters,
            state=state,
            source="file_alias_compare",
            status="multi_document_alias_resolved",
            changed=False,
            allowed_document_ids=allowed_ids,
            cross_document_allowed=True,
            alias_trace=self._alias_trace(
                status="multi_document_alias_resolved",
                alias=normalized_aliases,
                binding=resolved_bindings[0] if resolved_bindings else None,
                compare_aliases=normalized_aliases,
                compare_bindings=resolved_bindings,
            ),
        )

    def _alias_trace(
        self,
        *,
        status: str,
        alias: str | list[str],
        binding: FileAliasBinding | None = None,
        alias_missing: bool = False,
        alias_conflict: bool = False,
        alias_stale_version: bool = False,
        compare_aliases: list[str] | None = None,
        compare_bindings: list[FileAliasBinding] | None = None,
        missing_aliases: list[str] | None = None,
        bind_failure_reason: str | None = None,
    ) -> dict[str, Any]:
        resolved_document_id = binding.document_id if binding else None
        resolved_title = binding.title if binding else None
        trace: dict[str, Any] = {
            "alias_resolution": {
                "status": status,
                "alias": alias,
                "resolved_document_id": resolved_document_id,
                "resolved_title": resolved_title,
                "alias_scope": "session",
                "alias_conflict": alias_conflict,
                "alias_missing": alias_missing,
                "alias_stale_version": alias_stale_version,
                "bind_failure_reason": bind_failure_reason,
            },
            "alias": alias,
            "resolved_document_id": resolved_document_id,
            "resolved_title": resolved_title,
            "alias_scope": "session",
            "alias_conflict": alias_conflict,
            "alias_missing": alias_missing,
            "alias_stale_version": alias_stale_version,
            "alias_bind_failure_reason": bind_failure_reason,
        }
        if binding:
            trace["alias_version_id"] = binding.version_id
            trace["alias_source_name"] = binding.source_name
            trace["alias_resolution"]["alias_version_id"] = binding.version_id
            trace["alias_resolution"]["alias_source_name"] = binding.source_name
        if compare_aliases is not None:
            trace["compare_aliases"] = compare_aliases
            trace["alias_resolution"]["compare_aliases"] = compare_aliases
        if compare_bindings is not None:
            compare_document_ids = [binding.document_id for binding in compare_bindings]
            compare_version_ids = [binding.version_id for binding in compare_bindings]
            trace["compare_document_ids"] = compare_document_ids
            trace["compare_version_ids"] = compare_version_ids
            trace["alias_resolution"]["compare_document_ids"] = compare_document_ids
            trace["alias_resolution"]["compare_version_ids"] = compare_version_ids
            if compare_aliases is not None:
                compare_versions = [
                    {
                        "alias": alias,
                        "document_id": binding.document_id,
                        "version_id": binding.version_id,
                    }
                    for alias, binding in zip(compare_aliases, compare_bindings)
                ]
                trace["compare_document_versions"] = compare_versions
                trace["alias_resolution"]["compare_document_versions"] = compare_versions
        if missing_aliases is not None:
            trace["missing_aliases"] = missing_aliases
            trace["alias_resolution"]["missing_aliases"] = missing_aliases
        return trace

    def finalize_pending_alias_binding(
        self,
        *,
        session_id: str,
        decision: DocumentScopeDecision,
        documents: list[ResolvedDocument | dict[str, Any]],
    ) -> DocumentScopeDecision:
        pending_status = str(decision.trace.get("scope_resolution_status") or "")
        if pending_status not in {
            "alias_bind_pending_current_retrieval",
            "alias_bind_pending_title_retrieval",
        }:
            return decision

        session_key = session_id or ""
        alias = self._normalize_alias(str(decision.trace.get("alias") or ""))
        resolved_documents = []
        for raw in documents:
            document = self._coerce_document(raw)
            if document:
                resolved_documents.append(document)
        unique_by_id = {document.document_id: document for document in resolved_documents}

        if len(unique_by_id) != 1:
            if pending_status == "alias_bind_pending_title_retrieval":
                reason = "no_title_retrieval_match" if not unique_by_id else "ambiguous_title_retrieval"
            else:
                reason = "no_active_document" if not unique_by_id else "ambiguous_current_retrieval"
            trace = dict(decision.trace)
            alias_trace = self._alias_trace(
                status="alias_bind_failed",
                alias=alias,
                alias_missing=False,
                alias_conflict=False,
                bind_failure_reason=reason,
            )
            trace.update(alias_trace)
            trace["scope_resolution_status"] = "alias_bind_failed"
            return DocumentScopeDecision(
                filters=decision.filters,
                trace=trace,
                allowed_document_ids=[],
                cross_document_allowed=False,
                suppress_retrieval=False,
            )

        document = next(iter(unique_by_id.values()))
        existing = self._get_alias(session_key, alias)
        alias_conflict = bool(existing and existing.document_id != document.document_id)
        binding = FileAliasBinding(
            alias=alias,
            document_id=document.document_id,
            title=document.title,
            version_id=document.version_id,
            source_name=document.source_name,
            alias_scope="session",
            scope_source=(
                "alias_bind_title_retrieval"
                if pending_status == "alias_bind_pending_title_retrieval"
                else "alias_bind_current_retrieval"
            ),
            updated_at=self._now(),
        )
        self._session_aliases(session_key)[alias] = binding
        state = self.get(session_key)
        new_state = DocumentScopeState(
            active_document_id=document.document_id,
            active_document_title=document.title,
            active_document_version_id=document.version_id,
            active_project=state.active_project,
            active_task=state.active_task,
            scope_source="file_alias",
            updated_at=self._now(),
        )
        self._states[session_key] = new_state
        self._save()
        trace = dict(decision.trace)
        alias_trace = self._alias_trace(
            status="alias_bound",
            alias=alias,
            binding=binding,
            alias_conflict=alias_conflict,
        )
        trace.update(alias_trace)
        trace.update(
            {
                "active_document_id": document.document_id,
                "active_document_title": document.title,
                "active_document_version_id": document.version_id,
                "document_scope_source": "file_alias",
                "document_scope_changed": state.active_document_id != document.document_id,
                "scope_resolution_status": "alias_bound",
                "allowed_document_ids": [document.document_id],
            }
        )
        context_scope = dict(trace.get("context_scope") or {})
        context_scope["source"] = "file_alias"
        context_scope["scope_type"] = "document"
        trace["context_scope"] = context_scope
        return DocumentScopeDecision(
            filters={**decision.filters, "document_id": document.document_id},
            trace=trace,
            allowed_document_ids=[document.document_id],
            cross_document_allowed=False,
            suppress_retrieval=False,
        )

    def _state_with_context_hints(
        self,
        *,
        state: DocumentScopeState,
        query: str,
        filters: dict[str, Any],
        session_key: str,
    ) -> DocumentScopeState:
        active_project = self._extract_project_hint(query, filters) or state.active_project
        active_task = self._extract_task_hint(query, filters) or state.active_task
        if active_project == state.active_project and active_task == state.active_task:
            return state
        new_state = DocumentScopeState(
            active_document_id=state.active_document_id,
            active_document_title=state.active_document_title,
            active_document_version_id=state.active_document_version_id,
            active_project=active_project,
            active_task=active_task,
            scope_source=state.scope_source,
            updated_at=self._now(),
        )
        self._states[session_key] = new_state
        self._save()
        return new_state

    def _extract_project_hint(self, query: str, filters: dict[str, Any]) -> str | None:
        for key in ("active_project", "project_id", "project", "project_name"):
            if filters.get(key):
                return str(filters[key])
        match = self._PROJECT_RE.search(query or "")
        return self._clean_context_hint(match.group(1)) if match else None

    def _extract_task_hint(self, query: str, filters: dict[str, Any]) -> str | None:
        for key in ("active_task", "task_id", "task", "task_name"):
            if filters.get(key):
                return str(filters[key])
        match = self._TASK_RE.search(query or "")
        return self._clean_context_hint(match.group(1)) if match else None

    def _decision(
        self,
        *,
        filters: dict[str, Any],
        state: DocumentScopeState,
        source: str,
        status: str,
        changed: bool,
        allowed_document_ids: list[str],
        cross_document_allowed: bool,
        alias_trace: dict[str, Any] | None = None,
        suppress_retrieval: bool = False,
    ) -> DocumentScopeDecision:
        trace = {
            "active_document_id": state.active_document_id,
            "active_document_title": state.active_document_title,
            "active_document_version_id": state.active_document_version_id,
            "active_project": state.active_project,
            "active_task": state.active_task,
            "document_scope_source": source,
            "document_scope_changed": changed,
            "scope_resolution_status": status,
            "cross_document_allowed": cross_document_allowed,
            "suppress_retrieval": suppress_retrieval,
            "allowed_document_ids": allowed_document_ids,
            "compare_document_ids": allowed_document_ids if cross_document_allowed else [],
            "active_document_bypassed": bool(cross_document_allowed and state.active_document_id),
            "active_document_id_bypassed": state.active_document_id if cross_document_allowed else None,
            "history_memory_used": False,
            "history_memory_as_evidence": False,
            "context_scope": {
                "source": source,
                "scope_type": self._scope_type(allowed_document_ids, cross_document_allowed, state),
                "priority": [
                    "explicit_document_id",
                    "alias_document_id",
                    "compare_scope",
                    "active_document",
                    "query_title_inference",
                    "ordinary_retrieval",
                    "active_project_task_hint",
                    "history_memory_context",
                ],
            },
        }
        if alias_trace:
            trace.update(alias_trace)
        return DocumentScopeDecision(
            filters=filters,
            trace=trace,
            allowed_document_ids=allowed_document_ids,
            cross_document_allowed=cross_document_allowed,
            suppress_retrieval=suppress_retrieval,
        )

    def _clean_title(self, title: str) -> str:
        cleaned = re.sub(r"\s+", " ", title or "").strip(" \t\r\n，。！？:：")
        cleaned = re.sub(r"^(请|请说明|说明|帮我|帮我说明|分析|看看)", "", cleaned).strip()
        for suffix in ("文件", "文档", "资料"):
            if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
                cleaned = cleaned[: -len(suffix)].strip()
        return cleaned

    def _clean_alias_bind_title(self, title: str) -> str:
        cleaned = self._clean_title(title)
        cleaned = re.sub(r"^(绑定|先绑定|请绑定)\s*", "", cleaned).strip()
        return cleaned.strip(" \t\r\n，。！？:：")

    def _clean_context_hint(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip(" \t\r\n，。！？:：")

    def _scope_type(
        self,
        allowed_document_ids: list[str],
        cross_document_allowed: bool,
        state: DocumentScopeState,
    ) -> str:
        if cross_document_allowed:
            return "compare"
        if allowed_document_ids:
            return "document"
        if state.active_project or state.active_task:
            return "project_task"
        return "unscoped"

    def _scoped_filters(
        self,
        filters: dict[str, Any],
        document_id: str,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        scoped_filters = {**filters, "document_id": document_id}
        if version_id:
            scoped_filters["version_id"] = version_id
        return scoped_filters

    def _is_compare_query(self, query: str) -> bool:
        return bool(
            self._COMPARE_RE.search(query or "")
            or self._DIFFERENCE_RE.search(query or "")
            or " 与 " in f" {query or ''} "
        )

    def _unique(self, values: list[str]) -> list[str]:
        seen = set()
        result = []
        for value in values:
            if value and value not in seen:
                result.append(value)
                seen.add(value)
        return result

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load(self) -> None:
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except Exception:
            return
        states = raw.get("states") if isinstance(raw, dict) else {}
        aliases = raw.get("aliases") if isinstance(raw, dict) else {}
        if isinstance(states, dict):
            for session_id, state in states.items():
                if isinstance(state, dict):
                    self._states[str(session_id)] = DocumentScopeState(
                        active_document_id=state.get("active_document_id"),
                        active_document_title=state.get("active_document_title"),
                        active_document_version_id=state.get("active_document_version_id"),
                        active_project=state.get("active_project"),
                        active_task=state.get("active_task"),
                        scope_source=state.get("scope_source"),
                        updated_at=state.get("updated_at"),
                    )
        if isinstance(aliases, dict):
            for session_id, bindings in aliases.items():
                if not isinstance(bindings, dict):
                    continue
                session_aliases: dict[str, FileAliasBinding] = {}
                for alias, binding in bindings.items():
                    if not isinstance(binding, dict) or not binding.get("document_id"):
                        continue
                    normalized_alias = self._normalize_alias(str(alias))
                    session_aliases[normalized_alias] = FileAliasBinding(
                        alias=normalized_alias,
                        document_id=str(binding["document_id"]),
                        title=str(binding.get("title") or binding["document_id"]),
                        version_id=str(binding["version_id"]) if binding.get("version_id") else None,
                        source_name=str(binding["source_name"]) if binding.get("source_name") else None,
                        alias_scope=str(binding.get("alias_scope") or "session"),
                        scope_source=str(binding["scope_source"]) if binding.get("scope_source") else None,
                        updated_at=str(binding["updated_at"]) if binding.get("updated_at") else None,
                    )
                if session_aliases:
                    self._aliases[str(session_id)] = session_aliases

    def _save(self) -> None:
        if not self._storage_path:
            return
        payload = {
            "states": {session_id: asdict(state) for session_id, state in self._states.items()},
            "aliases": {
                session_id: {alias: asdict(binding) for alias, binding in bindings.items()}
                for session_id, bindings in self._aliases.items()
            },
        }
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(self._storage_path.parent),
                delete=False,
            ) as temp_file:
                json.dump(payload, temp_file, ensure_ascii=False, indent=2, sort_keys=True)
                temp_name = temp_file.name
            os.replace(temp_name, self._storage_path)
        except Exception:
            try:
                if "temp_name" in locals():
                    Path(temp_name).unlink(missing_ok=True)
            except Exception:
                pass
