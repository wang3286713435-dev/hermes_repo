from __future__ import annotations

from agent.memory_kernel.context_builder import ContextBuilder
from agent.memory_kernel.interfaces import KernelItem, KernelRequest, QueryRoute, RetrievalOutput
from agent.memory_kernel.kernel import MemoryKernel
from agent.memory_kernel.session_document_scope import DocumentScopeDecision


class _FakeFactsRetrieval:
    def __init__(self, facts):
        self.facts = facts
        self.calls = []
        self.stale_calls = []

    def search_confirmed_facts(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.facts)

    def search_stale_confirmed_facts(self, **kwargs):
        self.stale_calls.append(kwargs)
        return [fact for fact in self.facts if fact.get("stale_source_version")]


def _fact(
    fact_id: str,
    *,
    status: str = "confirmed",
    document_id: str = "doc-a",
    version_id: str = "v1",
    stale: bool = False,
) -> dict:
    return {
        "fact_id": fact_id,
        "fact_type": "project_profile",
        "subject": "项目",
        "predicate": "建设单位",
        "value": "深圳市福升建设开发有限公司",
        "source_document_id": document_id,
        "source_version_id": version_id,
        "source_chunk_id": f"chunk-{fact_id}",
        "stale_source_version": stale,
        "latest_version_id": "v2" if stale else version_id,
        "verification_status": status,
    }


def _facts_trace(facts, *, with_retrieval: bool = True) -> dict:
    kernel = MemoryKernel.__new__(MemoryKernel)
    kernel.retrieval = _FakeFactsRetrieval(facts)
    request = KernelRequest(
        query="请结合已确认事实回答",
        session_id="session-a",
        user_id="requester-a",
        filters={"document_id": "doc-a"},
        document_scope={"facts_context_requested": True},
    )
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="retrieved-a",
                document_id="doc-a",
                version_id="v1",
                text="retrieval evidence",
            )
        ]
        if with_retrieval
        else [],
        backend="fake",
        trace={},
    )
    scope_decision = DocumentScopeDecision(
        filters={"document_id": "doc-a"},
        trace={"facts_context_requested": True},
        allowed_document_ids=["doc-a"],
    )
    trace = kernel._with_context_governance_trace({}, retrieval, scope_decision)
    return kernel._with_facts_context_trace(trace, request, retrieval, scope_decision)


def _stale_diagnostic_trace(facts) -> dict:
    kernel = MemoryKernel.__new__(MemoryKernel)
    kernel.retrieval = _FakeFactsRetrieval(facts)
    request = KernelRequest(
        query="请检查 stale fact source",
        session_id="session-a",
        user_id="requester-a",
        filters={"document_id": "doc-a"},
        document_scope={"facts_context_requested": True},
    )
    retrieval = RetrievalOutput(items=[], backend="fake", trace={})
    scope_decision = DocumentScopeDecision(
        filters={"document_id": "doc-a"},
        trace={"facts_context_requested": True, "active_document_id": "doc-a"},
        allowed_document_ids=["doc-a"],
    )
    trace = kernel._with_context_governance_trace({}, retrieval, scope_decision)
    return kernel._with_facts_context_trace(trace, request, retrieval, scope_decision)


def test_only_confirmed_facts_are_injected():
    trace = _facts_trace([_fact("confirmed-1"), _fact("unverified-1", status="unverified")])

    assert trace["facts_context_used"] is True
    assert trace["facts_context_fact_ids"] == ["confirmed-1"]
    assert trace["facts_as_answer"] is False


def test_retrieval_evidence_missing_suppresses_facts_context():
    trace = _facts_trace([_fact("confirmed-1")], with_retrieval=False)

    assert trace["facts_context_used"] is False
    assert trace["facts_context_fact_ids"] == []
    assert trace["facts_context_suppressed_reason"] == "no_current_retrieval_evidence"
    assert trace["facts_as_answer"] is False


