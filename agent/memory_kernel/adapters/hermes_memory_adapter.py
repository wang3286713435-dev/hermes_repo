from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from ..config import MemoryKernelConfig
from ..interfaces import KernelCitation, KernelItem, KernelRequest, RetrievalOutput

logger = logging.getLogger(__name__)


def _model_dump(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {}


class HermesMemoryAdapter:
    """Direct Python adapter into the Hermes_memory internal subsystem.

    This is intentionally not an HTTP client and not a model-callable tool. It
    lets Hermes core call the current Hermes_memory retrieval implementation
    during the pre-model phase while we migrate modules into the main repo.
    """

    def __init__(self, config: MemoryKernelConfig) -> None:
        self.config = config
        self._available = False
        self._session_local = None
        self._kernel_cls = None
        self._request_cls = None
        self._filter_cls = None
        self._load()

    @property
    def available(self) -> bool:
        return self._available

    def retrieve(self, request: KernelRequest) -> RetrievalOutput:
        if not self._available:
            return RetrievalOutput(backend="unavailable", trace={"error": "Hermes_memory adapter is unavailable"})

        db = self._session_local()
        try:
            filters = self._filter_cls(**(request.filters or {}))
            kernel_request = self._request_cls(
                query=request.query,
                user_id=request.user_id or "hermes",
                session_id=request.session_id,
                filters=filters,
                top_k=request.top_k,
                route_type=request.route_type,
                retrieval_mode=request.retrieval_mode,
                enable_dense=request.enable_dense,
                enable_sparse=request.enable_sparse,
                enable_hybrid=request.enable_hybrid,
                debug=request.debug,
                query_vector=request.query_vector,
                citation_required=True,
            )
            result = self._kernel_cls(db=db).run(kernel_request)
            retrieval_results = list(getattr(result, "retrieval_results", []) or [])
            context = getattr(result, "context", None)
            raw_citations = list(getattr(context, "citations", []) or [])
            return RetrievalOutput(
                items=[self._item_from_raw(item) for item in retrieval_results],
                citations=[self._citation_from_raw(citation) for citation in raw_citations],
                backend=str(getattr(context, "backend", "hermes_memory") if context else "hermes_memory"),
                dense_retrieval_status=str(getattr(context, "dense_retrieval_status", "not_executed") if context else "not_executed"),
                sparse_retrieval_status=str(getattr(context, "sparse_retrieval_status", "not_executed") if context else "not_executed"),
                retrieval_mode=str(getattr(context, "retrieval_mode", request.retrieval_mode) if context else request.retrieval_mode),
                applied_filters=dict(getattr(context, "applied_filters", {}) or {}),
                ignored_filters=dict(getattr(context, "ignored_filters", {}) or {}),
                trace=dict(getattr(result, "trace", {}) or {}),
            )
        finally:
            db.close()

    def _load(self) -> None:
        root = Path(self.config.hermes_memory_path).expanduser().resolve()
        if not root.exists():
            logger.info("Hermes memory kernel path does not exist: %s", root)
            return
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        try:
            from app.db.session import SessionLocal
            from app.memory_kernel.contracts import MemoryKernelRequest
            from app.memory_kernel.kernel import MemoryKernel
            from app.schemas.retrieval import RetrievalFilter
        except Exception as exc:
            logger.warning("Hermes_memory adapter import failed: %s", exc)
            return

        self._session_local = SessionLocal
        self._kernel_cls = MemoryKernel
        self._request_cls = MemoryKernelRequest
        self._filter_cls = RetrievalFilter
        self._available = True

    def _item_from_raw(self, raw: Any) -> KernelItem:
        data = _model_dump(raw)
        return KernelItem(
            chunk_id=str(data.get("chunk_id", "")),
            document_id=str(data.get("document_id", "")),
            version_id=str(data.get("version_id", "")),
            text=str(data.get("text", "") or ""),
            score=float(data.get("score") or 0.0),
            source_name=data.get("source_name"),
            source_uri=data.get("source_uri"),
            version_name=data.get("version_name"),
            heading_path=list(data.get("heading_path") or []),
            section_path=list(data.get("section_path") or []),
            page_start=data.get("page_start"),
            page_end=data.get("page_end"),
            metadata=dict(data.get("metadata") or {}),
        )

    def _citation_from_raw(self, raw: Any) -> KernelCitation:
        data = _model_dump(raw)
        return KernelCitation(
            document_id=str(data.get("document_id", "")),
            version_id=str(data.get("version_id", "")),
            chunk_id=str(data.get("chunk_id", "")),
            source_name=data.get("source_name"),
            source_uri=data.get("source_uri"),
            version_name=data.get("version_name"),
            heading_path=list(data.get("heading_path") or []),
            section_path=list(data.get("section_path") or []),
            page_start=data.get("page_start"),
            page_end=data.get("page_end"),
            quote_text=str(data.get("quote_text", "") or ""),
        )
