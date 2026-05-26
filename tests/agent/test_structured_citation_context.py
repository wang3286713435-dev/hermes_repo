from __future__ import annotations

from agent.memory_kernel.citation_engine import CitationEngine
from agent.memory_kernel.adapters.hermes_memory_adapter import HermesMemoryAdapter
from agent.memory_kernel.context_builder import ContextBuilder
from agent.memory_kernel.interfaces import KernelCitation, KernelItem, KernelResult, QueryRoute, KernelRequest, RetrievalOutput
from agent.memory_kernel.kernel import MemoryKernel
from agent.memory_kernel.session_document_scope import DocumentScopeDecision


def test_citation_engine_preserves_excel_metadata_from_items():
    item = KernelItem(
        chunk_id="chunk-xlsx",
        document_id="doc-excel",
        version_id="ver-1",
        text="报价位于报价汇总表。",
        source_name="硬件清单.xlsx",
        metadata={
            "parser": "xlsx",
            "sheet_name": "报价汇总",
            "cell_range": "B2:F8",
            "row_start": 2,
            "row_end": 8,
        },
    )

    citations = CitationEngine().normalize_citations([], [item])

    assert citations[0].metadata["sheet_name"] == "报价汇总"
    assert citations[0].metadata["cell_range"] == "B2:F8"


def test_context_builder_renders_excel_structured_citation_with_cell_range():
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="chunk-xlsx",
                document_id="doc-excel",
                version_id="ver-1",
                text="含税总价见报价汇总。",
                source_name="硬件清单.xlsx",
                metadata={
                    "parser": "xlsx",
                    "sheet_name": "报价汇总",
                    "cell_range": "B2:F8",
                    "row_start": 2,
                    "row_end": 8,
                },
            )
        ],
        citations=[],
        backend="hermes_memory",
    )

    context = ContextBuilder().build(
        route=type("Route", (), {"needs_retrieval": True, "route_type": "enterprise_retrieval", "mode": "hybrid"})(),
        retrieval=retrieval,
    )

    assert "document_id=doc-excel" in context
    assert "sheet_name=报价汇总" in context
    assert "cell_range=B2:F8" in context
    assert "citation_precision=multi_row_range" in context
    assert "cell_range_fallback_reason" not in context


def test_context_builder_renders_excel_single_row_cell_range_without_fallback():
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="chunk-xlsx",
                document_id="doc-excel",
                version_id="ver-1",
                text="含税总价见报价汇总。",
                source_name="硬件清单.xlsx",
                metadata={
                    "parser": "xlsx",
                    "sheet_name": "报价汇总",
                    "cell_range": "B7:F7",
                    "row_start": 7,
                    "row_end": 7,
                },
            )
        ],
        citations=[],
        backend="hermes_memory",
    )

    context = ContextBuilder().build(
        route=type("Route", (), {"needs_retrieval": True, "route_type": "enterprise_retrieval", "mode": "hybrid"})(),
        retrieval=retrieval,
    )

    assert "sheet_name=报价汇总" in context
    assert "cell_range=B7:F7" in context
    assert "citation_precision=cell_range" in context
    assert "row_range_fallback=true" not in context
    assert "cell_range_fallback_reason" not in context


def test_citation_engine_backfills_raw_citation_metadata_from_items():
    item = KernelItem(
        chunk_id="chunk-xlsx",
        document_id="doc-excel",
        version_id="ver-1",
        text="含税总价见报价汇总。",
        source_name="硬件清单.xlsx",
        metadata={"parser": "xlsx", "sheet_name": "报价汇总", "cell_range": "B2:F8"},
    )
    raw = KernelCitation(
        chunk_id="chunk-xlsx",
        document_id="doc-excel",
        version_id="ver-1",
        source_name="硬件清单.xlsx",
    )

    citations = CitationEngine().normalize_citations([raw], [item])

    assert citations[0].metadata["sheet_name"] == "报价汇总"
    assert citations[0].metadata["cell_range"] == "B2:F8"


def test_context_builder_renders_excel_row_range_fallback_when_cell_range_missing():
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="chunk-xlsx",
                document_id="doc-excel",
                version_id="ver-1",
                text="报价位于某行区间。",
                source_name="硬件清单.xlsx",
                metadata={
                    "parser": "xlsx",
                    "sheet_name": "报价汇总",
                    "row_start": 12,
                    "row_end": 18,
                },
            )
        ],
        backend="hermes_memory",
    )

    context = ContextBuilder().build(
        route=type("Route", (), {"needs_retrieval": True, "route_type": "enterprise_retrieval", "mode": "hybrid"})(),
        retrieval=retrieval,
    )

    assert "sheet_name=报价汇总" in context
    assert "row_range=12-18" in context
    assert "row_range_fallback=true" in context
    assert "citation_precision=row_range_fallback" in context
    assert "cell_range_fallback_reason=missing_cell_range" in context


