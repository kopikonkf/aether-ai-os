"""Which body tool calls need Aether North Star gate."""
from __future__ import annotations
from typing import Any, Dict

IRREVERSIBLE_TOOLS = {
    "write_file", "patch", "file_edit", "skill_manage",
    "delegate_task", "browser_click",
}

DANGEROUS_CMD_FRAGMENTS = (
    "rm ", "rm\t", "del ", "format ", "mkfs", "dd if=",
    "shutdown", "reboot", "> /dev/", "curl | sh", "wget | sh",
)


def is_irreversible_tool(tool_name: str, args: Dict[str, Any]) -> bool:
    name = (tool_name or "").lower()
    if name in IRREVERSIBLE_TOOLS or name.startswith("write"):
        return True
    if name in {"terminal", "bash", "run_terminal", "execute_code"}:
        cmd = str(args.get("command") or args.get("cmd") or args.get("code") or "").lower()
        return any(f in cmd for f in DANGEROUS_CMD_FRAGMENTS)
    return False


def estimate_amount_usd(tool_name: str, args: Dict[str, Any]) -> float:
    for key in ("amount_usd", "usd", "spend", "notional", "size_usd"):
        if key in args and args[key] is not None:
            try:
                return float(args[key])
            except (TypeError, ValueError):
                pass
    return 0.0


def should_gate(tool_name: str, args: Dict[str, Any]) -> bool:
    if estimate_amount_usd(tool_name, args) > 0:
        return True
    return is_irreversible_tool(tool_name, args)
