from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from agent.memory_kernel.natural_file_import import NaturalFileImportRequest
from agent.memory_kernel.natural_file_upload_adapter import NaturalFileUploadResult


class HermesMemoryUploadClient:
    """Small HTTP client for Hermes_memory natural single-file uploads."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000",
        timeout: int = 120,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = (base_url or "http://127.0.0.1:8000").rstrip("/")
        self.timeout = timeout
        self._opener = opener or urllib_request.urlopen

    def upload(self, request: NaturalFileImportRequest) -> NaturalFileUploadResult:
        if not request.source_path:
            return _failed("missing_source_path", "Natural import request did not include source_path.")
        source_path = Path(request.source_path).expanduser()
        if not source_path.is_file():
            return _failed("source_file_not_found", f"Source file does not exist: {request.source_path}")

        try:
            body, content_type = self._multipart_body(request=request, source_path=source_path)
            http_request = urllib_request.Request(
                f"{self.base_url}/api/v1/documents/upload",
                data=body,
                method="POST",
                headers={
                    "Content-Type": content_type,
                    "Accept": "application/json",
                },
            )
            with self._opener(http_request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return _failed("api_http_error", f"Hermes_memory upload returned HTTP {exc.code}.")
        except URLError as exc:
            return _failed("api_unavailable", str(exc.reason))
        except OSError as exc:
            return _failed("source_file_read_failed", str(exc))
        except json.JSONDecodeError as exc:
            return _failed("invalid_upload_response", str(exc))

        return self._result_from_payload(payload)

    def _multipart_body(
        self,
        *,
        request: NaturalFileImportRequest,
        source_path: Path,
    ) -> tuple[bytes, str]:
        boundary = f"----HermesNaturalImport{uuid.uuid4().hex}"
        parts: list[bytes] = []

        fields = {
            "title": request.title or source_path.name,
            "source_type": request.source_type or "manual",
        }
        if request.document_type:
            fields["document_type"] = request.document_type

        for name, value in fields.items():
            parts.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )

        content_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        parts.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="file"; filename="{source_path.name}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode("utf-8"),
                source_path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode("utf-8"),
            ]
        )
        return b"".join(parts), f"multipart/form-data; boundary={boundary}"

    def _result_from_payload(self, payload: dict[str, Any]) -> NaturalFileUploadResult:
        status = str(payload.get("status") or "")
        message = payload.get("message")
        document_id = payload.get("document_id")
        version_id = payload.get("version_id")
        if status != "completed":
            return _failed(f"upload_status_{status or 'unknown'}", str(message or "Upload did not complete."))
        if not document_id:
            return _failed("missing_document_id", "Hermes_memory upload response did not include document_id.")
        if not version_id:
            return _failed("missing_version_id", "Hermes_memory upload response did not include version_id.")
        return NaturalFileUploadResult(
            success=True,
            document_id=str(document_id),
            version_id=str(version_id),
            chunk_count=_int_or_none(payload.get("chunk_count")),
            indexed_count=_int_or_none(payload.get("indexed_count")),
            message=str(message) if message is not None else None,
        )


def _failed(reason: str, message: str) -> NaturalFileUploadResult:
    return NaturalFileUploadResult(
        success=False,
        error_type=reason,
        error_message=message,
        failed_reason=reason,
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
