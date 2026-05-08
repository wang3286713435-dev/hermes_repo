from __future__ import annotations

import builtins

from agent.memory_kernel.file_steward_ux import (
    ActiveDocumentHint,
    FileCandidate,
    build_active_document_continuation_hint,
    build_alias_failure_helper,
    build_file_answer_metadata,
)


def test_alias_missing_without_candidates_gives_next_step_without_evidence():
    helper = build_alias_failure_helper(alias="主标书", candidates=[], failed_reason="alias_missing")

    assert helper["status"] == "no_candidate_no_active_document"
    assert helper["candidate_count"] == 0
    assert helper["active_document"] is None
    assert helper["auto_bind_allowed"] is False
    assert helper["retrieval_evidence_document_ids"] == []
    assert helper["next_action"] == "ask_user_for_exact_title_or_import_file"


def test_alias_missing_with_multiple_candidates_requires_selection():
    candidates = [
        FileCandidate(document_id="doc-a", version_id="ver-a", title="主标书 A"),
        FileCandidate(document_id="doc-b", version_id="ver-b", title="主标书 B"),
    ]

    helper = build_alias_failure_helper(alias="主标书", candidates=candidates)

    assert helper["status"] == "multiple_candidates_need_selection"
    assert helper["candidate_count"] == 2
    assert helper["auto_bind_allowed"] is False
    assert helper["next_action"] == "ask_user_to_select_one_candidate"
    assert helper["candidates"][0]["document_id"] == "doc-a"
    assert helper["candidates"][1]["version_id"] == "ver-b"


def test_active_document_continuation_hint_keeps_metadata_out_of_answer():
    active_document = ActiveDocumentHint(
        document_id="doc-1",
        version_id="ver-1",
        title="会议纪要",
        source_name="meeting.docx",
        source_type="docx",
        scope_source="session_active_document",
    )

    helper = build_active_document_continuation_hint(active_document)

    assert helper["status"] == "active_document_available"
    assert helper["can_continue"] is True
    assert helper["active_document"]["document_id"] == "doc-1"
    assert helper["active_document"]["version_id"] == "ver-1"
    assert helper["metadata_as_answer"] is False
    assert helper["requires_retrieval_evidence"] is True


def test_file_answer_metadata_contains_stable_file_fields():
    metadata = build_file_answer_metadata(
        document_id="doc-1",
        version_id="ver-1",
        title="硬件清单",
        source_name="hardware.xlsx",
        source_type="xlsx",
        evidence_scope="document",
        citation_count=3,
    )

    assert metadata["type"] == "file_answer_metadata"
    assert metadata["file"]["document_id"] == "doc-1"
    assert metadata["file"]["version_id"] == "ver-1"
    assert metadata["file"]["title"] == "硬件清单"
    assert metadata["file"]["source_name"] == "hardware.xlsx"
    assert metadata["file"]["source_type"] == "xlsx"
    assert metadata["file"]["citation_count"] == 3


def test_safe_answer_flags_remain_false_for_all_helpers():
    active_document = ActiveDocumentHint(document_id="doc-1", version_id="ver-1", title="主标书")
    helpers = [
        build_alias_failure_helper(alias="主标书"),
        build_alias_failure_helper(alias="主标书", active_document=active_document),
        build_active_document_continuation_hint(active_document),
        build_file_answer_metadata(document_id="doc-1", version_id="ver-1", title="主标书"),
    ]

    for helper in helpers:
        assert helper["facts_as_answer"] is False
        assert helper["transcript_as_fact"] is False
        assert helper["snapshot_as_answer"] is False
        assert helper["metadata_as_answer"] is False
        assert helper["requires_retrieval_evidence"] is True


def test_helpers_are_pure_functions_without_filesystem_access(monkeypatch):
    def fail_open(*args, **kwargs):
        raise AssertionError("file steward UX helper must not access filesystem")

    monkeypatch.setattr(builtins, "open", fail_open)

    helper = build_alias_failure_helper(
        alias="交付标准",
        candidates=[FileCandidate(document_id="doc-1", title="交付标准")],
    )

    assert helper["status"] == "single_candidate_needs_confirmation"
    assert helper["candidates"][0]["title"] == "交付标准"
