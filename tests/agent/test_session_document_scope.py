from __future__ import annotations

from agent.memory_kernel.config import MemoryKernelConfig
from agent.memory_kernel.context_builder import ContextBuilder
from agent.memory_kernel.interfaces import KernelCitation, KernelItem, KernelRequest, KernelResult, QueryRoute, RetrievalOutput
from agent.memory_kernel.kernel import MemoryKernel
from agent.memory_kernel.session_document_scope import (
    DocumentScopeDecision,
    FileAliasBinding,
    ResolvedDocument,
    SessionDocumentScopeStore,
)


def _resolver(titles, filters):
    documents = {
        "A标书": ResolvedDocument(document_id="doc-a", title="A标书", version_id="v1"),
        "B标书": ResolvedDocument(document_id="doc-b", title="B标书", version_id="v2"),
    }
    return [documents[title] for title in titles if title in documents]


def test_session_document_scope_switches_a_b_a_in_same_session():
    store = SessionDocumentScopeStore()

    first = store.resolve(session_id="s1", query="请围绕《A标书》回答", filters={}, resolver=_resolver)
    second = store.resolve(session_id="s1", query="切到《B标书》继续", filters={}, resolver=_resolver)
    third = store.resolve(session_id="s1", query="切回《A标书》回答", filters={}, resolver=_resolver)

    assert first.filters["document_id"] == "doc-a"
    assert first.filters["version_id"] == "v1"
    assert first.trace["document_scope_changed"] is True
    assert second.filters["document_id"] == "doc-b"
    assert second.filters["version_id"] == "v2"
    assert second.trace["document_scope_changed"] is True
    assert third.filters["document_id"] == "doc-a"
    assert third.filters["version_id"] == "v1"
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
    assert decision.filters["version_id"] == "v2"
    assert decision.trace["alias_resolution"]["status"] == "alias_bound"
    assert decision.trace["resolved_document_id"] == "doc-b"
    assert decision.trace["alias_version_id"] == "v2"
    assert decision.trace["document_scope_source"] == "file_alias"


def test_active_document_state_preserves_version_id():
    store = SessionDocumentScopeStore()

    decision = store.resolve(session_id="s1", query="请围绕《A标书》回答", filters={}, resolver=_resolver)
    state = store.get("s1")

    assert state.active_document_id == "doc-a"
    assert state.active_document_version_id == "v1"
    assert decision.trace["active_document_version_id"] == "v1"


def test_session_file_alias_resolves_to_scoped_retrieval():
    store = SessionDocumentScopeStore()
    store.resolve(session_id="s1", query="把《A标书》设为 @主标书", filters={}, resolver=_resolver)
    store.resolve(session_id="s1", query="切到《B标书》继续", filters={}, resolver=_resolver)

    decision = store.resolve(session_id="s1", query="围绕 @主标书 回答总工期", filters={}, resolver=_resolver)

    assert decision.filters["document_id"] == "doc-a"
    assert decision.filters["version_id"] == "v1"
    assert decision.allowed_document_ids == ["doc-a"]
    assert decision.trace["scope_resolution_status"] == "alias_resolved"
    assert decision.trace["document_scope_changed"] is True
    assert decision.trace["alias_resolution"]["resolved_document_id"] == "doc-a"


