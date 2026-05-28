from __future__ import annotations

from dataclasses import dataclass

from agent.memory_kernel.natural_file_import import NaturalFileImportRequest
from agent.memory_kernel.natural_file_import_runtime import (
    NaturalFileImportRuntimeResponse,
    build_natural_import_context,
    maybe_handle_temporary_attachment_boundary,
    maybe_handle_natural_file_import,
    render_natural_file_import_response,
    validate_natural_import_response,
)
from agent.memory_kernel.natural_file_upload_adapter import NaturalFileUploadResult
from agent.memory_kernel.config import MemoryKernelConfig
from agent.memory_kernel.interfaces import KernelCitation, KernelItem, KernelRequest, RetrievalOutput
from agent.memory_kernel.kernel import MemoryKernel
from agent.memory_kernel.session_document_scope import DocumentScopeDecision, SessionDocumentScopeStore
from run_agent import AIAgent


@dataclass
class FakeUploadAdapter:
    result: NaturalFileUploadResult
    calls: int = 0

    def upload(self, request: NaturalFileImportRequest) -> NaturalFileUploadResult:
        self.calls += 1
        return self.result


@dataclass
class FakeNaturalImportLLM:
    reply: str
    contexts: list[dict] | None = None

    def __post_init__(self) -> None:
        self.contexts = []

    def __call__(self, context: dict) -> str:
        self.contexts.append(context)
        return self.reply


class FakeBodyRetrieval:
    def __init__(self):
        self.requests = []

    def resolve_document_titles(self, titles, filters):
        if "C塔智能化标准" in titles:
            return [
                {
                    "document_id": "doc-standard",
                    "version_id": "ver-standard",
                    "title": "C塔智能化标准",
                    "source_name": "C塔智能化专业标准.docx",
                }
            ]
        return []

    def retrieve(self, request, route):
        self.requests.append(request)
        return RetrievalOutput(
            items=[
                KernelItem(
                    chunk_id="chunk-standard-1",
                    document_id=request.filters.get("document_id", "doc-standard"),
                    version_id=request.filters.get("version_id", "ver-standard"),
                    text="C塔智能化专业采用数字化交付标准、BIM模型交付标准和系统联调验收标准。",
                    source_name="C塔智能化专业标准.docx",
                    metadata={"parser": "docx", "source_type": "docx"},
                )
            ],
            citations=[
                KernelCitation(
                    chunk_id="chunk-standard-1",
                    document_id=request.filters.get("document_id", "doc-standard"),
                    version_id=request.filters.get("version_id", "ver-standard"),
                    source_name="C塔智能化专业标准.docx",
                    quote_text="C塔智能化专业采用数字化交付标准、BIM模型交付标准和系统联调验收标准。",
                    metadata={"parser": "docx", "source_type": "docx"},
                )
            ],
            backend="fake",
            sparse_retrieval_status="executed",
            applied_filters=dict(request.filters),
            trace={"retrieval_evidence_document_ids": [request.filters.get("document_id", "doc-standard")]},
        )


def _success_result() -> NaturalFileUploadResult:
    return NaturalFileUploadResult(
        success=True,
        document_id="doc-runtime",
        version_id="ver-runtime",
        chunk_count=4,
        indexed_count=4,
        message="fake upload ok",
    )


def _bound_success_diagnostics(alias: str = "测试文件") -> dict:
    return {
        "natural_import_detected": True,
        "real_upload_enabled": True,
        "upload_adapter_status": "executed",
        "ingestion_status": "upload_succeeded",
        "import_failed_reason": None,
        "document_id": "doc-runtime",
        "version_id": "ver-runtime",
        "chunk_count": 4,
        "indexed_count": 4,
        "alias_persisted": True,
        "alias_resolution": {
            "status": "alias_bound",
            "alias": alias,
            "resolved_document_id": "doc-runtime",
            "resolved_version_id": "ver-runtime",
        },
        "alias_continuity_status": "stored",
        "alias_continuity_source": "natural_import_success",
        "post_import_alias_verification_status": "passed",
        "post_import_alias_verification_alias": f"@{alias}",
        "post_import_alias_verification_owner_source": "api_derived_session_id",
        "post_import_alias_verification_failure_reason": None,
        "api_session_key_source": "api_derived_session_id",
        "history_message_count": 0,
        "retrieval_evidence_document_ids": [],
        "import_diagnostics_as_retrieval_evidence": False,
        "metadata_as_answer": False,
        "facts_as_answer": False,
        "snapshot_as_answer": False,
        "transcript_as_fact": False,
        "requires_retrieval_evidence": True,
        "third_document_contamination": False,
        "workspace_context": {
            "workspace_id": "ws-demo",
            "workspace_name": "测试项目",
            "workspace_type": "project",
            "document_category": "测试资料",
            "confidence": "medium",
            "needs_user_confirmation": True,
        },
        "suggested_alias": f"@{alias}",
        "alias_status": "alias_bound",
        "workspace_context_as_retrieval_evidence": False,
    }


def test_non_import_prompt_is_not_intercepted():
    response = maybe_handle_natural_file_import("帮我看看 /tmp/demo.docx")

    assert response is None