def test_context_builder_renders_pptx_structured_citation():
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="chunk-pptx",
                document_id="doc-pptx",
                version_id="ver-1",
                text="总体建设目标见第 3 页。",
                source_name="建设方案.pptx",
                metadata={
                    "parser": "pptx",
                    "slide_number": 3,
                    "slide_title": "总体建设目标",
                },
            )
        ],
        backend="hermes_memory",
    )

    context = ContextBuilder().build(
        route=type("Route", (), {"needs_retrieval": True, "route_type": "enterprise_retrieval", "mode": "hybrid"})(),
        retrieval=retrieval,
    )

    assert "document_id=doc-pptx" in context
    assert "slide_number=3" in context
    assert "slide_title=总体建设目标" in context


def test_context_builder_renders_kernel_self_awareness_boundaries_without_evidence():
    retrieval = RetrievalOutput(
        items=[],
        citations=[],
        backend="hermes_memory",
        trace={"kernel_capability_requested": True},
    )

    context = ContextBuilder().build(
        route=type("Route", (), {"needs_retrieval": True, "route_type": "enterprise_retrieval", "mode": "hybrid"})(),
        retrieval=retrieval,
    )

    assert "Hermes Memory Kernel capability boundary" in context
    assert "governed_import_catalog=true" in context
    assert "aliases_and_workspace_refs=true" in context
    assert "retrieval_evidence_and_citations_required=true" in context
    assert "missing_evidence_policy=Missing Evidence" in context
    assert "low_sensitive_continuity_hints_only=true" in context
    assert "raw_paths_raw_content_secrets_forbidden=true" in context
    assert "dwg_rvt_bim_content_claim_without_evidence_forbidden=true" in context


def test_kernel_capability_trigger_covers_file_management_wording():
    kernel = MemoryKernel.__new__(MemoryKernel)

    for query in [
        "你可以帮我管理文件吗",
        "你能管理公司文件吗",
        "能不能管理文件",
        "你怎么使用记忆库",
    ]:
        trace = kernel._with_kernel_capability_trace({}, KernelRequest(query=query, session_id="s1"))

        assert trace["kernel_capability_requested"] is True
        assert trace["facts_as_answer"] is False
        assert trace["transcript_as_fact"] is False
        assert trace["snapshot_as_answer"] is False


def test_context_builder_renders_structured_fields_on_citation_lines():
    retrieval = RetrievalOutput(
        items=[],
        citations=[
            KernelCitation(
                chunk_id="chunk-pptx",
                document_id="doc-pptx",
                version_id="ver-1",
                source_name="建设方案.pptx",
                metadata={"parser": "pptx", "slide_number": 3, "slide_title": "总体建设目标"},
            )
        ],
        backend="hermes_memory",
    )

    context = ContextBuilder().build(
        route=type("Route", (), {"needs_retrieval": True, "route_type": "enterprise_retrieval", "mode": "hybrid"})(),
        retrieval=retrieval,
    )

    assert "[C1]" in context
    assert "slide_number=3" in context
    assert "slide_title=总体建设目标" in context


def test_adapter_flattens_meeting_trace_as_non_fact():
    adapter = HermesMemoryAdapter.__new__(HermesMemoryAdapter)

    trace = adapter._normalize_trace(
        {
            "retrieval_trace": {
                "meeting_transcript_used": True,
                "meeting_fields_matched": ["action_item", "decision"],
                "meeting_source_chunk_ids": ["m1"],
                "action_items_detected": 2,
                "decisions_detected": 1,
                "transcript_as_fact": True,
            }
        }
    )

    assert trace["meeting_transcript_used"] is True
    assert trace["meeting_fields_matched"] == ["action_item", "decision"]
    assert trace["meeting_source_chunk_ids"] == ["m1"]
    assert trace["transcript_as_fact"] is False
    assert trace["evidence_required"] is True


