from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class DocumentScopeState:
    active_document_id: str | None = None
    active_document_title: str | None = None
    active_project: str | None = None
    active_task: str | None = None
    scope_source: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ResolvedDocument:
    document_id: str
    title: str


@dataclass(frozen=True)
class DocumentScopeDecision:
    filters: dict[str, Any]
    trace: dict[str, Any]
    allowed_document_ids: list[str] = field(default_factory=list)
    cross_document_allowed: bool = False


DocumentTitleResolver = Callable[[list[str], dict[str, Any]], list[ResolvedDocument | dict[str, Any]]]


class SessionDocumentScopeStore:
    """In-process active document scope store keyed by Hermes session id."""

    _QUOTED_TITLE_RE = re.compile(r"[《「『\"]([^》」』\"]+)[》」』\"]")
    _SWITCH_TITLE_RE = re.compile(
        r"(?:围绕|切到|切换到|切回|回到)\s*(.+?)(?:文件|文档|资料)?(?:回答|继续|$|[，。！？\n])"
    )
    _CURRENT_DOC_RE = re.compile(r"(刚才那份文件|刚才的文件|当前文件|当前文档|这份文件|这个文件)")
    _COMPARE_RE = re.compile(r"(对比|比较|比对)")
    _DIFFERENCE_RE = re.compile(r"(区别|差异|不同)")
    _PROJECT_RE = re.compile(r"(?:项目|project)\s*[：:]\s*(.+?)(?=\s*(?:任务|task)\s*[：:]|[，。！？\n]|$)", re.IGNORECASE)
    _TASK_RE = re.compile(r"(?:任务|task)\s*[：:]\s*(.+?)(?=[，。！？\n]|$)", re.IGNORECASE)

    def __init__(self) -> None:
        self._states: dict[str, DocumentScopeState] = {}

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

        titles = self._extract_title_candidates(query or "")
        is_compare = bool(
            len(titles) >= 2
            and (
                self._COMPARE_RE.search(query or "")
                or self._DIFFERENCE_RE.search(query or "")
                or " 与 " in f" {query or ''} "
            )
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
                    active_project=state.active_project,
                    active_task=state.active_task,
                    scope_source="query_title",
                    updated_at=self._now(),
                )
                self._states[session_key] = new_state
                scoped_filters = {**incoming_filters, "document_id": document.document_id}
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
                scoped_filters = {**incoming_filters, "document_id": state.active_document_id}
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
            scoped_filters = {**incoming_filters, "document_id": state.active_document_id}
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
                return ResolvedDocument(document_id=str(document_id), title=str(title))
        return None

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
            active_project=active_project,
            active_task=active_task,
            scope_source=state.scope_source,
            updated_at=self._now(),
        )
        self._states[session_key] = new_state
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
    ) -> DocumentScopeDecision:
        trace = {
            "active_document_id": state.active_document_id,
            "active_document_title": state.active_document_title,
            "active_project": state.active_project,
            "active_task": state.active_task,
            "document_scope_source": source,
            "document_scope_changed": changed,
            "scope_resolution_status": status,
            "cross_document_allowed": cross_document_allowed,
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
                    "compare_scope",
                    "active_document",
                    "active_project_task_hint",
                    "query_title_inference",
                    "ordinary_retrieval",
                    "history_memory_context",
                ],
            },
        }
        return DocumentScopeDecision(
            filters=filters,
            trace=trace,
            allowed_document_ids=allowed_document_ids,
            cross_document_allowed=cross_document_allowed,
        )

    def _clean_title(self, title: str) -> str:
        cleaned = re.sub(r"\s+", " ", title or "").strip(" \t\r\n，。！？:：")
        cleaned = re.sub(r"^(请|请说明|说明|帮我|帮我说明|分析|看看)", "", cleaned).strip()
        for suffix in ("文件", "文档", "资料"):
            if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
                cleaned = cleaned[: -len(suffix)].strip()
        return cleaned

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
