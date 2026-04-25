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
            item_metadata_by_key = {
                self._item_key(item): dict(item.metadata or {})
                for item in items
                if self._item_key(item) is not None and item.metadata
            }
            citations = [self._from_raw(citation) for citation in raw_citations]
            enriched = []
            for citation in citations:
                metadata = dict(citation.metadata or {})
                if not metadata:
                    metadata = item_metadata_by_key.get(self._citation_key(citation), {})
                enriched.append(
                    KernelCitation(
                        document_id=citation.document_id,
                        version_id=citation.version_id,
                        chunk_id=citation.chunk_id,
                        source_name=citation.source_name,
                        source_uri=citation.source_uri,
                        version_name=citation.version_name,
                        heading_path=citation.heading_path,
                        section_path=citation.section_path,
                        page_start=citation.page_start,
                        page_end=citation.page_end,
                        quote_text=citation.quote_text,
                        metadata=dict(metadata or {}),
                    )
                )
            return enriched
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
            metadata=dict(_get(citation, "metadata", {}) or {}),
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
            metadata=dict(item.metadata or {}),
        )

    def _item_key(self, item: KernelItem) -> tuple[str, str, str] | None:
        return self._key(item.document_id, item.version_id, item.chunk_id)

    def _citation_key(self, citation: KernelCitation) -> tuple[str, str, str] | None:
        return self._key(citation.document_id, citation.version_id, citation.chunk_id)

    def _key(self, document_id: str, version_id: str, chunk_id: str) -> tuple[str, str, str] | None:
        if not document_id or not chunk_id:
            return None
        return (document_id, version_id or "", chunk_id)
