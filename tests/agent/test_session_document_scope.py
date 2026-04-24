from __future__ import annotations

from agent.memory_kernel.config import MemoryKernelConfig
from agent.memory_kernel.context_builder import ContextBuilder
from agent.memory_kernel.interfaces import KernelCitation, KernelItem, KernelRequest, KernelResult, QueryRoute, RetrievalOutput
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


def test_session_file_alias_binds_title_to_alias():
    store = SessionDocumentScopeStore()

    decision = store.resolve(session_id="s1", query="把《A标书》设为 @主标书", filters={}, resolver=_resolver)

    assert decision.filters["document_id"] == "doc-a"
    assert decision.trace["alias_resolution"]["status"] == "alias_bound"
    assert decision.trace["alias"] == "主标书"
    assert decision.trace["resolved_document_id"] == "doc-a"
    assert decision.trace["resolved_title"] == "A标书"
    assert decision.trace["alias_scope"] == "session"


def test_session_file_alias_binds_current_active_document():
    store = SessionDocumentScopeStore()

    store.resolve(session_id="s1", query="请围绕《B标书》回答", filters={}, resolver=_resolver)
    decision = store.resolve(session_id="s1", query="把当前文件设为 @交付标准", filters={}, resolver=_resolver)

    assert decision.filters["document_id"] == "doc-b"
    assert decision.trace["alias_resolution"]["status"] == "alias_bound"
    assert decision.trace["resolved_document_id"] == "doc-b"
    assert decision.trace["document_scope_source"] == "file_alias"


def test_session_file_alias_resolves_to_scoped_retrieval():
    store = SessionDocumentScopeStore()
    store.resolve(session_id="s1", query="把《A标书》设为 @主标书", filters={}, resolver=_resolver)
    store.resolve(session_id="s1", query="切到《B标书》继续", filters={}, resolver=_resolver)

    decision = store.resolve(session_id="s1", query="围绕 @主标书 回答总工期", filters={}, resolver=_resolver)

    assert decision.filters["document_id"] == "doc-a"
    assert decision.allowed_document_ids == ["doc-a"]
    assert decision.trace["scope_resolution_status"] == "alias_resolved"
    assert decision.trace["document_scope_changed"] is True
    assert decision.trace["alias_resolution"]["resolved_document_id"] == "doc-a"


def test_session_file_alias_compare_resolves_two_aliases():
    store = SessionDocumentScopeStore()
    store.resolve(session_id="s1", query="把《A标书》设为 @主标书", filters={}, resolver=_resolver)
    store.resolve(session_id="s1", query="把《B标书》设为 @交付标准", filters={}, resolver=_resolver)

    decision = store.resolve(session_id="s1", query="对比 @主标书 和 @交付标准", filters={}, resolver=_resolver)

    assert "document_id" not in decision.filters
    assert decision.cross_document_allowed is True
    assert decision.allowed_document_ids == ["doc-a", "doc-b"]
    assert decision.trace["scope_resolution_status"] == "multi_document_alias_resolved"
    assert decision.trace["compare_aliases"] == ["主标书", "交付标准"]
    assert decision.trace["compare_document_ids"] == ["doc-a", "doc-b"]


def test_session_file_alias_missing_does_not_reuse_active_document():
    store = SessionDocumentScopeStore()
    store.resolve(session_id="s1", query="请围绕《B标书》回答", filters={}, resolver=_resolver)

    decision = store.resolve(session_id="s1", query="围绕 @不存在 回答", filters={}, resolver=_resolver)

    assert "document_id" not in decision.filters
    assert decision.allowed_document_ids == []
    assert decision.trace["scope_resolution_status"] == "alias_missing"
    assert decision.trace["alias_missing"] is True
    assert decision.trace["active_document_id"] == "doc-b"
    assert decision.trace["suppress_retrieval"] is True


