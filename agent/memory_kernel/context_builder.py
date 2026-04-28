from __future__ import annotations

from typing import Any

from .interfaces import KernelCitation, KernelItem, KernelResult, QueryRoute, RetrievalOutput


class ContextBuilder:
    def build(self, route: QueryRoute, retrieval: RetrievalOutput) -> str:
        trace = retrieval.trace or {}
        scope_lines = self._scope_lines(trace)
        facts_diagnostic_lines = self._facts_diagnostic_lines(trace)
        confirmed_facts_lines = self._confirmed_facts_lines(trace)
        if (
            not route.needs_retrieval
            or (
                not retrieval.items
                and not retrieval.citations
                and not scope_lines
                and not facts_diagnostic_lines
                and not confirmed_facts_lines
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

        if confirmed_facts_lines:
            parts.append("Confirmed facts auxiliary context:")
            parts.extend(confirmed_facts_lines)
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
            return "; ".join(parts)

        row_start = metadata.get("row_start")
        row_end = metadata.get("row_end")
        if row_start is not None or row_end is not None:
            row_label = row_start if row_start == row_end or row_end is None else f"{row_start}-{row_end}"
            parts.append(f"row_range={row_label}")
            parts.append("cell_range_fallback_reason=missing_cell_range")
        return "; ".join(parts)

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
