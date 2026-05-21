from __future__ import annotations

from dataclasses import dataclass

from agent.memory_kernel.natural_file_import import NaturalFileImportRequest
from agent.memory_kernel.natural_file_import_flow import (
    NaturalFileImportFlowResult,
    NaturalFileUploadResult,
    run_natural_file_import_preflight,
)


@dataclass
class FakeUploadAdapter:
    result: NaturalFileUploadResult
    calls: int = 0
    last_request: NaturalFileImportRequest | None = None

    def upload(self, request: NaturalFileImportRequest) -> NaturalFileUploadResult:
        self.calls += 1
        self.last_request = request
        return self.result


def _success_result() -> NaturalFileUploadResult:
    return NaturalFileUploadResult(
        success=True,
        document_id="doc-1",
        version_id="ver-1",
        chunk_count=3,
        indexed_count=3,
        message="mocked upload ok",
    )


def test_no_import_intent_allows_normal_flow():
    result = run_natural_file_import_preflight("帮我看看 /tmp/demo.pdf")

    assert result.intercepted is False
    assert result.normal_flow_allowed is True
    assert result.diagnostics["natural_import_detected"] is False
    assert result.diagnostics["retrieval_evidence_document_ids"] == []


def test_negated_import_intent_allows_normal_flow():
    result = run_natural_file_import_preflight("请不要上传 /tmp/demo.pdf 到企业记忆")

    assert result.intercepted is False
    assert result.normal_flow_allowed is True
    assert result.diagnostics["natural_import_detected"] is False


def test_fail_closed_import_returns_diagnostics_without_upload():
    adapter = FakeUploadAdapter(_success_result())

    result = run_natural_file_import_preflight("导入 /tmp/demo.exe 到企业记忆", upload_adapter=adapter)

    assert result.intercepted is True
    assert result.normal_flow_allowed is False
    assert adapter.calls == 0
    assert result.diagnostics["ingestion_status"] == "not_executed"
    assert result.diagnostics["import_failed_reason"] == "unsupported_extension"
    assert result.diagnostics["retrieval_evidence_document_ids"] == []


def test_valid_import_with_adapter_fails_closed_when_real_upload_disabled():
    adapter = FakeUploadAdapter(_success_result())

    result = run_natural_file_import_preflight("导入 /tmp/demo.pdf 到企业记忆", upload_adapter=adapter)

    assert result.intercepted is True
    assert result.normal_flow_allowed is False
    assert adapter.calls == 0
    assert result.diagnostics["real_upload_enabled"] is False
    assert result.diagnostics["upload_adapter_status"] == "disabled"
    assert result.diagnostics["ingestion_status"] == "not_executed"
    assert result.diagnostics["import_failed_reason"] == "real_upload_disabled"
    assert result.diagnostics["retrieval_evidence_document_ids"] == []


def test_missing_path_directory_and_bulk_fail_closed_without_retrieval_evidence():
    missing = run_natural_file_import_preflight("请导入企业记忆")
    directory = run_natural_file_import_preflight("导入 /tmp/data/ 目录到企业记忆")
    bulk = run_natural_file_import_preflight("批量导入 /tmp/a.pdf 到企业记忆")

    assert missing.diagnostics["import_failed_reason"] == "missing_path"
    assert directory.diagnostics["import_failed_reason"] == "directory_import_not_supported"
    assert bulk.diagnostics["import_failed_reason"] == "bulk_import_not_supported"
    assert missing.diagnostics["retrieval_evidence_document_ids"] == []
    assert directory.diagnostics["retrieval_evidence_document_ids"] == []
    assert bulk.diagnostics["retrieval_evidence_document_ids"] == []


def test_mocked_upload_success_returns_document_and_version():
    adapter = FakeUploadAdapter(_success_result())

    result = run_natural_file_import_preflight(
        "导入 /tmp/demo.pdf 到企业记忆",
        upload_adapter=adapter,
        real_upload_enabled=True,
    )

    assert result.intercepted is True
    assert result.normal_flow_allowed is False
    assert adapter.calls == 1
    assert adapter.last_request is not None
    assert adapter.last_request.source_path == "/tmp/demo.pdf"
    assert result.diagnostics["ingestion_status"] == "upload_succeeded"
    assert result.diagnostics["document_id"] == "doc-1"
    assert result.diagnostics["version_id"] == "ver-1"
    assert result.diagnostics["chunk_count"] == 3
    assert result.diagnostics["indexed_count"] == 3


