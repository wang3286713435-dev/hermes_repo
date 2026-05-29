from __future__ import annotations

import json
from types import SimpleNamespace

from agent.memory_kernel.interfaces import (
    KernelCitation,
    KernelItem,
    KernelResult,
    QueryRoute,
    RetrievalOutput,
)
from agent.memory_kernel.session_document_scope import DocumentScopeDecision
from model_tools import get_tool_definitions
from toolsets import resolve_toolset
from run_agent import AIAgent, _ENTERPRISE_MEMORY_TOOL_GUIDANCE


class FakeEnterpriseMemoryKernel:
    def __init__(
        self,
        *,
        with_evidence: bool = True,
        decision: DocumentScopeDecision | None = None,
        item_source_name: str = "主标书.docx",
        citation_source_name: str = "主标书.docx",
        item_metadata: dict | None = None,
        citation_metadata: dict | None = None,
        result_trace: dict | None = None,
    ):
        self.with_evidence = with_evidence
        self.requests = []
        self.decision = decision or DocumentScopeDecision(
            filters={"document_id": "doc-a", "version_id": "ver-a"},
            trace={
                "scope_resolution_status": "alias_resolved",
                "alias_resolution": {
                    "status": "alias_resolved",
                    "alias": "主标书",
                    "resolved_document_id": "doc-a",
                    "resolved_version_id": "ver-a",
                },
                "alias_missing": False,
                "suppress_retrieval": False,
            },
            allowed_document_ids=["doc-a"],
        )
        self.item_source_name = item_source_name
        self.citation_source_name = citation_source_name
        self.item_metadata = item_metadata or {}
        self.citation_metadata = citation_metadata or {}
        self.result_trace = result_trace if result_trace is not None else {"enabled": True}

    def resolve_document_scope(self, *, session_id, query, filters):
        return self.decision

    def start_turn(self, request):
        self.requests.append(request)
        items = []
        citations = []
        if self.with_evidence:
            items = [
                KernelItem(
                    chunk_id="chunk-a",
                    document_id="doc-a",
                    version_id="ver-a",
                    text="工程地点位于深圳市福田区。",
                    source_name=self.item_source_name,
                    score=0.91,
                    metadata=self.item_metadata,
                )
            ]
            citations = [
                KernelCitation(
                    document_id="doc-a",
                    version_id="ver-a",
                    chunk_id="chunk-a",
                    source_name=self.citation_source_name,
                    quote_text="工程地点位于深圳市福田区。",
                    metadata=self.citation_metadata,
                )
            ]
        retrieval = RetrievalOutput(
            items=items,
            citations=citations,
            backend="fake",
            dense_retrieval_status="executed",
            sparse_retrieval_status="executed",
            retrieval_mode=request.retrieval_mode,
            applied_filters=request.filters,
            trace={"fake": True},
        )
        return KernelResult(
            route=QueryRoute("enterprise_retrieval", True, "fake", request.retrieval_mode),
            retrieval=retrieval,
            context_block="",
            trace=self.result_trace,
        )


def _make_agent(kernel):
    agent = AIAgent.__new__(AIAgent)
    agent._memory_kernel = kernel
    agent._memory_kernel_config = SimpleNamespace(top_k=8)
    agent.session_id = "enterprise-tool-session"
    agent._user_id = "user-1"
    agent._gateway_session_key = None
    agent.platform = "cli"
    agent._register_alias_continuity_owner = lambda: {}
    agent._register_workspace_file_registry_owner = lambda: {}
    return agent


def _loads(text: str) -> dict:
    return json.loads(text)


def _assert_no_raw_storage_markers(payload: dict):
    rendered = json.dumps(payload, ensure_ascii=False)
    for marker in ("/Users/", "/Volumes/", "file://", "nas://", "smb://"):
        assert marker not in rendered


def test_enterprise_memory_tools_are_registered_and_visible():
    definitions = get_tool_definitions(enabled_toolsets=["enterprise_memory"], quiet_mode=True)
    names = {definition["function"]["name"] for definition in definitions}

    assert {
        "enterprise_memory_search",
        "enterprise_memory_import_file",
        "enterprise_memory_find_files",
        "enterprise_memory_resolve_alias",
    }.issubset(names)
    assert "enterprise_memory_search" in resolve_toolset("hermes-api-server")
    assert "enterprise_memory_search" in resolve_toolset("hermes-cli")


