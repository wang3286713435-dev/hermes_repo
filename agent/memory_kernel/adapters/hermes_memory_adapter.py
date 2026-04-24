from __future__ import annotations

import importlib
import logging
import re
import sys
from pathlib import Path
from typing import Any

from ..config import MemoryKernelConfig
from ..interfaces import KernelCitation, KernelItem, KernelRequest, RetrievalOutput

logger = logging.getLogger(__name__)


_METADATA_TRACE_FIELDS = (
    "metadata_snapshot",
    "metadata_snapshot_used",
    "metadata_fields_matched",
    "metadata_source_chunk_ids",
    "evidence_required",
    "snapshot_as_answer",
)


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
        self._document_cls = None
        self._loaded_source_mtime = 0.0
        self._load()

    @property
    def available(self) -> bool:
        return self._available

    def retrieve(self, request: KernelRequest) -> RetrievalOutput:
        if not self._available:
            return RetrievalOutput(backend="unavailable", trace={"error": "Hermes_memory adapter is unavailable"})

        self._reload_if_needed()
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
            trace = self._normalize_trace(dict(getattr(result, "trace", {}) or {}))
            return RetrievalOutput(
                items=[self._item_from_raw(item) for item in retrieval_results],
                citations=[self._citation_from_raw(citation) for citation in raw_citations],
                backend=str(getattr(context, "backend", "hermes_memory") if context else "hermes_memory"),
                dense_retrieval_status=str(getattr(context, "dense_retrieval_status", "not_executed") if context else "not_executed"),
                sparse_retrieval_status=str(getattr(context, "sparse_retrieval_status", "not_executed") if context else "not_executed"),
                retrieval_mode=str(getattr(context, "retrieval_mode", request.retrieval_mode) if context else request.retrieval_mode),
                applied_filters=dict(getattr(context, "applied_filters", {}) or {}),
                ignored_filters=dict(getattr(context, "ignored_filters", {}) or {}),
                trace=trace,
            )
        finally:
            db.close()

    def resolve_document_titles(self, titles: list[str], filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self._available or self._document_cls is None:
            return []

        self._reload_if_needed()
        db = self._session_local()
        try:
            resolved: list[dict[str, Any]] = []
            scoped_filters = filters or {}
            for title in titles:
                document = self._resolve_one_title(db, title, scoped_filters)
                if document is not None:
                    resolved.append(
                        {
                            "document_id": str(document.id),
                            "title": str(document.title),
                            "source_type": getattr(document, "source_type", None),
                            "document_type": getattr(document, "document_type", None),
                        }
                    )
            return resolved
        finally:
            db.close()

    def _load(self, force_reload: bool = False) -> None:
        root = Path(self.config.hermes_memory_path).expanduser().resolve()
        if not root.exists():
            logger.info("Hermes memory kernel path does not exist: %s", root)
            return
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        try:
            module_names = [
                "app.db.session",
                "app.models.document",
                "app.schemas.retrieval",
                "app.memory_kernel.contracts",
                "app.memory_kernel.retrieval_orchestrator",
                "app.memory_kernel.kernel",
                "app.services.retrieval.service",
            ]
            importlib.invalidate_caches()
            loaded_modules = {}
            for name in module_names:
                if force_reload and name in sys.modules:
                    loaded_modules[name] = importlib.reload(sys.modules[name])
                else:
                    loaded_modules[name] = importlib.import_module(name)
        except Exception as exc:
            logger.warning("Hermes_memory adapter import failed: %s", exc)
            return

        self._session_local = loaded_modules["app.db.session"].SessionLocal
        self._kernel_cls = loaded_modules["app.memory_kernel.kernel"].MemoryKernel
        self._request_cls = loaded_modules["app.memory_kernel.contracts"].MemoryKernelRequest
        self._filter_cls = loaded_modules["app.schemas.retrieval"].RetrievalFilter
        self._document_cls = loaded_modules["app.models.document"].Document
        self._loaded_source_mtime = self._source_tree_mtime(root)
        self._available = True

    def _reload_if_needed(self) -> None:
        root = Path(self.config.hermes_memory_path).expanduser().resolve()
        current_mtime = self._source_tree_mtime(root)
        if current_mtime > self._loaded_source_mtime:
            self._load(force_reload=True)

    def _source_tree_mtime(self, root: Path) -> float:
        candidate_paths = [
            root / "app/db/session.py",
            root / "app/models/document.py",
            root / "app/schemas/retrieval.py",
            root / "app/memory_kernel/contracts.py",
            root / "app/memory_kernel/retrieval_orchestrator.py",
            root / "app/memory_kernel/kernel.py",
            root / "app/services/retrieval/service.py",
        ]
        mtimes = []
        for path in candidate_paths:
            try:
                mtimes.append(path.stat().st_mtime)
            except OSError:
                continue
        return max(mtimes) if mtimes else 0.0

    def _normalize_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        retrieval_trace = trace.get("retrieval_trace")
        if isinstance(retrieval_trace, dict):
            for field in _METADATA_TRACE_FIELDS:
                if field in retrieval_trace:
                    trace[field] = retrieval_trace[field]
        if trace.get("metadata_snapshot_used") or trace.get("metadata_snapshot"):
            trace["evidence_required"] = True
            trace["snapshot_as_answer"] = False
        return trace

    def _resolve_one_title(self, db: Any, title: str, filters: dict[str, Any]) -> Any | None:
        target = self._normalize_title(title)
        if not target:
            return None

        query = db.query(self._document_cls)
        if hasattr(self._document_cls, "status"):
            query = query.filter(self._document_cls.status == "active")
        if filters.get("source_type") and hasattr(self._document_cls, "source_type"):
            query = query.filter(self._document_cls.source_type == filters["source_type"])
        if filters.get("document_type") and hasattr(self._document_cls, "document_type"):
            query = query.filter(self._document_cls.document_type == filters["document_type"])
        try:
            candidates = query.order_by(self._document_cls.updated_at.desc()).limit(200).all()
        except Exception:
            candidates = query.limit(200).all()

        exact = []
        partial = []
        for document in candidates:
            candidate_title = self._normalize_title(str(getattr(document, "title", "") or ""))
            if candidate_title == target:
                exact.append(document)
            elif target in candidate_title or candidate_title in target:
                partial.append(document)
        if exact:
            return exact[0]
        if partial:
            return partial[0]
        return None

    def _normalize_title(self, title: str) -> str:
        text = re.sub(r"\s+", "", title or "").lower()
        return text.strip("《》「」『』\"'，。！？:：")

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
