from __future__ import annotations

from typing import Any

from .interfaces import KernelCitation, KernelItem


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class CitationEngine:
    def normalize_citations(self, raw_citations: list[Any], items: list[KernelItem]) -> list[KernelCitation]:
        if raw_citations:
            return [self._from_raw(citation) for citation in raw_citations]
        return [self._from_item(item) for item in items]

    def _from_raw(self, citation: Any) -> KernelCitation:
        return KernelCitation(
            document_id=str(_get(citation, "document_id", "")),
            version_id=str(_get(citation, "version_id", "")),
            chunk_id=str(_get(citation, "chunk_id", "")),
            source_name=_get(citation, "source_name"),
            source_uri=_get(citation, "source_uri"),
            version_name=_get(citation, "version_name"),
            heading_path=list(_get(citation, "heading_path", []) or []),
            section_path=list(_get(citation, "section_path", []) or []),
            page_start=_get(citation, "page_start"),
            page_end=_get(citation, "page_end"),
            quote_text=str(_get(citation, "quote_text", "") or ""),
        )

    def _from_item(self, item: KernelItem) -> KernelCitation:
        quote = item.text[:300] if item.text else ""
        return KernelCitation(
            document_id=item.document_id,
            version_id=item.version_id,
            chunk_id=item.chunk_id,
            source_name=item.source_name,
            source_uri=item.source_uri,
            version_name=item.version_name,
            heading_path=item.heading_path,
            section_path=item.section_path,
            page_start=item.page_start,
            page_end=item.page_end,
            quote_text=quote,
        )

