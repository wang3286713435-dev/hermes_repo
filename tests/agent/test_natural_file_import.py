from __future__ import annotations

import pytest

from agent.memory_kernel.natural_file_import import (
    build_natural_file_import_diagnostics,
    parse_natural_file_import,
)


def test_parse_explicit_pdf_import():
    request = parse_natural_file_import("把 /tmp/demo.pdf 导入企业记忆")

    assert request.detected is True
    assert request.source_path == "/tmp/demo.pdf"
    assert request.import_action == "导入"
    assert request.failed_reason is None
    assert request.dry_run is True
    assert request.trace["natural_import_detected"] is True
    assert request.trace["ingestion_status"] == "not_executed"


def test_parse_quoted_path_and_title():
    request = parse_natural_file_import('把 "/tmp/demo file.pdf" 导入企业记忆，标题叫 测试文件')

    assert request.detected is True
    assert request.source_path == "/tmp/demo file.pdf"
    assert request.title == "测试文件"
    assert request.failed_reason is None
    assert request.trace["import_title"] == "测试文件"


def test_parse_alias_binding():
    request = parse_natural_file_import("上传 /tmp/demo.xlsx 到企业记忆，绑定为 @硬件清单")

    assert request.detected is True
    assert request.source_path == "/tmp/demo.xlsx"
    assert request.alias == "硬件清单"
    assert request.trace["alias_requested"] is True
    assert request.trace["alias_resolution"]["status"] == "pending_upload"
    assert request.trace["alias_resolution"]["alias"] == "硬件清单"


@pytest.mark.parametrize(
    "phrase",
    [
        "绑定为 @建筑类数据样表",
        "绑定成 @建筑类数据样表",
        "命名为 @建筑类数据样表",
        "取名为 @建筑类数据样表",
        "别名 @建筑类数据样表",
        "别名为 @建筑类数据样表",
        "别名叫 @建筑类数据样表",
        "别名设为 @建筑类数据样表",
        "设定别名为 @建筑类数据样表",
        "我想叫它 @建筑类数据样表",
    ],
)
def test_parse_explicit_alias_phrases_preserves_requested_alias(phrase: str):
    request = parse_natural_file_import(f"请上传 /tmp/demo.xlsx 到企业记忆，{phrase}")

    assert request.detected is True
    assert request.source_path == "/tmp/demo.xlsx"
    assert request.alias == "建筑类数据样表"
    assert request.trace["alias_requested"] is True
    assert request.trace["alias_resolution"]["alias"] == "建筑类数据样表"


@pytest.mark.parametrize(
    "phrase",
    [
        "别名为 @",
        "别名 @@@",
        "设定别名为 @@@",
    ],
)
def test_malformed_explicit_alias_is_not_requested(phrase: str):
    request = parse_natural_file_import(f"请上传 /tmp/demo.xlsx 到企业记忆，{phrase}")

    assert request.detected is True
    assert request.alias is None
    assert request.trace["alias_requested"] is False
    assert request.trace["alias_resolution"]["status"] == "not_requested"


def test_parse_document_type_and_source_type():
    request = parse_natural_file_import("收录 /tmp/demo.docx 到企业记忆，文档类型=标书，source_type=manual")

    assert request.detected is True
    assert request.document_type == "标书"
    assert request.source_type == "manual"
    assert request.trace["document_type"] == "标书"
    assert request.trace["source_type"] == "manual"


def test_non_import_path_inspection_does_not_trigger():
    view_request = parse_natural_file_import("帮我看看 /tmp/demo.pdf")
    summary_request = parse_natural_file_import("总结 /tmp/demo.pdf")

    assert view_request.detected is False
    assert view_request.failed_reason is None
    assert view_request.trace["natural_import_detected"] is False
    assert summary_request.detected is False


def test_negated_import_intent_does_not_trigger():
    direct_request = parse_natural_file_import("不要导入 /tmp/demo.pdf")
    polite_request = parse_natural_file_import("请不要上传 /tmp/demo.pdf 到企业记忆")
    object_request = parse_natural_file_import("不要把 /tmp/demo.pdf 收录到企业记忆")

    assert direct_request.detected is False
    assert direct_request.failed_reason is None
    assert direct_request.trace["natural_import_detected"] is False
    assert polite_request.detected is False
    assert object_request.detected is False


def test_missing_path_fails_closed():
    request = parse_natural_file_import("请导入企业记忆，标题叫 测试文件")

    assert request.detected is True
    assert request.source_path is None
    assert request.failed_reason == "missing_path"
    assert request.trace["import_failed_reason"] == "missing_path"
    assert request.trace["dry_run"] is True


def test_multiple_paths_fail_closed():
    request = parse_natural_file_import("把 /tmp/a.pdf 和 /tmp/b.pdf 导入企业记忆")

    assert request.detected is True
    assert request.failed_reason == "multiple_paths_not_supported"
    assert request.trace["import_failed_reason"] == "multiple_paths_not_supported"


def test_directory_bulk_nas_bim_intents_fail_closed():
    directory_request = parse_natural_file_import("导入 /tmp/data/ 目录到企业记忆")
    bulk_request = parse_natural_file_import("批量导入 /tmp/a.pdf 到企业记忆")
    nas_request = parse_natural_file_import("扫描NAS并导入企业记忆")
    bim_request = parse_natural_file_import("导入整个BIM文件池到企业记忆")

    assert directory_request.failed_reason == "directory_import_not_supported"
    assert bulk_request.failed_reason == "bulk_import_not_supported"
    assert nas_request.failed_reason == "bulk_import_not_supported"
    assert bim_request.failed_reason == "bulk_import_not_supported"


def test_unsupported_extension_fails_closed():
    request = parse_natural_file_import("导入 /tmp/demo.exe 到企业记忆")

    assert request.detected is True
    assert request.failed_reason == "unsupported_extension"
    assert request.trace["import_failed_reason"] == "unsupported_extension"


def test_diagnostics_fields_are_stable_and_safe():
    request = parse_natural_file_import("上传 /tmp/demo.xlsx 到企业记忆，绑定为 @硬件清单")
    diagnostics = build_natural_file_import_diagnostics(request)

    assert diagnostics["natural_import_detected"] is True
    assert diagnostics["import_action"] == "上传"
    assert diagnostics["import_source_path"] == "/tmp/demo.xlsx"
    assert diagnostics["alias_requested"] is True
    assert diagnostics["ingestion_status"] == "not_executed"
    assert diagnostics["dry_run"] is True
    assert diagnostics["facts_as_answer"] is False
    assert diagnostics["snapshot_as_answer"] is False
    assert diagnostics["transcript_as_fact"] is False
