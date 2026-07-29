from __future__ import annotations
import logging
import os
import sys

log = logging.getLogger(__name__)
_CORE = os.environ.get("AETHER_CORE_SRC")
if _CORE and _CORE not in sys.path:
    sys.path.insert(0, _CORE)


def register(ctx):
    """Register MemoryProvider if ABC present; else no-op with log."""
    try:
        from agent.memory_provider import MemoryProvider  # type: ignore
    except ImportError:
        log.warning("MemoryProvider ABC missing — skip aether memory plugin")
        return

    from aether.adapters.client import AetherClient
    from .provider import AetherMemoryCore

    class AetherMemoryProvider(MemoryProvider):  # type: ignore
        @property
        def name(self) -> str:
            return "aether"

        def is_available(self) -> bool:
            return True

        def initialize(self, session_id: str, **kwargs) -> None:
            self._session_id = session_id
            self._core = AetherMemoryCore(AetherClient())

        def get_tool_schemas(self):
            return []

        def handle_tool_call(self, tool_name, args, **kwargs):
            return "{}"

        def get_config_schema(self):
            return []

        def save_config(self, values, aether_home):
            return None

        def prefetch(self, query, *, session_id=""):
            return self._core.prefetch(query)

        def sync_turn(self, user, assistant, *, session_id="", messages=None):
            try:
                self._core.write_operational(f"User: {user}\nAether: {assistant}", session_id=session_id or self._session_id)
            except Exception as e:
                log.warning("sync_turn: %s", e)

    ctx.register_memory_provider(AetherMemoryProvider())