def test_session_file_alias_missing_suppresses_kernel_retrieval():
    store = SessionDocumentScopeStore()
    decision = store.resolve(session_id="s1", query="围绕 @不存在 回答", filters={}, resolver=_resolver)
    kernel = MemoryKernel.__new__(MemoryKernel)

    retrieval = kernel._retrieve_with_document_scope(
        KernelRequest(query="围绕 @不存在 回答", session_id="s1"),
        QueryRoute("enterprise_retrieval", True, "test"),
        decision,
    )

    assert retrieval.backend == "document_scope_suppressed"
    assert retrieval.trace["scope_retrieval_suppressed"] is True


def test_session_file_alias_binds_after_same_turn_retrieval():
    class FakeRetrieval:
        def resolve_document_titles(self, titles, filters):
            return _resolver(titles, filters)

        def retrieve(self, request, route):
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id="a1",
                        document_id="doc-a",
                        version_id="v1",
                        text="A evidence",
                        source_name="A标书",
                    )
                ],
                citations=[KernelCitation(document_id="doc-a", version_id="v1", chunk_id="a1", source_name="A标书")],
                backend="fake",
            )

    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.retrieval = FakeRetrieval()

    result = kernel.start_turn(KernelRequest(query="把当前文件设为 @主标书", session_id="s1"))
    decision = kernel.resolve_document_scope(session_id="s1", query="围绕 @主标书 回答", filters={})

    assert result.trace["alias_resolution"]["status"] == "alias_bound"
    assert result.trace["resolved_document_id"] == "doc-a"
    assert decision.filters["document_id"] == "doc-a"
    assert "Alias handling is done by Hermes session state" in result.context_block


def test_alias_scope_forces_retrieval_even_without_router_hint():
    class FakeRetrieval:
        def __init__(self):
            self.calls = []

        def resolve_document_titles(self, titles, filters):
            return _resolver(titles, filters)

        def retrieve(self, request, route):
            self.calls.append((request, route))
            return RetrievalOutput(
                items=[KernelItem(chunk_id="a1", document_id="doc-a", version_id="v1", text="A evidence")],
                backend="fake",
            )

    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    fake_retrieval = FakeRetrieval()
    kernel.retrieval = fake_retrieval
    kernel.document_scope.resolve(session_id="s1", query="把《A标书》设为 @主标书", filters={}, resolver=_resolver)

    result = kernel.start_turn(KernelRequest(query="围绕 @主标书 回答", session_id="s1"))

    assert fake_retrieval.calls
    assert fake_retrieval.calls[0][1].needs_retrieval is True
    assert fake_retrieval.calls[0][0].filters["document_id"] == "doc-a"
    assert result.trace["alias_resolution"]["status"] == "alias_resolved"


def test_session_file_alias_rebind_is_diagnostic():
    store = SessionDocumentScopeStore()

    store.resolve(session_id="s1", query="把《A标书》设为 @主标书", filters={}, resolver=_resolver)
    decision = store.resolve(session_id="s1", query="把《B标书》设为 @主标书", filters={}, resolver=_resolver)

    assert decision.filters["document_id"] == "doc-b"
    assert decision.trace["alias_resolution"]["status"] == "alias_bound"
    assert decision.trace["alias_conflict"] is True
    assert decision.trace["resolved_document_id"] == "doc-b"


def test_alias_context_block_reports_missing_without_fake_evidence():
    builder = ContextBuilder()
    retrieval = RetrievalOutput(
        backend="document_scope_suppressed",
        trace={
            "alias_resolution": {
                "status": "alias_missing",
                "alias": "主标书",
                "resolved_document_id": None,
                "resolved_title": None,
                "alias_scope": "session",
                "alias_missing": True,
            },
            "scope_retrieval_suppressed": True,
        },
    )

    context = builder.build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "Alias handling is done by Hermes session state" in context
    assert "alias_resolution.status=alias_missing" in context
    assert "Retrieved evidence:" not in context
    assert "do not answer from history memory as document evidence" in context


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
    governed = kernel._with_context_governance_trace(filtered.trace, filtered, decision)
    assert governed["retrieval_evidence_document_ids"] == ["doc-a", "doc-b"]
    assert "out_of_scope_evidence_filtered" in governed["contamination_flags"]


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
        "active_project",
        "active_task",
        "history_memory_used",
        "history_memory_as_evidence",
        "context_scope",
    ):
        assert field in decision.trace


