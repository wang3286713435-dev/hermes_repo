"""Enterprise memory kernel for Hermes.

This package is intentionally part of the agent core. It is not a plugin
surface: plugins may extend it later, but query-time enterprise memory belongs
in the Hermes request path.
"""

from .config import MemoryKernelConfig
from .kernel import MemoryKernel

__all__ = ["MemoryKernel", "MemoryKernelConfig"]