def test_natural_import_alias_continuity_restores_across_api_session_drift():
    store = SessionDocumentScopeStore()
    store.set_continuity_owner(
        session_id="api-import-turn",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    store.set_continuity_owner(
        session_id="api-followup-drifted",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    pending = DocumentScopeDecision(
        filters={},
        trace={
            "scope_resolution_status": "alias_bind_pending_current_retrieval",
            "alias": "建筑类数据样表",
            "alias_continuity_source": "natural_import_success",
        },
    )

    stored = store.finalize_pending_alias_binding(
        session_id="api-import-turn",
        decision=pending,
        documents=[
            ResolvedDocument(
                document_id="doc-imported",
                title="建筑类数据样表.xlsx",
                version_id="ver-imported",
                source_name="建筑类数据样表.xlsx",
            )
        ],
    )
    decision = store.resolve(
        session_id="api-followup-drifted",
        query="围绕 @建筑类数据样表 总结这个文件，必须给出 citation",
        filters={},
        resolver=_resolver,
    )

    assert stored.trace["scope_resolution_status"] == "alias_bound"
    assert stored.trace["alias_continuity_status"] == "stored"
    assert decision.trace["scope_resolution_status"] == "alias_resolved"
    assert decision.trace["alias_resolution"]["status"] == "alias_resolved"
    assert decision.trace["alias_continuity_status"] == "restored"
    assert decision.trace["alias_continuity_source"] == "bounded_alias_registry"
    assert decision.trace["alias_continuity_owner_source"] == "gateway_session_key"
    assert decision.suppress_retrieval is False
    assert decision.filters["document_id"] == "doc-imported"
    assert decision.filters["version_id"] == "ver-imported"


def test_natural_import_alias_continuity_restores_after_store_reload(tmp_path):
    storage_path = tmp_path / "session_document_scope.json"
    store = SessionDocumentScopeStore(storage_path)
    store.set_continuity_owner(
        session_id="api-import-turn",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    store.finalize_pending_alias_binding(
        session_id="api-import-turn",
        decision=DocumentScopeDecision(
            filters={},
            trace={
                "scope_resolution_status": "alias_bind_pending_current_retrieval",
                "alias": "建筑类数据样表",
                "alias_continuity_source": "natural_import_success",
            },
        ),
        documents=[
            ResolvedDocument(
                document_id="doc-imported",
                title="建筑类数据样表.xlsx",
                version_id="ver-imported",
                source_name="建筑类数据样表.xlsx",
            )
        ],
    )

    reloaded = SessionDocumentScopeStore(storage_path)
    reloaded.set_continuity_owner(
        session_id="api-followup-drifted",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    decision = reloaded.resolve(
        session_id="api-followup-drifted",
        query="围绕 @建筑类数据样表 总结这个文件，必须给出 citation",
        filters={},
        resolver=_resolver,
    )

    assert decision.suppress_retrieval is False
    assert decision.filters["document_id"] == "doc-imported"
    assert decision.filters["version_id"] == "ver-imported"
    assert decision.trace["alias_continuity_status"] == "restored"
    assert decision.trace["alias_resolution"]["alias_continuity_status"] == "restored"
    assert decision.trace["alias_resolution"]["alias_continuity_owner_source"] == "gateway_session_key"
    assert decision.trace["alias_resolution"]["alias_continuity_persistent"] is True


def test_alias_continuity_different_owner_does_not_restore_imported_alias():
    store = SessionDocumentScopeStore()
    store.set_continuity_owner(
        session_id="api-import-turn",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    store.set_continuity_owner(
        session_id="api-followup-other",
        owner_value="gateway-chat-2",
        owner_source="gateway_session_key",
    )

    store.finalize_pending_alias_binding(
        session_id="api-import-turn",
        decision=DocumentScopeDecision(
            filters={},
            trace={
                "scope_resolution_status": "alias_bind_pending_current_retrieval",
                "alias": "建筑类数据样表",
                "alias_continuity_source": "natural_import_success",
            },
        ),
        documents=[
            ResolvedDocument(
                document_id="doc-imported",
                title="建筑类数据样表.xlsx",
                version_id="ver-imported",
                source_name="建筑类数据样表.xlsx",
            )
        ],
    )

    decision = store.resolve(
        session_id="api-followup-other",
        query="围绕 @建筑类数据样表 总结这个文件",
        filters={},
        resolver=_resolver,
    )

    assert decision.suppress_retrieval is True
    assert "document_id" not in decision.filters
    assert decision.trace["scope_resolution_status"] == "alias_missing"
    assert decision.trace["alias_continuity_status"] == "not_found"
    assert decision.trace["alias_continuity_owner_source"] == "gateway_session_key"
    assert decision.trace["alias_resolution"]["alias_continuity_status"] == "not_found"
    assert decision.trace["alias_resolution"]["alias_continuity_owner_source"] == "gateway_session_key"


def test_alias_missing_without_stable_owner_reports_stable_owner_missing():
    store = SessionDocumentScopeStore()

    decision = store.resolve(
        session_id="api-followup-drifted",
        query="围绕 @建筑类数据样表 总结这个文件，必须给出 citation",
        filters={},
        resolver=_resolver,
    )

    assert decision.suppress_retrieval is True
    assert decision.trace["alias_continuity_status"] == "not_found"
    assert decision.trace["alias_continuity_owner_source"] == "process_local_fallback"
    assert decision.trace["alias_continuity_persistent"] is False
    assert decision.trace["alias_resolution"]["alias_continuity_status"] == "not_found"
    assert decision.trace["alias_resolution"]["alias_continuity_owner_source"] == "process_local_fallback"
    assert decision.trace["alias_resolution"]["alias_continuity_persistent"] is False
    assert decision.trace["stable_owner_missing"] is True
    assert decision.trace["alias_resolution"]["stable_owner_missing"] is True


def test_alias_continuity_conflict_fails_closed_after_store_reload(tmp_path):
    storage_path = tmp_path / "session_document_scope.json"
    store = SessionDocumentScopeStore(storage_path)
    store.set_continuity_owner(
        session_id="api-import-turn-1",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    for session_id, document_id, version_id in (
        ("api-import-turn-1", "doc-imported-1", "ver-imported-1"),
        ("api-import-turn-2", "doc-imported-2", "ver-imported-2"),
    ):
        store.set_continuity_owner(
            session_id=session_id,
            owner_value="gateway-chat-1",
            owner_source="gateway_session_key",
        )
        store.finalize_pending_alias_binding(
            session_id=session_id,
            decision=DocumentScopeDecision(
                filters={},
                trace={
                    "scope_resolution_status": "alias_bind_pending_current_retrieval",
                    "alias": "建筑类数据样表",
                    "alias_continuity_source": "natural_import_success",
                },
            ),
            documents=[
                ResolvedDocument(
                    document_id=document_id,
                    title="建筑类数据样表.xlsx",
                    version_id=version_id,
                    source_name="建筑类数据样表.xlsx",
                )
            ],
        )

    reloaded = SessionDocumentScopeStore(storage_path)
    reloaded.set_continuity_owner(
        session_id="api-followup-drifted",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    decision = reloaded.resolve(
        session_id="api-followup-drifted",
        query="围绕 @建筑类数据样表 总结这个文件",
        filters={},
        resolver=_resolver,
    )

    assert decision.suppress_retrieval is True
    assert "document_id" not in decision.filters
    assert decision.trace["scope_resolution_status"] == "alias_continuity_conflict"
    assert decision.trace["alias_continuity_status"] == "conflict"
    assert decision.trace["alias_resolution"]["alias_continuity_status"] == "conflict"
    assert decision.trace["alias_resolution"]["alias_continuity_owner_source"] == "gateway_session_key"


def test_unscoped_alias_continuity_fallback_is_not_persisted_across_store_load(tmp_path):
    scope_path = tmp_path / "scope.json"
    first_store = SessionDocumentScopeStore(scope_path)
    first_store.finalize_pending_alias_binding(
        session_id="api-import-turn",
        decision=DocumentScopeDecision(
            filters={},
            trace={
                "scope_resolution_status": "alias_bind_pending_current_retrieval",
                "alias": "建筑类数据样表",
                "alias_continuity_source": "natural_import_success",
            },
        ),
        documents=[
            ResolvedDocument(
                document_id="doc-imported",
                title="建筑类数据样表.xlsx",
                version_id="ver-imported",
                source_name="建筑类数据样表.xlsx",
            )
        ],
    )

    resumed_store = SessionDocumentScopeStore(scope_path)
    decision = resumed_store.resolve(
        session_id="api-followup-drifted",
        query="围绕 @建筑类数据样表 总结这个文件",
        filters={},
        resolver=_resolver,
    )

    assert decision.suppress_retrieval is True
    assert "document_id" not in decision.filters
    assert decision.trace["scope_resolution_status"] == "alias_missing"
    assert decision.trace["alias_continuity_status"] == "not_found"


def test_expired_alias_continuity_does_not_restore():
    store = SessionDocumentScopeStore()
    store.set_continuity_owner(
        session_id="api-import-turn",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    store.set_continuity_owner(
        session_id="api-followup-drifted",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    store.finalize_pending_alias_binding(
        session_id="api-import-turn",
        decision=DocumentScopeDecision(
            filters={},
            trace={
                "scope_resolution_status": "alias_bind_pending_current_retrieval",
                "alias": "建筑类数据样表",
                "alias_continuity_source": "natural_import_success",
            },
        ),
        documents=[
            ResolvedDocument(
                document_id="doc-imported",
                title="建筑类数据样表.xlsx",
                version_id="ver-imported",
                source_name="建筑类数据样表.xlsx",
            )
        ],
    )
    owner = next(iter(store._alias_continuity))
    store._alias_continuity[owner]["建筑类数据样表"][0] = FileAliasBinding(
        alias="建筑类数据样表",
        document_id="doc-imported",
        title="建筑类数据样表.xlsx",
        version_id="ver-imported",
        source_name="建筑类数据样表.xlsx",
        alias_scope="continuity",
        scope_source="natural_import_success",
        updated_at="2000-01-01T00:00:00+00:00",
        continuity_owner_key=owner,
        continuity_owner_source="gateway_session_key",
        continuity_persistent=True,
        expires_at="2000-01-01T00:00:00+00:00",
    )

    decision = store.resolve(
        session_id="api-followup-drifted",
        query="围绕 @建筑类数据样表 总结这个文件",
        filters={},
        resolver=_resolver,
    )

    assert decision.suppress_retrieval is True
    assert decision.trace["scope_resolution_status"] == "alias_missing"
    assert decision.trace["alias_continuity_status"] == "expired"


def test_alias_continuity_conflict_suppresses_retrieval():
    store = SessionDocumentScopeStore()
    store.set_continuity_owner(
        session_id="api-import-a",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    store.set_continuity_owner(
        session_id="api-import-b",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    store.set_continuity_owner(
        session_id="api-followup-drifted",
        owner_value="gateway-chat-1",
        owner_source="gateway_session_key",
    )
    for session_id, document_id, version_id in (
        ("api-import-a", "doc-a", "v1"),
        ("api-import-b", "doc-b", "v2"),
    ):
        store.finalize_pending_alias_binding(
            session_id=session_id,
            decision=DocumentScopeDecision(
                filters={},
                trace={
                    "scope_resolution_status": "alias_bind_pending_current_retrieval",
                    "alias": "建筑类数据样表",
                    "alias_continuity_source": "natural_import_success",
                },
            ),
            documents=[
                ResolvedDocument(
                    document_id=document_id,
                    title=f"{document_id}.xlsx",
                    version_id=version_id,
                    source_name=f"{document_id}.xlsx",
                )
            ],
        )

    decision = store.resolve(
        session_id="api-followup-drifted",
        query="围绕 @建筑类数据样表 总结这个文件",
        filters={},
        resolver=_resolver,
    )

    assert decision.suppress_retrieval is True
    assert "document_id" not in decision.filters
    assert decision.allowed_document_ids == []
    assert decision.trace["scope_resolution_status"] == "alias_continuity_conflict"
    assert decision.trace["alias_resolution"]["status"] == "alias_continuity_conflict"
    assert decision.trace["alias_continuity_status"] == "conflict"
    assert decision.trace["alias_missing"] is False
    assert decision.trace["alias_conflict"] is True
    assert decision.trace["alias_continuity_owner_source"] == "gateway_session_key"
    candidates = decision.trace["alias_continuity_candidates"]
    assert {candidate["document_id"] for candidate in candidates} == {"doc-a", "doc-b"}
    assert all("tmp/" not in str(candidate) and "Users/" not in str(candidate) for candidate in candidates)
    assert "gateway-chat-1" not in str(decision.trace)


def test_stale_alias_maps_version_scope_to_alias_trace():
    store = SessionDocumentScopeStore()
    store.resolve(session_id="s1", query="把《A标书》设为 @版本测试", filters={}, resolver=_resolver)
    decision = store.resolve(session_id="s1", query="围绕 @版本测试 回答", filters={}, resolver=_resolver)
    retrieval = RetrievalOutput(
        items=[KernelItem(chunk_id="a-old", document_id="doc-a", version_id="v1", text="old evidence")],
        citations=[KernelCitation(document_id="doc-a", version_id="v1", chunk_id="a-old")],
        backend="fake",
        trace={
            "retrieval_trace": {
                "version_scope": {
                    "stale_version": True,
                    "version_id": "v1",
                    "latest_version_id": "v2",
                    "superseded_by_version_id": "v2",
                    "version_policy": "explicit_history_version",
                }
            }
        },
    )
    kernel = MemoryKernel.__new__(MemoryKernel)

    trace = kernel._with_context_governance_trace(retrieval.trace, retrieval, decision)

    assert decision.filters["version_id"] == "v1"
    assert trace["alias_stale_version"] is True
    assert trace["alias_resolution"]["alias_stale_version"] is True
    assert trace["alias_resolution"]["latest_version_id"] == "v2"
    assert trace["alias_resolution"]["superseded_by_version_id"] == "v2"


def test_latest_alias_does_not_report_stale():
    store = SessionDocumentScopeStore()
    store.resolve(session_id="s1", query="把《A标书》设为 @版本测试", filters={}, resolver=_resolver)
    decision = store.resolve(session_id="s1", query="围绕 @版本测试 回答", filters={}, resolver=_resolver)
    retrieval = RetrievalOutput(
        items=[KernelItem(chunk_id="a-new", document_id="doc-a", version_id="v1", text="latest evidence")],
        backend="fake",
        trace={"retrieval_trace": {"version_scope": {"stale_version": False, "version_id": "v1"}}},
    )
    kernel = MemoryKernel.__new__(MemoryKernel)

    trace = kernel._with_context_governance_trace(retrieval.trace, retrieval, decision)

    assert trace["alias_stale_version"] is False
    assert trace["alias_resolution"]["alias_stale_version"] is False


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
    assert decision.trace["compare_version_ids"] == ["v1", "v2"]


def test_compare_mode_surfaces_one_sided_stale_alias_trace():
    class FakeRetrieval:
        def __init__(self):
            self.requests = []

        def retrieve(self, request, route):
            self.requests.append(request)
            version_id = request.filters.get("version_id")
            document_id = request.filters["document_id"]
            stale = document_id == "doc-a"
            version_scope = {
                "stale_version": stale,
                "version_id": version_id,
                "latest_version_id": "v-latest-a" if stale else version_id,
                "superseded_by_version_id": "v-latest-a" if stale else None,
            }
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id=f"{document_id}-1",
                        document_id=document_id,
                        version_id=version_id or "latest",
                        text=f"{document_id} evidence",
                    )
                ],
                backend="fake",
                trace={"retrieval_trace": {"version_scope": version_scope}},
            )

    store = SessionDocumentScopeStore()
    decision = store.resolve(session_id="s1", query="把《A标书》设为 @旧标书", filters={}, resolver=_resolver)
    assert decision.trace["alias_version_id"] == "v1"
    store.resolve(session_id="s1", query="把《B标书》设为 @新标书", filters={}, resolver=_resolver)
    compare_decision = store.resolve(session_id="s1", query="对比 @旧标书 和 @新标书", filters={}, resolver=_resolver)

    kernel = MemoryKernel.__new__(MemoryKernel)
    kernel.retrieval = FakeRetrieval()
    retrieval = kernel._retrieve_multi_document_scope(
        KernelRequest(query="对比 @旧标书 和 @新标书", session_id="s1", document_scope=compare_decision.trace),
        QueryRoute("enterprise_retrieval", True, "test"),
        compare_decision,
    )
    trace = kernel._with_context_governance_trace(retrieval.trace, retrieval, compare_decision)

    assert [request.filters["version_id"] for request in kernel.retrieval.requests] == ["v1", "v2"]
    assert trace["alias_stale_version"] is True
    assert trace["compare_alias_stale_versions"] == [
        {
            "alias": "旧标书",
            "document_id": "doc-a",
            "alias_version_id": "v1",
            "latest_version_id": "v-latest-a",
            "superseded_by_version_id": "v-latest-a",
        }
    ]


def test_session_file_alias_persists_across_store_instances(tmp_path):
    storage_path = tmp_path / "session_document_scope.json"
    first_store = SessionDocumentScopeStore(storage_path=storage_path)
    first_store.resolve(session_id="s1", query="把《A标书》设为 @主标书", filters={}, resolver=_resolver)

    resumed_store = SessionDocumentScopeStore(storage_path=storage_path)
    decision = resumed_store.resolve(session_id="s1", query="围绕 @主标书 回答总工期", filters={}, resolver=_resolver)

    assert decision.filters["document_id"] == "doc-a"
    assert decision.trace["scope_resolution_status"] == "alias_resolved"
    assert decision.trace["alias_resolution"]["resolved_document_id"] == "doc-a"


def test_session_file_alias_compare_persists_across_store_instances(tmp_path):
    storage_path = tmp_path / "session_document_scope.json"
    first_store = SessionDocumentScopeStore(storage_path=storage_path)
    first_store.resolve(session_id="s1", query="把《A标书》设为 @主标书", filters={}, resolver=_resolver)
    first_store.resolve(session_id="s1", query="把《B标书》设为 @交付标准", filters={}, resolver=_resolver)

    resumed_store = SessionDocumentScopeStore(storage_path=storage_path)
    decision = resumed_store.resolve(session_id="s1", query="对比 @主标书 和 @交付标准", filters={}, resolver=_resolver)

    assert decision.cross_document_allowed is True
    assert decision.allowed_document_ids == ["doc-a", "doc-b"]
    assert decision.trace["scope_resolution_status"] == "multi_document_alias_resolved"
    assert decision.trace["compare_document_ids"] == ["doc-a", "doc-b"]
    assert decision.trace["compare_version_ids"] == ["v1", "v2"]


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


def test_session_file_alias_title_bind_falls_back_to_same_turn_retrieval(tmp_path):
    class FakeRetrieval:
        def __init__(self):
            self.requests = []

        def resolve_document_titles(self, titles, filters):
            return []

        def retrieve(self, request, route):
            self.requests.append(request)
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id="hw1",
                        document_id="doc-hardware",
                        version_id="v-hardware",
                        text="硬件清单 evidence",
                        source_name="硬件清单",
                    )
                ],
                citations=[
                    KernelCitation(
                        document_id="doc-hardware",
                        version_id="v-hardware",
                        chunk_id="hw1",
                        source_name="硬件清单",
                    )
                ],
                backend="fake",
            )

    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(tmp_path / "scope.json")
    fake_retrieval = FakeRetrieval()
    kernel.retrieval = fake_retrieval

    result = kernel.start_turn(KernelRequest(query="把《硬件清单》设为 @硬件清单", session_id="s1"))
    decision = kernel.resolve_document_scope(session_id="s1", query="围绕 @硬件清单 回答总价", filters={})

    assert fake_retrieval.requests
    assert fake_retrieval.requests[0].document_scope["scope_resolution_status"] == "alias_bind_pending_title_retrieval"
    assert result.trace["alias_resolution"]["status"] == "alias_bound"
    assert result.trace["alias_resolution"]["resolved_document_id"] == "doc-hardware"
    assert result.trace["alias_resolution"]["resolved_title"] == "硬件清单"
    assert decision.filters["document_id"] == "doc-hardware"
    assert decision.filters["version_id"] == "v-hardware"


def test_session_file_alias_unquoted_meeting_file_bind_falls_back_to_retrieval(tmp_path):
    class FakeRetrieval:
        def __init__(self):
            self.requests = []

        def resolve_document_titles(self, titles, filters):
            return []

        def retrieve(self, request, route):
            self.requests.append(request)
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id="meeting-1",
                        document_id="doc-meeting",
                        version_id="v-meeting",
                        text="会议纪要 evidence",
                        source_name="会议纪要",
                    )
                ],
                citations=[
                    KernelCitation(
                        document_id="doc-meeting",
                        version_id="v-meeting",
                        chunk_id="meeting-1",
                        source_name="会议纪要",
                    )
                ],
                backend="fake",
            )

    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(tmp_path / "scope.json")
    fake_retrieval = FakeRetrieval()
    kernel.retrieval = fake_retrieval

    result = kernel.start_turn(KernelRequest(query="把会议纪要文件设为 @会议纪要", session_id="s1"))
    decision = kernel.resolve_document_scope(session_id="s1", query="围绕 @会议纪要 提取行动项", filters={})

    assert fake_retrieval.requests
    assert fake_retrieval.requests[0].document_scope["scope_resolution_status"] == "alias_bind_pending_title_retrieval"
    assert result.trace["alias_resolution"]["status"] == "alias_bound"
    assert result.trace["alias_resolution"]["resolved_document_id"] == "doc-meeting"
    assert decision.filters["document_id"] == "doc-meeting"
    assert decision.filters["version_id"] == "v-meeting"


def test_session_file_alias_unquoted_hardware_bind_resolves_later_query(tmp_path):
    class FakeRetrieval:
        def resolve_document_titles(self, titles, filters):
            return []

        def retrieve(self, request, route):
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id="hardware-1",
                        document_id="doc-hardware",
                        version_id="v-hardware",
                        text="硬件清单 evidence",
                        source_name="硬件清单",
                    )
                ],
                citations=[
                    KernelCitation(
                        document_id="doc-hardware",
                        version_id="v-hardware",
                        chunk_id="hardware-1",
                        source_name="硬件清单",
                    )
                ],
                backend="fake",
            )

    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(tmp_path / "scope.json")
    kernel.retrieval = FakeRetrieval()

    result = kernel.start_turn(KernelRequest(query="把硬件清单设为 @硬件清单", session_id="s1"))
    decision = kernel.resolve_document_scope(session_id="s1", query="围绕 @硬件清单 查询设备金额", filters={})

    assert result.trace["alias_resolution"]["status"] == "alias_bound"
    assert result.trace["alias_resolution"]["resolved_document_id"] == "doc-hardware"
    assert decision.trace["scope_resolution_status"] == "alias_resolved"
    assert decision.filters["document_id"] == "doc-hardware"


