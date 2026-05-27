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


def render_natural_file_import_response(
    diagnostics: dict[str, Any],
    *,
    include_diagnostics: bool = False,
) -> str:
    alias_resolution = diagnostics.get("alias_resolution") or {}
    alias = alias_resolution.get("alias") if isinstance(alias_resolution, dict) else None
    upload_succeeded = diagnostics.get("ingestion_status") == "upload_succeeded"
    if upload_succeeded:
        lines = _render_import_success(diagnostics, alias)
    else:
        lines = _render_import_failure(diagnostics)

    if include_diagnostics:
        lines.extend(["", *_debug_diagnostics_lines(diagnostics)])
    return "\n".join(lines)


def _render_import_success(diagnostics: dict[str, Any], alias: str | None) -> list[str]:
    workspace_context = diagnostics.get("workspace_context") or {}
    workspace_name = _display_value(workspace_context.get("workspace_name"), fallback="待确认工作区")
    category = _display_value(workspace_context.get("document_category"), fallback="待确认分类")
    alias_text = f"@{alias}" if alias else _display_value(diagnostics.get("suggested_alias"), fallback="@待确认别名")
    fuzzy_query = _fuzzy_followup_query(workspace_name, category)
    return [
        "文件我已经记下了。",
        "",
        "我把它放入了：",
        f"- 工作区：{workspace_name}",
        f"- 分类：{category}",
        f"- 别名：{alias_text}",
        "",
        "后续你可以直接问：",
        f"- {alias_text} 这份文件有哪些重点？",
        f"- {fuzzy_query}",
        "",
        "说明：工作区和别名只是定位信息；回答文件内容时我仍会基于 retrieval evidence 和 citation。",
    ]


def _render_import_failure(diagnostics: dict[str, Any]) -> list[str]:
    workspace_context = diagnostics.get("workspace_context") or {}
    workspace_name = _display_value(workspace_context.get("workspace_name"), fallback="待确认工作区")
    category = _display_value(workspace_context.get("document_category"), fallback="待确认分类")
    return [
        f"我识别到你想导入一份文件，并判断它可能属于：{workspace_name} / {category}。",
        "",
        "但我现在无法读取到这个文件。通常是因为这个路径对 Hermes 后端不可见。",
        "",
        "你可以把文件放到 Hermes 授权导入目录，或让运维把该目录加入授权导入范围。",
        "",
        "然后再对我说：",
        "帮我导入这个文件：<授权目录中的文件名.docx>。",
    ]


def _debug_diagnostics_lines(diagnostics: dict[str, Any]) -> list[str]:
    alias_resolution = diagnostics.get("alias_resolution") or {}
    alias = alias_resolution.get("alias") if isinstance(alias_resolution, dict) else None
    lines = ["Natural file import diagnostics:"]
    if alias:
        lines.append(f"别名我设定为：@{alias}")
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
        f"- workspace_context={json.dumps(diagnostics.get('workspace_context') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- suggested_alias={diagnostics.get('suggested_alias')}",
        f"- alias_status={diagnostics.get('alias_status')}",
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
        f"- workspace_context_as_retrieval_evidence={_bool_text(diagnostics.get('workspace_context_as_retrieval_evidence'))}",
        f"- third_document_contamination={_bool_text(diagnostics.get('third_document_contamination'))}",
        ]
    )
    if diagnostics.get("ingestion_status") != "upload_succeeded":
        lines.append("Import was not completed. No retrieval evidence was produced.")
    else:
        lines.append("Import preflight completed through the configured upload adapter.")
    return lines


def _display_value(value: Any, *, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text and text != "unknown" else fallback


def _fuzzy_followup_query(workspace_name: str, category: str) -> str:
    if workspace_name != "待确认工作区" and "人力" in category and "成本" in category:
        return f"帮我找 {workspace_name}的人力成本表"
    if workspace_name != "待确认工作区":
        return f"帮我找 {workspace_name}的相关文件"
    return "帮我找刚才导入的这份文件"


def _bool_text(value: Any) -> str:
    return "true" if value is True else "false" if value is False else str(value)
