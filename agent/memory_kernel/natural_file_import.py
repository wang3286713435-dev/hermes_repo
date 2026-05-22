from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any


_IMPORT_ACTION_RE = re.compile(r"(导入|上传|收录|加入企业记忆|写入企业记忆)")
_NEGATED_IMPORT_ACTION_RE = re.compile(
    r"(?:请\s*)?(?:不要|不|别)\s*(?:把\s+.+?\s*)?(?:导入|上传|收录|加入企业记忆|写入企业记忆)"
)
_QUOTED_PATH_RE = re.compile(r"[\"'“”‘’](/.+?)[\"'“”‘’]")
_UNQUOTED_PATH_RE = re.compile(
    r"(/[^，,。；;！？!?\n\r]+?\.[A-Za-z0-9]{1,12})",
    re.IGNORECASE,
)
_DIRECTORY_PATH_RE = re.compile(r"(/[^\s，,。；;！？!?\n\r]+/)")
_TITLE_RE = re.compile(r"(?:标题|名称)\s*(?:叫|为|=|：|:)\s*(.+?)(?=[，,。；;\n]|$)")
_DOCUMENT_TYPE_RE = re.compile(r"(?:document_type|文档类型)\s*(?:=|：|:)\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)")
_SOURCE_TYPE_RE = re.compile(r"(?:source_type|来源类型)\s*(?:=|：|:)\s*([A-Za-z0-9_\-]+)")
_ALIAS_RE = re.compile(
    r"(?:绑定为|绑定成|设为|命名为|取名为|叫做|叫|别名(?:为|叫|设为)?|设定别名为|我想叫它)\s*@([A-Za-z0-9_\-\u4e00-\u9fff]+)"
)
_BULK_INTENT_RE = re.compile(r"(批量导入|整个目录|整个文件夹|递归|扫描\s*NAS|NAS|文件池|TB\s*级|BIM.*(?:批量|目录|文件池))", re.IGNORECASE)
_DIRECTORY_INTENT_RE = re.compile(r"(目录|文件夹)")
_SUPPORTED_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".htm",
    ".html",
    ".md",
    ".pdf",
    ".ppt",
    ".pptx",
    ".txt",
    ".xls",
    ".xlsx",
}


@dataclass
class NaturalFileImportRequest:
    detected: bool
    source_path: str | None = None
    title: str | None = None
    document_type: str | None = None
    source_type: str = "manual"
    alias: str | None = None
    workspace_context: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True
    failed_reason: str | None = None
    import_action: str | None = None
    trace: dict[str, Any] = field(default_factory=dict)


def parse_natural_file_import(text: str) -> NaturalFileImportRequest:
    """Parse explicit single-file import intent without touching the filesystem."""

    query = text or ""
    if _NEGATED_IMPORT_ACTION_RE.search(query):
        return _with_trace(NaturalFileImportRequest(detected=False))

    action_match = _IMPORT_ACTION_RE.search(query)
    if not action_match:
        return _with_trace(NaturalFileImportRequest(detected=False))

    paths = _extract_paths(query)
    failed_reason: str | None = None
    source_path = paths[0] if paths else None

    if _BULK_INTENT_RE.search(query):
        failed_reason = "bulk_import_not_supported"
    elif not paths:
        failed_reason = "missing_path"
    elif len(paths) > 1:
        failed_reason = "multiple_paths_not_supported"
    elif _is_directory_import(query, source_path):
        failed_reason = "directory_import_not_supported"
    elif source_path and _unsupported_extension(source_path):
        failed_reason = "unsupported_extension"

    request = NaturalFileImportRequest(
        detected=True,
        source_path=source_path,
        title=_extract_optional(_TITLE_RE, query),
        document_type=_extract_optional(_DOCUMENT_TYPE_RE, query),
        source_type=_extract_optional(_SOURCE_TYPE_RE, query) or "manual",
        alias=_extract_optional(_ALIAS_RE, query),
        workspace_context=_infer_workspace_context(query, source_path),
        dry_run=True,
        failed_reason=failed_reason,
        import_action=action_match.group(1),
    )
    return _with_trace(request)


