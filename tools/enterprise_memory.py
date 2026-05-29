"""Enterprise memory tool schemas.

Execution is handled by ``AIAgent`` because these tools need session-scoped
memory kernel state. The registry handlers are intentionally fail-closed so a
missed agent-level dispatch cannot silently answer from ordinary file tools.
"""

from __future__ import annotations

import json
from typing import Any

from tools.registry import registry


ENTERPRISE_MEMORY_TOOL_NAMES = {
    "enterprise_memory_search",
    "enterprise_memory_import_file",
    "enterprise_memory_find_files",
    "enterprise_memory_resolve_alias",
}


def _agent_dispatch_required(args: dict[str, Any], **kwargs: Any) -> str:
    return json.dumps(
        {
            "success": False,
            "error": "enterprise_memory_agent_dispatch_required",
            "message": (
                "enterprise_memory tools require Hermes Agent session/kernel dispatch; "
                "ordinary registry dispatch is intentionally disabled."
            ),
            "facts_as_answer": False,
            "snapshot_as_answer": False,
            "transcript_as_fact": False,
        },
        ensure_ascii=False,
    )


def _always_available() -> bool:
    return True


registry.register(
    name="enterprise_memory_search",
    toolset="enterprise_memory",
    emoji="🏢",
    check_fn=_always_available,
    handler=_agent_dispatch_required,
    schema={
        "description": (
            "Search governed Hermes enterprise memory for company files. Use this instead of "
            "read_file/search_files/execute_code for questions about imported enterprise "
            "documents, aliases, meeting transcripts, bids, spreadsheets, PPTX, or knowledge "
            "that must be grounded in retrieval evidence and citations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user-facing enterprise document question to retrieve evidence for.",
                },
                "alias": {
                    "type": "string",
                    "description": "Optional session alias such as @主标书. If provided, search is scoped to that alias.",
                },
                "document_id": {
                    "type": "string",
                    "description": "Optional explicit document_id scope.",
                },
                "version_id": {
                    "type": "string",
                    "description": "Optional explicit version_id scope, including historical versions.",
                },
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Maximum retrieval candidates to request.",
                },
                "retrieval_mode": {
                    "type": "string",
                    "enum": ["hybrid", "sparse", "dense"],
                    "description": "Retrieval mode. Defaults to hybrid.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
)

registry.register(
    name="enterprise_memory_import_file",
    toolset="enterprise_memory",
    emoji="📥",
    check_fn=_always_available,
    handler=_agent_dispatch_required,
    schema={
        "description": (
            "Import one explicit local file into Hermes enterprise memory through the governed "
            "upload flow. Only report success when upload, alias persistence, and post-bind "
            "verification all pass. Do not use this for directories, bulk imports, or temporary "
            "attachments without an explicit import request."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Single local file path to import. Directories and bulk import are not supported.",
                },
                "alias": {
                    "type": "string",
                    "description": "Optional session alias to bind, with or without leading @.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional display title for Hermes_memory upload.",
                },
                "document_type": {
                    "type": "string",
                    "description": "Optional document_type metadata such as tender, meeting, xlsx, pptx.",
                },
                "source_type": {
                    "type": "string",
                    "description": "Optional source_type metadata. Defaults to manual.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
)

registry.register(
    name="enterprise_memory_find_files",
    toolset="enterprise_memory",
    emoji="🗂️",
    check_fn=_always_available,
    handler=_agent_dispatch_required,
    schema={
        "description": (
            "Find safe candidate enterprise memory files by alias, title, workspace, or natural "
            "file description. Returns aliases/document ids and low-sensitive metadata only; "
            "does not expose raw local paths or raw file content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language file lookup query, e.g. C塔智能化标准 or @主标书.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Maximum number of candidates to return.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
)

registry.register(
    name="enterprise_memory_resolve_alias",
    toolset="enterprise_memory",
    emoji="🏷️",
    check_fn=_always_available,
    handler=_agent_dispatch_required,
    schema={
        "description": (
            "Resolve a session enterprise memory alias such as @主标书 to document_id/version_id "
            "using governed session scope. Use before answering alias-bound questions when the "
            "model needs to verify the alias target."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "alias": {
                    "type": "string",
                    "description": "Alias name, with or without leading @.",
                }
            },
            "required": ["alias"],
            "additionalProperties": False,
        },
    },
)
