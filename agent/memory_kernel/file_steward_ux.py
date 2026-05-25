from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SAFE_EVIDENCE_FLAGS = {
    "facts_as_answer": False,
    "transcript_as_fact": False,
    "snapshot_as_answer": False,
    "metadata_as_answer": False,
    "requires_retrieval_evidence": True,
}


@dataclass(frozen=True)
class FileCandidate:
    document_id: str
    title: str
    version_id: str | None = None
    source_name: str | None = None
    source_type: str | None = None
    alias: str | None = None
    workspace_name: str | None = None
    document_category: str | None = None
    match_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "version_id": self.version_id,
            "title": self.title,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "alias": self.alias,
            "workspace_name": self.workspace_name,
            "document_category": self.document_category,
            "match_reason": self.match_reason,
        }


@dataclass(frozen=True)
class ActiveDocumentHint:
    document_id: str
    title: str
    version_id: str | None = None
    source_name: str | None = None
    source_type: str | None = None
    scope_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "version_id": self.version_id,
            "title": self.title,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "scope_source": self.scope_source,
        }


@dataclass(frozen=True)
class FileAnswerMetadata:
    document_id: str
    version_id: str | None
    title: str
    source_name: str | None = None
    source_type: str | None = None
    evidence_scope: str = "document"
    citation_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "version_id": self.version_id,
            "title": self.title,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "evidence_scope": self.evidence_scope,
            "citation_count": self.citation_count,
        }


def build_alias_failure_helper(
    *,
    alias: str,
    candidates: list[FileCandidate] | None = None,
    active_document: ActiveDocumentHint | None = None,
    failed_reason: str = "alias_missing",
) -> dict[str, Any]:
    candidate_list = candidates or []
    candidate_count = len(candidate_list)
    active_document_payload = active_document.to_dict() if active_document else None

    if candidate_count == 0 and active_document is None:
        status = "no_candidate_no_active_document"
        next_action = "ask_user_for_exact_title_or_import_file"
    elif candidate_count == 0:
        status = "no_candidate_active_document_available"
        next_action = "offer_continue_with_active_document_or_ask_for_exact_title"
    elif candidate_count == 1:
        status = "single_candidate_needs_confirmation"
        next_action = "ask_user_to_confirm_candidate_before_binding"
    else:
        status = "multiple_candidates_need_selection"
        next_action = "ask_user_to_select_one_candidate"

    return _with_safe_flags(
        {
            "type": "alias_failure_helper",
            "alias": alias,
            "status": status,
            "failed_reason": failed_reason,
            "candidate_count": candidate_count,
            "candidates": [candidate.to_dict() for candidate in candidate_list],
            "active_document": active_document_payload,
            "auto_bind_allowed": False,
            "retrieval_evidence_document_ids": [],
            "next_action": next_action,
        }
    )


def build_active_document_continuation_hint(
    active_document: ActiveDocumentHint | None,
) -> dict[str, Any]:
    if active_document is None:
        payload = {
            "type": "active_document_continuation_hint",
            "status": "no_active_document",
            "can_continue": False,
            "active_document": None,
            "next_action": "ask_user_to_specify_or_bind_a_file",
        }
    else:
        payload = {
            "type": "active_document_continuation_hint",
            "status": "active_document_available",
            "can_continue": True,
            "active_document": active_document.to_dict(),
            "next_action": "continue_with_active_document_using_retrieval_evidence",
        }
    return _with_safe_flags(payload)


def build_file_answer_metadata(
    *,
    document_id: str,
    version_id: str | None,
    title: str,
    source_name: str | None = None,
    source_type: str | None = None,
    evidence_scope: str = "document",
    citation_count: int = 0,
) -> dict[str, Any]:
    metadata = FileAnswerMetadata(
        document_id=document_id,
        version_id=version_id,
        title=title,
        source_name=source_name,
        source_type=source_type,
        evidence_scope=evidence_scope,
        citation_count=citation_count,
    )
    return _with_safe_flags(
        {
            "type": "file_answer_metadata",
            "status": "metadata_available",
            "file": metadata.to_dict(),
        }
    )


def _with_safe_flags(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, **SAFE_EVIDENCE_FLAGS}