def build_natural_file_import_diagnostics(request: NaturalFileImportRequest) -> dict[str, Any]:
    alias_status = "pending_upload" if request.alias else "not_requested"
    return {
        "natural_import_detected": request.detected,
        "import_action": request.import_action,
        "import_source_path": request.source_path,
        "import_title": request.title,
        "document_type": request.document_type,
        "source_type": request.source_type,
        "workspace_context": dict(request.workspace_context or _unknown_workspace_context()),
        "workspace_context_as_retrieval_evidence": False,
        "alias_requested": bool(request.alias),
        "alias": request.alias,
        "alias_resolution": {
            "status": alias_status,
            "alias": request.alias,
            "resolved_document_id": None,
            "resolved_version_id": None,
        },
        "ingestion_status": "not_executed",
        "dry_run": True,
        "import_failed_reason": request.failed_reason,
        "facts_as_answer": False,
        "snapshot_as_answer": False,
        "transcript_as_fact": False,
    }


def _extract_paths(text: str) -> list[str]:
    paths: list[str] = []
    masked = list(text)
    for match in _QUOTED_PATH_RE.finditer(text):
        paths.append(_clean_path(match.group(1)))
        for index in range(match.start(), match.end()):
            masked[index] = " "
    unquoted_source = "".join(masked)
    for match in _UNQUOTED_PATH_RE.finditer(unquoted_source):
        paths.append(_clean_path(match.group(1)))
    if not paths:
        for match in _DIRECTORY_PATH_RE.finditer(unquoted_source):
            paths.append(_clean_path(match.group(1)))
    return _unique([path for path in paths if path])


def _clean_path(path: str) -> str:
    return path.strip().rstrip("，,。；;！？!?)）]")


def _extract_optional(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _is_directory_import(text: str, source_path: str | None) -> bool:
    if source_path and source_path.endswith("/"):
        return True
    return bool(source_path and _DIRECTORY_INTENT_RE.search(text))


def _unsupported_extension(source_path: str) -> bool:
    suffix = PurePosixPath(source_path).suffix.lower()
    return bool(suffix and suffix not in _SUPPORTED_EXTENSIONS)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _infer_workspace_context(query: str, source_path: str | None) -> dict[str, Any]:
    source = PurePosixPath(source_path or "")
    source_name = source.name
    stem = source.stem
    parent_labels = [
        part
        for part in source.parts[-4:-1]
        if part not in {"", "/", "Users", "tmp", "var", "private", "hermes", "import_samples"}
    ]
    safe_text = " ".join([query or "", *parent_labels, stem])
    workspace_name = _infer_workspace_name(safe_text)
    document_category = _infer_document_category(safe_text)
    has_workspace = workspace_name != "unknown"
    has_category = document_category != "unknown"
    if has_workspace and has_category:
        confidence = "high"
    elif has_workspace or has_category:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "workspace_id": _workspace_id(workspace_name, document_category),
        "workspace_name": workspace_name,
        "workspace_type": "project" if has_workspace else "unknown",
        "document_category": document_category,
        "confidence": confidence,
        "needs_user_confirmation": confidence == "low",
    }


def _unknown_workspace_context() -> dict[str, Any]:
    return {
        "workspace_id": "ws-unknown",
        "workspace_name": "unknown",
        "workspace_type": "unknown",
        "document_category": "unknown",
        "confidence": "low",
        "needs_user_confirmation": True,
    }


def _infer_workspace_name(text: str) -> str:
    for pattern in (
        r"([A-Za-z0-9\u4e00-\u9fff]{1,12}塔项目)",
        r"([\u4e00-\u9fffA-Za-z0-9]{2,32}项目)",
    ):
        match = re.search(pattern, text or "")
        if match:
            return match.group(1)
    return "unknown"


def _infer_document_category(text: str) -> str:
    compact = re.sub(r"\s+", "", text or "")
    if "人力" in compact and any(marker in compact for marker in ("成本", "配置", "测算")):
        return "人力配置 / 成本测算"
    if "交付" in compact and "标准" in compact:
        return "数字化交付标准"
    if "会议" in compact and "纪要" in compact:
        return "会议纪要"
    if "招标" in compact:
        return "招标资料"
    if "硬件" in compact and "清单" in compact:
        return "硬件清单"
    return "unknown"


def _workspace_id(workspace_name: str, document_category: str) -> str:
    if workspace_name == "unknown":
        return "ws-unknown"
    digest = sha256(f"{workspace_name}:{document_category}".encode("utf-8")).hexdigest()[:10]
    return f"ws-{digest}"


def _with_trace(request: NaturalFileImportRequest) -> NaturalFileImportRequest:
    request.trace = build_natural_file_import_diagnostics(request)
    return request