def test_alias_requested_and_mocked_upload_success_seeds_session_alias():
    adapter = FakeUploadAdapter(_success_result())

    result = run_natural_file_import_preflight(
        "上传 /tmp/demo.pdf 到企业记忆，绑定为 @测试文件",
        upload_adapter=adapter,
        real_upload_enabled=True,
    )

    alias_resolution = result.diagnostics["alias_resolution"]
    assert alias_resolution["status"] == "alias_seeded"
    assert alias_resolution["alias"] == "测试文件"
    assert alias_resolution["alias_scope"] == "session"
    assert alias_resolution["resolved_document_id"] == "doc-1"
    assert alias_resolution["resolved_version_id"] == "ver-1"


def test_mocked_upload_success_without_alias_generates_safe_session_alias():
    adapter = FakeUploadAdapter(_success_result())

    result = run_natural_file_import_preflight(
        "帮我导入 \"/tmp/建筑类 数据样表.xlsx\" 到企业记忆",
        upload_adapter=adapter,
        real_upload_enabled=True,
    )

    alias_resolution = result.diagnostics["alias_resolution"]
    assert alias_resolution["status"] == "alias_seeded"
    assert alias_resolution["alias"] == "建筑类数据样表"
    assert alias_resolution["alias_generated"] is True
    assert alias_resolution["resolved_document_id"] == "doc-1"
    assert alias_resolution["resolved_version_id"] == "ver-1"


def test_alias_requested_and_upload_failed_does_not_bind_alias():
    adapter = FakeUploadAdapter(
        NaturalFileUploadResult(
            success=False,
            error_type="api_unavailable",
            error_message="mocked outage",
            failed_reason="api_unavailable",
        )
    )

    result = run_natural_file_import_preflight(
        "上传 /tmp/demo.pdf 到企业记忆，绑定为 @测试文件",
        upload_adapter=adapter,
        real_upload_enabled=True,
    )

    assert result.diagnostics["ingestion_status"] == "failed"
    assert result.diagnostics["import_failed_reason"] == "api_unavailable"
    alias_resolution = result.diagnostics["alias_resolution"]
    assert alias_resolution["status"] == "not_bound"
    assert alias_resolution["resolved_document_id"] is None
    assert alias_resolution["alias_bind_failed_reason"] == "api_unavailable"


def test_missing_document_id_or_version_id_fails_closed():
    missing_doc = run_natural_file_import_preflight(
        "导入 /tmp/demo.pdf 到企业记忆",
        upload_adapter=FakeUploadAdapter(NaturalFileUploadResult(success=True, version_id="ver-1")),
        real_upload_enabled=True,
    )
    missing_version = run_natural_file_import_preflight(
        "导入 /tmp/demo.pdf 到企业记忆",
        upload_adapter=FakeUploadAdapter(NaturalFileUploadResult(success=True, document_id="doc-1")),
        real_upload_enabled=True,
    )

    assert missing_doc.diagnostics["ingestion_status"] == "failed"
    assert missing_doc.diagnostics["import_failed_reason"] == "missing_document_id"
    assert missing_version.diagnostics["ingestion_status"] == "failed"
    assert missing_version.diagnostics["import_failed_reason"] == "missing_version_id"


def test_import_diagnostics_are_not_retrieval_evidence():
    result: NaturalFileImportFlowResult = run_natural_file_import_preflight(
        "导入 /tmp/demo.pdf 到企业记忆",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )

    assert result.retrieval_evidence_document_ids == []
    assert result.diagnostics["retrieval_evidence_document_ids"] == []
    assert result.diagnostics["import_diagnostics_as_retrieval_evidence"] is False


def test_safe_flags_remain_false_for_all_flow_modes():
    no_intent = run_natural_file_import_preflight("帮我看看 /tmp/demo.pdf")
    fail_closed = run_natural_file_import_preflight("导入 /tmp/demo.exe 到企业记忆")
    success = run_natural_file_import_preflight(
        "导入 /tmp/demo.pdf 到企业记忆",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )

    for result in (no_intent, fail_closed, success):
        assert result.diagnostics["facts_as_answer"] is False
        assert result.diagnostics["snapshot_as_answer"] is False
        assert result.diagnostics["transcript_as_fact"] is False
