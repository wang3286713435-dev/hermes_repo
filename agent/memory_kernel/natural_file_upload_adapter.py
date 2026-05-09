from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent.memory_kernel.natural_file_import import NaturalFileImportRequest


@dataclass
class NaturalFileUploadResult:
    success: bool
    document_id: str | None = None
    version_id: str | None = None
    chunk_count: int | None = None
    indexed_count: int | None = None
    message: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    failed_reason: str | None = None


class NaturalFileUploadAdapter(Protocol):
    def upload(self, request: NaturalFileImportRequest) -> NaturalFileUploadResult:
        ...


class HermesMemoryUploadClient(Protocol):
    def upload(self, request: NaturalFileImportRequest) -> NaturalFileUploadResult:
        ...


@dataclass
class FeatureFlaggedHermesMemoryUploadAdapter:
    client: HermesMemoryUploadClient | None = None
    enabled: bool = False

    def upload(self, request: NaturalFileImportRequest) -> NaturalFileUploadResult:
        if not self.enabled:
            return NaturalFileUploadResult(
                success=False,
                error_type="real_upload_disabled",
                error_message="Real Hermes_memory upload is disabled by feature flag.",
                failed_reason="real_upload_disabled",
            )
        if self.client is None:
            return NaturalFileUploadResult(
                success=False,
                error_type="upload_client_not_configured",
                error_message="Hermes_memory upload client is not configured.",
                failed_reason="upload_client_not_configured",
            )
        return self.client.upload(request)