def test_temporary_attachment_alias_workspace_question_returns_product_boundary():
    response = maybe_handle_temporary_attachment_boundary("这个附件现在有别名或工作区吗？")

    assert response is not None
    assert response.completed is True
    assert response.diagnostics["temporary_attachment_boundary"] is True
    assert response.diagnostics["facts_as_answer"] is False
    assert response.diagnostics["retrieval_evidence_document_ids"] == []
    assert "临时附件上下文" in response.final_response
    assert "不能确认它已经进入 Hermes 记忆库" in response.final_response
    assert "不能说它已经绑定别名或工作区" in response.final_response
    assert "帮我导入这个文件" in response.final_response
    assert "系统预设回复" not in response.final_response
    assert "Natural file import diagnostics:" not in response.final_response


def test_temporary_attachment_boundary_does_not_intercept_explicit_import():
    response = maybe_handle_temporary_attachment_boundary("帮我导入这个文件：/tmp/demo.pdf")

    assert response is None


def test_temporary_attachment_boundary_can_be_skipped_when_imported_scope_exists(tmp_path):
    agent = object.__new__(AIAgent)
    agent.session_id = "s-imported"
    agent._memory_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    agent._memory_kernel.document_scope = SessionDocumentScopeStore(tmp_path / "scope.json")
    agent._memory_kernel.document_scope.resolve(
        session_id="s-imported",
        query="把《C塔智能化标准》设为 @C塔智能化标准",
        filters={},
        resolver=FakeBodyRetrieval().resolve_document_titles,
    )

    boundary = maybe_handle_temporary_attachment_boundary("这个文件现在有别名或工作区吗？")

    assert boundary is not None
    assert agent._has_imported_file_scope_for_query("这个文件现在有别名或工作区吗？") is True


def test_alias_followup_retrieval_returns_body_evidence_and_citation(tmp_path):
    kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    kernel.document_scope = SessionDocumentScopeStore(tmp_path / "scope.json")
    fake_retrieval = FakeBodyRetrieval()
    kernel.retrieval = fake_retrieval

    kernel.start_turn(KernelRequest(query="把《C塔智能化标准》设为 @C塔智能化标准", session_id="s1"))
    result = kernel.start_turn(
        KernelRequest(
            query="围绕 @C塔智能化标准 回答 C塔智能化专业的标准有哪些？请给 citation",
            session_id="s1",
        )
    )

    assert result.retrieval.items
    assert result.retrieval.citations
    assert result.trace["retrieval_items"] == 1
    assert result.trace["citations"] == 1
    assert result.trace["retrieval_evidence_document_ids"] == ["doc-standard"]
    assert fake_retrieval.requests[-1].filters["document_id"] == "doc-standard"
    assert fake_retrieval.requests[-1].filters["version_id"] == "ver-standard"
    assert "[C1]" in result.context_block
    assert "C塔智能化专业标准.docx" in result.context_block


def test_import_prompt_defaults_to_disabled_and_does_not_call_adapter():
    adapter = FakeUploadAdapter(_success_result())

    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=adapter,
    )

    assert isinstance(response, NaturalFileImportRuntimeResponse)
    assert adapter.calls == 0
    assert response.diagnostics["natural_import_detected"] is True
    assert response.diagnostics["real_upload_enabled"] is False
    assert response.diagnostics["upload_adapter_status"] == "disabled"
    assert response.diagnostics["ingestion_status"] == "not_executed"
    assert response.diagnostics["import_failed_reason"] == "real_upload_disabled"
    assert response.completed is True
    assert response.diagnostics["retrieval_evidence_document_ids"] == []


def test_fake_adapter_success_returns_upload_fields_and_alias_seeded():
    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )

    assert response is not None
    assert response.diagnostics["upload_adapter_status"] == "executed"
    assert response.diagnostics["ingestion_status"] == "upload_succeeded"
    assert response.diagnostics["document_id"] == "doc-runtime"
    assert response.diagnostics["version_id"] == "ver-runtime"
    assert response.diagnostics["chunk_count"] == 4
    assert response.diagnostics["indexed_count"] == 4
    assert response.diagnostics["alias_resolution"]["status"] == "alias_seeded"
    assert response.diagnostics["alias_resolution"]["resolved_document_id"] == "doc-runtime"
    assert response.diagnostics["alias_resolution"]["resolved_version_id"] == "ver-runtime"
    assert response.diagnostics["natural_import_context"]["can_claim_file_remembered"] is False
    assert response.diagnostics["natural_import_context"]["can_claim_alias_bound"] is False
    assert "文件我已经记下了" not in response.final_response
    assert "别名：@测试文件" not in response.final_response
    assert "别名还没有完成会话绑定" in response.final_response


def test_bound_success_response_explains_import_status_followups_and_evidence_boundary():
    diagnostics = _bound_success_diagnostics()
    rendered = render_natural_file_import_response(diagnostics)

    assert "Natural file import diagnostics:" not in rendered
    assert "document_id=doc-runtime" not in rendered
    assert "version_id=ver-runtime" not in rendered
    assert "chunk_count=4" not in rendered
    assert "indexed_count=4" not in rendered
    assert "后续你可以直接问" in rendered
    assert "@测试文件 这份文件有哪些重点？" in rendered
    assert "工作区和别名只是定位信息" in rendered
    assert "retrieval evidence 和 citation" in rendered


