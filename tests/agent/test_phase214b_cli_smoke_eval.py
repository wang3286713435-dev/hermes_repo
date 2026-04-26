from __future__ import annotations

from pathlib import Path

from scripts.phase214b_cli_smoke_eval import (
    SmokeCase,
    build_chat_command,
    evaluate_output,
    parse_session_id,
    summarize,
)


def test_evaluate_output_passes_required_and_absent_forbidden():
    case = SmokeCase(
        id="ok",
        prompts=["prompt"],
        required_substrings=["aliasmissing", "suppress_retrieval=true"],
        forbidden_substrings=["unexpected-doc"],
    )

    result = evaluate_output(
        case,
        "alias_resolution.status=aliasmissing suppress_retrieval=true",
    )

    assert result["status"] == "passed"
    assert result["missing_required_substrings"] == []
    assert result["forbidden_substrings_present"] == []


def test_evaluate_output_tolerates_trace_format_variants():
    case = SmokeCase(
        id="trace-format",
        prompts=["prompt"],
        required_substrings=[
            "aliasmissing",
            "suppress_retrieval=true",
            "retrieval_evidence_document_ids=[]",
        ],
    )

    result = evaluate_output(
        case,
        "alias_resolution.status: alias_missing\n"
        "suppress_retrieval: true\n"
        "retrieval_evidence_document_ids: []",
    )

    assert result["status"] == "passed"


def test_evaluate_output_detects_missing_required_substring():
    case = SmokeCase(id="missing", prompts=["prompt"], required_substrings=["document_id=abc"])

    result = evaluate_output(case, "document_id=def")

    assert result["status"] == "failed"
    assert result["missing_required_substrings"] == ["document_id=abc"]


def test_evaluate_output_detects_forbidden_substring():
    case = SmokeCase(id="forbidden", prompts=["prompt"], forbidden_substrings=["third-doc"])

    result = evaluate_output(case, "returned third-doc by mistake")

    assert result["status"] == "failed"
    assert result["forbidden_substrings_present"] == ["third-doc"]


def test_evaluate_output_marks_skipped_case():
    case = SmokeCase(id="skip", prompts=["prompt"], skip_reason="cli_only")

    result = evaluate_output(case, "anything")

    assert result["status"] == "skipped"
    assert result["skip_reason"] == "cli_only"


def test_summarize_counts_statuses_and_latency():
    summary = summarize(
        [
            {"id": "a", "status": "passed"},
            {"id": "b", "status": "failed"},
            {"id": "c", "status": "skipped"},
        ],
        [10.0, 20.0],
    )

    assert summary["total"] == 3
    assert summary["executed"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["latency_ms"]["p50"] == 15.0


def test_build_chat_command_bootstraps_without_continue_or_resume():
    cmd = build_chat_command(Path("./.venv/bin/hermes"), "hello")

    assert "--continue" not in cmd
    assert "--resume" not in cmd
    assert cmd[-2:] == ["-q", "hello"]


def test_build_chat_command_resumes_existing_session_for_later_prompts():
    cmd = build_chat_command(Path("./.venv/bin/hermes"), "next", "20260426_abc123")

    assert "--continue" not in cmd
    assert "--resume" in cmd
    assert "20260426_abc123" in cmd
    assert cmd[-2:] == ["-q", "next"]


def test_parse_session_id_from_quiet_output():
    output = "final answer\n\nsession_id: 20260426_abc123\n"

    assert parse_session_id(output) == "20260426_abc123"


def test_parse_session_id_from_exit_summary_output():
    output = "Resume this session with:\n  hermes --resume 20260426_def456\nSession:        20260426_def456\n"

    assert parse_session_id(output) == "20260426_def456"