def test_session_file_alias_unquoted_pptx_title_bind_falls_back_to_retrieval(tmp_path):
    class FakeRetrieval:
        def resolve_document_titles(self, titles, filters):
            return []

        def retrieve(self, request, route):
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id="pptx-1",
                        document_id="doc-ctower",
                        version_id="v-ctower",
                        text="C塔方案 evidence",
                        source_name="C塔方案",
                    )
                ],
                citations=[
                    KernelCitation(
                        document_id="doc-ctower",
                        version_id="v-ctower",
                        chunk_id="pptx-1",
                        source_name="C塔方案",
                    )
                ],
                backend="fake",
            )

    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(tmp_path / "scope.json")
    kernel.retrieval = FakeRetrieval()

    result = kernel.start_turn(KernelRequest(query="把C塔方案设为 @C塔方案", session_id="s1"))
    decision = kernel.resolve_document_scope(session_id="s1", query="围绕 @C塔方案 查询第一页", filters={})

    assert result.trace["alias_resolution"]["status"] == "alias_bound"
    assert result.trace["alias_resolution"]["resolved_document_id"] == "doc-ctower"
    assert decision.filters["document_id"] == "doc-ctower"
    assert decision.filters["version_id"] == "v-ctower"


def test_session_file_alias_current_main_tender_binds_active_document_without_title_lookup():
    class Resolver:
        def __init__(self):
            self.calls = []

        def __call__(self, titles, filters):
            self.calls.append((titles, filters))
            return _resolver(titles, filters)

    store = SessionDocumentScopeStore()
    resolver = Resolver()
    store.resolve(session_id="s1", query="请围绕《A标书》回答", filters={}, resolver=resolver)
    resolver.calls.clear()

    decision = store.resolve(session_id="s1", query="把当前主标书设为 @主标书", filters={}, resolver=resolver)

    assert resolver.calls == []
    assert decision.trace["alias_resolution"]["status"] == "alias_bound"
    assert decision.trace["alias_resolution"]["resolved_document_id"] == "doc-a"
    assert decision.trace["alias_version_id"] == "v1"
    assert decision.filters["document_id"] == "doc-a"
    assert decision.filters["version_id"] == "v1"