def test_post_bind_verification_failed_blocks_success_even_with_optimistic_alias_bound():
    diagnostics = _bound_success_diagnostics(alias="数据中台体系建设方案")
    diagnostics["post_import_alias_verification_status"] = "failed"
    diagnostics["post_import_alias_verification_failure_reason"] = "alias_resolver_mismatch"

    rendered = render_natural_file_import_response(diagnostics)
    context = diagnostics["natural_import_context"]

    assert context["post_import_alias_verification_status"] == "failed"
    assert context["can_claim_file_remembered"] is False
    assert context["can_claim_alias_bound"] is False
    assert "文件我已经记下了" not in rendered
    assert "别名：@数据中台体系建设方案" not in rendered
    assert "后续你可以直接问" not in rendered
    assert "别名还没有完成" in rendered


def test_post_bind_verification_missing_blocks_success_by_default():
    diagnostics = _bound_success_diagnostics(alias="数据中台体系建设方案")
    diagnostics.pop("post_import_alias_verification_status")
    diagnostics.pop("post_import_alias_verification_alias")
    diagnostics.pop("post_import_alias_verification_owner_source")
    diagnostics.pop("post_import_alias_verification_failure_reason")

    rendered = render_natural_file_import_response(diagnostics)
    context = diagnostics["natural_import_context"]

    assert context["post_import_alias_verification_status"] == "not_run"
    assert context["can_claim_file_remembered"] is False
    assert context["can_claim_alias_bound"] is False
    assert "文件我已经记下了" not in rendered
    assert "别名：@数据中台体系建设方案" not in rendered


def test_bound_success_response_uses_generated_safe_alias_without_exposing_raw_path():
    diagnostics = _bound_success_diagnostics(alias="建筑类数据样表")
    diagnostics["import_source_path"] = "/Users/example/private/建筑类数据样表.xlsx"
    diagnostics["alias_resolution"]["alias_generated"] = True
    response = render_natural_file_import_response(diagnostics)

    assert diagnostics["natural_import_context"]["can_claim_file_remembered"] is True
    assert "别名：@建筑类数据样表" in response
    assert "recommended_alias=@建筑类数据样表" not in response
    assert "/Users/example/private" not in response


def test_seeded_success_response_does_not_claim_alias_bound_without_persistence():
    response = maybe_handle_natural_file_import(
        "请把 /Users/example/private/建筑类数据样表.xlsx 导入企业记忆",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )

    assert response is not None
    assert response.diagnostics["alias_resolution"]["alias_generated"] is True
    assert response.diagnostics["alias_resolution"]["alias"] == "建筑类数据样表"
    assert "文件我已经记下了" not in response.final_response
    assert "别名：@建筑类数据样表" not in response.final_response
    assert "/Users/example/private" not in response.final_response


def test_bound_success_response_renders_workspace_context_and_keeps_raw_path_hidden():
    diagnostics = _bound_success_diagnostics(alias="C塔人力成本测算表")
    diagnostics["import_source_path"] = "/Users/hermes/import_samples/C塔项目人力配置及成本测算表0506.xlsx"
    diagnostics["workspace_context"] = {
        "workspace_id": "ws-demo",
        "workspace_name": "C塔项目",
        "workspace_type": "project",
        "document_category": "人力配置 / 成本测算",
        "confidence": "high",
        "needs_user_confirmation": False,
    }
    rendered = render_natural_file_import_response(diagnostics)

    assert "Natural file import diagnostics:" not in rendered
    assert "工作区：C塔项目" in rendered
    assert "分类：人力配置 / 成本测算" in rendered
    assert "别名：@C塔人力成本测算表" in rendered
    assert "帮我找 C塔项目的人力成本表" in rendered
    assert "workspace_id" not in rendered
    assert "document_id" not in rendered
    assert "version_id" not in rendered
    assert "chunk_count" not in rendered
    assert "/Users/hermes/import_samples" not in rendered


def test_render_success_response_uses_persisted_alias_bound_status():
    diagnostics = _bound_success_diagnostics()

    response = render_natural_file_import_response(diagnostics, include_diagnostics=True)

    assert "别名我设定为：@测试文件" in response
    assert '"status": "alias_bound"' in response
    assert "alias_continuity_status=stored" in response
    assert "alias_continuity_source=natural_import_success" in response
    assert "api_session_key_source=api_derived_session_id" in response
    assert "history_message_count=0" in response
    assert "retrieval_evidence_document_ids=[]" in response


def test_default_success_response_preserves_diagnostics_on_response_object_not_user_text():
    response = maybe_handle_natural_file_import(
        "帮我导入这个文件：/Users/hermes/import_samples/C塔项目人力配置及成本测算表0506.xlsx。",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )

    assert response is not None
    assert response.diagnostics["document_id"] == "doc-runtime"
    assert response.diagnostics["version_id"] == "ver-runtime"
    assert response.diagnostics["chunk_count"] == 4
    assert response.diagnostics["workspace_context"]["workspace_name"] == "C塔项目"
    assert "Natural file import diagnostics:" not in response.final_response


