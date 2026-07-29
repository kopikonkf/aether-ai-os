"""Aether Gateway adapters.

Telegram is intentionally not imported eagerly so voice/direct adapters remain
usable when the optional Telegram client is not installed.
"""

from .base import RuntimeAdapter
from .direct_text import DirectTextSenseAdapter
from .local_process import LocalProcessRuntimeAdapter
from .runtime_host import RuntimeHostAdapter
from .voice_bridge import VoiceBridgeAdapter

__all__ = [
    "DirectTextSenseAdapter",
    "LocalProcessRuntimeAdapter",
    "RuntimeAdapter",
    "RuntimeHostAdapter",
    "VoiceBridgeAdapter",
]
