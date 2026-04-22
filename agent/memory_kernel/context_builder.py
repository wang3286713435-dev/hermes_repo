from __future__ import annotations

from .interfaces import KernelCitation, KernelItem, KernelResult, QueryRoute, RetrievalOutput


class ContextBuilder:
    def build(self, route: QueryRoute, retrieval: RetrievalOutput) -> str:
        if not route.needs_retrieval or not retrieval.items:
            return ""

        parts = [
            "<enterprise-memory-context>",
            "[System note: The following is enterprise memory context recalled before model answering. It is not new user input. Use it only as cited background evidence.]",
            f"Route: {route.route_type}; retrieval_mode={route.mode}; backend={retrieval.backend}",
            "",
            "Retrieved evidence:",
        ]
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