def test_natural_import_context_injection_present_and_separates_allowed_claims():
    seeded = maybe_handle_natural_file_import(
        "请把 '/Users/vc/Documents/New project/hermes训练文件 /PDF资料/数据中台体系建设方案.pdf' 导入企业记忆，并绑定为 @数据中台体系建设方案",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )
    bound = _bound_success_diagnostics(alias="数据中台体系建设方案")

    assert seeded is not None
    seeded_context = seeded.diagnostics["natural_import_context"]
    bound_context = build_natural_import_context(bound)

    assert seeded.diagnostics["import_source_path"] == "/Users/vc/Documents/New project/hermes训练文件 /PDF资料/数据中台体系建设方案.pdf"
    assert seeded_context["can_claim_file_remembered"] is False
    assert seeded_context["can_claim_alias_bound"] is False
    assert seeded_context["evidence_boundary"]["requires_retrieval_evidence"] is True
    assert "raw_path" in seeded_context["forbidden_claims"]
    assert bound_context["can_claim_file_remembered"] is True
    assert bound_context["can_claim_alias_bound"] is True


def test_llm_context_injection_receives_natural_import_context_and_success_passes_validator():
    diagnostics = _bound_success_diagnostics()
    llm = FakeNaturalImportLLM("我已把这份文件接入当前会话，并完成 @测试文件 的绑定。回答内容仍需要 retrieval evidence 和 citation。")

    response = render_natural_file_import_response(
        diagnostics,
        llm_response_generator=llm,
    )

    assert llm.contexts == [diagnostics["natural_import_context"]]
    assert response == llm.reply
    assert diagnostics["natural_import_response_path"] == "llm"
    assert diagnostics["natural_import_response_safety_fallback"] is False


def test_llm_failure_response_stays_natural_and_safe():
    llm = FakeNaturalImportLLM("我识别到你想导入文件，但这次没有完成导入，所以我不能说已经记下。请放入授权目录后再试。")

    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(_success_result()),
        llm_response_generator=llm,
    )

    assert response is not None
    assert llm.contexts == [response.diagnostics["natural_import_context"]]
    assert response.final_response == llm.reply
    assert "文件我已经记下了" not in response.final_response
    assert "Natural file import diagnostics:" not in response.final_response
    assert response.diagnostics["natural_import_response_path"] == "llm"


def test_llm_false_success_response_is_replaced_by_safety_fallback():
    llm = FakeNaturalImportLLM("文件我已经记下了。\n- 别名：@测试文件\n后续你可以直接问。")

    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
        llm_response_generator=llm,
    )

    assert response is not None
    assert llm.contexts == [response.diagnostics["natural_import_context"]]
    assert response.final_response != llm.reply
    assert "文件我已经记下了" not in response.final_response
    assert "别名：@测试文件" not in response.final_response
    assert "别名还没有完成会话绑定" in response.final_response
    assert response.diagnostics["natural_import_response_path"] == "safety_fallback"
    assert response.diagnostics["natural_import_response_safety_fallback"] is True


def test_llm_raw_path_response_is_replaced_by_safety_fallback():
    diagnostics = _bound_success_diagnostics()
    llm = FakeNaturalImportLLM("我已把文件接入当前会话。原路径：/Users/example/private/demo.pdf。")

    response = render_natural_file_import_response(
        diagnostics,
        llm_response_generator=llm,
    )

    assert response != llm.reply
    assert "/Users/example/private" not in response
    assert "别名：@测试文件" in response
    assert diagnostics["natural_import_response_path"] == "safety_fallback"
    assert diagnostics["natural_import_response_safety_fallback"] is True


def test_llm_diagnostics_block_hidden_from_ordinary_response_but_available_in_debug():
    diagnostics = _bound_success_diagnostics()
    llm = FakeNaturalImportLLM("我已把这份文件接入当前会话，并完成 @测试文件 的绑定。")

    ordinary = render_natural_file_import_response(
        diagnostics,
        llm_response_generator=llm,
    )
    debug = render_natural_file_import_response(
        diagnostics,
        include_diagnostics=True,
        llm_response_generator=llm,
    )

    assert "Natural file import diagnostics:" not in ordinary
    assert "Natural file import diagnostics:" in debug
    assert "document_id=doc-runtime" in debug


def test_false_success_guard_blocks_llm_claim_when_alias_not_bound():
    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )

    assert response is not None
    guarded = validate_natural_import_response(
        response.diagnostics["natural_import_context"],
        "文件我已经记下了。\n- 别名：@测试文件\n后续你可以直接问。",
    )

    assert "文件我已经记下了" not in guarded
    assert "别名：@测试文件" not in guarded
    assert "别名还没有完成会话绑定" in guarded


