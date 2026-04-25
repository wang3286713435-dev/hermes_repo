from __future__ import annotations

from agent.memory_kernel.citation_engine import CitationEngine
from agent.memory_kernel.context_builder import ContextBuilder
from agent.memory_kernel.interfaces import KernelCitation, KernelItem, RetrievalOutput


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