def test_session_file_alias_previous_locked_current_file_binds_active_document_without_title_lookup():
    class Resolver:
        def __init__(self):
            self.calls = []

        def __call__(self, titles, filters):
            self.calls.append((titles, filters))
            return _resolver(titles, filters)

    store = SessionDocumentScopeStore()
    resolver = Resolver()
    store.resolve(session_id="s1", query="请围绕《A标书》回答", filters={}, resolver=resolver)
    resolver.calls.clear()

    decision = store.resolve(
        session_id="s1",
        query="请把上一轮已锁定的当前文件设为 @主标书",
        filters={},
        resolver=resolver,
    )

    assert resolver.calls == []
    assert decision.trace["alias_resolution"]["status"] == "alias_bound"
    assert decision.trace["alias_resolution"]["resolved_document_id"] == "doc-a"
    assert decision.trace["alias_version_id"] == "v1"
    assert decision.filters["document_id"] == "doc-a"
    assert decision.filters["version_id"] == "v1"


def test_session_file_alias_current_tender_without_active_document_uses_retrieval_fallback(tmp_path):
    class FakeRetrieval:
        def __init__(self):
            self.requests = []

        def resolve_document_titles(self, titles, filters):
            return []

        def retrieve(self, request, route):
            self.requests.append(request)
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id="tender-1",
                        document_id="doc-a",
                        version_id="v1",
                        text="A evidence",
                        source_name="A标书",
                    )
                ],
                citations=[KernelCitation(document_id="doc-a", version_id="v1", chunk_id="tender-1", source_name="A标书")],
                backend="fake",
            )

    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(tmp_path / "scope.json")
    fake_retrieval = FakeRetrieval()
    kernel.retrieval = fake_retrieval

    result = kernel.start_turn(KernelRequest(query="把当前标书设为 @主标书", session_id="s1"))

    assert fake_retrieval.requests
    assert fake_retrieval.requests[0].document_scope["scope_resolution_status"] == "alias_bind_pending_current_retrieval"
    assert result.trace["alias_resolution"]["status"] == "alias_bound"
    assert result.trace["alias_resolution"]["resolved_document_id"] == "doc-a"


def test_natural_import_seeded_alias_persists_and_scopes_same_session_retrieval(tmp_path):
    scope_path = tmp_path / "scope.json"
    store = SessionDocumentScopeStore(scope_path)
    decision = DocumentScopeDecision(
        filters={},
        trace={
            "scope_resolution_status": "alias_bind_pending_current_retrieval",
            "alias": "建筑类数据样表",
        },
    )

    bound = store.finalize_pending_alias_binding(
        session_id="natural-import-session",
        decision=decision,
        documents=[
            ResolvedDocument(
                document_id="doc-imported",
                title="建筑类数据样表.xlsx",
                version_id="ver-imported",
                source_name="建筑类数据样表.xlsx",
            )
        ],
    )
    resumed = SessionDocumentScopeStore(scope_path).resolve(
        session_id="natural-import-session",
        query="围绕 @建筑类数据样表 总结这个文件的主要内容，必须给出 citation",
        filters={},
        resolver=_resolver,
    )

    assert bound.trace["alias_resolution"]["status"] == "alias_bound"
    assert bound.trace["active_document_id"] == "doc-imported"
    assert resumed.trace["alias_resolution"]["status"] == "alias_resolved"
    assert resumed.filters["document_id"] == "doc-imported"
    assert resumed.filters["version_id"] == "ver-imported"
    assert resumed.allowed_document_ids == ["doc-imported"]