def test_alias_overclaim_natural_wording_blocked_when_alias_not_bound():
    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )

    assert response is not None
    guarded = validate_natural_import_response(
        response.diagnostics["natural_import_context"],
        "我已把这份文件接入当前会话，并完成 @测试文件 的绑定。回答内容仍需要 retrieval evidence 和 citation。",
    )

    assert "完成 @测试文件 的绑定" not in guarded
    assert "接入当前会话" not in guarded
    assert "别名还没有完成会话绑定" in guarded


def test_followup_alias_availability_overclaim_blocked_when_alias_not_bound():
    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )

    assert response is not None
    guarded = validate_natural_import_response(
        response.diagnostics["natural_import_context"],
        "后续可以用 @测试文件 继续问，我会按这份文件回答。",
    )

    assert "后续可以用 @测试文件 继续问" not in guarded
    assert "别名还没有完成会话绑定" in guarded


def test_generic_save_or_import_overclaim_blocked_when_import_success_not_allowed():
    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(_success_result()),
    )

    assert response is not None
    guarded = validate_natural_import_response(
        response.diagnostics["natural_import_context"],
        "我已经帮你保存到企业记忆里，后续可以继续查询。",
    )

    assert "保存到企业记忆里" not in guarded
    assert "无法读取到这个文件" in guarded


def test_valid_bound_alias_natural_wording_still_passes_validator():
    context = build_natural_import_context(_bound_success_diagnostics(alias="测试文件"))
    candidate = "我已把这份文件接入当前会话，并完成 @测试文件 的绑定。回答内容仍需要 retrieval evidence 和 citation。"

    guarded = validate_natural_import_response(context, candidate)

    assert guarded == candidate


def test_raw_path_safety_validator_sanitizes_llm_output_even_on_success():
    context = build_natural_import_context(_bound_success_diagnostics(alias="测试文件"))

    guarded = validate_natural_import_response(
        context,
        "文件我已经记下了。原路径：/Users/example/private/demo.pdf\n- 别名：@测试文件",
    )

    assert "/Users/example/private" not in guarded
    assert "别名：@测试文件" in guarded


def test_pdf_parser_failure_is_safe_failure_without_success_or_raw_path():
    response = maybe_handle_natural_file_import(
        "请导入 '/Users/vc/Documents/New project/hermes训练文件 /PDF资料/数据中台体系建设方案.pdf' 到企业记忆，别名为 @数据中台体系建设方案",
        upload_adapter=FakeUploadAdapter(
            NaturalFileUploadResult(
                success=False,
                failed_reason="parser_failed",
                error_type="parser_failed",
                error_message="pdf parser unavailable",
            )
        ),
        real_upload_enabled=True,
    )

    assert response is not None
    assert response.diagnostics["import_failed_reason"] == "parser_failed"
    assert response.diagnostics["natural_import_context"]["can_claim_file_remembered"] is False
    assert "文件我已经记下了" not in response.final_response
    assert "别名：@数据中台体系建设方案" not in response.final_response
    assert "/Users/vc/Documents" not in response.final_response


def test_pending_workspace_confirmation_does_not_block_bound_success_but_failed_import_stays_safe():
    diagnostics = _bound_success_diagnostics()
    diagnostics["workspace_context"]["needs_user_confirmation"] = True
    diagnostics["workspace_context"]["confidence"] = "low"
    rendered = render_natural_file_import_response(diagnostics)

    failed = dict(diagnostics)
    failed["ingestion_status"] = "failed"
    failed["import_failed_reason"] = "file_not_found"
    failed["document_id"] = None
    failed["version_id"] = None
    failed["alias_persisted"] = False
    failed["alias_resolution"] = {
        "status": "not_bound",
        "alias": "测试文件",
        "resolved_document_id": None,
        "resolved_version_id": None,
    }
    failed_rendered = render_natural_file_import_response(failed)

    assert "文件我已经记下了" in rendered
    assert "工作区：测试项目" in rendered
    assert "文件我已经记下了" not in failed_rendered
    assert "别名：@测试文件" not in failed_rendered


def test_run_agent_persists_natural_import_alias_as_bound_and_continuity(tmp_path):
    agent = object.__new__(AIAgent)
    agent.session_id = "api-natural-import-session"
    agent._gateway_session_key = "gateway-chat-1"
    agent._memory_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    agent._memory_kernel.document_scope._storage_path = tmp_path / "scope.json"
    diagnostics = {
        "ingestion_status": "upload_succeeded",
        "document_id": "doc-runtime",
        "version_id": "ver-runtime",
        "import_source_path": "/tmp/测试文件.docx",
        "alias_resolution": {
            "status": "alias_seeded",
            "alias": "测试文件",
            "resolved_document_id": "doc-runtime",
            "resolved_version_id": "ver-runtime",
        },
    }

    agent._persist_natural_import_alias(diagnostics)
    agent.session_id = "api-followup-drift-session"
    agent._register_alias_continuity_owner()
    decision = agent._memory_kernel.resolve_document_scope(
        session_id="api-followup-drift-session",
        query="围绕 @测试文件 回答，必须给出 citation",
        filters={},
    )

    assert diagnostics["alias_persisted"] is True
    assert diagnostics["alias_resolution"]["status"] == "alias_bound"
    assert diagnostics["alias_continuity_status"] == "stored"
    assert diagnostics["alias_continuity_source"] == "natural_import_success"
    assert diagnostics["api_session_key_source"] == "gateway_session_key"
    assert decision.trace["alias_resolution"]["status"] == "alias_resolved"
    assert decision.trace["alias_continuity_status"] == "restored"
    assert decision.trace["alias_continuity_owner_source"] == "gateway_session_key"
    assert decision.filters["document_id"] == "doc-runtime"
    assert decision.filters["version_id"] == "ver-runtime"


