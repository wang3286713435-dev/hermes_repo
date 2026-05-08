from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent.memory_kernel.natural_file_import import (
    NaturalFileImportRequest,
    build_natural_file_import_diagnostics,
    parse_natural_file_import,
)


@dataclass
class NaturalFileUploadResult:
    success: bool
    document_id: str | None = None
    version_id: str | None = None
    chunk_count: int | None = None
    indexed_count: int | None = None
    message: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    failed_reason: str | None = None


class NaturalFileUploadAdapter(Protocol):
    def upload(self, request: NaturalFileImportRequest) -> NaturalFileUploadResult:
        ...


@dataclass
class NaturalFileImportFlowResult:
    intercepted: bool
    normal_flow_allowed: bool
    request: NaturalFileImportRequest
    diagnostics: dict[str, Any]
    retrieval_evidence_document_ids: list[str] = field(default_factory=list)


def run_natural_file_import_preflight(
    text: str,
    *,
    upload_adapter: NaturalFileUploadAdapter | None = None,
) -> NaturalFileImportFlowResult:
    """Run mocked natural import preflight without calling real upload APIs."""

    request = parse_natural_file_import(text)
    diagnostics = _base_flow_diagnostics(request)

    if not request.detected:
        return NaturalFileImportFlowResult(
            intercepted=False,
            normal_flow_allowed=True,
            request=request,
            diagnostics=diagnostics,
        )

    if request.failed_reason:
        diagnostics["ingestion_status"] = "not_executed"
        diagnostics["upload_adapter_status"] = "not_called"
        diagnostics["import_failed_reason"] = request.failed_reason
        return NaturalFileImportFlowResult(
            intercepted=True,
            normal_flow_allowed=False,
            request=request,
            diagnostics=diagnostics,
        )

    if upload_adapter is None:
        diagnostics["ingestion_status"] = "not_executed"
        diagnostics["upload_adapter_status"] = "not_configured"
        diagnostics["import_failed_reason"] = "upload_adapter_not_configured"
        diagnostics["alias_resolution"] = _alias_not_bound(request, "upload_adapter_not_configured")
        return NaturalFileImportFlowResult(
            intercepted=True,
            normal_flow_allowed=False,
            request=request,
            diagnostics=diagnostics,
        )

    upload_result = upload_adapter.upload(request)
    diagnostics["upload_adapter_status"] = "mocked_executed"
    diagnostics["upload_message"] = upload_result.message

    if not upload_result.success:
        failed_reason = upload_result.failed_reason or upload_result.error_type or "upload_failed"
        diagnostics["ingestion_status"] = "failed"
        diagnostics["import_failed_reason"] = failed_reason
        diagnostics["error_type"] = upload_result.error_type
        diagnostics["error_message"] = upload_result.error_message
        diagnostics["alias_resolution"] = _alias_not_bound(request, failed_reason)
        return NaturalFileImportFlowResult(
            intercepted=True,
            normal_flow_allowed=False,
            request=request,
            diagnostics=diagnostics,
        )

    missing_field = _missing_success_field(upload_result)
    if missing_field:
        diagnostics["ingestion_status"] = "failed"
        diagnostics["import_failed_reason"] = missing_field
        diagnostics["document_id"] = upload_result.document_id
        diagnostics["version_id"] = upload_result.version_id
        diagnostics["alias_resolution"] = _alias_not_bound(request, missing_field)
        return NaturalFileImportFlowResult(
            intercepted=True,
            normal_flow_allowed=False,
            request=request,
            diagnostics=diagnostics,
        )

    diagnostics.update(
        {
            "ingestion_status": "mocked_upload_succeeded",
            "document_id": upload_result.document_id,
            "version_id": upload_result.version_id,
            "chunk_count": upload_result.chunk_count,
            "indexed_count": upload_result.indexed_count,
            "import_failed_reason": None,
        }
    )
    diagnostics["alias_resolution"] = _alias_seeded(request, upload_result)

    return NaturalFileImportFlowResult(
        intercepted=True,
        normal_flow_allowed=False,
        request=request,
        diagnostics=diagnostics,
    )


def _base_flow_diagnostics(request: NaturalFileImportRequest) -> dict[str, Any]:
    diagnostics = build_natural_file_import_diagnostics(request)
    diagnostics.update(
        {
            "upload_adapter_status": "not_called",
            "document_id": None,
            "version_id": None,
            "chunk_count": None,
            "indexed_count": None,
            "retrieval_evidence_document_ids": [],
            "import_diagnostics_as_retrieval_evidence": False,
            "dry_run": True,
            "facts_as_answer": False,
            "snapshot_as_answer": False,
            "transcript_as_fact": False,
        }
    )
    return diagnostics


def _alias_not_bound(request: NaturalFileImportRequest, reason: str) -> dict[str, Any]:
    if not request.alias:
        return {
            "status": "not_requested",
            "alias": None,
            "resolved_document_id": None,
            "resolved_version_id": None,
        }
    return {
        "status": "not_bound",
        "alias": request.alias,
        "alias_scope": "session",
        "resolved_document_id": None,
        "resolved_version_id": None,
        "alias_bind_failed_reason": reason,
    }


def _alias_seeded(
    request: NaturalFileImportRequest,
    upload_result: NaturalFileUploadResult,
) -> dict[str, Any]:
    if not request.alias:
        return {
            "status": "not_requested",
            "alias": None,
            "resolved_document_id": None,
            "resolved_version_id": None,
        }
    return {
        "status": "alias_seeded",
        "alias": request.alias,
        "alias_scope": "session",
        "resolved_document_id": upload_result.document_id,
        "resolved_version_id": upload_result.version_id,
    }


def _missing_success_field(upload_result: NaturalFileUploadResult) -> str | None:
    if not upload_result.document_id:
        return "missing_document_id"
    if not upload_result.version_id:
        return "missing_version_id"
    return None