def test_adapter_flattens_deep_field_trace():
    adapter = HermesMemoryAdapter.__new__(HermesMemoryAdapter)

    trace = adapter._normalize_trace(
        {
            "retrieval_trace": {
                "metadata_deep_field_profile": "pricing_scope",
                "deep_field_profile": "pricing_scope",
                "deep_field_section_hints": ["投标人须知前附表", "最高投标限价"],
                "deep_field_query_aliases": ["最高投标限价", "招标控制价"],
                "deep_field_missing_reason": "missing_concrete_price_amount",
                "deep_field_diagnostics": {
                    "status": "missing_concrete_evidence",
                    "concrete_evidence_required": True,
                    "concrete_evidence_missing_fields": ["price_ceiling"],
                },
            }
        }
    )

    assert trace["metadata_deep_field_profile"] == "pricing_scope"
    assert trace["deep_field_profile"] == "pricing_scope"
    assert trace["deep_field_section_hints"] == ["投标人须知前附表", "最高投标限价"]
    assert trace["deep_field_query_aliases"] == ["最高投标限价", "招标控制价"]
    assert trace["deep_field_missing_reason"] == "missing_concrete_price_amount"
    assert trace["deep_field_diagnostics"]["status"] == "missing_concrete_evidence"


def test_kernel_promotes_deep_field_trace_from_retrieval_trace():
    kernel = MemoryKernel.__new__(MemoryKernel)
    retrieval = RetrievalOutput(
        items=[KernelItem(chunk_id="c1", document_id="doc-tender", version_id="v1", text="evidence")],
        trace={
            "retrieval_trace": {
                "metadata_deep_field_profile": "qualification_scope",
                "deep_field_profile": "qualification_scope",
                "deep_field_section_hints": ["资格审查"],
                "deep_field_query_aliases": ["资质要求"],
                "deep_field_missing_reason": "missing_concrete_qualification_level_or_category",
                "deep_field_diagnostics": {
                    "status": "missing_concrete_evidence",
                    "concrete_evidence_required": True,
                    "concrete_evidence_missing_fields": ["qualification_requirement"],
                },
            }
        },
    )
    decision = DocumentScopeDecision(filters={}, trace={})

    trace = kernel._with_context_governance_trace(retrieval.trace, retrieval, decision)

    assert trace["metadata_deep_field_profile"] == "qualification_scope"
    assert trace["deep_field_profile"] == "qualification_scope"
    assert trace["deep_field_section_hints"] == ["资格审查"]
    assert trace["deep_field_query_aliases"] == ["资质要求"]
    assert trace["deep_field_missing_reason"] == "missing_concrete_qualification_level_or_category"
    assert trace["deep_field_diagnostics"]["concrete_evidence_missing_fields"] == ["qualification_requirement"]


def test_context_builder_renders_deep_field_diagnostics():
    retrieval = RetrievalOutput(
        backend="fake",
        trace={
            "metadata_deep_field_profile": "pricing_scope",
            "deep_field_profile": "pricing_scope",
            "deep_field_section_hints": ["投标人须知前附表", "最高投标限价"],
            "deep_field_query_aliases": ["最高投标限价", "招标控制价"],
            "deep_field_missing_reason": "missing_concrete_price_amount",
            "deep_field_diagnostics": {
                "status": "missing_concrete_evidence",
                "concrete_evidence_required": True,
                "concrete_evidence_present": False,
                "concrete_evidence_missing_fields": ["price_ceiling"],
                "boosted_phrases_used": ["最高投标限价", "招标控制价"],
            },
        },
    )

    context = ContextBuilder().build(
        QueryRoute("enterprise_retrieval", True, "test"),
        retrieval,
    )

    assert "deep_field_profile=pricing_scope" in context
    assert "metadata_deep_field_profile=pricing_scope" in context
    assert "deep_field_missing_reason=missing_concrete_price_amount" in context
    assert "deep_field_section_hints=['投标人须知前附表', '最高投标限价']" in context
    assert "deep_field_query_aliases=['最高投标限价', '招标控制价']" in context
    assert "concrete_evidence_missing_fields=['price_ceiling']" in context
    assert "do not replace retrieval evidence or Missing Evidence" in context


