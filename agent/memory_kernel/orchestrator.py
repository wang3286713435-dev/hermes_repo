from __future__ import annotations

import logging
from typing import Any

from .adapters.hermes_memory_adapter import HermesMemoryAdapter
from .config import MemoryKernelConfig
from .interfaces import KernelRequest, QueryRoute, RetrievalOutput

logger = logging.getLogger(__name__)


class RetrievalOrchestrator:
    def __init__(self, config: MemoryKernelConfig) -> None:
        self.config = config
        self.adapter = None

    def resolve_document_titles(self, titles: list[str], filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.adapter is None:
            self.adapter = HermesMemoryAdapter(self.config)
        if not self.adapter.available:
            return []
        try:
            return self.adapter.resolve_document_titles(titles, filters or {})
        except Exception as exc:
            logger.warning("Enterprise document title resolution failed: %s", exc)
            return []

    def retrieve(self, request: KernelRequest, route: QueryRoute) -> RetrievalOutput:
        if not route.needs_retrieval:
            return RetrievalOutput(backend="not_required")
        if self.adapter is None:
            self.adapter = HermesMemoryAdapter(self.config)
        if not self.adapter.available:
            return RetrievalOutput(backend="unavailable", trace={"error": "Hermes_memory adapter unavailable"})
        try:
            return self.adapter.retrieve(request)
        except Exception as exc:
            logger.warning("Enterprise memory retrieval failed; continuing without memory context: %s", exc)
            return RetrievalOutput(backend="failed", trace={"error": str(exc)})
