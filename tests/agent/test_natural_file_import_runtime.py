from __future__ import annotations

from dataclasses import dataclass

from agent.memory_kernel.natural_file_import import NaturalFileImportRequest
from agent.memory_kernel.natural_file_import_runtime import (
    NaturalFileImportRuntimeResponse,
    maybe_handle_natural_file_import,
    render_natural_file_import_response,
)
from agent.memory_kernel.natural_file_upload_adapter import NaturalFileUploadResult
from agent.memory_kernel.config import MemoryKernelConfig
from agent.memory_kernel.kernel import MemoryKernel
from run_agent import AIAgent


@dataclass
class FakeUploadAdapter:
    result: NaturalFileUploadResult
    calls: int = 0

    def upload(self, request: NaturalFileImportRequest) -> NaturalFileUploadResult:
        self.calls += 1
        return self.result


def _success_result() -> NaturalFileUploadResult:
    return NaturalFileUploadResult(
        success=True,
        document_id="doc-runtime",
        version_id="ver-runtime",
        chunk_count=4,
        indexed_count=4,
        message="fake upload ok",
    )


def test_non_import_prompt_is_not_intercepted():
    response = maybe_handle_natural_file_import("帮我看看 /tmp/demo.docx")

    assert response is None


def test_import_prompt_defaults_to_disabled_and_does_not_call_adapter():
    adapter = FakeUploadAdapter(_success_result())

    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=adapter,
    )

    assert isinstance(response, NaturalFileImportRuntimeResponse)
    assert adapter.calls == 0
    assert response.diagnostics["natural_import_detected"] is True
    assert response.diagnostics["real_upload_enabled"] is False
    assert response.diagnostics["upload_adapter_status"] == "disabled"
    assert response.diagnostics["ingestion_status"] == "not_executed"
    assert response.diagnostics["import_failed_reason"] == "real_upload_disabled"
    assert response.completed is True
    assert response.diagnostics["retrieval_evidence_document_ids"] == []


def test_fake_adapter_success_returns_upload_fields_and_alias_seeded():
    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )

    assert response is not None
    assert response.diagnostics["upload_adapter_status"] == "executed"
    assert response.diagnostics["ingestion_status"] == "upload_succeeded"
    assert response.diagnostics["document_id"] == "doc-runtime"
    assert response.diagnostics["version_id"] == "ver-runtime"
    assert response.diagnostics["chunk_count"] == 4
    assert response.diagnostics["indexed_count"] == 4
    assert response.diagnostics["alias_resolution"]["status"] == "alias_seeded"
    assert response.diagnostics["alias_resolution"]["resolved_document_id"] == "doc-runtime"
    assert response.diagnostics["alias_resolution"]["resolved_version_id"] == "ver-runtime"
    assert "文件我已经记下了" in response.final_response
    assert "别名我设定为：@测试文件" in response.final_response


def test_render_success_response_uses_persisted_alias_bound_status():
    diagnostics = {
        "natural_import_detected": True,
        "real_upload_enabled": True,
        "upload_adapter_status": "executed",
        "ingestion_status": "upload_succeeded",
        "import_failed_reason": None,
        "document_id": "doc-runtime",
        "version_id": "ver-runtime",
        "chunk_count": 4,
        "indexed_count": 4,
        "alias_persisted": True,
        "alias_resolution": {
            "status": "alias_bound",
            "alias": "测试文件",
            "resolved_document_id": "doc-runtime",
            "resolved_version_id": "ver-runtime",
        },
        "retrieval_evidence_document_ids": [],
        "import_diagnostics_as_retrieval_evidence": False,
        "metadata_as_answer": False,
        "facts_as_answer": False,
        "snapshot_as_answer": False,
        "transcript_as_fact": False,
        "requires_retrieval_evidence": True,
        "third_document_contamination": False,
    }

    response = render_natural_file_import_response(diagnostics)

    assert "别名我设定为：@测试文件" in response
    assert '"status": "alias_bound"' in response
    assert "retrieval_evidence_document_ids=[]" in response


def test_run_agent_persists_natural_import_alias_as_bound_for_same_session(tmp_path):
    agent = object.__new__(AIAgent)
    agent.session_id = "natural-import-session"
    agent._memory_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    agent._memory_kernel.document_scope._storage_path = tmp_path / "scope.json"
    diagnostics = {
        "ingestion_status": "upload_succeeded",
        "document_id": "doc-runtime",
        "version_id": "ver-runtime",
        "import_source_path": "/tmp/测试文件.docx",
        "alias_resolution": {
            "status": "alias_seeded",
            "alias": "测试文件",
            "resolved_document_id": "doc-runtime",
            "resolved_version_id": "ver-runtime",
        },
    }

    agent._persist_natural_import_alias(diagnostics)
    decision = agent._memory_kernel.resolve_document_scope(
        session_id="natural-import-session",
        query="围绕 @测试文件 回答，必须给出 citation",
        filters={},
    )

    assert diagnostics["alias_persisted"] is True
    assert diagnostics["alias_resolution"]["status"] == "alias_bound"
    assert decision.trace["alias_resolution"]["status"] == "alias_resolved"
    assert decision.filters["document_id"] == "doc-runtime"
    assert decision.filters["version_id"] == "ver-runtime"


