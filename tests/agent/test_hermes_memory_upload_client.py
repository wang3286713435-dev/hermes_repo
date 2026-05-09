from __future__ import annotations

import json
from urllib.error import URLError

from agent.memory_kernel.hermes_memory_upload_client import HermesMemoryUploadClient
from agent.memory_kernel.natural_file_import import NaturalFileImportRequest


class FakeResponse:
    def __init__(self, payload: dict | bytes) -> None:
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload


def _request(path: str) -> NaturalFileImportRequest:
    return NaturalFileImportRequest(
        detected=True,
        source_path=path,
        title="Demo Upload",
        document_type="mvp_test",
        source_type="manual",
        alias="测试文件",
    )


def test_upload_posts_multipart_and_maps_success(tmp_path):
    source = tmp_path / "demo.docx"
    source.write_bytes(b"docx-bytes")
    captured = {}

    def opener(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["content_type"] = req.headers["Content-type"]
        captured["body"] = req.data
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "status": "completed",
                "message": "ok",
                "document_id": "doc-1",
                "version_id": "ver-1",
                "chunk_count": 3,
                "indexed_count": 3,
            }
        )

    result = HermesMemoryUploadClient(
        base_url="http://memory.local",
        timeout=12,
        opener=opener,
    ).upload(_request(str(source)))

    assert result.success is True
    assert result.document_id == "doc-1"
    assert result.version_id == "ver-1"
    assert result.chunk_count == 3
    assert result.indexed_count == 3
    assert captured["url"] == "http://memory.local/api/v1/documents/upload"
    assert captured["method"] == "POST"
    assert "multipart/form-data" in captured["content_type"]
    assert b'name="title"' in captured["body"]
    assert b"Demo Upload" in captured["body"]
    assert b'name="document_type"' in captured["body"]
    assert b"mvp_test" in captured["body"]
    assert b'demo.docx' in captured["body"]
    assert captured["timeout"] == 12


def test_upload_missing_source_path_fails_closed():
    result = HermesMemoryUploadClient(opener=lambda req, timeout: None).upload(
        NaturalFileImportRequest(detected=True, source_path=None)
    )

    assert result.success is False
    assert result.failed_reason == "missing_source_path"


def test_upload_http_error_fails_closed(tmp_path):
    source = tmp_path / "demo.docx"
    source.write_bytes(b"docx-bytes")

    def opener(req, timeout):
        raise URLError("connection refused")

    result = HermesMemoryUploadClient(opener=opener).upload(_request(str(source)))

    assert result.success is False
    assert result.failed_reason == "api_unavailable"
    assert result.error_type == "api_unavailable"


def test_upload_invalid_json_fails_closed(tmp_path):
    source = tmp_path / "demo.docx"
    source.write_bytes(b"docx-bytes")

    result = HermesMemoryUploadClient(opener=lambda req, timeout: FakeResponse(b"not-json")).upload(
        _request(str(source))
    )

    assert result.success is False
    assert result.failed_reason == "invalid_upload_response"


def test_upload_missing_ids_fails_closed(tmp_path):
    source = tmp_path / "demo.docx"
    source.write_bytes(b"docx-bytes")

    result = HermesMemoryUploadClient(
        opener=lambda req, timeout: FakeResponse({"status": "completed", "version_id": "ver-1"})
    ).upload(_request(str(source)))

    assert result.success is False
    assert result.failed_reason == "missing_document_id"


def test_upload_non_completed_status_fails_closed(tmp_path):
    source = tmp_path / "demo.docx"
    source.write_bytes(b"docx-bytes")

    result = HermesMemoryUploadClient(
        opener=lambda req, timeout: FakeResponse({"status": "failed", "message": "parser failed"})
    ).upload(_request(str(source)))

    assert result.success is False
    assert result.failed_reason == "upload_status_failed"
    assert result.error_message == "parser failed"
