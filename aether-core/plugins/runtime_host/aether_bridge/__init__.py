from __future__ import annotations
import json
import logging
import os
import sys

log = logging.getLogger(__name__)
_CORE = os.environ.get("AETHER_CORE_SRC")
if _CORE and _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from .policy import should_gate, estimate_amount_usd


class GateDenied(Exception):
    """Raised to signal tool must not run. Whether aether-agent honors this
    depends on hook semantics — VERIFY on local install (open question §13.1)."""


def register(ctx):
    from aether.adapters.client import AetherClient
    client = AetherClient()

    def pre_tool_call(tool_name, args, task_id=None, **kwargs):
        args = args or {}
        if not should_gate(tool_name, args):
            return None
        if not client.is_alive():
            raise GateDenied("Aether mind unavailable — gated tool blocked")
        amount = estimate_amount_usd(tool_name, args)
        result = client.evaluate(
            action=f"tool:{tool_name}",
            reason=json.dumps(args)[:500],
            amount_usd=amount,
            metadata={"task_id": task_id or "", "tool": tool_name},
        )
        if result.escalate_to_dee:
            raise GateDenied(f"Escalate to Dee: {result.veto_reason}")
        if not result.approved:
            raise GateDenied(result.veto_reason or "North Star veto")
        return None

    def post_tool_call(tool_name, args, result=None, task_id=None, **kwargs):
        if not client.is_alive():
            return None
        try:
            client.experience(
                action=f"tool:{tool_name}",
                new_state={"result_preview": str(result)[:300] if result is not None else ""},
                source="body",
            )
        except Exception as e:
            log.warning("post experience failed: %s", e)
        return None

    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("post_tool_call", post_tool_call)
