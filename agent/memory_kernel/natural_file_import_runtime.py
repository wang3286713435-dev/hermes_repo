from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

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


NaturalImportLLMResponseGenerator = Callable[[dict[str, Any]], str | None]


_RAW_LOCAL_PATH_RE = re.compile(
    r"(?:file://|nas://|smb://|/Users/|/Volumes/|/private/|/var/folders/)",
    re.IGNORECASE,
)
_SUCCESS_CLAIM_RE = re.compile(
    r"(文件我已经记下了|导入成功|已经导入|已导入|别名：@|后续你可以直接问|已完成别名绑定|别名已绑定)"
)
_ALIAS_OVERCLAIM_RE = re.compile(
    r"("
    r"完成\s*@[^\s，。；、,.!?]+(?:\s*的)?绑定"
    r"|@[^\s，。；、,.!?]+\s*(?:已|已经)?绑定"
    r"|绑定(?:了|为|成)?\s*@[^\s，。；、,.!?]+"
    r"|(?:可以|可|能|直接)?用\s*@[^\s，。；、,.!?]+\s*(?:继续)?(?:问|查询|提问)"
    r"|@[^\s，。；、,.!?]+\s*(?:继续)?(?:问|查询|提问)"
    r")"
)
_SAVE_OR_IMPORT_OVERCLAIM_RE = re.compile(
    r"("
    r"接入当前会话"
    r"|已把这份文件接入"
    r"|已经?帮你保存"
    r"|已经?保存"
    r"|已保存"
    r"|已经?收录"
    r"|已收录"
    r"|已经?入库"
    r"|已入库"
    r"|保存到企业记忆"
    r"|接入企业记忆"
    r"|写入企业记忆"
    r"|加入企业记忆"
    r"|纳入企业记忆"
    r")"
)
_SECRET_OR_INTERNAL_RE = re.compile(
    r"(Natural file import diagnostics:|\b(document_id|version_id|chunk_count|indexed_count)\b\s*[:=]?|api[_-]?key|token|password|secret)",
    re.IGNORECASE,
)