def test_run_agent_post_import_alias_verification_must_pass_for_success_claim(tmp_path):
    agent = object.__new__(AIAgent)
    agent.session_id = "api-natural-import-session"
    agent._gateway_session_key = "gateway-chat-1"
    agent._memory_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    agent._memory_kernel.document_scope._storage_path = tmp_path / "scope.json"
    diagnostics = {
        "ingestion_status": "upload_succeeded",
        "document_id": "doc-runtime",
        "version_id": "ver-runtime",
        "import_source_path": "/tmp/测试文件.docx",
        "alias_resolution": {
            "status": "alias_seeded",
            "alias": "测试文件",
            "resolved_document_id": "doc-runtime",
            "resolved_version_id": "ver-runtime",
        },
    }

    agent._persist_natural_import_alias(diagnostics)
    context = build_natural_import_context(diagnostics)

    assert diagnostics["alias_persisted"] is True
    assert diagnostics["post_import_alias_verification_status"] == "passed"
    assert context["can_claim_file_remembered"] is True
    assert context["can_claim_alias_bound"] is True


def test_run_agent_failed_post_import_alias_verification_blocks_success_claim(tmp_path):
    agent = object.__new__(AIAgent)
    agent.session_id = "api-natural-import-session"
    agent._gateway_session_key = "gateway-chat-1"
    agent._memory_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    agent._memory_kernel.document_scope._storage_path = tmp_path / "scope.json"
    diagnostics = {
        "ingestion_status": "upload_succeeded",
        "document_id": "doc-runtime",
        "version_id": "ver-runtime",
        "import_source_path": "/tmp/测试文件.docx",
        "alias_resolution": {
            "status": "alias_seeded",
            "alias": "测试文件",
            "resolved_document_id": "doc-runtime",
            "resolved_version_id": "ver-runtime",
        },
    }

    def _alias_missing_scope(**_: object) -> DocumentScopeDecision:
        return DocumentScopeDecision(
            filters={},
            trace={
                "scope_resolution_status": "alias_missing",
                "alias_resolution": {"status": "alias_missing", "alias": "测试文件"},
                "alias_missing": True,
            },
            suppress_retrieval=True,
        )

    agent._memory_kernel.resolve_document_scope = _alias_missing_scope  # type: ignore[method-assign]

    agent._persist_natural_import_alias(diagnostics)
    context = build_natural_import_context(diagnostics)

    assert diagnostics["alias_persisted"] is True
    assert diagnostics["post_import_alias_verification_status"] == "failed"
    assert diagnostics["post_import_alias_verification_failure_reason"] == "alias_not_resolved"
    assert context["can_claim_file_remembered"] is False
    assert context["can_claim_alias_bound"] is False


def test_run_agent_restores_import_alias_continuity_in_new_agent_instance(tmp_path):
    storage_path = tmp_path / "scope.json"
    import_agent = object.__new__(AIAgent)
    import_agent.session_id = "api-natural-import-session"
    import_agent._gateway_session_key = "gateway-chat-1"
    import_agent._memory_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    import_agent._memory_kernel.document_scope._storage_path = storage_path
    diagnostics = {
        "ingestion_status": "upload_succeeded",
        "document_id": "doc-runtime",
        "version_id": "ver-runtime",
        "import_source_path": "/tmp/测试文件.docx",
        "alias_resolution": {
            "status": "alias_seeded",
            "alias": "测试文件",
            "resolved_document_id": "doc-runtime",
            "resolved_version_id": "ver-runtime",
        },
    }

    import_agent._persist_natural_import_alias(diagnostics)
    followup_agent = object.__new__(AIAgent)
    followup_agent.session_id = "api-followup-drift-session"
    followup_agent._gateway_session_key = "gateway-chat-1"
    followup_agent._memory_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    followup_agent._memory_kernel.document_scope._storage_path = storage_path
    followup_agent._memory_kernel.document_scope._load()
    followup_agent._register_alias_continuity_owner()
    decision = followup_agent._memory_kernel.resolve_document_scope(
        session_id="api-followup-drift-session",
        query="围绕 @测试文件 回答，必须给出 citation",
        filters={},
    )

    assert diagnostics["alias_continuity_status"] == "stored"
    assert decision.suppress_retrieval is False
    assert decision.trace["scope_resolution_status"] == "alias_resolved"
    assert decision.trace["alias_continuity_status"] == "restored"
    assert decision.trace["alias_resolution"]["alias_continuity_status"] == "restored"
    assert decision.filters["document_id"] == "doc-runtime"
    assert decision.filters["version_id"] == "ver-runtime"


