from __future__ import annotations

from .interfaces import KernelCitation, KernelItem, KernelResult, QueryRoute, RetrievalOutput


class ContextBuilder:
    def build(self, route: QueryRoute, retrieval: RetrievalOutput) -> str:
        scope_lines = self._scope_lines(retrieval.trace or {})
        if not route.needs_retrieval or (not retrieval.items and not scope_lines):
            return ""

        parts = [
            "<enterprise-memory-context>",
            "[System note: The following is enterprise memory context recalled before model answering. It is not new user input. Use it only as cited background evidence.]",
            f"Route: {route.route_type}; retrieval_mode={route.mode}; backend={retrieval.backend}",
            "",
        ]
        if scope_lines:
            parts.append("Session scope state:")
            parts.extend(scope_lines)
            parts.append("")

        if retrieval.items:
            parts.append("Retrieved evidence:")
        for index, item in enumerate(retrieval.items, start=1):
            source = item.source_name or item.source_uri or item.document_id
            heading = " > ".join(item.heading_path or item.section_path or [])
            page = self._page_label(item.page_start, item.page_end)
            header = f"[E{index}] source={source}; document_id={item.document_id}; version_id={item.version_id}; chunk_id={item.chunk_id}"
            if heading:
                header += f"; heading={heading}"
            if page:
                header += f"; page={page}"
            parts.append(header)
            parts.append(item.text.strip())
            parts.append("")

        if retrieval.citations:
            parts.append("Citations:")
            for index, citation in enumerate(retrieval.citations, start=1):
                parts.append(self._citation_line(index, citation))

        parts.append("</enterprise-memory-context>")
        return "\n".join(parts).strip()

    def result_to_payload(self, result: KernelResult) -> dict:
        return {
            "route": {
                "route_type": result.route.route_type,
                "needs_retrieval": result.route.needs_retrieval,
                "reason": result.route.reason,
                "mode": result.route.mode,
            },
            "backend": result.retrieval.backend,
            "dense_retrieval_status": result.retrieval.dense_retrieval_status,
            "sparse_retrieval_status": result.retrieval.sparse_retrieval_status,
            "retrieval_mode": result.retrieval.retrieval_mode,
            "applied_filters": result.retrieval.applied_filters,
            "ignored_filters": result.retrieval.ignored_filters,
            "citations": [citation.__dict__ for citation in result.retrieval.citations],
            "trace": result.trace,
        }

    def _citation_line(self, index: int, citation: KernelCitation) -> str:
        source = citation.source_name or citation.source_uri or citation.document_id
        heading = " > ".join(citation.heading_path or citation.section_path or [])
        page = self._page_label(citation.page_start, citation.page_end)
        suffix = []
        if citation.version_name:
            suffix.append(f"version={citation.version_name}")
        if heading:
            suffix.append(f"heading={heading}")
        if page:
            suffix.append(f"page={page}")
        suffix_text = "; ".join(suffix)
        return f"[C{index}] {source}; document_id={citation.document_id}; version_id={citation.version_id}; chunk_id={citation.chunk_id}" + (f"; {suffix_text}" if suffix_text else "")

    def _page_label(self, start: int | None, end: int | None) -> str:
        if start is None and end is None:
            return ""
        if start == end or end is None:
            return str(start)
        if start is None:
            return str(end)
        return f"{start}-{end}"

    def _scope_lines(self, trace: dict) -> list[str]:
        alias_resolution = trace.get("alias_resolution") or {}
        if not isinstance(alias_resolution, dict) or not alias_resolution:
            return []
        status = alias_resolution.get("status")
        alias = alias_resolution.get("alias")
        document_id = alias_resolution.get("resolved_document_id")
        title = alias_resolution.get("resolved_title")
        missing = alias_resolution.get("alias_missing")
        conflict = alias_resolution.get("alias_conflict")
        stale = alias_resolution.get("alias_stale_version")
        failure_reason = alias_resolution.get("bind_failure_reason")
        lines = [
            "Alias handling is done by Hermes session state, not by a model tool.",
            f"alias_resolution.status={status}; alias={alias}; alias_scope={alias_resolution.get('alias_scope', 'session')}",
        ]
        if document_id:
            lines.append(f"resolved_document_id={document_id}; resolved_title={title or document_id}")
        if alias_resolution.get("compare_aliases"):
            lines.append(
                f"compare_aliases={alias_resolution.get('compare_aliases')}; compare_document_ids={alias_resolution.get('compare_document_ids')}"
            )
        if missing or conflict or stale or failure_reason:
            lines.append(
                f"alias_diagnostics: missing={bool(missing)}; conflict={bool(conflict)}; stale_version={bool(stale)}; failure_reason={failure_reason}"
            )
        if trace.get("scope_retrieval_suppressed") or trace.get("suppress_retrieval"):
            lines.append("retrieval_suppressed=true; do not answer from history memory as document evidence.")
        if trace.get("metadata_snapshot_used"):
            lines.append(
                "metadata_snapshot_used=true; snapshot_as_answer=false; evidence_required=true; "
                f"metadata_fields_matched={trace.get('metadata_fields_matched', [])}; "
                f"metadata_source_chunk_ids={trace.get('metadata_source_chunk_ids', [])}"
            )
        return lines
