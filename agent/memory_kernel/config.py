from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


@dataclass(frozen=True)
class MemoryKernelConfig:
    enabled: bool = False
    hermes_memory_path: str = ""
    top_k: int = 8
    timeout_ms: int = 3000
    fail_open: bool = True
    inject_context: bool = True
    citation_required: bool = True

    @classmethod
    def from_config(cls, raw: dict[str, Any] | None) -> "MemoryKernelConfig":
        raw = raw or {}
        env_enabled = os.getenv("HERMES_MEMORY_KERNEL_ENABLED")
        env_path = os.getenv("HERMES_MEMORY_PATH")
        default_path = Path.home() / "Hermes_memory"
        return cls(
            enabled=_as_bool(env_enabled, _as_bool(raw.get("enabled"), False)),
            hermes_memory_path=str(env_path or raw.get("hermes_memory_path") or default_path),
            top_k=int(raw.get("top_k", os.getenv("HERMES_MEMORY_TOP_K", 8)) or 8),
            timeout_ms=int(raw.get("timeout_ms", os.getenv("HERMES_MEMORY_TIMEOUT_MS", 3000)) or 3000),
            fail_open=_as_bool(raw.get("fail_open"), True),
            inject_context=_as_bool(raw.get("inject_context"), True),
            citation_required=_as_bool(raw.get("citation_required"), True),
        )

