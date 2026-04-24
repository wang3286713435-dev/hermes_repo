from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class DocumentScopeState:
    active_document_id: str | None = None
    active_document_title: str | None = None
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
            "document_scope_source": source,
            "document_scope_changed": changed,
            "scope_resolution_status": status,
            "cross_document_allowed": cross_document_allowed,
            "allowed_document_ids": allowed_document_ids,
            "compare_document_ids": allowed_document_ids if cross_document_allowed else [],
            "active_document_bypassed": bool(cross_document_allowed and state.active_document_id),
            "active_document_id_bypassed": state.active_document_id if cross_document_allowed else None,
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
