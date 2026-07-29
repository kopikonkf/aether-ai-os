"""Mind prefix builder for body ContextEngine plugin."""
from __future__ import annotations


def build_mind_prefix(client) -> str:
    if not client.is_alive():
        return (
            "[AETHER FAIL-SAFE] Mind daemon unavailable. "
            "Do NOT change identity, mission, goals, or irreversible state. "
            "Reply helpfully only; escalate to Dee if unsure.\n"
        )
    me = client.who_am_i()
    values = ", ".join(me.values[:5]) if getattr(me, "values", None) else ""
    return (
        f"[AETHER MIND]\n"
        f"Name: {me.name}\n"
        f"Stage: {me.stage}\n"
        f"Mission: {me.mission}\n"
        f"Values: {values}\n"
        f"Self: {me.narrative}\n"
        f"Authority: North Star gate required for irreversible / spend >= escalate threshold.\n"
        f"[/AETHER MIND]\n"
    )
