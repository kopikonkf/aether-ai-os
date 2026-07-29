"""
Aether Traffic Controller — Deterministic Routing Engine
========================================================
Pure rules only. Zero LLM calls. Zero AI logic.
Rule-based model mapping for task dispatching.
"""

FAILSAFE_MODEL = "mimo-v2.5-pro"
FAILSAFE_PROVIDER = "xiaomimimo"

_FALLBACK_CHAINS = {
    "mimo":        ["arkoda", "openagentic"],
    "arkoda":      ["openagentic", "mimo"],
    "openagentic": ["arkoda", "mimo"],
}

_VALID_TASK_TYPES   = {"chat", "code", "reasoning", "trading", "system"}
_VALID_URGENCY      = {"low", "medium", "high", "critical"}
_VALID_CONTEXT_SIZE = {"small", "medium", "large"}


class TrafficController:
    """Deterministic routing engine for Aether model routing."""

    def route(
        self,
        task_type: str,
        urgency: str = "medium",
        context_size: str = "small",
        channel: str = "cli",
    ) -> dict:
        task_type = str(task_type).strip().lower()
        urgency = str(urgency).strip().lower()
        context_size = str(context_size).strip().lower()
        channel = str(channel).strip().lower()

        # Rules (strict order, first match wins)
        if task_type == "system":
            selected = "arkoda"
            reason = "P1: task_type=system → arkoda (high-stakes system ops)"
        elif task_type == "trading":
            selected = "arkoda"
            reason = "P2: task_type=trading → arkoda (zero margin for error)"
        elif task_type == "reasoning" and urgency != "low":
            selected = "arkoda"
            reason = "P3: task_type=reasoning + urgency!=low → arkoda"
        elif task_type == "code" and context_size == "large":
            selected = "arkoda"
            reason = "P4: task_type=code + context_size=large → arkoda"
        elif urgency == "critical":
            selected = "openagentic"
            reason = "P5: urgency=critical → openagentic"
        elif task_type == "chat":
            selected = "mimo"
            reason = "P6: task_type=chat → mimo"
        else:
            selected = "mimo"
            reason = "P7: DEFAULT → mimo"

        fallback_chain = _FALLBACK_CHAINS.get(selected, ["mimo"])

        return {
            "selected_model": selected,
            "fallback_chain": fallback_chain,
            "reason": reason,
        }
