from __future__ import annotations

from dataclasses import dataclass

from agent.memory_kernel.natural_file_import import NaturalFileImportRequest
from agent.memory_kernel.natural_file_import_runtime import (
    NaturalFileImportRuntimeResponse,
    maybe_handle_natural_file_import,
)
from agent.memory_kernel.natural_file_upload_adapter import NaturalFileUploadResult


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