def test_enterprise_memory_find_files_returns_safe_candidates_without_raw_path():
    decision = DocumentScopeDecision(
        filters={"document_id": "doc-standard", "version_id": "ver-standard"},
        trace={
            "scope_resolution_status": "file_discovery_single_candidate_scoped",
            "file_candidates": [
                {
                    "alias": "C塔智能化标准",
                    "document_id": "doc-standard",
                    "version_id": "ver-standard",
                    "title": "C塔智能化专业标准清单.docx",
                    "source_name": "C塔智能化专业标准清单.docx",
                    "source_path": "/Users/sensitive/raw/path.docx",
                    "match_reason": "workspace_file_registry_fuzzy_match",
                }
            ],
        },
        allowed_document_ids=["doc-standard"],
    )
    agent = _make_agent(FakeEnterpriseMemoryKernel(decision=decision))

    result = _loads(agent._handle_enterprise_memory_tool("enterprise_memory_find_files", {"query": "C塔智能化标准"}))

    assert result["success"] is True
    assert result["raw_paths_exposed"] is False
    assert result["candidates"][0]["document_id"] == "doc-standard"
    assert "source_path" not in result["candidates"][0]
    _assert_no_raw_storage_markers(result)


def test_enterprise_memory_find_files_sanitizes_raw_title_and_source_name():
    decision = DocumentScopeDecision(
        filters={"document_id": "doc-standard", "version_id": "ver-standard"},
        trace={
            "scope_resolution_status": "file_discovery_single_candidate_scoped",
            "file_candidates": [
                {
                    "alias": "demo",
                    "document_id": "doc-standard",
                    "version_id": "ver-standard",
                    "title": "/Users/vc/secret/demo.docx",
                    "source_name": "file:///Users/vc/secret/demo.docx",
                    "match_reason": "workspace_file_registry_fuzzy_match",
                }
            ],
        },
        allowed_document_ids=["doc-standard"],
    )
    agent = _make_agent(FakeEnterpriseMemoryKernel(decision=decision))

    result = _loads(agent._handle_enterprise_memory_tool("enterprise_memory_find_files", {"query": "demo"}))

    assert result["candidates"][0]["title"] == "demo.docx"
    assert result["candidates"][0]["source_name"] == "demo.docx"
    assert result["candidates"][0]["document_id"] == "doc-standard"
    _assert_no_raw_storage_markers(result)


def test_enterprise_memory_resolve_alias_uses_session_scope():
    agent = _make_agent(FakeEnterpriseMemoryKernel())

    result = _loads(agent._handle_enterprise_memory_tool("enterprise_memory_resolve_alias", {"alias": "@主标书"}))

    assert result["success"] is True
    assert result["resolved"] is True
    assert result["resolved_document_id"] == "doc-a"
    assert result["resolved_version_id"] == "ver-a"
    assert result["retrieval_suppressed"] is False


def test_enterprise_memory_search_returns_evidence_and_citations():
    kernel = FakeEnterpriseMemoryKernel(with_evidence=True)
    agent = _make_agent(kernel)

    result = _loads(
        agent._handle_enterprise_memory_tool(
            "enterprise_memory_search",
            {"query": "工程地点是什么", "alias": "@主标书", "top_k": 3},
        )
    )

    assert result["success"] is True
    assert result["missing_evidence"] is False
    assert result["retrieval_evidence_document_ids"] == ["doc-a"]
    assert result["evidence"][0]["chunk_id"] == "chunk-a"
    assert result["citations"][0]["label"] == "C1"
    assert kernel.requests[0].filters["document_id"] == "doc-a"
    assert result["read_file_as_content_evidence"] is False
    assert result["search_files_as_company_file_authority"] is False
    assert result["execute_code_as_content_evidence"] is False