def test_existing_natural_import_alias_title_bind_does_not_fail_when_resolver_misses(tmp_path):
    scope_path = tmp_path / "scope.json"
    store = SessionDocumentScopeStore(scope_path)
    decision = DocumentScopeDecision(
        filters={},
        trace={
            "scope_resolution_status": "alias_bind_pending_current_retrieval",
            "alias": "建筑类数据样表",
        },
    )
    store.finalize_pending_alias_binding(
        session_id="s1",
        decision=decision,
        documents=[
            ResolvedDocument(
                document_id="doc-imported",
                title="建筑类数据样表.xlsx",
                version_id="ver-imported",
                source_name="建筑类数据样表.xlsx",
            )
        ],
    )

    rebound = store.resolve(
        session_id="s1",
        query="把《建筑类数据样表》设为 @建筑类数据样表",
        filters={},
        resolver=lambda titles, filters: [],
    )
    followup = store.resolve(
        session_id="s1",
        query="围绕 @建筑类数据样表 总结内容",
        filters={},
        resolver=lambda titles, filters: [],
    )

    assert rebound.trace["alias_resolution"]["status"] == "alias_bound"
    assert rebound.trace["alias_bind_failure_reason"] is None
    assert rebound.filters["document_id"] == "doc-imported"
    assert rebound.filters["version_id"] == "ver-imported"
    assert followup.trace["alias_resolution"]["status"] == "alias_resolved"
    assert followup.suppress_retrieval is False


def test_session_file_alias_current_tender_uses_top_document_when_retrieval_has_other_candidates(tmp_path):
    class FakeRetrieval:
        def __init__(self):
            self.requests = []

        def resolve_document_titles(self, titles, filters):
            return []

        def retrieve(self, request, route):
            self.requests.append(request)
            document_id = request.filters.get("document_id")
            if document_id:
                return RetrievalOutput(
                    items=[
                        KernelItem(
                            chunk_id=f"{document_id}-1",
                            document_id=document_id,
                            version_id="v-main",
                            text="scoped main tender evidence",
                            source_name="主标书",
                        )
                    ],
                    citations=[
                        KernelCitation(
                            document_id=document_id,
                            version_id="v-main",
                            chunk_id=f"{document_id}-1",
                            source_name="主标书",
                        )
                    ],
                    backend="fake",
                )
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id="main-1",
                        document_id="doc-main",
                        version_id="v-main",
                        text="主标书 evidence",
                        source_name="主标书",
                    ),
                    KernelItem(
                        chunk_id="other-1",
                        document_id="doc-other",
                        version_id="v-other",
                        text="other evidence",
                        source_name="其他文件",
                    ),
                ],
                citations=[
                    KernelCitation(
                        document_id="doc-main",
                        version_id="v-main",
                        chunk_id="main-1",
                        source_name="主标书",
                    ),
                    KernelCitation(
                        document_id="doc-other",
                        version_id="v-other",
                        chunk_id="other-1",
                        source_name="其他文件",
                    ),
                ],
                backend="fake",
            )

    scope_path = tmp_path / "scope.json"
    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(scope_path)
    fake_retrieval = FakeRetrieval()
    kernel.retrieval = fake_retrieval

    result = kernel.start_turn(KernelRequest(query="把当前主标书设为 @主标书", session_id="s1"))
    resumed_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    resumed_kernel.document_scope = SessionDocumentScopeStore(scope_path)
    resumed_kernel.retrieval = fake_retrieval
    resumed = resumed_kernel.start_turn(KernelRequest(query="围绕 @主标书 回答工程名称", session_id="s1"))

    assert result.trace["alias_resolution"]["status"] == "alias_bound"
    assert result.trace["alias_resolution"]["resolved_document_id"] == "doc-main"
    assert result.trace["alias_resolution"]["alias_version_id"] == "v-main"
    assert result.trace["alias_resolution"]["ambiguous_retrieval_document_ids"] == ["doc-main", "doc-other"]
    assert resumed.trace["alias_resolution"]["status"] == "alias_resolved"
    assert resumed.trace["alias_missing"] is False
    assert resumed.trace.get("retrieval_suppressed") is not True
    assert fake_retrieval.requests[-1].filters["document_id"] == "doc-main"
    assert fake_retrieval.requests[-1].filters["version_id"] == "v-main"


def test_session_file_discovery_returns_safe_alias_candidates_without_retrieval():
    store = SessionDocumentScopeStore()
    store.resolve(session_id="s1", query="把《A标书》设为 @C塔招标文件", filters={}, resolver=_resolver)
    store.resolve(session_id="s1", query="把《B标书》设为 @C塔招标清单", filters={}, resolver=_resolver)

    decision = store.resolve(
        session_id="s1",
        query="C塔项目的招标要求文件你帮我找出来",
        filters={},
        resolver=_resolver,
    )

    assert decision.suppress_retrieval is True
    assert decision.trace["scope_resolution_status"] == "file_discovery_candidates"
    assert decision.trace["file_discovery_requires_clarification"] is True
    assert [candidate["alias"] for candidate in decision.trace["file_candidates"]] == [
        "C塔招标文件",
        "C塔招标清单",
    ]
    assert "document_id" not in decision.filters


def test_session_file_discovery_matches_workspace_context_metadata():
    store = SessionDocumentScopeStore()
    store._session_aliases("s1")["C塔人力成本测算表"] = FileAliasBinding(
        alias="C塔人力成本测算表",
        document_id="doc-cost",
        title="C塔项目人力配置及成本测算表0506.xlsx",
        version_id="v-cost",
        source_name="C塔项目人力配置及成本测算表0506.xlsx",
        workspace_id="ws-ctower",
        workspace_name="C塔项目",
        workspace_type="project",
        document_category="人力配置 / 成本测算",
        workspace_confidence="high",
        workspace_needs_user_confirmation=False,
    )
    store._session_aliases("s1")["C塔主标书"] = FileAliasBinding(
        alias="C塔主标书",
        document_id="doc-tender",
        title="C塔项目招标文件.docx",
        version_id="v-tender",
        source_name="C塔项目招标文件.docx",
        workspace_id="ws-ctower",
        workspace_name="C塔项目",
        workspace_type="project",
        document_category="招标资料",
        workspace_confidence="high",
        workspace_needs_user_confirmation=False,
    )

    decision = store.resolve(
        session_id="s1",
        query="帮我找 C塔项目的人力成本表",
        filters={},
        resolver=lambda titles, filters: [],
    )

    assert decision.trace["scope_resolution_status"] == "file_discovery_candidates"
    assert decision.suppress_retrieval is True
    assert decision.trace["file_discovery_requires_clarification"] is True
    assert decision.trace["file_candidates"][0]["alias"] == "C塔人力成本测算表"
    assert decision.trace["file_candidates"][0]["workspace_name"] == "C塔项目"
    assert decision.trace["file_candidates"][0]["document_category"] == "人力配置 / 成本测算"


def test_session_file_discovery_no_candidate_suppresses_retrieval_with_missing_evidence_boundary():
    store = SessionDocumentScopeStore()

    decision = store.resolve(
        session_id="s1",
        query="帮我找一下C塔项目那份文件",
        filters={},
        resolver=_resolver,
    )

    assert decision.suppress_retrieval is True
    assert decision.trace["scope_resolution_status"] == "file_discovery_no_safe_candidate"
    assert decision.trace["file_discovery_requires_clarification"] is True
    assert decision.trace["file_candidates"] == []
    assert decision.trace["no_safe_file_candidate"] is True
    assert decision.trace["requires_retrieval_evidence"] is True
    assert decision.trace["missing_evidence_policy"] == "Missing Evidence"
    assert "document_id" not in decision.filters


def test_session_file_discovery_does_not_suppress_ordinary_content_lookup():
    store = SessionDocumentScopeStore()

    for query in [
        "帮我找一下工程地点",
        "帮我找一下主标书里的工期要求",
        "帮我查一下付款比例",
        "找一下这份表里的数量",
    ]:
        decision = store.resolve(session_id=f"s-{query}", query=query, filters={}, resolver=_resolver)

        assert decision.suppress_retrieval is False
        assert decision.trace["scope_resolution_status"] == "unscoped"
        assert decision.trace["scope_resolution_status"] != "file_discovery_no_safe_candidate"


