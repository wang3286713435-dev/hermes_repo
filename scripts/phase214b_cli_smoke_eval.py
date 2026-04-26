#!/usr/bin/env python3
"""Phase 2.14b Hermes CLI smoke eval.

This runner intentionally stays small: it verifies a few session-state
behaviors that API-level deterministic eval cannot cover, especially alias
state and CLI-visible evidence policy flags.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MAIN_TENDER_ID = "869d4684-0a98-4825-bc72-ada65c15cfc9"
MEETING_ID = "92051cc6-56b5-4930-bdf0-119163c83a75"
OLD_QA_ID = "1db84714-d49f-48a2-8fa9-c6f73424dd32"
OLD_DELIVERY_ID = "46372530-ea3d-4442-bd67-23efeb0b70df"
COMPARE_TENDER_ID = "a47a409f-cb8a-4d29-b938-43c10767802d"
NEW_DELIVERY_ID = "60d9601a-e797-47c9-a421-61dba6f88c7c"


@dataclass(frozen=True)
class SmokeCase:
    id: str
    prompts: list[str]
    required_substrings: list[str] = field(default_factory=list)
    forbidden_substrings: list[str] = field(default_factory=list)
    skip_reason: str | None = None


def default_cases() -> list[SmokeCase]:
    third_party_doc_ids = [OLD_QA_ID, OLD_DELIVERY_ID, COMPARE_TENDER_ID, NEW_DELIVERY_ID]
    return [
        SmokeCase(
            id="missing_alias_suppress_retrieval",
            prompts=[
                "围绕 @不存在别名 回答：这份文件的工程地点是什么？请输出 alias_resolution、suppress_retrieval、retrieval_evidence_document_ids。"
            ],
            required_substrings=[
                "aliasmissing",
                "suppress_retrieval=true",
                "retrieval_evidence_document_ids=[]",
            ],
            forbidden_substrings=[MAIN_TENDER_ID, MEETING_ID, *third_party_doc_ids],
        ),
        SmokeCase(
            id="alias_bind_and_use_main_tender",
            prompts=[
                "围绕《福田区园岭街道兄弟高登高新产业园城市更新项目施工总承包工程招标文件_V1.0_招标文件》回答：请锁定这份文件，并输出 document_id 与 trace。",
                f"把当前文件作为整份文档设为 @主标书，绑定 document_id={MAIN_TENDER_ID}，不要绑定单一 chunk。请输出 alias_resolution trace。",
                "围绕 @主标书 回答工程地点是什么？必须执行本轮 scoped retrieval，不要使用历史记忆替代 evidence；请输出 alias_resolution、document_id、retrieval_evidence_document_ids 与 citation。",
            ],
            required_substrings=[
                "@主标书",
                MAIN_TENDER_ID,
                "alias",
                "retrieval_evidence_document_ids",
            ],
            forbidden_substrings=[
                "alias_bind_failed",
                "alias_missing",
                "retrieval_suppressed=true",
                "suppress_retrieval=true",
                MEETING_ID,
                *third_party_doc_ids,
            ],
        ),
        SmokeCase(
            id="compare_meeting_and_main_tender_aliases",
            prompts=[
                "围绕《福田区园岭街道兄弟高登高新产业园城市更新项目施工总承包工程招标文件_V1.0_招标文件》回答：请锁定这份文件，并输出 document_id。",
                f"把当前文件作为整份文档设为 @主标书，绑定 document_id={MAIN_TENDER_ID}，不要绑定单一 chunk。请输出 alias_resolution trace。",
                "围绕《会议纪要汇编 (2)》回答：请锁定这份文件，并输出 document_id。",
                f"把当前文件作为整份文档设为 @会议纪要，绑定 document_id={MEETING_ID}，不要绑定单一 chunk。请输出 alias_resolution trace。",
                "对比 @会议纪要 和 @主标书：会议内容能否作为主标书条款？必须分别执行两份 scoped retrieval，不要 suppress retrieval，不要使用历史记忆替代 evidence；请输出 compare_document_ids、retrieval_evidence_document_ids、transcript_as_fact。",
            ],
            required_substrings=[
                MAIN_TENDER_ID,
                MEETING_ID,
                "compare_document_ids",
                "retrieval_evidence_document_ids",
                "transcript_as_fact=false",
            ],
            forbidden_substrings=[
                "retrieval suppressed",
                "retrieval_suppressed=true",
                "suppress_retrieval=true",
                "cannot source from history memory",
                *third_party_doc_ids,
            ],
        ),
        SmokeCase(
            id="meeting_transcript_non_fact",
            prompts=[
                "围绕《会议纪要汇编 (2)》回答：会议里有哪些行动项？请输出 meeting_transcript_used、transcript_as_fact、evidence_required、retrieval_evidence_document_ids。"
            ],
            required_substrings=[
                MEETING_ID,
                "meeting_transcript_used=true",
                "transcript_as_fact=false",
                "evidence_required=true",
            ],
            forbidden_substrings=["transcript_as_fact=true", MAIN_TENDER_ID],
        ),
    ]


def normalize(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


def evaluate_output(case: SmokeCase, raw_output: str) -> dict[str, Any]:
    if case.skip_reason:
        return {
            "id": case.id,
            "status": "skipped",
            "skip_reason": case.skip_reason,
            "raw_output_excerpt": "",
            "missing_required_substrings": [],
            "forbidden_substrings_present": [],
        }

    normalized = normalize(raw_output)
    missing = [item for item in case.required_substrings if normalize(item) not in normalized]
    forbidden_present = [
        item for item in case.forbidden_substrings if normalize(item) in normalized
    ]
    status = "passed" if not missing and not forbidden_present else "failed"
    return {
        "id": case.id,
        "status": status,
        "raw_output_excerpt": raw_output[-1200:],
        "missing_required_substrings": missing,
        "forbidden_substrings_present": forbidden_present,
    }


def check_memory_api(health_url: str, timeout_s: float = 3.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(health_url, timeout=timeout_s) as response:
            return {"ok": 200 <= response.status < 300, "status": response.status, "error": None}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "ok": False,
            "status": None,
            "error": f"{type(exc).__name__}: {exc}",
            "hint": "Start Hermes_memory API first, for example: scripts/run_local_api.sh",
        }


def parse_session_id(output: str) -> str | None:
    for pattern in (r"session_id:\s*([^\s]+)", r"Session:\s*([^\s]+)"):
        match = re.search(pattern, output, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def build_chat_command(hermes_bin: Path, prompt: str, session_id: str | None = None) -> list[str]:
    cmd = [str(hermes_bin), "chat", "-Q"]
    if session_id:
        cmd.extend(["--resume", session_id])
    cmd.extend(["-q", prompt])
    return cmd


def run_case(case: SmokeCase, hermes_bin: Path, timeout_s: int) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    chunks: list[str] = []
    session_id: str | None = None
    for index, prompt in enumerate(case.prompts):
        cmd = build_chat_command(hermes_bin, prompt, session_id)
        completed = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
            check=False,
        )
        chunks.append(completed.stdout)
        if completed.returncode != 0:
            result = evaluate_output(case, "\n".join(chunks))
            result["status"] = "failed"
            result["returncode"] = completed.returncode
            result["failed_command"] = " ".join(cmd[:5] + ["..."])
            if "No session found" in completed.stdout:
                result["session_bootstrap_error"] = (
                    "attempted_to_resume_missing_session"
                )
            return result, (time.perf_counter() - started) * 1000
        if index == 0:
            session_id = parse_session_id(completed.stdout)
            if len(case.prompts) > 1 and not session_id:
                result = evaluate_output(case, "\n".join(chunks))
                result["status"] = "failed"
                result["returncode"] = completed.returncode
                result["session_bootstrap_error"] = "session_id_not_found_in_first_turn"
                result["failed_command"] = " ".join(cmd[:4] + ["..."])
                return result, (time.perf_counter() - started) * 1000
    result = evaluate_output(case, "\n".join(chunks))
    result["returncode"] = 0
    result["session_id"] = session_id
    return result, (time.perf_counter() - started) * 1000


def summarize(results: list[dict[str, Any]], latencies_ms: list[float]) -> dict[str, Any]:
    executed = [item for item in results if item["status"] != "skipped"]
    passed = sum(1 for item in results if item["status"] == "passed")
    failed = sum(1 for item in results if item["status"] == "failed")
    skipped = sum(1 for item in results if item["status"] == "skipped")
    if latencies_ms:
        latency_p50 = statistics.median(latencies_ms)
        latency_p95 = sorted(latencies_ms)[max(0, int(len(latencies_ms) * 0.95) - 1)]
    else:
        latency_p50 = None
        latency_p95 = None
    return {
        "total": len(results),
        "executed": len(executed),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "latency_ms": {"p50": latency_p50, "p95": latency_p95},
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 2.14b Hermes CLI smoke eval.")
    parser.add_argument("--hermes-bin", default="./.venv/bin/hermes")
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--skip-health-check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout-s", type=int, default=180)
    args = parser.parse_args()

    cases = default_cases()
    if args.dry_run:
        results = [
            {
                "id": case.id,
                "status": "skipped",
                "skip_reason": "dry_run",
                "prompt_count": len(case.prompts),
                "required_substrings": case.required_substrings,
                "forbidden_substrings": case.forbidden_substrings,
            }
            for case in cases
        ]
        print(json.dumps(summarize(results, []), ensure_ascii=False, indent=2))
        return 0

    if not args.skip_health_check:
        health = check_memory_api(args.health_url)
        if not health["ok"]:
            summary = summarize([], [])
            summary["environment_error"] = health
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 2

    hermes_bin = Path(args.hermes_bin)
    if not hermes_bin.exists():
        summary = summarize([], [])
        summary["environment_error"] = {
            "ok": False,
            "error": f"Hermes CLI not found: {hermes_bin}",
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2

    results: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    for case in cases:
        result, latency_ms = run_case(case, hermes_bin, args.timeout_s)
        result["latency_ms"] = latency_ms
        results.append(result)
        if result["status"] != "skipped":
            latencies_ms.append(latency_ms)

    summary = summarize(results, latencies_ms)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