def test_active_document_takes_priority_over_project_task_hint():
    store = SessionDocumentScopeStore()

    store.resolve(session_id="s1", query="请围绕《A标书》回答", filters={}, resolver=_resolver)
    decision = store.resolve(
        session_id="s1",
        query="项目：宝安项目，任务：审标，请继续回答",
        filters={},
        resolver=_resolver,
    )

    assert decision.filters["document_id"] == "doc-a"
    assert decision.trace["active_project"] == "宝安项目"
    assert decision.trace["active_task"] == "审标"
    assert decision.trace["context_scope"]["scope_type"] == "document"


def test_project_task_hint_only_enters_trace_without_forcing_filter():
    store = SessionDocumentScopeStore()

    decision = store.resolve(
        session_id="s1",
        query="请看当前上下文",
        filters={"project_id": "project-1", "task_id": "task-1"},
        resolver=_resolver,
    )

    assert "document_id" not in decision.filters
    assert decision.trace["active_project"] == "project-1"
    assert decision.trace["active_task"] == "task-1"
    assert decision.trace["context_scope"]["scope_type"] == "project_task"


def test_empty_retrieval_does_not_let_history_memory_pretend_to_be_evidence():
    decision = DocumentScopeDecision(
        filters={"document_id": "doc-a"},
        trace={
            "active_document_id": "doc-a",
            "active_document_title": "A标书",
            "document_scope_source": "active_document",
            "document_scope_changed": False,
            "scope_resolution_status": "active_document_applied",
            "cross_document_allowed": False,
            "history_memory_used": True,
        },
        allowed_document_ids=["doc-a"],
        cross_document_allowed=False,
    )
    retrieval = RetrievalOutput(items=[], citations=[], backend="fake")

    kernel = MemoryKernel.__new__(MemoryKernel)
    trace = kernel._with_context_governance_trace({}, retrieval, decision)

    assert trace["retrieval_evidence_document_ids"] == []
    assert trace["history_memory_used"] is True
    assert trace["history_memory_as_evidence"] is False
    assert trace["context_scope"]["history_memory_as_evidence"] is False
    assert "no_current_retrieval_evidence" in trace["contamination_flags"]


def test_retrieval_evidence_present_keeps_history_memory_as_non_evidence():
    decision = DocumentScopeDecision(
        filters={"document_id": "doc-a"},
        trace={
            "active_document_id": "doc-a",
            "active_document_title": "A标书",
            "document_scope_source": "active_document",
            "document_scope_changed": False,
            "scope_resolution_status": "active_document_applied",
            "cross_document_allowed": False,
            "history_memory_used": True,
        },
        allowed_document_ids=["doc-a"],
        cross_document_allowed=False,
    )
    retrieval = RetrievalOutput(
        items=[KernelItem(chunk_id="a1", document_id="doc-a", version_id="v1", text="A evidence")],
        citations=[KernelCitation(document_id="doc-a", version_id="v1", chunk_id="a1")],
        backend="fake",
    )
    kernel = MemoryKernel.__new__(MemoryKernel)
    trace = kernel._with_context_governance_trace({}, retrieval, decision)
    result = KernelResult(
        route=QueryRoute("enterprise_retrieval", True, "test"),
        retrieval=retrieval,
        trace=trace,
    )

    kernel.mark_history_memory_usage(result, True)

    assert result.trace["retrieval_evidence_document_ids"] == ["doc-a"]
    assert result.trace["history_memory_used"] is True
    assert result.trace["history_memory_as_evidence"] is False
    assert result.trace["context_scope"]["history_memory_as_evidence"] is False
    assert result.trace["evidence_source_policy"]["history_memory_can_cite"] is False
    assert "no_current_retrieval_evidence" not in result.trace["contamination_flags"]