def test_session_file_discovery_preserves_clear_file_candidate_queries():
    store = SessionDocumentScopeStore()

    for query in [
        "C塔项目的招标要求文件你帮我找出来",
        "帮我找 C塔项目相关文件",
        "有哪些 C塔项目人力配置相关文件",
    ]:
        decision = store.resolve(session_id=f"s-{query}", query=query, filters={}, resolver=_resolver)

        assert decision.suppress_retrieval is True
        assert decision.trace["scope_resolution_status"] == "file_discovery_no_safe_candidate"
        assert decision.trace["file_discovery_requires_clarification"] is True
        assert decision.trace["file_candidates"] == []


def test_session_file_alias_title_bind_still_rejects_ambiguous_retrieval(tmp_path):
    class FakeRetrieval:
        def __init__(self):
            self.requests = []

        def resolve_document_titles(self, titles, filters):
            return []

        def retrieve(self, request, route):
            self.requests.append(request)
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id="a-1",
                        document_id="doc-a",
                        version_id="v1",
                        text="A evidence",
                        source_name="A标书",
                    ),
                    KernelItem(
                        chunk_id="b-1",
                        document_id="doc-b",
                        version_id="v2",
                        text="B evidence",
                        source_name="B标书",
                    ),
                ],
                backend="fake",
            )

    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(tmp_path / "scope.json")
    fake_retrieval = FakeRetrieval()
    kernel.retrieval = fake_retrieval

    result = kernel.start_turn(KernelRequest(query="把《泛化文件》设为 @测试文件", session_id="s1"))

    assert fake_retrieval.requests
    assert result.trace["alias_resolution"]["status"] == "alias_bind_failed"
    assert result.trace["alias_resolution"]["bind_failure_reason"] == "ambiguous_title_retrieval"


def test_session_file_alias_previous_locked_current_file_fallback_persists_across_store_instances(tmp_path):
    class FakeRetrieval:
        def __init__(self):
            self.requests = []

        def resolve_document_titles(self, titles, filters):
            return []

        def retrieve(self, request, route):
            self.requests.append(request)
            document_id = request.filters.get("document_id") or "doc-a"
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id=f"{document_id}-1",
                        document_id=document_id,
                        version_id="v1",
                        text="A evidence",
                        source_name="A标书",
                    )
                ],
                citations=[
                    KernelCitation(
                        document_id=document_id,
                        version_id="v1",
                        chunk_id=f"{document_id}-1",
                        source_name="A标书",
                    )
                ],
                backend="fake",
            )

    scope_path = tmp_path / "scope.json"
    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(scope_path)
    fake_retrieval = FakeRetrieval()
    kernel.retrieval = fake_retrieval

    result = kernel.start_turn(KernelRequest(query="请把上一轮已锁定的当前文件设为 @主标书", session_id="s1"))

    assert fake_retrieval.requests
    assert fake_retrieval.requests[0].document_scope["scope_resolution_status"] == "alias_bind_pending_current_retrieval"
    assert result.trace["alias_resolution"]["status"] == "alias_bound"
    assert result.trace["alias_resolution"]["resolved_document_id"] == "doc-a"

    kernel_after_resume = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel_after_resume.document_scope = SessionDocumentScopeStore(scope_path)
    kernel_after_resume.retrieval = fake_retrieval
    resumed = kernel_after_resume.start_turn(KernelRequest(query="围绕 @主标书 回答", session_id="s1"))

    assert resumed.trace["alias_resolution"]["status"] == "alias_resolved"
    assert resumed.trace["alias_resolution"]["resolved_document_id"] == "doc-a"
    assert resumed.trace["alias_missing"] is False
    assert resumed.trace.get("retrieval_suppressed") is not True
    assert fake_retrieval.requests[-1].filters["document_id"] == "doc-a"
    assert fake_retrieval.requests[-1].filters["version_id"] == "v1"


def test_run_agent_pre_resolved_previous_locked_current_alias_persists_for_resume(tmp_path):
    class FakeRetrieval:
        def __init__(self):
            self.requests = []

        def resolve_document_titles(self, titles, filters):
            return []

        def retrieve(self, request, route):
            self.requests.append(request)
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id="doc-a-1",
                        document_id="doc-a",
                        version_id="v1",
                        text="A evidence",
                        source_name="A标书",
                    )
                ],
                citations=[
                    KernelCitation(
                        document_id="doc-a",
                        version_id="v1",
                        chunk_id="doc-a-1",
                        source_name="A标书",
                    )
                ],
                backend="fake",
            )

    scope_path = tmp_path / "scope.json"
    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(scope_path)
    fake_retrieval = FakeRetrieval()
    kernel.retrieval = fake_retrieval
    query = "请把上一轮已锁定的当前文件设为 @主标书"
    pre_resolved_scope = kernel.resolve_document_scope(session_id="s1", query=query, filters={})

    result = kernel.start_turn(
        KernelRequest(
            query=query,
            session_id="s1",
            document_scope=pre_resolved_scope.trace,
            allowed_document_ids=pre_resolved_scope.allowed_document_ids,
            cross_document_allowed=pre_resolved_scope.cross_document_allowed,
        )
    )
    resumed_scope = SessionDocumentScopeStore(scope_path).resolve(
        session_id="s1",
        query="围绕 @主标书 回答",
        filters={},
        resolver=fake_retrieval.resolve_document_titles,
    )

    assert pre_resolved_scope.trace["scope_resolution_status"] == "alias_bind_pending_current_retrieval"
    assert result.trace["alias_resolution"]["status"] == "alias_bound"
    assert resumed_scope.trace["alias_resolution"]["status"] == "alias_resolved"
    assert resumed_scope.filters["document_id"] == "doc-a"
    assert resumed_scope.filters["version_id"] == "v1"
    assert resumed_scope.suppress_retrieval is False


def test_session_file_alias_title_bind_failure_does_not_suppress_retrieval(tmp_path):
    class FakeRetrieval:
        def __init__(self):
            self.requests = []

        def resolve_document_titles(self, titles, filters):
            return []

        def retrieve(self, request, route):
            self.requests.append(request)
            return RetrievalOutput(items=[], citations=[], backend="fake")

    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(tmp_path / "scope.json")
    fake_retrieval = FakeRetrieval()
    kernel.retrieval = fake_retrieval

    result = kernel.start_turn(KernelRequest(query="把《不存在的文件》设为 @测试文件", session_id="s1"))

    assert fake_retrieval.requests
    assert fake_retrieval.requests[0].document_scope["scope_resolution_status"] == "alias_bind_pending_title_retrieval"
    assert result.retrieval.backend == "fake"
    assert result.trace["scope_resolution_status"] == "alias_bind_failed"
    assert result.trace["alias_resolution"]["bind_failure_reason"] == "no_title_retrieval_match"


