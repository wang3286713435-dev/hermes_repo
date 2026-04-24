from __future__ import annotations

from agent.memory_kernel.interfaces import KernelCitation, KernelItem, KernelRequest, QueryRoute, RetrievalOutput
from agent.memory_kernel.kernel import MemoryKernel
from agent.memory_kernel.session_document_scope import (
    DocumentScopeDecision,
    ResolvedDocument,
    SessionDocumentScopeStore,
)


def _resolver(titles, filters):
    documents = {
        "A标书": ResolvedDocument(document_id="doc-a", title="A标书"),
        "B标书": ResolvedDocument(document_id="doc-b", title="B标书"),
    }
    return [documents[title] for title in titles if title in documents]


def test_session_document_scope_switches_a_b_a_in_same_session():
    store = SessionDocumentScopeStore()

    first = store.resolve(session_id="s1", query="请围绕《A标书》回答", filters={}, resolver=_resolver)
    second = store.resolve(session_id="s1", query="切到《B标书》继续", filters={}, resolver=_resolver)
    third = store.resolve(session_id="s1", query="切回《A标书》回答", filters={}, resolver=_resolver)

    assert first.filters["document_id"] == "doc-a"
    assert first.trace["document_scope_changed"] is True
    assert second.filters["document_id"] == "doc-b"
    assert second.trace["document_scope_changed"] is True
    assert third.filters["document_id"] == "doc-a"
    assert third.trace["document_scope_changed"] is True


def test_session_document_scope_reuses_current_document_reference():
    store = SessionDocumentScopeStore()

    store.resolve(session_id="s1", query="切到《B标书》继续", filters={}, resolver=_resolver)
    decision = store.resolve(session_id="s1", query="刚才那份文件里的关键节点是什么", filters={}, resolver=_resolver)

    assert decision.filters["document_id"] == "doc-b"
    assert decision.trace["document_scope_source"] == "current_document_reference"
    assert decision.trace["scope_resolution_status"] == "active_document_reused"


def test_session_document_scope_failed_title_does_not_reuse_old_active_document():
    store = SessionDocumentScopeStore()

    store.resolve(session_id="s1", query="切到《B标书》继续", filters={}, resolver=_resolver)
    decision = store.resolve(session_id="s1", query="请围绕《不存在的文件》回答", filters={}, resolver=_resolver)

    assert "document_id" not in decision.filters
    assert decision.trace["scope_resolution_status"] == "scope_resolution_failed"
    assert decision.trace["active_document_id"] == "doc-b"


def test_session_document_scope_compare_allows_two_documents_without_updating_active():
    store = SessionDocumentScopeStore()
    store.resolve(session_id="s1", query="切到《B标书》继续", filters={}, resolver=_resolver)

    decision = store.resolve(session_id="s1", query="请对比《A标书》和《B标书》", filters={}, resolver=_resolver)

    assert "document_id" not in decision.filters
    assert decision.cross_document_allowed is True
    assert decision.allowed_document_ids == ["doc-a", "doc-b"]
    assert decision.trace["scope_resolution_status"] == "multi_document_resolved"
    assert store.get("s1").active_document_id == "doc-b"


def test_session_document_scope_detects_difference_phrase_as_compare():
    store = SessionDocumentScopeStore()

    decision = store.resolve(session_id="s1", query="《A标书》与《B标书》的区别是什么", filters={}, resolver=_resolver)

    assert decision.cross_document_allowed is True
    assert decision.allowed_document_ids == ["doc-a", "doc-b"]
    assert decision.trace["compare_document_ids"] == ["doc-a", "doc-b"]


def test_session_document_scope_detects_unquoted_compare_slash():
    store = SessionDocumentScopeStore()

    decision = store.resolve(session_id="s1", query="比较 A标书/B标书", filters={}, resolver=_resolver)

    assert decision.cross_document_allowed is True
    assert decision.allowed_document_ids == ["doc-a", "doc-b"]


