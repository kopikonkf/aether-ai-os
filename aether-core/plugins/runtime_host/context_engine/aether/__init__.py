"""
Register Aether ContextEngine with aether-agent.

Install: copy this directory to ~/.aether/plugins/context_engine/aether/
Then set config: context.engine: "aether"

If aether-agent ABC differs, adapt register() to match installed version.
Docs: https://aether-agent.nousresearch.com/docs/developer-guide/context-engine-plugin
"""
from __future__ import annotations
import logging
import os
import sys

log = logging.getLogger(__name__)

_CORE = os.environ.get("AETHER_CORE_SRC")
if _CORE and _CORE not in sys.path:
    sys.path.insert(0, _CORE)


def register(ctx):
    """aether-agent plugin entry. Prefer ContextEngine ABC if available."""
    try:
        from agent.context_engine import ContextEngine  # type: ignore
    except ImportError:
        log.warning("ContextEngine ABC not found — register hook fallback only")
        _register_hook_fallback(ctx)
        return

    from .engine import build_mind_prefix

    class AetherContextEngine(ContextEngine):  # type: ignore
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            from aether.adapters.client import AetherClient
            self._client = AetherClient()

        def compress(self, messages, **kwargs):
            if hasattr(super(), "compress"):
                return super().compress(messages, **kwargs)
            return messages

        def build_context(self, conversation_history, system_prompt="", **kwargs):
            prefix = build_mind_prefix(self._client)
            base = system_prompt or ""
            return f"{prefix}\n{base}"

    try:
        ctx.register_context_engine(AetherContextEngine())
    except Exception as e:
        log.warning("register_context_engine failed (%s) — hook fallback", e)
        _register_hook_fallback(ctx)


def _register_hook_fallback(ctx):
    from aether.adapters.client import AetherClient
    from .engine import build_mind_prefix
    client = AetherClient()

    def pre_llm_call(session_id=None, user_message=None, **kwargs):
        return {"context": build_mind_prefix(client)}

    ctx.register_hook("pre_llm_call", pre_llm_call)