def test_session_file_alias_compare_after_title_bind_fallback(tmp_path):
    class FakeRetrieval:
        def __init__(self):
            self.requests = []

        def resolve_document_titles(self, titles, filters):
            return []

        def retrieve(self, request, route):
            self.requests.append(request)
            query = request.query or ""
            document_id = request.filters.get("document_id")
            if document_id:
                title_by_id = {"doc-meeting": "会议纪要", "doc-tender": "主标书"}
                version_by_id = {"doc-meeting": "v-meeting", "doc-tender": "v-tender"}
                return RetrievalOutput(
                    items=[
                        KernelItem(
                            chunk_id=f"{document_id}-1",
                            document_id=document_id,
                            version_id=version_by_id[document_id],
                            text=f"{title_by_id[document_id]} evidence",
                            source_name=title_by_id[document_id],
                        )
                    ],
                    citations=[
                        KernelCitation(
                            document_id=document_id,
                            version_id=version_by_id[document_id],
                            chunk_id=f"{document_id}-1",
                            source_name=title_by_id[document_id],
                        )
                    ],
                    backend="fake",
                )
            if "会议纪要" in query:
                return RetrievalOutput(
                    items=[
                        KernelItem(
                            chunk_id="meeting-1",
                            document_id="doc-meeting",
                            version_id="v-meeting",
                            text="会议纪要 evidence",
                            source_name="会议纪要",
                        )
                    ],
                    citations=[
                        KernelCitation(
                            document_id="doc-meeting",
                            version_id="v-meeting",
                            chunk_id="meeting-1",
                            source_name="会议纪要",
                        )
                    ],
                    backend="fake",
                )
            return RetrievalOutput(
                items=[
                    KernelItem(
                        chunk_id="tender-1",
                        document_id="doc-tender",
                        version_id="v-tender",
                        text="主标书 evidence",
                        source_name="主标书",
                    )
                ],
                citations=[
                    KernelCitation(
                        document_id="doc-tender",
                        version_id="v-tender",
                        chunk_id="tender-1",
                        source_name="主标书",
                    )
                ],
                backend="fake",
            )

    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(tmp_path / "scope.json")
    kernel.retrieval = FakeRetrieval()

    meeting_result = kernel.start_turn(KernelRequest(query="把《会议纪要》设为 @会议纪要", session_id="s1"))
    tender_result = kernel.start_turn(KernelRequest(query="把《主标书》设为 @主标书", session_id="s1"))
    compare_result = kernel.start_turn(KernelRequest(query="对比 @会议纪要 和 @主标书", session_id="s1"))

    assert meeting_result.trace["alias_resolution"]["resolved_document_id"] == "doc-meeting"
    assert tender_result.trace["alias_resolution"]["resolved_document_id"] == "doc-tender"
    assert compare_result.trace["alias_resolution"]["status"] == "multi_document_alias_resolved"
    assert compare_result.trace["compare_document_ids"] == ["doc-meeting", "doc-tender"]
    assert compare_result.trace["returned_document_ids"] == ["doc-meeting", "doc-tender"]
    assert "scope_retrieval_suppressed" not in compare_result.trace


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


def test_session_file_alias_binds_curly_quoted_locked_title_with_binding_phrase():
    store = SessionDocumentScopeStore()

    decision = store.resolve(
        session_id="s1",
        query="请在企业记忆中锁定“A标书”，并绑定为 @主标书。",
        filters={},
        resolver=_resolver,
    )

    assert decision.trace["alias_resolution"]["status"] == "alias_bound"
    assert decision.trace["alias_resolution"]["resolved_document_id"] == "doc-a"
    assert decision.trace["alias_resolution"]["resolved_title"] == "A标书"
    assert decision.filters["document_id"] == "doc-a"
    assert decision.filters["version_id"] == "v1"


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


def test_file_steward_alias_missing_context_block_gives_next_step_without_evidence():
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

    assert "File steward diagnostics:" in context
    assert "file_steward.type=alias_failure_helper" in context
    assert "alias=主标书" in context
    assert "auto_bind_allowed=false" in context
    assert "retrieval_evidence_document_ids=[]" in context
    assert "next_action=ask_user_for_exact_title_or_import_file" in context
    assert "metadata_as_answer=false" in context
    assert "requires_retrieval_evidence=true" in context
    assert "Retrieved evidence:" not in context


def test_file_steward_active_document_continuation_context_block():
    builder = ContextBuilder()
    retrieval = RetrievalOutput(
        backend="fake",
        trace={
            "active_document_id": "doc-a",
            "active_document_version_id": "v1",
            "active_document_title": "A标书",
            "active_document_source_name": "a.docx",
            "active_document_source_type": "docx",
            "document_scope_source": "active_document",
            "scope_resolution_status": "active_document_applied",
        },
    )

    context = builder.build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "File steward diagnostics:" in context
    assert "file_steward.type=active_document_continuation_hint" in context
    assert "can_continue=true" in context
    assert "document_id=doc-a" in context
    assert "version_id=v1" in context
    assert "title=A标书" in context
    assert "metadata_as_answer=false" in context
    assert "requires_retrieval_evidence=true" in context


def test_file_steward_file_answer_metadata_context_block_from_evidence():
    builder = ContextBuilder()
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="chunk-a",
                document_id="doc-a",
                version_id="v1",
                text="A evidence",
                source_name="a.docx",
                metadata={"source_type": "docx", "title": "A标书"},
            )
        ],
        citations=[
            KernelCitation(
                document_id="doc-a",
                version_id="v1",
                chunk_id="chunk-a",
                source_name="a.docx",
            )
        ],
        backend="fake",
    )

    context = builder.build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "File steward diagnostics:" in context
    assert "file_steward.type=file_answer_metadata" in context
    assert "file_answer_metadata: document_id=doc-a" in context
    assert "version_id=v1" in context
    assert "title=A标书" in context
    assert "source_name=a.docx" in context
    assert "source_type=docx" in context
    assert "citation_count=1" in context
    assert "metadata_as_answer=false" in context
    assert "file_answer_metadata_required_fields=document_id,version_id,title,source_name,source_type,citation_count" in context
    assert "file_answer_metadata_echo_required=true" in context
    assert "file_answer_metadata_source_fields_present=true" in context
    assert "file_answer_metadata_safety_flags: metadata_as_answer=false" in context
    assert "facts_as_answer=false" in context
    assert "snapshot_as_answer=false" in context
    assert "requires_retrieval_evidence=true" in context
    assert "metadata_is_display_only_not_answer_evidence=true" in context
    assert "Retrieved evidence:" in context


def test_file_steward_file_answer_metadata_falls_back_to_metadata_source_name():
    builder = ContextBuilder()
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="chunk-a",
                document_id="doc-a",
                version_id="v1",
                text="A evidence",
                metadata={"source_type": "docx", "source_name": "fallback.docx"},
            )
        ],
        citations=[
            KernelCitation(
                document_id="doc-a",
                version_id="v1",
                chunk_id="chunk-a",
            )
        ],
        backend="fake",
    )

    context = builder.build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "file_steward.type=file_answer_metadata" in context
    assert "title=fallback.docx" in context
    assert "source_name=fallback.docx" in context
    assert "file_answer_metadata_source_fields_present=true" in context


def test_alias_context_block_reports_stale_version_hint():
    builder = ContextBuilder()
    retrieval = RetrievalOutput(
        backend="fake",
        trace={
            "alias_resolution": {
                "status": "alias_resolved",
                "alias": "版本测试",
                "resolved_document_id": "doc-a",
                "resolved_title": "A标书",
                "alias_scope": "session",
                "alias_stale_version": True,
                "latest_version_id": "v2",
                "superseded_by_version_id": "v2",
            }
        },
    )

    context = builder.build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "alias_diagnostics" in context
    assert "stale_version=True" in context
    assert "latest_version_id=v2" in context
    assert "alias_stale_version=true" in context


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
    assert governed["third_document_mixed"] is False
    assert governed["third_document_mixed_document_ids"] == []
    assert governed["out_of_scope_document_ids_filtered"] == ["doc-c"]
    assert "out_of_scope_evidence_filtered" not in governed["contamination_flags"]
    assert "unexpected_document_id" not in governed["contamination_flags"]


def test_alias_scope_overrides_stale_third_document_contamination_trace_when_evidence_is_in_scope():
    retrieval = RetrievalOutput(
        items=[
            KernelItem(chunk_id="a1", document_id="doc-a", version_id="v1", text="A evidence"),
        ],
        citations=[
            KernelCitation(document_id="doc-a", version_id="v1", chunk_id="a1"),
        ],
        backend="fake",
        trace={
            "third_document_contamination": True,
            "third_document_mixed": True,
            "third_document_mixed_document_ids": ["doc-c"],
            "document_scope_filter": {
                "filtered_out_document_ids": ["doc-c"],
            },
        },
    )
    decision = DocumentScopeDecision(
        filters={"document_id": "doc-a", "version_id": "v1"},
        trace={
            "scope_resolution_status": "alias_resolved",
            "alias_resolution": {
                "status": "alias_resolved",
                "alias": "测试文件",
                "resolved_document_id": "doc-a",
                "resolved_version_id": "v1",
            },
        },
        allowed_document_ids=["doc-a"],
        cross_document_allowed=False,
    )

    kernel = MemoryKernel.__new__(MemoryKernel)
    governed = kernel._with_context_governance_trace(retrieval.trace, retrieval, decision)

    assert governed["retrieval_evidence_document_ids"] == ["doc-a"]
    assert governed["third_document_mixed"] is False
    assert governed["third_document_contamination"] is False
    assert governed["third_document_mixed_document_ids"] == []
    assert "unexpected_document_id" not in governed["contamination_flags"]