def test_denied_or_empty_facts_are_not_injected():
    trace = _facts_trace([])

    assert trace["facts_context_used"] is False
    assert trace["facts_context_suppressed_reason"] == "no_confirmed_facts"
    assert trace["facts_as_answer"] is False


def test_stale_fact_source_is_visible_in_context_block():
    trace = _facts_trace([_fact("stale-1", stale=True)])
    block = ContextBuilder().build(
        QueryRoute("enterprise_retrieval", True, "test"),
        RetrievalOutput(
            items=[KernelItem(chunk_id="retrieved-a", document_id="doc-a", version_id="v1", text="evidence")],
            backend="fake",
            trace=trace,
        ),
    )

    assert "Confirmed facts auxiliary context:" in block
    assert "facts_context_used=true" in block
    assert "facts_as_answer=false" in block
    assert "confirmed facts are auxiliary context" in block.lower()
    assert "stale_source_version=True" in block
    assert "confirmed_fact_warning" in block


def test_facts_context_trace_records_fact_ids_for_audit():
    trace = _facts_trace([_fact("confirmed-1")])

    assert trace["facts_context_audit"]["session_id"] == "session-a"
    assert trace["facts_context_audit"]["requester_id"] == "requester-a"
    assert trace["facts_context_audit"]["facts_context_fact_ids"] == ["confirmed-1"]
    assert all(not fact_id.startswith(("E", "C")) for fact_id in trace["facts_context_fact_ids"])


def test_transcript_evidence_is_not_marked_as_facts_context():
    kernel = MemoryKernel.__new__(MemoryKernel)
    kernel.retrieval = _FakeFactsRetrieval([])
    request = KernelRequest(query="会议里有哪些行动项", session_id="session-a", filters={"document_id": "meeting-doc"})
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="meeting-1",
                document_id="meeting-doc",
                version_id="meeting-v1",
                text="meeting transcript evidence",
                metadata={"content_profile": "meeting_transcript"},
            )
        ],
        backend="fake",
        trace={"meeting_transcript_used": True, "transcript_as_fact": False},
    )
    scope_decision = DocumentScopeDecision(filters={"document_id": "meeting-doc"}, trace={}, allowed_document_ids=["meeting-doc"])
    trace = kernel._with_context_governance_trace(retrieval.trace, retrieval, scope_decision)
    trace = kernel._with_facts_context_trace(trace, request, retrieval, scope_decision)
    block = ContextBuilder().build(QueryRoute("enterprise_retrieval", True, "test"), RetrievalOutput(items=retrieval.items, backend="fake", trace=trace))

    assert trace["facts_context_used"] is False
    assert trace["facts_context_fact_ids"] == []
    assert trace["facts_as_answer"] is False
    assert "meeting_transcript_used=true" in block
    assert "Confirmed facts auxiliary context:" not in block
    assert "confirmed_fact:" not in block


def test_no_facts_outputs_false_flags_when_requested():
    trace = _facts_trace([])
    block = ContextBuilder().build(
        QueryRoute("enterprise_retrieval", True, "test"),
        RetrievalOutput(
            items=[KernelItem(chunk_id="retrieved-a", document_id="doc-a", version_id="v1", text="evidence")],
            backend="fake",
            trace=trace,
        ),
    )

    assert trace["facts_context_used"] is False
    assert trace["facts_context_fact_ids"] == []
    assert trace["facts_as_answer"] is False
    assert "Facts context diagnostics:" in block
    assert "Confirmed facts auxiliary context:" not in block
    assert "facts_context_used=false" in block


def test_stale_fact_diagnostic_can_run_without_retrieval_evidence():
    trace = _stale_diagnostic_trace([_fact("54e3926c-4d4f-4490-8068-bd53fcf23fa8"), _fact("9f98384b-5053-4a8f-9b83-35983b28b38e", stale=True)])

    assert trace["facts_context_used"] is True
    assert trace["facts_context_fact_ids"] == ["9f98384b-5053-4a8f-9b83-35983b28b38e"]
    assert trace["facts_context_diagnostic_only"] is True
    assert trace["facts_as_answer"] is False
    assert trace["stale_fact_source_count"] == 1


