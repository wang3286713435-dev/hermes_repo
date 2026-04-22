from __future__ import annotations

import logging

from .citation_engine import CitationEngine
from .config import MemoryKernelConfig
from .context_builder import ContextBuilder
from .interfaces import KernelRequest, KernelResult, RetrievalOutput
from .orchestrator import RetrievalOrchestrator
from .router import QueryRouter

logger = logging.getLogger(__name__)


class MemoryKernel:
    """Hermes-owned enterprise memory kernel.

    Phase 1.5 keeps this small: route, retrieve through the Hermes_memory
    adapter, normalize citations, and build an API-time context block.
    """

    def __init__(self, config: MemoryKernelConfig) -> None:
        self.config = config
        self.router = QueryRouter()
        self.retrieval = RetrievalOrchestrator(config)
        self.citations = CitationEngine()
        self.context_builder = ContextBuilder()

    def start_turn(self, request: KernelRequest) -> KernelResult:
        if not self.config.enabled:
            route = self.router.route(request.query)
            disabled_retrieval = RetrievalOutput(backend="disabled")
            return KernelResult(route=route, retrieval=disabled_retrieval, trace={"enabled": False})

        route = self.router.route(request.query)
        retrieval = self.retrieval.retrieve(request, route)
        citations = self.citations.normalize_citations(retrieval.citations, retrieval.items)
        retrieval = RetrievalOutput(
            items=retrieval.items,
            citations=citations,
            backend=retrieval.backend,
            dense_retrieval_status=retrieval.dense_retrieval_status,
            sparse_retrieval_status=retrieval.sparse_retrieval_status,
            retrieval_mode=retrieval.retrieval_mode,
            applied_filters=retrieval.applied_filters,
            ignored_filters=retrieval.ignored_filters,
            trace=retrieval.trace,
        )
        context_block = self.context_builder.build(route, retrieval) if self.config.inject_context else ""
        return KernelResult(
            route=route,
            retrieval=retrieval,
            context_block=context_block,
            trace={
                "enabled": True,
                "route_type": route.route_type,
                "needs_retrieval": route.needs_retrieval,
                "route_reason": route.reason,
                "retrieval_backend": retrieval.backend,
                "retrieval_mode": retrieval.retrieval_mode,
                "retrieval_items": len(retrieval.items),
                "citations": len(retrieval.citations),
                "dense_retrieval_status": retrieval.dense_retrieval_status,
                "sparse_retrieval_status": retrieval.sparse_retrieval_status,
                "applied_filters": retrieval.applied_filters,
                "ignored_filters": retrieval.ignored_filters,
                **(retrieval.trace or {}),
            },
        )

    def finish_turn(self, request: KernelRequest, response: str, result: KernelResult) -> None:
        # TODO Phase 2: write retrieval/citation trace and safe memory writeback.
        return None

    def result_payload(self, result: KernelResult) -> dict:
        return self.context_builder.result_to_payload(result)