def test_compare_scope_does_not_flag_third_document_when_evidence_is_subset():
    retrieval = RetrievalOutput(
        items=[
            KernelItem(chunk_id="a1", document_id="doc-a", version_id="v1", text="A evidence"),
            KernelItem(chunk_id="b1", document_id="doc-b", version_id="v2", text="B evidence"),
        ],
        citations=[
            KernelCitation(document_id="doc-a", version_id="v1", chunk_id="a1"),
            KernelCitation(document_id="doc-b", version_id="v2", chunk_id="b1"),
        ],
        backend="fake",
    )
    decision = DocumentScopeDecision(
        filters={},
        trace={
            "document_scope_source": "query_compare_titles",
            "scope_resolution_status": "multi_document_resolved",
            "cross_document_allowed": True,
            "compare_document_ids": ["doc-a", "doc-b"],
        },
        allowed_document_ids=["doc-a", "doc-b"],
        cross_document_allowed=True,
    )

    kernel = MemoryKernel.__new__(MemoryKernel)
    governed = kernel._with_context_governance_trace({}, retrieval, decision)

    assert governed["retrieval_evidence_document_ids"] == ["doc-a", "doc-b"]
    assert governed["third_document_mixed"] is False
    assert governed["third_document_mixed_document_ids"] == []
    assert governed["contamination_flags"] == []


def test_compare_scope_still_flags_actual_third_document_evidence():
    retrieval = RetrievalOutput(
        items=[
            KernelItem(chunk_id="a1", document_id="doc-a", version_id="v1", text="A evidence"),
            KernelItem(chunk_id="c1", document_id="doc-c", version_id="v3", text="C evidence"),
        ],
        citations=[],
        backend="fake",
    )
    decision = DocumentScopeDecision(
        filters={},
        trace={
            "document_scope_source": "query_compare_titles",
            "scope_resolution_status": "multi_document_resolved",
            "cross_document_allowed": True,
            "compare_document_ids": ["doc-a", "doc-b"],
        },
        allowed_document_ids=["doc-a", "doc-b"],
        cross_document_allowed=True,
    )

    kernel = MemoryKernel.__new__(MemoryKernel)
    governed = kernel._with_context_governance_trace({}, retrieval, decision)

    assert governed["retrieval_evidence_document_ids"] == ["doc-a", "doc-c"]
    assert governed["third_document_mixed"] is True
    assert governed["third_document_mixed_document_ids"] == ["doc-c"]
    assert "unexpected_document_id" in governed["contamination_flags"]


def test_context_block_tells_model_not_to_report_false_third_document_mixing():
    retrieval = RetrievalOutput(
        items=[
            KernelItem(chunk_id="a1", document_id="doc-a", version_id="v1", text="A evidence"),
            KernelItem(chunk_id="b1", document_id="doc-b", version_id="v2", text="B evidence"),
        ],
        backend="fake",
        trace={
            "compare_document_ids": ["doc-a", "doc-b"],
            "retrieval_evidence_document_ids": ["doc-a", "doc-b"],
            "third_document_mixed": False,
            "third_document_mixed_document_ids": [],
        },
    )

    context = ContextBuilder().build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "third_document_mixed=false" in context
    assert "do not describe this compare as third-document contamination" in context


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


def test_metadata_snapshot_trace_is_never_answer_evidence():
    decision = DocumentScopeDecision(
        filters={"document_id": "doc-a"},
        trace={
            "active_document_id": "doc-a",
            "active_document_title": "A标书",
            "document_scope_source": "active_document",
            "document_scope_changed": False,
            "scope_resolution_status": "active_document_applied",
            "cross_document_allowed": False,
        },
        allowed_document_ids=["doc-a"],
        cross_document_allowed=False,
    )
    retrieval = RetrievalOutput(
        items=[KernelItem(chunk_id="a1", document_id="doc-a", version_id="v1", text="工程地点：深圳市福田区")],
        citations=[KernelCitation(document_id="doc-a", version_id="v1", chunk_id="a1")],
        backend="fake",
        trace={
            "retrieval_trace": {
                "metadata_snapshot_used": True,
                "metadata_fields_matched": ["project_location"],
                "metadata_source_chunk_ids": ["a1"],
                "evidence_required": True,
                "snapshot_as_answer": True,
            }
        },
    )
    kernel = MemoryKernel.__new__(MemoryKernel)
    trace = kernel._with_context_governance_trace(retrieval.trace, retrieval, decision)

    assert trace["metadata_snapshot_used"] is True
    assert trace["metadata_source_chunk_ids"] == ["a1"]
    assert trace["evidence_required"] is True
    assert trace["snapshot_as_answer"] is False
    assert trace["retrieval_evidence_document_ids"] == ["doc-a"]


def test_metadata_snapshot_context_block_says_navigation_only():
    builder = ContextBuilder()
    retrieval = RetrievalOutput(
        items=[KernelItem(chunk_id="a1", document_id="doc-a", version_id="v1", text="工程地点：深圳市福田区")],
        backend="fake",
        trace={
            "alias_resolution": {"status": "alias_resolved", "alias": "主标书", "resolved_document_id": "doc-a"},
            "metadata_snapshot_used": True,
            "metadata_fields_matched": ["project_location"],
            "metadata_source_chunk_ids": ["a1"],
            "snapshot_as_answer": False,
            "evidence_required": True,
        },
    )

    context = builder.build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "metadata_snapshot_used=true" in context
    assert "snapshot_as_answer=false" in context
    assert "evidence_required=true" in context


def test_meeting_transcript_trace_is_never_fact_evidence():
    decision = DocumentScopeDecision(
        filters={"document_id": "meeting-doc"},
        trace={
            "active_document_id": "meeting-doc",
            "document_scope_source": "active_document",
            "scope_resolution_status": "active_document_applied",
        },
        allowed_document_ids=["meeting-doc"],
        cross_document_allowed=False,
    )
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="m1",
                document_id="meeting-doc",
                version_id="v1",
                text="行动项：唐总负责跟进。",
                metadata={"meeting_transcript": True, "action_item": ["行动项：唐总负责跟进。"]},
            )
        ],
        trace={
            "retrieval_trace": {
                "meeting_transcript_used": True,
                "meeting_fields_matched": ["action_item"],
                "action_items_detected": 1,
                "transcript_as_fact": True,
                "evidence_required": True,
            }
        },
    )
    kernel = MemoryKernel.__new__(MemoryKernel)
    trace = kernel._with_context_governance_trace(retrieval.trace, retrieval, decision)

    assert trace["meeting_transcript_used"] is True
    assert trace["action_items_detected"] == 1
    assert trace["evidence_required"] is True
    assert trace["transcript_as_fact"] is False
    assert trace["retrieval_evidence_document_ids"] == ["meeting-doc"]


def test_meeting_transcript_context_block_says_retrieval_evidence_not_fact():
    builder = ContextBuilder()
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="m1",
                document_id="meeting-doc",
                version_id="v1",
                text="严总：决定采用数字化交付平台作为试点。",
                source_name="会议纪要汇编",
                metadata={
                    "content_profile": "meeting_transcript",
                    "meeting_transcript": True,
                    "meeting_fields_matched": ["speaker", "decision"],
                    "speaker": "严总",
                    "source_location": "会议纪要 > 结论",
                    "transcript_as_fact": False,
                    "evidence_required": True,
                },
            )
        ],
        backend="fake",
        trace={
            "meeting_transcript_used": True,
            "meeting_fields_matched": ["speaker", "decision"],
            "meeting_source_chunk_ids": ["m1"],
            "transcript_as_fact": False,
            "evidence_required": True,
        },
    )

    context = builder.build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "meeting_transcript_used=true" in context
    assert "transcript_as_fact=false" in context
    assert "retrieval evidence only, not confirmed facts" in context
    assert "content_profile=meeting_transcript" in context
    assert "speaker=严总" in context