def test_run_agent_preserves_requested_natural_alias_for_followup_restore(tmp_path):
    response = maybe_handle_natural_file_import(
        "请上传 /tmp/系统生成名.xlsx 到企业记忆，别名设为 @建筑类数据样表",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )
    assert response is not None
    assert response.diagnostics["alias_resolution"]["alias"] == "建筑类数据样表"
    assert response.diagnostics["alias_resolution"]["status"] == "alias_seeded"

    agent = object.__new__(AIAgent)
    agent.session_id = "api-natural-import-session"
    agent._gateway_session_key = "gateway-chat-1"
    agent._memory_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    agent._memory_kernel.document_scope._storage_path = tmp_path / "scope.json"

    agent._persist_natural_import_alias(response.diagnostics)
    agent.session_id = "api-followup-drift-session"
    agent._register_alias_continuity_owner()
    decision = agent._memory_kernel.resolve_document_scope(
        session_id="api-followup-drift-session",
        query="围绕 @建筑类数据样表 总结文件内容，必须给出 citation",
        filters={},
    )

    assert response.diagnostics["alias_resolution"]["alias"] == "建筑类数据样表"
    assert response.diagnostics["alias_resolution"]["status"] == "alias_bound"
    assert decision.trace["alias_resolution"]["status"] == "alias_resolved"
    assert decision.trace["alias_missing"] is False
    assert decision.suppress_retrieval is False
    assert decision.filters["document_id"] == "doc-runtime"
    assert decision.filters["version_id"] == "ver-runtime"


def test_run_agent_persists_generated_alias_with_workspace_for_fuzzy_discovery(tmp_path):
    response = maybe_handle_natural_file_import(
        "帮我导入这个文件：/Users/hermes/import_samples/C塔项目人力配置及成本测算表0506.xlsx。",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )
    assert response is not None

    agent = object.__new__(AIAgent)
    agent.session_id = "api-natural-import-session"
    agent._gateway_session_key = "gateway-chat-ctower"
    agent._memory_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    agent._memory_kernel.document_scope._storage_path = tmp_path / "scope.json"

    agent._persist_natural_import_alias(response.diagnostics)
    decision = agent._memory_kernel.resolve_document_scope(
        session_id="api-natural-import-session",
        query="帮我找 C塔项目的人力成本表",
        filters={},
    )

    assert response.diagnostics["alias_resolution"]["status"] == "alias_bound"
    assert response.diagnostics["alias_resolution"]["alias"] == "C塔人力成本测算表"
    assert response.diagnostics["alias_status"] == "alias_bound"
    assert decision.trace["scope_resolution_status"] == "file_discovery_candidates"
    assert decision.suppress_retrieval is True
    assert decision.trace["file_candidates"][0]["alias"] == "C塔人力成本测算表"
    assert decision.trace["file_candidates"][0]["workspace_name"] == "C塔项目"
    assert decision.trace["file_candidates"][0]["document_category"] == "人力配置 / 成本测算"
    assert "document_id" not in decision.filters


def test_run_agent_hydrates_natural_import_alias_from_conversation_history(tmp_path):
    agent = object.__new__(AIAgent)
    agent.session_id = "api-derived-followup-session"
    agent._memory_kernel = MemoryKernel(MemoryKernelConfig(enabled=True, inject_context=True))
    agent._memory_kernel.document_scope._storage_path = tmp_path / "scope.json"
    previous_response = render_natural_file_import_response(
        {
            "natural_import_detected": True,
            "real_upload_enabled": True,
            "upload_adapter_status": "executed",
            "ingestion_status": "upload_succeeded",
            "import_failed_reason": None,
            "document_id": "doc-imported",
            "version_id": "ver-imported",
            "chunk_count": 6,
            "indexed_count": 6,
            "alias_resolution": {
                "status": "alias_bound",
                "alias": "建筑类数据样表",
                "resolved_document_id": "doc-imported",
                "resolved_version_id": "ver-imported",
            },
            "retrieval_evidence_document_ids": [],
            "import_diagnostics_as_retrieval_evidence": False,
            "metadata_as_answer": False,
            "facts_as_answer": False,
            "snapshot_as_answer": False,
            "transcript_as_fact": False,
            "requires_retrieval_evidence": True,
            "third_document_contamination": False,
        },
        include_diagnostics=True,
    )

    agent._hydrate_natural_import_aliases_from_history(
        [{"role": "assistant", "content": previous_response}]
    )
    decision = agent._memory_kernel.resolve_document_scope(
        session_id="api-derived-followup-session",
        query="围绕 @建筑类数据样表 总结文件内容，必须给出 citation",
        filters={},
    )

    assert decision.trace["alias_resolution"]["status"] == "alias_resolved"
    assert decision.trace["alias_missing"] is False
    assert decision.suppress_retrieval is False
    assert decision.filters["document_id"] == "doc-imported"
    assert decision.filters["version_id"] == "ver-imported"
    assert decision.allowed_document_ids == ["doc-imported"]


