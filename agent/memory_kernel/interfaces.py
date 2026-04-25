from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RouteType = Literal["ordinary_chat", "enterprise_retrieval"]
RetrievalMode = Literal["sparse", "dense", "hybrid"]


@dataclass(frozen=True)
class QueryRoute:
    route_type: RouteType
    needs_retrieval: bool
    reason: str
    mode: RetrievalMode = "hybrid"


@dataclass(frozen=True)
class KernelRequest:
    query: str
    session_id: str
    user_id: str | None = None
    top_k: int = 8
    filters: dict[str, Any] = field(default_factory=dict)
    route_type: str | None = None
    retrieval_mode: RetrievalMode = "hybrid"
    enable_dense: bool = True
    enable_sparse: bool = True
    enable_hybrid: bool = True
    debug: bool = False
    query_vector: list[float] | None = None
    document_scope: dict[str, Any] = field(default_factory=dict)
    allowed_document_ids: list[str] = field(default_factory=list)
    cross_document_allowed: bool = False


@dataclass(frozen=True)
class KernelCitation:
    document_id: str
    version_id: str
    chunk_id: str
    source_name: str | None = None
    source_uri: str | None = None
    version_name: str | None = None
    heading_path: list[str] = field(default_factory=list)
    section_path: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    quote_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KernelItem:
    chunk_id: str
    document_id: str
    version_id: str
    text: str
    score: float = 0.0
    source_name: str | None = None
    source_uri: str | None = None
    version_name: str | None = None
    heading_path: list[str] = field(default_factory=list)
    section_path: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalOutput:
    items: list[KernelItem] = field(default_factory=list)
    citations: list[KernelCitation] = field(default_factory=list)
    backend: str = "none"
    dense_retrieval_status: str = "not_executed"
    sparse_retrieval_status: str = "not_executed"
    retrieval_mode: RetrievalMode = "hybrid"
    applied_filters: dict[str, Any] = field(default_factory=dict)
    ignored_filters: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KernelResult:
    route: QueryRoute
    retrieval: RetrievalOutput
    context_block: str = ""
    trace: dict[str, Any] = field(default_factory=dict)
