from __future__ import annotations

from agent.memory_kernel.natural_file_import import parse_natural_file_import
from agent.memory_kernel.natural_file_upload_adapter import (
    FeatureFlaggedHermesMemoryUploadAdapter,
    NaturalFileUploadResult,
)


class FakeHermesMemoryUploadClient:
    def __init__(self) -> None:
        self.calls = 0

    def upload(self, request):
        self.calls += 1
        return NaturalFileUploadResult(
            success=True,
            document_id="doc-real",
            version_id="ver-real",
            chunk_count=2,
            indexed_count=2,
            message=f"uploaded {request.source_path}",
        )


def test_feature_flagged_upload_adapter_is_disabled_by_default():
    client = FakeHermesMemoryUploadClient()
    adapter = FeatureFlaggedHermesMemoryUploadAdapter(client=client)

    result = adapter.upload(parse_natural_file_import("导入 /tmp/demo.pdf 到企业记忆"))

    assert client.calls == 0
    assert result.success is False
    assert result.failed_reason == "real_upload_disabled"
    assert result.error_type == "real_upload_disabled"


def test_enabled_upload_adapter_delegates_to_client():
    client = FakeHermesMemoryUploadClient()
    adapter = FeatureFlaggedHermesMemoryUploadAdapter(client=client, enabled=True)

    result = adapter.upload(parse_natural_file_import("导入 /tmp/demo.pdf 到企业记忆"))

    assert client.calls == 1
    assert result.success is True
    assert result.document_id == "doc-real"
    assert result.version_id == "ver-real"


def test_enabled_upload_adapter_without_client_fails_closed():
    adapter = FeatureFlaggedHermesMemoryUploadAdapter(enabled=True)

    result = adapter.upload(parse_natural_file_import("导入 /tmp/demo.pdf 到企业记忆"))

    assert result.success is False
    assert result.failed_reason == "upload_client_not_configured"
    assert result.error_type == "upload_client_not_configured"
