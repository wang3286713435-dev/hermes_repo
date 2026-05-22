from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import PurePosixPath
from typing import Any

from agent.memory_kernel.natural_file_import import (
    NaturalFileImportRequest,
    build_natural_file_import_diagnostics,
    parse_natural_file_import,
)
from agent.memory_kernel.natural_file_upload_adapter import (
    NaturalFileUploadAdapter,
    NaturalFileUploadResult,
)


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
    real_upload_enabled: bool = False,
) -> NaturalFileImportFlowResult:
    """Run natural import preflight with real upload fail-closed by default."""

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

    diagnostics["real_upload_enabled"] = real_upload_enabled
    if not real_upload_enabled:
        diagnostics["ingestion_status"] = "not_executed"
        diagnostics["upload_adapter_status"] = "disabled"
        diagnostics["import_failed_reason"] = "real_upload_disabled"
        diagnostics["alias_resolution"] = _alias_not_bound(request, "real_upload_disabled")
        return NaturalFileImportFlowResult(
            intercepted=True,
            normal_flow_allowed=False,
            request=request,
            diagnostics=diagnostics,
        )

    upload_result = upload_adapter.upload(request)
    diagnostics["upload_adapter_status"] = "executed"
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
            "ingestion_status": "upload_succeeded",
            "document_id": upload_result.document_id,
            "version_id": upload_result.version_id,
            "chunk_count": upload_result.chunk_count,
            "indexed_count": upload_result.indexed_count,
            "import_failed_reason": None,
        }
    )
    diagnostics["alias_resolution"] = _alias_seeded(request, upload_result)
    diagnostics["suggested_alias"] = f"@{diagnostics['alias_resolution']['alias']}"
    diagnostics["alias_status"] = "alias_seeded"

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
            "retrieval_evidence_version_ids": [],
            "import_diagnostics_as_retrieval_evidence": False,
            "real_upload_enabled": False,
            "dry_run": True,
            "metadata_as_answer": False,
            "facts_as_answer": False,
            "snapshot_as_answer": False,
            "transcript_as_fact": False,
            "requires_retrieval_evidence": True,
            "third_document_contamination": False,
            "suggested_alias": _suggested_alias(request),
            "alias_status": "pending_upload" if request.alias else "alias_suggested",
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
    alias = request.alias or _generated_safe_alias(request)
    alias_generated = not bool(request.alias)
    return {
        "status": "alias_seeded",
        "alias": alias,
        "alias_scope": "session",
        "alias_generated": alias_generated,
        "resolved_document_id": upload_result.document_id,
        "resolved_version_id": upload_result.version_id,
    }


def _generated_safe_alias(request: NaturalFileImportRequest) -> str:
    workspace = request.workspace_context or {}
    workspace_name = str(workspace.get("workspace_name") or "")
    category = str(workspace.get("document_category") or "")
    if workspace_name and workspace_name != "unknown" and category == "人力配置 / 成本测算":
        project_prefix = re.sub(r"项目$", "", workspace_name)
        raw = f"{project_prefix}人力成本测算表"
        alias = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "", raw)
        return alias[:24] or "导入文件"

    source_name = PurePosixPath(request.source_path or "").name
    stem = PurePosixPath(source_name).stem if source_name else ""
    stem = re.sub(r"[_\-\s]*(?:20\d{2}[01]\d[0-3]\d|20\d{2}[-._]?\d{1,2}[-._]?\d{1,2}|\d{4,})$", "", stem)
    raw = request.title or stem or "导入文件"
    alias = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "", raw)
    return alias[:24] or "导入文件"


def _suggested_alias(request: NaturalFileImportRequest) -> str | None:
    if not request.detected or not request.source_path:
        return f"@{request.alias}" if request.alias else None
    alias = request.alias or _generated_safe_alias(request)
    return f"@{alias}" if alias else None


def _missing_success_field(upload_result: NaturalFileUploadResult) -> str | None:
    if not upload_result.document_id:
        return "missing_document_id"
    if not upload_result.version_id:
        return "missing_version_id"
    return None