def maybe_handle_natural_file_import(
    text: str,
    *,
    upload_adapter: NaturalFileUploadAdapter | None = None,
    real_upload_enabled: bool = False,
    llm_response_generator: NaturalImportLLMResponseGenerator | None = None,
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
        final_response=render_natural_file_import_response(
            diagnostics,
            llm_response_generator=llm_response_generator,
        ),
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
    diagnostics["natural_import_context"] = build_natural_import_context(diagnostics)
    return diagnostics


def build_natural_import_context(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Build a structured, path-safe context for natural import replies.

    This context is the only source of truth for what the response layer may
    claim. Upload success alone is not enough: user-visible success requires
    a document id, version id, and a persisted session alias binding.
    """

    alias_resolution = diagnostics.get("alias_resolution")
    if not isinstance(alias_resolution, dict):
        alias_resolution = {}
    alias = alias_resolution.get("alias")
    alias_status = str(alias_resolution.get("status") or diagnostics.get("alias_status") or "unknown")
    document_id = diagnostics.get("document_id")
    version_id = diagnostics.get("version_id")
    upload_succeeded = diagnostics.get("ingestion_status") == "upload_succeeded"
    has_document_scope = bool(document_id and version_id)
    alias_bound = (
        alias_status == "alias_bound"
        and bool(diagnostics.get("alias_persisted") is True or diagnostics.get("alias_status") == "alias_bound")
        and bool(alias_resolution.get("resolved_document_id") or document_id)
        and bool(alias_resolution.get("resolved_version_id") or version_id)
    )
    can_claim_success = bool(upload_succeeded and has_document_scope and alias_bound)
    import_failed_reason = diagnostics.get("import_failed_reason")
    if can_claim_success:
        status = "ready_for_followup"
        status_reason = "upload_succeeded_and_alias_bound"
    elif upload_succeeded and has_document_scope:
        status = "import_incomplete"
        status_reason = "alias_not_bound"
    elif import_failed_reason:
        status = "failed"
        status_reason = str(import_failed_reason)
    else:
        status = "not_executed"
        status_reason = str(diagnostics.get("ingestion_status") or "not_executed")

    workspace_context = dict(diagnostics.get("workspace_context") or {})
    alias_text = f"@{alias}" if alias else _display_value(diagnostics.get("suggested_alias"), fallback="@待确认别名")
    safe_next_actions = []
    if can_claim_success:
        safe_next_actions = [
            f"{alias_text} 这份文件有哪些重点？",
            _fuzzy_followup_query(
                _display_value(workspace_context.get("workspace_name"), fallback="待确认工作区"),
                _display_value(workspace_context.get("document_category"), fallback="待确认分类"),
            ),
        ]
    elif upload_succeeded and has_document_scope:
        safe_next_actions = ["重新绑定别名，或让用户确认继续使用当前文件。"]
    else:
        safe_next_actions = ["把文件放入 Hermes 授权导入目录后重新发起导入。"]

    return {
        "type": "natural_import_context",
        "status": status,
        "status_reason": status_reason,
        "ingestion_status": diagnostics.get("ingestion_status"),
        "import_failed_reason": import_failed_reason,
        "alias_status": alias_status,
        "alias": alias,
        "suggested_alias": alias_text,
        "workspace_context": workspace_context,
        "can_claim_file_remembered": can_claim_success,
        "can_claim_alias_bound": can_claim_success,
        "can_claim_followup_ready": can_claim_success,
        "allowed_claims": [
            "file_imported",
            "session_alias_bound",
            "workspace_context_is_locator_only",
        ]
        if can_claim_success
        else [
            "import_intent_detected",
            "workspace_context_is_provisional",
            "no_retrieval_evidence_created",
        ],
        "forbidden_claims": [
            "raw_path",
            "file_content_summary_without_retrieval",
            "metadata_or_import_diagnostics_as_answer",
            "claim_alias_bound_when_alias_not_persisted",
            "claim_import_success_when_upload_or_binding_failed",
        ],
        "safe_next_actions": safe_next_actions,
        "evidence_boundary": {
            "retrieval_evidence_document_ids": list(diagnostics.get("retrieval_evidence_document_ids") or []),
            "requires_retrieval_evidence": True,
            "import_diagnostics_as_retrieval_evidence": False,
            "workspace_context_as_retrieval_evidence": False,
            "facts_as_answer": False,
            "snapshot_as_answer": False,
            "transcript_as_fact": False,
        },
        "diagnostics_separation": {
            "document_id_hidden_from_user_text": True,
            "version_id_hidden_from_user_text": True,
            "raw_path_hidden_from_user_text": True,
        },
    }


def render_natural_file_import_response(
    diagnostics: dict[str, Any],
    *,
    include_diagnostics: bool = False,
    llm_response_generator: NaturalImportLLMResponseGenerator | None = None,
) -> str:
    context = build_natural_import_context(diagnostics)
    diagnostics["natural_import_context"] = context
    candidate = ""
    if llm_response_generator is not None:
        try:
            candidate = str(llm_response_generator(context) or "").strip()
            diagnostics["natural_import_response_path"] = "llm"
            diagnostics["natural_import_response_safety_fallback"] = False
        except Exception as exc:
            diagnostics["natural_import_response_path"] = "safety_fallback"
            diagnostics["natural_import_response_safety_fallback"] = True
            diagnostics["natural_import_response_fallback_reason"] = type(exc).__name__
    else:
        diagnostics["natural_import_response_path"] = "safety_fallback"
        diagnostics["natural_import_response_safety_fallback"] = True
        diagnostics["natural_import_response_fallback_reason"] = "llm_response_generator_unavailable"

    if not candidate:
        candidate = "\n".join(_render_safety_fallback_response(context))

    unsafe = _natural_import_response_unsafe(context, candidate)
    if unsafe:
        diagnostics["natural_import_response_path"] = "safety_fallback"
        diagnostics["natural_import_response_safety_fallback"] = True
        diagnostics["natural_import_response_fallback_reason"] = "validator_rejected_candidate"
    final_response = validate_natural_import_response(context, candidate)

    if include_diagnostics:
        final_response = final_response + "\n\n" + "\n".join(_debug_diagnostics_lines(diagnostics))
    return final_response


def validate_natural_import_response(context: dict[str, Any], candidate_response: str) -> str:
    """Apply final safety gates to model- or renderer-produced import text."""

    response = candidate_response or ""
    if _natural_import_response_unsafe(context, response):
        return "\n".join(_render_safety_fallback_response(context))
    return response


def build_natural_import_llm_messages(context: dict[str, Any]) -> list[dict[str, str]]:
    """Build the prompt payload used by the Hermes LLM natural import response path."""

    context_json = json.dumps(
        {"natural_import_context": context},
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    return [
        {
            "role": "system",
            "content": (
                "你是 Hermes 企业内核 Agent。请根据 natural_import_context 生成自然、简短、中文的用户回复。\n"
                "只能依据 allowed_claims 说明状态；必须遵守 forbidden_claims。\n"
                "不要输出 raw path、URI、secret、document_id、version_id、chunk_count、诊断块或 traceback。\n"
                "如果 can_claim_file_remembered=false，不得说文件已经记下、导入成功或别名已绑定。\n"
                "如果 can_claim_alias_bound=false，不得展示“别名：@...”或暗示后续可直接用该别名。\n"
                "工作区、别名、导入状态只是定位/治理上下文，不是文件内容 evidence；回答文件内容仍需要 retrieval evidence 和 citation。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请基于下面结构化上下文生成普通用户可见回复。只输出最终回复文本：\n\n"
                f"```json\n{context_json}\n```"
            ),
        },
    ]


def _natural_import_response_unsafe(context: dict[str, Any], response: str) -> bool:
    if _RAW_LOCAL_PATH_RE.search(response):
        return True
    if _SECRET_OR_INTERNAL_RE.search(response):
        return True
    if not context.get("can_claim_file_remembered") and _SUCCESS_CLAIM_RE.search(response):
        return True
    if not context.get("can_claim_file_remembered") and _SAVE_OR_IMPORT_OVERCLAIM_RE.search(response):
        return True
    if not context.get("can_claim_alias_bound") and _ALIAS_OVERCLAIM_RE.search(response):
        return True
    if not context.get("can_claim_alias_bound") and "别名：@" in response:
        return True
    return False


def _render_context_governed_import_response(context: dict[str, Any]) -> list[str]:
    if context.get("can_claim_file_remembered"):
        return _render_import_success(context)
    if context.get("status") == "import_incomplete":
        return _render_import_incomplete(context)
    return _render_import_failure(context)


def _render_import_success(context: dict[str, Any]) -> list[str]:
    workspace_context = context.get("workspace_context") or {}
    workspace_name = _display_value(workspace_context.get("workspace_name"), fallback="待确认工作区")
    category = _display_value(workspace_context.get("document_category"), fallback="待确认分类")
    alias_text = _display_value(context.get("suggested_alias"), fallback="@待确认别名")
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


def _render_import_incomplete(context: dict[str, Any]) -> list[str]:
    workspace_context = context.get("workspace_context") or {}
    workspace_name = _display_value(workspace_context.get("workspace_name"), fallback="待确认工作区")
    category = _display_value(workspace_context.get("document_category"), fallback="待确认分类")
    return [
        f"我识别到这次导入属于：{workspace_name} / {category}。",
        "",
        "上传流程已经返回结果，但别名还没有完成会话绑定，所以我不能先说文件已经记下。",
        "",
        "下一步请重新绑定别名，或让我用当前文件继续确认一次。",
        "",
        "说明：导入状态、工作区和别名都不是文件内容证据；回答文件内容仍必须基于 retrieval evidence 和 citation。",
    ]


def _render_import_failure(context: dict[str, Any]) -> list[str]:
    workspace_context = context.get("workspace_context") or {}
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


def _render_safety_fallback_response(context: dict[str, Any]) -> list[str]:
    if context.get("can_claim_file_remembered"):
        return _render_import_success(context)
    if context.get("status") == "import_incomplete":
        return _render_import_incomplete(context)
    return _render_import_failure(context)


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