def test_enterprise_memory_search_sanitizes_evidence_citation_metadata_and_trace():
    decision = DocumentScopeDecision(
        filters={"document_id": "doc-a", "version_id": "ver-a"},
        trace={
            "scope_resolution_status": "alias_resolved",
            "active_document_title": "/Users/vc/secret/demo.docx",
            "nested": {
                "raw_path": "/Users/vc/secret/demo.docx",
                "safe_value": "keep-me",
                "deep": [
                    {"source_uri": "file:///Users/vc/secret/demo.docx"},
                    "nas://server/private/demo.docx",
                ],
            },
            "alias_resolution": {
                "status": "alias_resolved",
                "alias": "demo",
                "resolved_document_id": "doc-a",
                "resolved_version_id": "ver-a",
            },
        },
        allowed_document_ids=["doc-a"],
    )
    kernel = FakeEnterpriseMemoryKernel(
        decision=decision,
        item_source_name="/Users/vc/secret/demo.docx",
        citation_source_name="file:///Users/vc/secret/demo.docx",
        item_metadata={
            "source_uri": "file:///Users/vc/secret/demo.docx",
            "raw_path": "/Users/vc/secret/demo.docx",
            "safe_key": "safe-value",
        },
        citation_metadata={
            "raw_path": "/Users/vc/secret/demo.docx",
            "storage_uri": "nas://server/private/demo.docx",
            "safe_key": "safe-citation",
        },
        result_trace={
            "backend": "fake",
            "nested": {
                "local_path": "/Users/vc/secret/demo.docx",
                "items": ["smb://server/private/demo.docx", {"ok": "preserved"}],
            },
        },
    )
    agent = _make_agent(kernel)

    result = _loads(
        agent._handle_enterprise_memory_tool(
            "enterprise_memory_search",
            {"query": "工程地点是什么", "alias": "@demo"},
        )
    )

    assert result["evidence"][0]["source_name"] == "demo.docx"
    assert result["citations"][0]["source_name"] == "demo.docx"
    assert result["evidence"][0]["metadata"] == {"safe_key": "safe-value"}
    assert result["citations"][0]["metadata"] == {"safe_key": "safe-citation"}
    assert result["scope_trace"]["nested"]["safe_value"] == "keep-me"
    assert result["trace"]["nested"]["items"][1]["ok"] == "preserved"
    assert result["evidence"][0]["document_id"] == "doc-a"
    assert result["citations"][0]["chunk_id"] == "chunk-a"
    assert result["citations"][0]["label"] == "C1"
    _assert_no_raw_storage_markers(result)


def test_enterprise_memory_search_missing_evidence_does_not_fallback_to_file_tools():
    agent = _make_agent(FakeEnterpriseMemoryKernel(with_evidence=False))

    result = _loads(
        agent._handle_enterprise_memory_tool(
            "enterprise_memory_search",
            {"query": "不存在的条款", "alias": "@主标书"},
        )
    )

    assert result["success"] is True
    assert result["missing_evidence"] is True
    assert result["message"] == "Missing Evidence / needs manual review."
    assert result["retrieval_evidence_document_ids"] == []
    assert result["read_file_as_content_evidence"] is False
    assert result["search_files_as_company_file_authority"] is False
    assert result["execute_code_as_content_evidence"] is False


def test_enterprise_memory_import_file_requires_post_bind_verification(monkeypatch):
    monkeypatch.setenv("HERMES_NATURAL_IMPORT_REAL_UPLOAD_ENABLED", "false")
    agent = _make_agent(FakeEnterpriseMemoryKernel())

    result = _loads(
        agent._handle_enterprise_memory_tool(
            "enterprise_memory_import_file",
            {"path": "/tmp/demo.docx", "alias": "@演示文件"},
        )
    )

    assert result["success"] is False
    assert result["can_claim_file_remembered"] is False
    assert result["can_claim_alias_bound"] is False
    assert result["post_import_alias_verification_status"] in {"not_run", "failed", None}
    assert result["import_diagnostics_as_retrieval_evidence"] is False


def test_enterprise_memory_prompt_guidance_blocks_ordinary_file_authority():
    assert "read_file" in _ENTERPRISE_MEMORY_TOOL_GUIDANCE
    assert "search_files" in _ENTERPRISE_MEMORY_TOOL_GUIDANCE
    assert "execute_code" in _ENTERPRISE_MEMORY_TOOL_GUIDANCE
    assert "enterprise_memory_search" in _ENTERPRISE_MEMORY_TOOL_GUIDANCE
    assert "post-bind verification" in _ENTERPRISE_MEMORY_TOOL_GUIDANCE
    assert "Missing Evidence" in _ENTERPRISE_MEMORY_TOOL_GUIDANCE