def test_document_scope_filter_removes_third_document_evidence():
    retrieval = RetrievalOutput(
        items=[
            KernelItem(chunk_id="a1", document_id="doc-a", version_id="v1", text="A evidence"),
            KernelItem(chunk_id="b1", document_id="doc-b", version_id="v2", text="B evidence"),
            KernelItem(chunk_id="c1", document_id="doc-c", version_id="v3", text="C evidence"),
        ],
        citations=[
            KernelCitation(document_id="doc-a", version_id="v1", chunk_id="a1"),
            KernelCitation(document_id="doc-c", version_id="v3", chunk_id="c1"),
        ],
        backend="fake",
    )
    decision = DocumentScopeDecision(
        filters={},
        trace={
            "active_document_id": None,
            "active_document_title": None,
            "document_scope_source": "query_compare_titles",
            "document_scope_changed": False,
            "scope_resolution_status": "multi_document_resolved",
            "cross_document_allowed": True,
        },
        allowed_document_ids=["doc-a", "doc-b"],
        cross_document_allowed=True,
    )

    kernel = MemoryKernel.__new__(MemoryKernel)
    filtered = kernel._filter_retrieval_by_document_scope(retrieval, decision)

    assert [item.document_id for item in filtered.items] == ["doc-a", "doc-b"]
    assert [citation.document_id for citation in filtered.citations] == ["doc-a"]
    assert filtered.trace["document_scope_filter"]["items_before"] == 3
    assert filtered.trace["document_scope_filter"]["items_after"] == 2


def test_multi_document_compare_runs_scoped_retrieval_for_each_document_and_merges():
    class FakeRetrieval:
        def __init__(self):
            self.requests = []

        def retrieve(self, request, route):
            self.requests.append(request)
            document_id = request.filters["document_id"]
            return RetrievalOutput(
                items=[
                    KernelItem(chunk_id=f"{document_id}-1", document_id=document_id, version_id="v1", text=f"{document_id} evidence"),
                    KernelItem(chunk_id="third-1", document_id="doc-third", version_id="v3", text="third evidence"),
                ],
                citations=[KernelCitation(document_id=document_id, version_id="v1", chunk_id=f"{document_id}-1")],
                backend="fake",
                sparse_retrieval_status="executed",
                applied_filters=dict(request.filters),
            )

    decision = DocumentScopeDecision(
        filters={},
        trace={
            "active_document_id": "doc-a",
            "active_document_title": "A标书",
            "document_scope_source": "query_compare_titles",
            "document_scope_changed": False,
            "scope_resolution_status": "multi_document_resolved",
            "cross_document_allowed": True,
            "compare_document_ids": ["doc-a", "doc-b"],
        },
        allowed_document_ids=["doc-a", "doc-b"],
        cross_document_allowed=True,
    )
    request = KernelRequest(
        query="请对比《A标书》和《B标书》",
        session_id="s1",
        top_k=8,
        document_scope=decision.trace,
        allowed_document_ids=decision.allowed_document_ids,
        cross_document_allowed=True,
    )
    route = QueryRoute("enterprise_retrieval", True, "test")
    kernel = MemoryKernel.__new__(MemoryKernel)
    kernel.retrieval = FakeRetrieval()

    retrieval = kernel._retrieve_with_document_scope(request, route, decision)
    filtered = kernel._filter_retrieval_by_document_scope(retrieval, decision)

    assert [call.filters["document_id"] for call in kernel.retrieval.requests] == ["doc-a", "doc-b"]
    assert [call.top_k for call in kernel.retrieval.requests] == [4, 4]
    assert [item.document_id for item in filtered.items] == ["doc-a", "doc-b"]
    assert filtered.backend == "multi_document_scoped"
    assert filtered.trace["compare_document_ids"] == ["doc-a", "doc-b"]
    assert filtered.trace["returned_document_ids"] == ["doc-a", "doc-b"]


def test_document_scope_trace_has_required_fields():
    store = SessionDocumentScopeStore()

    decision = store.resolve(session_id="s1", query="请围绕《A标书》回答", filters={}, resolver=_resolver)

    for field in (
        "active_document_id",
        "active_document_title",
        "document_scope_source",
        "document_scope_changed",
        "scope_resolution_status",
        "cross_document_allowed",
    ):
        assert field in decision.trace