def test_fake_adapter_failure_fails_closed_and_does_not_bind_alias():
    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(
            NaturalFileUploadResult(
                success=False,
                failed_reason="api_unavailable",
                error_type="api_unavailable",
            )
        ),
        real_upload_enabled=True,
    )

    assert response is not None
    assert response.diagnostics["ingestion_status"] == "failed"
    assert response.diagnostics["import_failed_reason"] == "api_unavailable"
    assert response.diagnostics["alias_resolution"]["status"] == "not_bound"
    assert response.diagnostics["alias_resolution"]["resolved_document_id"] is None


def test_file_not_found_response_is_human_readable_without_diagnostics_dump():
    response = maybe_handle_natural_file_import(
        "帮我导入这个文件：/Users/private/C塔项目人力配置及成本测算表0506.xlsx。",
        upload_adapter=FakeUploadAdapter(
            NaturalFileUploadResult(
                success=False,
                failed_reason="file_not_found",
                error_type="file_not_found",
            )
        ),
        real_upload_enabled=True,
    )

    assert response is not None
    rendered = response.final_response
    assert "我识别到你想导入一份文件" in rendered
    assert "C塔项目 / 人力配置 / 成本测算" in rendered
    assert "无法读取到这个文件" in rendered
    assert "授权导入目录" in rendered
    assert "Natural file import diagnostics:" not in rendered
    assert "document_id=" not in rendered
    assert "upload_adapter_status" not in rendered
    assert "/Users/private" not in rendered
    assert "/Users/" not in rendered
    assert "/Volumes/" not in rendered
    assert "file://" not in rendered
    assert "nas://" not in rendered
    assert "smb://" not in rendered


def test_runtime_response_keeps_import_diagnostics_out_of_evidence_and_sets_safety_flags():
    response = maybe_handle_natural_file_import(
        "请把 /tmp/demo.docx 导入企业记忆，并绑定为 @测试文件",
        upload_adapter=FakeUploadAdapter(_success_result()),
        real_upload_enabled=True,
    )

    assert response is not None
    assert response.diagnostics["retrieval_evidence_document_ids"] == []
    assert response.diagnostics["import_diagnostics_as_retrieval_evidence"] is False
    assert response.diagnostics["metadata_as_answer"] is False
    assert response.diagnostics["facts_as_answer"] is False
    assert response.diagnostics["snapshot_as_answer"] is False
    assert response.diagnostics["transcript_as_fact"] is False
    assert response.diagnostics["requires_retrieval_evidence"] is True
    assert "导入状态、工作区和别名都不是文件内容证据" in response.final_response
    assert "retrieval evidence 和 citation" in response.final_response
    assert "import_diagnostics_as_retrieval_evidence=false" not in response.final_response
    assert "facts_as_answer=false" not in response.final_response
    assert "requires_retrieval_evidence=true" not in response.final_response


def test_rendered_import_diagnostics_do_not_expose_raw_paths_or_turn_into_evidence():
    response = render_natural_file_import_response(
        {
            "natural_import_detected": True,
            "real_upload_enabled": True,
            "upload_adapter_status": "executed",
            "ingestion_status": "upload_succeeded",
            "import_failed_reason": None,
            "document_id": "doc-runtime",
            "version_id": "ver-runtime",
            "chunk_count": 4,
            "indexed_count": 4,
            "import_source_path": "/Users/example/private/测试文件.xlsx",
            "alias_resolution": {
                "status": "alias_bound",
                "alias": "测试文件",
                "resolved_document_id": "doc-runtime",
                "resolved_version_id": "ver-runtime",
            },
            "alias_continuity_status": "stored",
            "alias_continuity_source": "natural_import_success",
            "api_session_key_source": "api_derived_session_id",
            "history_message_count": 0,
            "retrieval_evidence_document_ids": [],
            "import_diagnostics_as_retrieval_evidence": False,
            "metadata_as_answer": False,
            "facts_as_answer": False,
            "snapshot_as_answer": False,
            "transcript_as_fact": False,
            "requires_retrieval_evidence": True,
            "third_document_contamination": False,
        }
    )

    assert "/Users/example/private" not in response
    assert "Natural file import diagnostics:" not in response
    assert "retrieval_evidence_document_ids=[]" not in response
    assert "import_diagnostics_as_retrieval_evidence=false" not in response


def test_missing_document_or_version_fails_closed():
    missing_doc = maybe_handle_natural_file_import(
        "导入 /tmp/demo.docx 到企业记忆",
        upload_adapter=FakeUploadAdapter(NaturalFileUploadResult(success=True, version_id="ver-1")),
        real_upload_enabled=True,
    )
    missing_version = maybe_handle_natural_file_import(
        "导入 /tmp/demo.docx 到企业记忆",
        upload_adapter=FakeUploadAdapter(NaturalFileUploadResult(success=True, document_id="doc-1")),
        real_upload_enabled=True,
    )

    assert missing_doc is not None
    assert missing_doc.diagnostics["import_failed_reason"] == "missing_document_id"
    assert missing_version is not None
    assert missing_version.diagnostics["import_failed_reason"] == "missing_version_id"