def test_run_agent_hydrates_natural_import_alias_from_conversation_history(tmp_path):
    agent = object.__new__(AIAgent)
    agent.session_id = "api-derived-followup-session"
    agent._memory_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    agent._memory_kernel.document_scope._storage_path = tmp_path / "scope.json"
    previous_response = render_natural_file_import_response(
        {
            "natural_import_detected": True,
            "real_upload_enabled": True,
            "upload_adapter_status": "executed",
            "ingestion_status": "upload_succeeded",
            "import_failed_reason": None,
            "document_id": "doc-imported",
            "version_id": "ver-imported",
            "chunk_count": 6,
            "indexed_count": 6,
            "alias_resolution": {
                "status": "alias_bound",
                "alias": "建筑类数据样表",
                "resolved_document_id": "doc-imported",
                "resolved_version_id": "ver-imported",
            },
            "retrieval_evidence_document_ids": [],
            "import_diagnostics_as_retrieval_evidence": False,
            "metadata_as_answer": False,
            "facts_as_answer": False,
            "snapshot_as_answer": False,
            "transcript_as_fact": False,
            "requires_retrieval_evidence": True,
            "third_document_contamination": False,
        }
    )

    agent._hydrate_natural_import_aliases_from_history(
        [{"role": "assistant", "content": previous_response}]
    )
    decision = agent._memory_kernel.resolve_document_scope(
        session_id="api-derived-followup-session",
        query="围绕 @建筑类数据样表 总结文件内容，必须给出 citation",
        filters={},
    )

    assert decision.trace["alias_resolution"]["status"] == "alias_resolved"
    assert decision.trace["alias_missing"] is False
    assert decision.suppress_retrieval is False
    assert decision.filters["document_id"] == "doc-imported"
    assert decision.filters["version_id"] == "ver-imported"
    assert decision.allowed_document_ids == ["doc-imported"]


def test_fake_adapter_failure_fails_closed_and_does_not_bind_alias():
    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(
            NaturalFileUploadResult(
                success=False,
                failed_reason="api_unavailable",
                error_type="api_unavailable",
            )
        ),
        real_upload_enabled=True,
    )

    assert response is not None
    assert response.diagnostics["ingestion_status"] == "failed"
    assert response.diagnostics["import_failed_reason"] == "api_unavailable"
    assert response.diagnostics["alias_resolution"]["status"] == "not_bound"
    assert response.diagnostics["alias_resolution"]["resolved_document_id"] is None


def test_runtime_response_keeps_import_diagnostics_out_of_evidence_and_sets_safety_flags():
    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )

    assert response is not None
    assert response.diagnostics["retrieval_evidence_document_ids"] == []
    assert response.diagnostics["import_diagnostics_as_retrieval_evidence"] is False
    assert response.diagnostics["metadata_as_answer"] is False
    assert response.diagnostics["facts_as_answer"] is False
    assert response.diagnostics["snapshot_as_answer"] is False
    assert response.diagnostics["transcript_as_fact"] is False
    assert response.diagnostics["requires_retrieval_evidence"] is True
    assert "import_diagnostics_as_retrieval_evidence=false" in response.final_response
    assert "facts_as_answer=false" in response.final_response
    assert "requires_retrieval_evidence=true" in response.final_response


def test_missing_document_or_version_fails_closed():
    missing_doc = maybe_handle_natural_file_import(
        "导入 /tmp/demo.docx 到企业记忆",
        upload_adapter=FakeUploadAdapter(NaturalFileUploadResult(success=True, version_id="ver-1")),
        real_upload_enabled=True,
    )
    missing_version = maybe_handle_natural_file_import(
        "导入 /tmp/demo.docx 到企业记忆",
        upload_adapter=FakeUploadAdapter(NaturalFileUploadResult(success=True, document_id="doc-1")),
        real_upload_enabled=True,
    )

    assert missing_doc is not None
    assert missing_doc.diagnostics["import_failed_reason"] == "missing_document_id"
    assert missing_version is not None
    assert missing_version.diagnostics["import_failed_reason"] == "missing_version_id"
