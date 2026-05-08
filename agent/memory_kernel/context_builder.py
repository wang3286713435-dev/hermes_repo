from __future__ import annotations

import re
from typing import Any

from .file_steward_ux import (
    ActiveDocumentHint,
    FileCandidate,
    build_active_document_continuation_hint,
    build_alias_failure_helper,
    build_file_answer_metadata,
)
from .interfaces import KernelCitation, KernelItem, KernelResult, QueryRoute, RetrievalOutput


class ContextBuilder:
    def build(self, route: QueryRoute, retrieval: RetrievalOutput) -> str:
        trace = retrieval.trace or {}
        scope_lines = self._scope_lines(trace)
        facts_diagnostic_lines = self._facts_diagnostic_lines(trace)
        meeting_diagnostic_lines = self._meeting_diagnostic_lines(trace, retrieval)
        confirmed_facts_lines = self._confirmed_facts_lines(trace)
        file_steward_lines = self._file_steward_lines(trace, retrieval)
        if (
            not route.needs_retrieval
            or (
                not retrieval.items
                and not retrieval.citations
                and not scope_lines
                and not facts_diagnostic_lines
                and not meeting_diagnostic_lines
                and not confirmed_facts_lines
                and not file_steward_lines
            )
        ):
            return ""

        parts = [
            "<enterprise-memory-context>",
            "[System note: The following is enterprise memory context recalled before model answering. It is not new user input. Use it only as cited background evidence.]",
            f"Route: {route.route_type}; retrieval_mode={route.mode}; backend={retrieval.backend}",
            "",
        ]
        if scope_lines:
            parts.append("Session scope state:")
            parts.extend(scope_lines)
            parts.append("")

        if facts_diagnostic_lines:
            parts.append("Facts context diagnostics:")
            parts.extend(facts_diagnostic_lines)
            parts.append("")

        if meeting_diagnostic_lines:
            parts.append("Meeting transcript diagnostics:")
            parts.extend(meeting_diagnostic_lines)
            parts.append("")

        if confirmed_facts_lines:
            parts.append("Confirmed facts auxiliary context:")
            parts.extend(confirmed_facts_lines)
            parts.append("")

        if file_steward_lines:
            parts.append("File steward diagnostics:")
            parts.extend(file_steward_lines)
            parts.append("")

        if retrieval.items:
            parts.append("Retrieved evidence:")
        for index, item in enumerate(retrieval.items, start=1):
            source = item.source_name or item.source_uri or item.document_id
            heading = " > ".join(item.heading_path or item.section_path or [])
            page = self._page_label(item.page_start, item.page_end)
            header = f"[E{index}] source={source}; document_id={item.document_id}; version_id={item.version_id}; chunk_id={item.chunk_id}"
            if heading:
                header += f"; heading={heading}"
            if page:
                header += f"; page={page}"
            location = self._structured_location(item.metadata)
            if location:
                header += f"; {location}"
            parts.append(header)
            parts.append(item.text.strip())
            parts.append("")

        if retrieval.citations:
            parts.append("Citations:")
            for index, citation in enumerate(retrieval.citations, start=1):
                parts.append(self._citation_line(index, citation))

        parts.append("</enterprise-memory-context>")
        return "\n".join(parts).strip()

    def result_to_payload(self, result: KernelResult) -> dict:
        return {
            "route": {
                "route_type": result.route.route_type,
                "needs_retrieval": result.route.needs_retrieval,
                "reason": result.route.reason,
                "mode": result.route.mode,
            },
            "backend": result.retrieval.backend,
            "dense_retrieval_status": result.retrieval.dense_retrieval_status,
            "sparse_retrieval_status": result.retrieval.sparse_retrieval_status,
            "retrieval_mode": result.retrieval.retrieval_mode,
            "applied_filters": result.retrieval.applied_filters,
            "ignored_filters": result.retrieval.ignored_filters,
            "citations": [citation.__dict__ for citation in result.retrieval.citations],
            "trace": result.trace,
        }

    def _citation_line(self, index: int, citation: KernelCitation) -> str:
        source = citation.source_name or citation.source_uri or citation.document_id
        heading = " > ".join(citation.heading_path or citation.section_path or [])
        page = self._page_label(citation.page_start, citation.page_end)
        suffix = []
        if citation.version_name:
            suffix.append(f"version={citation.version_name}")
        if heading:
            suffix.append(f"heading={heading}")
        if page:
            suffix.append(f"page={page}")
        location = self._structured_location(citation.metadata)
        if location:
            suffix.append(location)
        suffix_text = "; ".join(suffix)
        return f"[C{index}] {source}; document_id={citation.document_id}; version_id={citation.version_id}; chunk_id={citation.chunk_id}" + (f"; {suffix_text}" if suffix_text else "")

    def _structured_location(self, metadata: dict[str, Any] | None) -> str:
        data = metadata or {}
        parser = str(data.get("parser") or "").lower()
        if parser == "xlsx" or data.get("sheet_name") or data.get("cell_range"):
            return self._xlsx_location(data)
        if parser == "pptx" or data.get("slide_number") is not None:
            return self._pptx_location(data)
        if data.get("meeting_transcript") or data.get("content_profile") == "meeting_transcript":
            return self._meeting_location(data)
        return ""

    def _xlsx_location(self, metadata: dict[str, Any]) -> str:
        parts: list[str] = []
        sheet_name = metadata.get("sheet_name")
        if sheet_name:
            parts.append(f"sheet_name={sheet_name}")

        cell_range = metadata.get("cell_range")
        if cell_range:
            parts.append(f"cell_range={cell_range}")
            parts.append(f"citation_precision={self._xlsx_citation_precision(str(cell_range))}")
            return "; ".join(parts)

        row_start = metadata.get("row_start")
        row_end = metadata.get("row_end")
        if row_start is not None or row_end is not None:
            row_label = row_start if row_start == row_end or row_end is None else f"{row_start}-{row_end}"
            parts.append(f"row_range={row_label}")
            parts.append("row_range_fallback=true")
            parts.append("citation_precision=row_range_fallback")
            parts.append("cell_range_fallback_reason=missing_cell_range")
        return "; ".join(parts)

    def _xlsx_citation_precision(self, cell_range: str) -> str:
        refs = [part.strip() for part in cell_range.split(":", 1)]
        if len(refs) == 1:
            return "cell_range"

        first_row = self._xlsx_row_number(refs[0])
        last_row = self._xlsx_row_number(refs[1])
        if first_row is None or last_row is None:
            return "range_unknown"
        if first_row != last_row:
            return "multi_row_range"
        return "cell_range"

    def _xlsx_row_number(self, ref: str) -> int | None:
        match = re.search(r"\$?[A-Za-z]+\$?(\d+)", ref)
        if not match:
            return None
        return int(match.group(1))

    def _pptx_location(self, metadata: dict[str, Any]) -> str:
        parts: list[str] = []
        slide_number = metadata.get("slide_number")
        slide_title = metadata.get("slide_title")
        if slide_number is not None:
            parts.append(f"slide_number={slide_number}")
        if slide_title:
            parts.append(f"slide_title={slide_title}")
        return "; ".join(parts)

    def _meeting_location(self, metadata: dict[str, Any]) -> str:
        parts: list[str] = ["content_profile=meeting_transcript", "transcript_as_fact=false"]
        source_location = metadata.get("source_location")
        speaker = metadata.get("speaker")
        timestamp = metadata.get("timestamp")
        fields = metadata.get("meeting_fields_matched") or metadata.get("meeting_fields")
        if source_location:
            parts.append(f"source_location={source_location}")
        if speaker:
            parts.append(f"speaker={speaker}")
        if timestamp:
            parts.append(f"timestamp={timestamp}")
        if fields:
            parts.append(f"meeting_fields_matched={fields}")
        return "; ".join(parts)

    def _page_label(self, start: int | None, end: int | None) -> str:
        if start is None and end is None:
            return ""
        if start == end or end is None:
            return str(start)
        if start is None:
            return str(end)
        return f"{start}-{end}"

    def _scope_lines(self, trace: dict) -> list[str]:
        lines: list[str] = []
        alias_resolution = trace.get("alias_resolution") or {}
        if isinstance(alias_resolution, dict) and alias_resolution:
            status = alias_resolution.get("status")
            alias = alias_resolution.get("alias")
            document_id = alias_resolution.get("resolved_document_id")
            title = alias_resolution.get("resolved_title")
            missing = alias_resolution.get("alias_missing")
            conflict = alias_resolution.get("alias_conflict")
            stale = alias_resolution.get("alias_stale_version")
            latest_version_id = alias_resolution.get("latest_version_id")
            superseded_by_version_id = alias_resolution.get("superseded_by_version_id")
            failure_reason = alias_resolution.get("bind_failure_reason")
            lines.extend(
                [
                    "Alias handling is done by Hermes session state, not by a model tool.",
                    f"alias_resolution.status={status}; alias={alias}; alias_scope={alias_resolution.get('alias_scope', 'session')}",
                ]
            )
            if document_id:
                lines.append(f"resolved_document_id={document_id}; resolved_title={title or document_id}")
            if alias_resolution.get("compare_aliases"):
                lines.append(
                    f"compare_aliases={alias_resolution.get('compare_aliases')}; compare_document_ids={alias_resolution.get('compare_document_ids')}"
                )
            if missing or conflict or stale or failure_reason:
                lines.append(
                    f"alias_diagnostics: missing={bool(missing)}; conflict={bool(conflict)}; "
                    f"stale_version={bool(stale)}; latest_version_id={latest_version_id}; "
                    f"superseded_by_version_id={superseded_by_version_id}; failure_reason={failure_reason}"
                )
            if stale:
                lines.append("alias_stale_version=true; this alias points to a historical version, recommend switching to latest when the user did not explicitly request history.")
            if alias_resolution.get("compare_alias_stale_versions"):
                lines.append(f"compare_alias_stale_versions={alias_resolution.get('compare_alias_stale_versions')}")
        if trace.get("scope_retrieval_suppressed") or trace.get("suppress_retrieval"):
            lines.append("retrieval_suppressed=true; do not answer from history memory as document evidence.")
        if trace.get("metadata_snapshot_used"):
            lines.append(
                "metadata_snapshot_used=true; snapshot_as_answer=false; evidence_required=true; "
                f"metadata_fields_matched={trace.get('metadata_fields_matched', [])}; "
                f"metadata_source_chunk_ids={trace.get('metadata_source_chunk_ids', [])}"
            )
        deep_field_lines = self._deep_field_lines(trace)
        if deep_field_lines:
            lines.extend(deep_field_lines)
        if trace.get("meeting_transcript_used"):
            lines.append(
                "meeting_transcript_used=true; transcript_as_fact=false; evidence_required=true; "
                "meeting transcript is retrieval evidence only, not confirmed facts; "
                f"meeting_fields_matched={trace.get('meeting_fields_matched', [])}; "
                f"meeting_source_chunk_ids={trace.get('meeting_source_chunk_ids', [])}"
            )
        compare_document_ids = trace.get("compare_document_ids") or trace.get("compare_scope_document_ids") or []
        if compare_document_ids:
            evidence_document_ids = trace.get("retrieval_evidence_document_ids", [])
            third_document_mixed = "true" if trace.get("third_document_mixed") else "false"
            lines.append(
                f"compare_scope: compare_document_ids={compare_document_ids}; "
                f"retrieval_evidence_document_ids={evidence_document_ids}; "
                f"third_document_mixed={third_document_mixed}; "
                f"third_document_mixed_document_ids={trace.get('third_document_mixed_document_ids', [])}"
            )
            lines.append(
                "If third_document_mixed=false, do not describe this compare as third-document contamination. "
                "Theme mismatch or partial evidence is not third-document mixing."
            )
        return lines

    def _deep_field_lines(self, trace: dict) -> list[str]:
        profile = trace.get("deep_field_profile")
        metadata_profile = trace.get("metadata_deep_field_profile")
        diagnostics = trace.get("deep_field_diagnostics") or {}
        if not any(
            [
                profile,
                metadata_profile,
                trace.get("deep_field_section_hints"),
                trace.get("deep_field_query_aliases"),
                trace.get("deep_field_missing_reason"),
                diagnostics,
            ]
        ):
            return []

        lines = [
            "deep_field_diagnostics are routing diagnostics only; they do not replace retrieval evidence or Missing Evidence.",
            f"deep_field_profile={profile}; metadata_deep_field_profile={metadata_profile}; "
            f"deep_field_missing_reason={trace.get('deep_field_missing_reason')}",
            f"deep_field_section_hints={trace.get('deep_field_section_hints', [])}",
            f"deep_field_query_aliases={trace.get('deep_field_query_aliases', [])}",
        ]
        if isinstance(diagnostics, dict) and diagnostics:
            lines.append(
                "deep_field_diagnostics: "
                f"status={diagnostics.get('status')}; "
                f"concrete_evidence_required={bool(diagnostics.get('concrete_evidence_required'))}; "
                f"concrete_evidence_present={bool(diagnostics.get('concrete_evidence_present'))}; "
                f"concrete_evidence_missing_fields={diagnostics.get('concrete_evidence_missing_fields', [])}; "
                f"boosted_phrases_used={diagnostics.get('boosted_phrases_used', [])}"
            )
        if profile == "personnel_scope" or metadata_profile == "personnel_scope":
            lines.extend(
                [
                    "personnel_answer_boundary: STRICT PERSONNEL-ONLY FINAL ANSWER GUARD.",
                    "personnel_forbidden_answer_terms=['项目经理', '项目负责人', '注册建造师', '一级建造师', 'B证', '安全考核证', '投标资质', '联合体', '类似工程业绩']",
                    "personnel_count_inference_forbidden=true; forbidden_count_inferences=['每个项目限1人', '每个项目只能1个', '每个项目各1人', '每项目1人', '每项目各1人', '每类1人', '每个岗位1人', '各1人', '至少各1名']",
                    "ignore_non_personnel_content_in_mixed_chunks=true",
                    "personnel_violation_if_answer_contains_forbidden_term=true",
                    "personnel_violation_if_answer_contains_inferred_count=true",
                    "personnel_safe_fallback_required_on_violation=true",
                    "personnel_safe_fallback_template=人员要求（仅限人员字段）: 数量: Missing Evidence / 人工复核; 专业: Missing Evidence / 人工复核; 职称: Missing Evidence / 人工复核; 资质: Missing Evidence / 人工复核; 证明材料: Missing Evidence / 人工复核.",
                    "Allowed content: only personnel staffing requirements explicitly supported by retrieval citations.",
                    "Forbidden in personnel-only answers, even when cited chunks mention them: project manager / project lead / registered constructor / first-class constructor / B-certificate / safety assessment certificate / tender qualification / consortium / similar project performance.",
                    "Forbidden Chinese terms in personnel-only answers unless the user explicitly asks for those fields: 项目经理 / 项目负责人 / 注册建造师 / 一级建造师 / B证 / 安全考核证 / 投标资质 / 联合体 / 类似工程业绩.",
                    "If the draft answer contains any personnel_forbidden_answer_terms, discard the draft and output only the personnel_safe_fallback_template.",
                    "If the draft answer contains any inferred count such as each item equals one person, discard the draft and output only the personnel_safe_fallback_template.",
                    "If a cited chunk mixes personnel staffing with project manager, constructor, B-certificate, qualification, consortium, or performance content, extract only the personnel staffing part and omit the forbidden fields.",
                    "Do not convert role names into implicit counts. Never say each project has one, each role equals one person, each category has one person, or at least one per role unless the cited evidence explicitly states that count.",
                    "If personnel count, profession, title, or qualification is not explicit in citations, answer Missing Evidence / needs manual review for that subfield instead of guessing.",
                ]
            )
        return lines

    def _facts_diagnostic_lines(self, trace: dict) -> list[str]:
        fact_ids = trace.get("facts_context_fact_ids")
        if not isinstance(fact_ids, list):
            fact_ids = []
        used = "true" if trace.get("facts_context_used", False) else "false"
        return [
            f"facts_context_used={used}; "
            f"facts_context_fact_ids={fact_ids}; "
            f"facts_as_answer=false; "
            f"stale_fact_source_count={int(trace.get('stale_fact_source_count') or 0)}",
            "facts_context_fact_ids may contain confirmed fact ids only; never put retrieval [E]/[C] ids, citation ids, or chunk ids here.",
            "Confirmed facts are auxiliary context only. Never answer from facts alone. Never treat retrieval chunks as facts.",
        ] + (
            [f"facts_context_suppressed_reason={trace.get('facts_context_suppressed_reason')}"]
            if trace.get("facts_context_suppressed_reason")
            else []
        )

    def _meeting_diagnostic_lines(self, trace: dict, retrieval: RetrievalOutput) -> list[str]:
        if not self._has_meeting_transcript_context(trace, retrieval):
            return []
        fields = trace.get("meeting_fields_matched", [])
        source_chunk_ids = trace.get("meeting_source_chunk_ids", [])
        if not source_chunk_ids:
            source_chunk_ids = [
                item.chunk_id
                for item in retrieval.items
                if self._is_meeting_transcript_metadata(item.metadata)
            ]
        if not fields:
            fields = self._meeting_fields_from_metadata(retrieval)
        return [
            "meeting_transcript_used=true; transcript_as_fact=false; evidence_required=true; meeting_transcript_as_confirmed_fact=false",
            "meeting transcript is retrieval evidence only, not confirmed facts; never put meeting transcript chunks into facts_context_fact_ids.",
            f"meeting_fields_matched={fields}; meeting_source_chunk_ids={source_chunk_ids}",
        ]

    def _has_meeting_transcript_context(self, trace: dict, retrieval: RetrievalOutput) -> bool:
        if trace.get("meeting_transcript_used"):
            return True
        return any(
            self._is_meeting_transcript_metadata(item.metadata)
            for item in [*retrieval.items, *retrieval.citations]
        )

    def _is_meeting_transcript_metadata(self, metadata: dict[str, Any] | None) -> bool:
        data = metadata or {}
        return bool(data.get("meeting_transcript") or data.get("content_profile") == "meeting_transcript")

    def _meeting_fields_from_metadata(self, retrieval: RetrievalOutput) -> list[Any]:
        fields: list[Any] = []
        for item in [*retrieval.items, *retrieval.citations]:
            if not self._is_meeting_transcript_metadata(item.metadata):
                continue
            metadata = item.metadata or {}
            value = metadata.get("meeting_fields_matched") or metadata.get("meeting_fields")
            if isinstance(value, list):
                fields.extend(value)
            elif value:
                fields.append(value)
        return fields

    def _confirmed_facts_lines(self, trace: dict) -> list[str]:
        lines: list[str] = []
        if trace.get("facts_context_used"):
            lines.append(
                "facts_context_used=true; facts_as_answer=false; "
                f"facts_context_fact_ids={trace.get('facts_context_fact_ids', [])}; "
                f"stale_fact_source_count={trace.get('stale_fact_source_count', 0)}; "
                f"facts_context_diagnostic_only={bool(trace.get('facts_context_diagnostic_only'))}"
            )
            lines.append(
                "Confirmed facts are auxiliary context only; final answers still require retrieval evidence, and facts must not replace citations. "
                "Never answer from facts alone. Never treat retrieval chunks as facts."
            )
            for fact in trace.get("facts_context") or []:
                if not isinstance(fact, dict):
                    continue
                lines.append(
                    "confirmed_fact: "
                    f"fact_id={fact.get('fact_id')}; fact_type={fact.get('fact_type')}; "
                    f"subject={fact.get('subject')}; predicate={fact.get('predicate')}; value={fact.get('value')}; "
                    f"source_document_id={fact.get('source_document_id')}; "
                    f"source_version_id={fact.get('source_version_id')}; "
                    f"source_chunk_id={fact.get('source_chunk_id')}; "
                    f"stale_source_version={bool(fact.get('stale_source_version'))}; "
                    f"latest_version_id={fact.get('latest_version_id')}"
                )
                if fact.get("stale_source_version"):
                    lines.append("confirmed_fact_warning: source version is stale; show the warning and prefer latest retrieval evidence when available.")
        return lines

    def _file_steward_lines(self, trace: dict, retrieval: RetrievalOutput) -> list[str]:
        helpers: list[dict[str, Any]] = []

        alias_helper = self._file_steward_alias_helper(trace)
        if alias_helper:
            helpers.append(alias_helper)

        active_helper = self._file_steward_active_document_helper(trace)
        if active_helper:
            helpers.append(active_helper)

        metadata_helper = self._file_steward_answer_metadata_helper(retrieval)
        if metadata_helper:
            helpers.append(metadata_helper)

        lines: list[str] = []
        for helper in helpers:
            lines.extend(self._format_file_steward_helper(helper))
        return lines

    def _file_steward_alias_helper(self, trace: dict) -> dict[str, Any] | None:
        alias_resolution = trace.get("alias_resolution") or {}
        if not isinstance(alias_resolution, dict):
            return None

        alias = alias_resolution.get("alias") or trace.get("alias")
        alias_missing = bool(alias_resolution.get("alias_missing") or trace.get("alias_missing"))
        retrieval_suppressed = bool(
            trace.get("scope_retrieval_suppressed")
            or trace.get("suppress_retrieval")
            or trace.get("retrieval_suppressed")
        )
        if not alias or not (alias_missing or retrieval_suppressed):
            return None

        return build_alias_failure_helper(
            alias=str(alias),
            candidates=self._file_steward_candidates(trace),
            active_document=self._file_steward_active_document_hint(trace),
            failed_reason=str(alias_resolution.get("status") or trace.get("scope_resolution_status") or "alias_missing"),
        )

    def _file_steward_active_document_helper(self, trace: dict) -> dict[str, Any] | None:
        active_document = self._file_steward_active_document_hint(trace)
        if active_document is None:
            return None
        return build_active_document_continuation_hint(active_document)

    def _file_steward_answer_metadata_helper(self, retrieval: RetrievalOutput) -> dict[str, Any] | None:
        evidence = self._first_file_steward_evidence(retrieval)
        if evidence is None:
            return None
        source_name = self._file_steward_source_name(evidence.metadata, evidence.source_name, evidence.source_uri, evidence.document_id)
        title = self._file_steward_title(evidence.metadata, source_name, evidence.document_id)
        return build_file_answer_metadata(
            document_id=evidence.document_id,
            version_id=evidence.version_id,
            title=title,
            source_name=source_name,
            source_type=self._file_steward_source_type(evidence.metadata),
            evidence_scope="document",
            citation_count=len(retrieval.citations),
        )

    def _file_steward_active_document_hint(self, trace: dict) -> ActiveDocumentHint | None:
        document_id = trace.get("active_document_id")
        title = trace.get("active_document_title") or trace.get("active_document_name")
        if not document_id:
            return None
        return ActiveDocumentHint(
            document_id=str(document_id),
            version_id=self._optional_str(trace.get("active_document_version_id")),
            title=str(title or document_id),
            source_name=self._optional_str(trace.get("active_document_source_name")),
            source_type=self._optional_str(trace.get("active_document_source_type")),
            scope_source=self._optional_str(trace.get("document_scope_source") or trace.get("scope_source")),
        )

    def _file_steward_candidates(self, trace: dict) -> list[FileCandidate]:
        raw_candidates = trace.get("file_candidates") or trace.get("alias_candidates") or trace.get("candidate_documents") or []
        candidates: list[FileCandidate] = []
        if not isinstance(raw_candidates, list):
            return candidates
        for candidate in raw_candidates:
            if not isinstance(candidate, dict) or not candidate.get("document_id"):
                continue
            candidates.append(
                FileCandidate(
                    document_id=str(candidate.get("document_id")),
                    version_id=self._optional_str(candidate.get("version_id")),
                    title=str(candidate.get("title") or candidate.get("source_name") or candidate.get("document_id")),
                    source_name=self._optional_str(candidate.get("source_name")),
                    source_type=self._optional_str(candidate.get("source_type")),
                    match_reason=self._optional_str(candidate.get("match_reason") or candidate.get("reason")),
                )
            )
        return candidates

    def _first_file_steward_evidence(self, retrieval: RetrievalOutput) -> KernelItem | KernelCitation | None:
        if retrieval.items:
            return retrieval.items[0]
        if retrieval.citations:
            return retrieval.citations[0]
        return None

    def _file_steward_title(self, metadata: dict[str, Any] | None, source_name: str | None, document_id: str) -> str:
        data = metadata or {}
        return str(
            data.get("title")
            or data.get("document_title")
            or data.get("source_title")
            or source_name
            or document_id
        )

    def _file_steward_source_type(self, metadata: dict[str, Any] | None) -> str | None:
        data = metadata or {}
        value = data.get("source_type") or data.get("document_type") or data.get("parser")
        return self._optional_str(value)

    def _format_file_steward_helper(self, helper: dict[str, Any]) -> list[str]:
        lines = [
            f"file_steward.type={helper.get('type')}; status={helper.get('status')}",
            "facts_as_answer=false; transcript_as_fact=false; snapshot_as_answer=false; "
            "metadata_as_answer=false; requires_retrieval_evidence=true",
        ]
        helper_type = helper.get("type")
        if helper_type == "alias_failure_helper":
            lines.append(
                f"alias={helper.get('alias')}; failed_reason={helper.get('failed_reason')}; "
                f"candidate_count={helper.get('candidate_count')}; auto_bind_allowed={str(helper.get('auto_bind_allowed')).lower()}; "
                f"retrieval_evidence_document_ids={helper.get('retrieval_evidence_document_ids', [])}; "
                f"next_action={helper.get('next_action')}"
            )
            for candidate in helper.get("candidates") or []:
                if not isinstance(candidate, dict):
                    continue
                lines.append(
                    "file_candidate: "
                    f"document_id={candidate.get('document_id')}; version_id={candidate.get('version_id')}; "
                    f"title={candidate.get('title')}; source_name={candidate.get('source_name')}; "
                    f"source_type={candidate.get('source_type')}; match_reason={candidate.get('match_reason')}"
                )
            active_document = helper.get("active_document")
            if isinstance(active_document, dict) and active_document:
                lines.append(self._format_active_document_line(active_document))
        elif helper_type == "active_document_continuation_hint":
            lines.append(
                f"can_continue={str(helper.get('can_continue')).lower()}; next_action={helper.get('next_action')}"
            )
            active_document = helper.get("active_document")
            if isinstance(active_document, dict) and active_document:
                lines.append(self._format_active_document_line(active_document))
        elif helper_type == "file_answer_metadata":
            file_metadata = helper.get("file") or {}
            if isinstance(file_metadata, dict):
                source_fields_present = all(
                    bool(file_metadata.get(field))
                    for field in ("document_id", "version_id", "title", "source_name", "source_type")
                )
                lines.extend(
                    [
                        "file_answer_metadata_required_fields=document_id,version_id,title,source_name,source_type,citation_count",
                        f"file_answer_metadata_echo_required=true; file_answer_metadata_source_fields_present={str(source_fields_present).lower()}",
                        "file_answer_metadata_safety_flags: metadata_as_answer=false; facts_as_answer=false; "
                        "snapshot_as_answer=false; requires_retrieval_evidence=true",
                        "file_answer_metadata_instruction=when_user_requests_file_answer_metadata_or_citation_count_echo_document_id_version_id_title_source_name_source_type_citation_count_and_safety_flags; "
                        "metadata_is_display_only_not_answer_evidence=true",
                    ]
                )
                lines.append(
                    "file_answer_metadata: "
                    f"document_id={file_metadata.get('document_id')}; "
                    f"version_id={file_metadata.get('version_id')}; "
                    f"title={file_metadata.get('title')}; "
                    f"source_name={file_metadata.get('source_name')}; "
                    f"source_type={file_metadata.get('source_type')}; "
                    f"evidence_scope={file_metadata.get('evidence_scope')}; "
                    f"citation_count={file_metadata.get('citation_count')}"
                )
        return lines

    def _file_steward_source_name(
        self,
        metadata: dict[str, Any] | None,
        source_name: str | None,
        source_uri: str | None,
        document_id: str,
    ) -> str:
        data = metadata or {}
        return str(
            source_name
            or source_uri
            or data.get("source_name")
            or data.get("file_name")
            or data.get("source_title")
            or data.get("title")
            or data.get("document_title")
            or document_id
        )

    def _format_active_document_line(self, active_document: dict[str, Any]) -> str:
        return (
            "active_document: "
            f"document_id={active_document.get('document_id')}; "
            f"version_id={active_document.get('version_id')}; "
            f"title={active_document.get('title')}; "
            f"source_name={active_document.get('source_name')}; "
            f"source_type={active_document.get('source_type')}; "
            f"scope_source={active_document.get('scope_source')}"
        )

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)