def test_context_builder_renders_personnel_answer_boundary():
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="personnel-1",
                document_id="doc-1",
                version_id="v1",
                text="项目管理机构包括技术负责人、安全员、质量员、施工员。",
                source_name="主标书",
            )
        ],
        citations=[
            KernelCitation(
                document_id="doc-1",
                version_id="v1",
                chunk_id="personnel-1",
                source_name="主标书",
            )
        ],
        backend="fake",
        trace={
            "metadata_deep_field_profile": "personnel_scope",
            "deep_field_profile": "personnel_scope",
            "deep_field_section_hints": ["项目管理机构", "人员要求"],
            "deep_field_query_aliases": ["人员数量", "人员专业", "人员资质"],
            "deep_field_missing_reason": None,
            "deep_field_diagnostics": {
                "status": "concrete_evidence_found",
                "concrete_evidence_required": False,
                "concrete_evidence_present": True,
                "concrete_evidence_missing_fields": [],
                "boosted_phrases_used": ["项目管理机构", "人员配备"],
            },
        },
    )

    context = ContextBuilder().build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "personnel_answer_boundary" in context
    assert "STRICT PERSONNEL-ONLY FINAL ANSWER GUARD" in context
    assert "personnel_forbidden_answer_terms=" in context
    assert "personnel_count_inference_forbidden=true" in context
    assert "ignore_non_personnel_content_in_mixed_chunks=true" in context
    assert "Forbidden in personnel-only answers" in context
    assert "project manager / project lead / registered constructor / first-class constructor / B-certificate" in context
    assert "项目经理 / 项目负责人 / 注册建造师 / 一级建造师 / B证 / 安全考核证 / 投标资质 / 联合体 / 类似工程业绩" in context
    assert "'项目经理'" in context
    assert "'注册建造师'" in context
    assert "'B证'" in context
    assert "'投标资质'" in context
    assert "'联合体'" in context
    assert "'类似工程业绩'" in context
    assert "'每个项目限1人'" in context
    assert "'每个项目只能1个'" in context
    assert "'每个项目各1人'" in context
    assert "'每项目1人'" in context
    assert "'每项目各1人'" in context
    assert "'每类1人'" in context
    assert "'每个岗位1人'" in context
    assert "'各1人'" in context
    assert "'至少各1名'" in context
    assert "personnel_violation_if_answer_contains_forbidden_term=true" in context
    assert "personnel_violation_if_answer_contains_inferred_count=true" in context
    assert "personnel_safe_fallback_required_on_violation=true" in context
    assert "personnel_safe_fallback_template=人员要求（仅限人员字段）" in context
    assert "discard the draft and output only the personnel_safe_fallback_template" in context
    assert "If a cited chunk mixes personnel staffing with project manager" in context
    assert "Do not convert role names into implicit counts" in context
    assert "Never say each project has one" in context
    assert "Missing Evidence / needs manual review for that subfield" in context


def test_context_builder_does_not_apply_personnel_boundary_to_broad_qualification_scope():
    retrieval = RetrievalOutput(
        items=[
            KernelItem(
                chunk_id="qualification-1",
                document_id="doc-1",
                version_id="v1",
                text="投标资质、项目经理、联合体、业绩、人员要求分别见资格审查章节。",
                source_name="主标书",
            )
        ],
        backend="fake",
        trace={
            "metadata_deep_field_profile": "qualification_scope",
            "deep_field_profile": "qualification_scope",
            "deep_field_section_hints": ["资格审查", "资信标"],
            "deep_field_query_aliases": ["投标资质", "项目经理", "联合体", "类似工程业绩", "人员要求"],
            "deep_field_diagnostics": {
                "status": "mixed_deep_field_query",
                "concrete_evidence_required": True,
                "concrete_evidence_present": True,
                "concrete_evidence_missing_fields": [],
            },
        },
    )

    context = ContextBuilder().build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "deep_field_profile=qualification_scope" in context
    assert "personnel_answer_boundary" not in context
    assert "personnel_forbidden_answer_terms" not in context
    assert "personnel_count_inference_forbidden" not in context
    assert "ignore_non_personnel_content_in_mixed_chunks" not in context
    assert "personnel_safe_fallback_required_on_violation" not in context
    assert "personnel_safe_fallback_template" not in context
    assert "STRICT PERSONNEL-ONLY FINAL ANSWER GUARD" not in context


