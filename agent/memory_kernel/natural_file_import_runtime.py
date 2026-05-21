from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent.memory_kernel.natural_file_import_flow import (
    NaturalFileImportFlowResult,
    run_natural_file_import_preflight,
)
from agent.memory_kernel.natural_file_upload_adapter import NaturalFileUploadAdapter


@dataclass
class NaturalFileImportRuntimeResponse:
    final_response: str
    diagnostics: dict[str, Any]
    completed: bool = True


def maybe_handle_natural_file_import(
    text: str,
    *,
    upload_adapter: NaturalFileUploadAdapter | None = None,
    real_upload_enabled: bool = False,
) -> NaturalFileImportRuntimeResponse | None:
    """Return a fail-closed natural import response, or None for normal chat."""

    flow_result = run_natural_file_import_preflight(
        text,
        upload_adapter=upload_adapter,
        real_upload_enabled=real_upload_enabled,
    )
    if not flow_result.intercepted:
        return None
    diagnostics = _runtime_diagnostics(flow_result)
    return NaturalFileImportRuntimeResponse(
        final_response=render_natural_file_import_response(diagnostics),
        diagnostics=diagnostics,
    )


def _runtime_diagnostics(flow_result: NaturalFileImportFlowResult) -> dict[str, Any]:
    diagnostics = dict(flow_result.diagnostics)
    diagnostics["metadata_as_answer"] = False
    diagnostics["facts_as_answer"] = False
    diagnostics["snapshot_as_answer"] = False
    diagnostics["transcript_as_fact"] = False
    diagnostics["requires_retrieval_evidence"] = True
    diagnostics["import_diagnostics_as_retrieval_evidence"] = False
    diagnostics["retrieval_evidence_document_ids"] = list(
        diagnostics.get("retrieval_evidence_document_ids") or []
    )
    diagnostics["retrieval_evidence_version_ids"] = list(
        diagnostics.get("retrieval_evidence_version_ids") or []
    )
    diagnostics["third_document_contamination"] = False
    return diagnostics


def render_natural_file_import_response(diagnostics: dict[str, Any]) -> str:
    alias_resolution = diagnostics.get("alias_resolution") or {}
    alias = alias_resolution.get("alias") if isinstance(alias_resolution, dict) else None
    lines = [
        "文件我已经记下了。" if diagnostics.get("ingestion_status") == "upload_succeeded" else "Natural file import diagnostics:",
    ]
    if diagnostics.get("ingestion_status") == "upload_succeeded" and alias:
        lines.extend(
            [
                f"别名我设定为：@{alias}",
                "后续你可以用这个别名继续问我；我仍会通过 retrieval evidence 和 citation 回答文件内容。",
                "",
                "Natural file import diagnostics:",
            ]
        )
    else:
        lines.append("")
    lines.extend(
        [
        f"- natural_import_detected={_bool_text(diagnostics.get('natural_import_detected'))}",
        f"- real_upload_enabled={_bool_text(diagnostics.get('real_upload_enabled'))}",
        f"- upload_adapter_status={diagnostics.get('upload_adapter_status')}",
        f"- ingestion_status={diagnostics.get('ingestion_status')}",
        f"- import_failed_reason={diagnostics.get('import_failed_reason')}",
        f"- document_id={diagnostics.get('document_id')}",
        f"- version_id={diagnostics.get('version_id')}",
        f"- chunk_count={diagnostics.get('chunk_count')}",
        f"- indexed_count={diagnostics.get('indexed_count')}",
        f"- alias_resolution={json.dumps(diagnostics.get('alias_resolution') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- alias_continuity_status={diagnostics.get('alias_continuity_status')}",
        f"- alias_continuity_source={diagnostics.get('alias_continuity_source')}",
        f"- api_session_key_source={diagnostics.get('api_session_key_source')}",
        f"- history_message_count={diagnostics.get('history_message_count')}",
        "- retrieval_evidence_document_ids=[]",
        f"- import_diagnostics_as_retrieval_evidence={_bool_text(diagnostics.get('import_diagnostics_as_retrieval_evidence'))}",
        f"- metadata_as_answer={_bool_text(diagnostics.get('metadata_as_answer'))}",
        f"- facts_as_answer={_bool_text(diagnostics.get('facts_as_answer'))}",
        f"- snapshot_as_answer={_bool_text(diagnostics.get('snapshot_as_answer'))}",
        f"- transcript_as_fact={_bool_text(diagnostics.get('transcript_as_fact'))}",
        f"- requires_retrieval_evidence={_bool_text(diagnostics.get('requires_retrieval_evidence'))}",
        f"- third_document_contamination={_bool_text(diagnostics.get('third_document_contamination'))}",
        ]
    )
    if diagnostics.get("ingestion_status") != "upload_succeeded":
        lines.append("Import was not completed. No retrieval evidence was produced.")
    else:
        lines.append("Import preflight completed through the configured upload adapter.")
    return "\n".join(lines)


def _bool_text(value: Any) -> str:
    return "true" if value is True else "false" if value is False else str(value)