def test_facts_context_request_forces_enterprise_context_route():
    kernel = MemoryKernel.__new__(MemoryKernel)
    route = QueryRoute("chat", False, "general")
    request = KernelRequest(query="请检查 stale fact source", session_id="session-a")
    decision = DocumentScopeDecision(filters={}, trace={"facts_context_requested": True})

    routed = kernel._route_with_scope_requirement(route, decision, request)

    assert routed.needs_retrieval is True
    assert routed.route_type == "enterprise_retrieval"


def test_fact_answer_policy_query_suppresses_unscoped_retrieval():
    kernel = MemoryKernel.__new__(MemoryKernel)
    request = KernelRequest(query="phase224a 测试事实是否可以直接作为最终答案来源", session_id="session-a")
    decision = DocumentScopeDecision(filters={}, trace={})

    retrieval = kernel._retrieve_with_document_scope(request, QueryRoute("enterprise_retrieval", True, "test"), decision)

    assert retrieval.backend == "facts_policy_suppressed"
    assert retrieval.items == []
    assert retrieval.citations == []
    assert retrieval.trace["facts_answer_policy_query"] is True
    assert retrieval.trace["facts_context_suppressed_reason"] == "no_current_retrieval_evidence"


def test_unscoped_stale_fact_query_suppresses_unrelated_retrieval():
    kernel = MemoryKernel.__new__(MemoryKernel)
    request = KernelRequest(query="请检查 stale fact source", session_id="session-a")
    decision = DocumentScopeDecision(filters={}, trace={})

    retrieval = kernel._retrieve_with_document_scope(request, QueryRoute("enterprise_retrieval", True, "test"), decision)

    assert retrieval.backend == "facts_policy_suppressed"
    assert retrieval.items == []
    assert retrieval.citations == []
    assert retrieval.trace["facts_stale_policy_query"] is True


def test_context_block_strongly_forbids_facts_as_answer():
    trace = _facts_trace([_fact("confirmed-1")])
    block = ContextBuilder().build(
        QueryRoute("enterprise_retrieval", True, "test"),
        RetrievalOutput(
            items=[KernelItem(chunk_id="retrieved-a", document_id="doc-a", version_id="v1", text="evidence")],
            backend="fake",
            trace=trace,
        ),
    )

    assert "Never answer from facts alone" in block
    assert "Never treat retrieval chunks as facts" in block
    assert "facts_as_answer=false" in block


def test_alias_bind_retrieval_only_renders_empty_facts_invariant():
    trace = {
        "alias_resolution": {
            "status": "alias_bound",
            "alias": "会议纪要",
            "resolved_document_id": "meeting-doc",
            "resolved_title": "会议纪要",
        },
        "facts_context_used": False,
        "facts_context_fact_ids": [],
        "facts_as_answer": False,
        "meeting_transcript_used": True,
    }
    block = ContextBuilder().build(
        QueryRoute("enterprise_retrieval", True, "test"),
        RetrievalOutput(
            items=[
                KernelItem(
                    chunk_id="meeting-chunk-1",
                    document_id="meeting-doc",
                    version_id="meeting-v1",
                    text="meeting evidence",
                    metadata={"content_profile": "meeting_transcript"},
                )
            ],
            citations=[],
            backend="fake",
            trace=trace,
        ),
    )

    assert "Facts context diagnostics:" in block
    assert "facts_context_used=false" in block
    assert "facts_context_fact_ids=[]" in block
    assert "facts_as_answer=false" in block
    assert "Confirmed facts auxiliary context:" not in block
    assert "confirmed_fact:" not in block
    assert "meeting-chunk-1" not in block.split("facts_context_fact_ids=", 1)[1].split(";", 1)[0]