def test_context_builder_file_discovery_candidates_hide_technical_ids_by_default():
    retrieval = RetrievalOutput(
        backend="fake",
        trace={
            "scope_resolution_status": "file_discovery_candidates",
            "file_discovery_requires_clarification": True,
            "file_candidates": [
                {
                    "alias": "C塔人力成本测算表",
                    "document_id": "doc-secret",
                    "version_id": "ver-secret",
                    "title": "C塔项目人力配置及成本测算表0506.xlsx",
                    "source_name": "C塔项目人力配置及成本测算表0506.xlsx",
                    "workspace_id": "ws-secret",
                    "workspace_name": "C塔项目",
                    "document_category": "人力配置 / 成本测算",
                    "chunk_count": 4,
                }
            ],
        },
    )

    context = ContextBuilder().build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "@C塔人力成本测算表 — 工作区：C塔项目 / 人力配置 / 成本测算" in context
    assert "document_id=doc-secret" not in context
    assert "version_id=ver-secret" not in context
    assert "workspace_id=ws-secret" not in context
    assert "chunk_count=4" not in context


def test_context_builder_file_discovery_candidates_hide_raw_paths_from_display_fallbacks():
    retrieval = RetrievalOutput(
        backend="fake",
        trace={
            "scope_resolution_status": "file_discovery_candidates",
            "file_discovery_requires_clarification": True,
            "file_candidates": [
                {
                    "document_id": "doc-secret",
                    "version_id": "ver-secret",
                    "title": "/Users/hermes/import_samples/C塔项目人力配置及成本测算表0506.xlsx",
                    "source_name": "/Users/hermes/import_samples/C塔项目人力配置及成本测算表0506.xlsx",
                    "display_path": "/Users/hermes/import_samples/C塔项目人力配置及成本测算表0506.xlsx",
                    "chunk_count": 4,
                }
            ],
        },
    )

    context = ContextBuilder().build(QueryRoute("enterprise_retrieval", True, "test"), retrieval)

    assert "C塔项目人力配置及成本测算表0506.xlsx" in context
    assert "/Users/hermes/import_samples" not in context
    assert "document_id=doc-secret" not in context
    assert "version_id=ver-secret" not in context
    assert "display_path" not in context

def _personnel_guard_result(profile: str = "personnel_scope") -> KernelResult:
    retrieval = RetrievalOutput(backend="fake", trace={"deep_field_profile": profile, "metadata_deep_field_profile": profile})
    return KernelResult(route=QueryRoute("enterprise_retrieval", True, "test"), retrieval=retrieval, trace={"deep_field_profile": profile, "metadata_deep_field_profile": profile})


def test_kernel_personnel_answer_guard_fallbacks_on_forbidden_term():
    kernel = MemoryKernel.__new__(MemoryKernel)
    request = KernelRequest(query="@主标书 人员要求是什么？请只回答人员要求。", session_id="s1")
    guarded = kernel.apply_personnel_answer_guard(request, "人员要求包括项目经理和安全员。", _personnel_guard_result())
    assert "项目经理" not in guarded
    assert "Missing Evidence / 人工复核" in guarded
    assert "facts_as_answer=false" in guarded
    assert "transcript_as_fact=false" in guarded


def test_kernel_personnel_answer_guard_fallbacks_on_count_inference():
    kernel = MemoryKernel.__new__(MemoryKernel)
    request = KernelRequest(query="@主标书 人员数量、专业、职称或资质要求是什么？请只回答人员要求。", session_id="s1")
    result = _personnel_guard_result()
    guarded = kernel.apply_personnel_answer_guard(request, "人员配置为施工员、安全员，每项目各1人。", result)
    assert "每项目各1人" not in guarded
    assert "Missing Evidence / 人工复核" in guarded
    assert result.trace["personnel_answer_guard"]["fallback_applied"] is True


def test_kernel_personnel_answer_guard_does_not_apply_to_broad_qualification_scope():
    kernel = MemoryKernel.__new__(MemoryKernel)
    request = KernelRequest(query="@主标书 投标资质、项目经理、联合体、业绩、人员要求分别是什么？", session_id="s1")
    response = "项目经理、联合体、类似工程业绩和人员要求分别如下。"
    guarded = kernel.apply_personnel_answer_guard(request, response, _personnel_guard_result("qualification_scope"))
    assert guarded == response


def test_kernel_personnel_safe_fallback_has_no_forbidden_terms_or_counts():
    kernel = MemoryKernel.__new__(MemoryKernel)
    fallback = kernel._personnel_safe_fallback_response()
    for term in kernel._PERSONNEL_FORBIDDEN_ANSWER_TERMS:
        assert term not in fallback
    for phrase in kernel._PERSONNEL_FORBIDDEN_COUNT_PHRASES:
        assert phrase not in fallback
    assert "facts_as_answer=false" in fallback
    assert "transcript_as_fact=false" in fallback
