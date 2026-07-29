"""Central command registry for Telegram and future operator surfaces."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

_COMMAND_RE = re.compile(r"^[a-z0-9_]{1,32}$")


@dataclass(frozen=True)
class TelegramCommandSpec:
    name: str
    description: str
    handler_name: str
    aliases: tuple[str, ...] = ()
    operator_only: bool = False
    menu_visible: bool = True
    category: str = "general"

    def __post_init__(self) -> None:
        names = (self.name, *self.aliases)
        for value in names:
            if not _COMMAND_RE.fullmatch(value):
                raise ValueError(f"invalid Telegram command: {value!r}")
        if not self.description.strip() or len(self.description) > 256:
            raise ValueError(f"invalid command description for /{self.name}")

    @property
    def all_names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


class TelegramCommandRegistry:
    """Single source of truth for command handlers, help, and Telegram menu."""

    def __init__(self, specs: Iterable[TelegramCommandSpec]) -> None:
        self._specs = tuple(specs)
        seen: set[str] = set()
        for spec in self._specs:
            for name in spec.all_names:
                if name in seen:
                    raise ValueError(f"duplicate Telegram command: {name}")
                seen.add(name)

    @property
    def specs(self) -> tuple[TelegramCommandSpec, ...]:
        return self._specs

    def bindings(self) -> tuple[tuple[str, str], ...]:
        rows: list[tuple[str, str]] = []
        for spec in self._specs:
            rows.extend((name, spec.handler_name) for name in spec.all_names)
        return tuple(rows)

    def menu_items(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (spec.name, spec.description)
            for spec in self._specs
            if spec.menu_visible
        )

    def help_text(self) -> str:
        groups: dict[str, list[TelegramCommandSpec]] = {}
        for spec in self._specs:
            if spec.menu_visible:
                groups.setdefault(spec.category, []).append(spec)
        labels = {
            "session": "Session",
            "system": "System",
            "cognition": "Cognition",
            "governance": "Governance",
            "general": "General",
        }
        lines = ["Aether command surface"]
        for category in ("session", "system", "cognition", "governance", "general"):
            specs = groups.get(category)
            if not specs:
                continue
            lines.append(f"\n{labels[category]}:")
            for spec in specs:
                lines.append(f"/{spec.name} — {spec.description}")
        lines.append(
            "\nNatural language remains the primary interface; commands are bounded operator controls."
        )
        return "\n".join(lines)


def default_telegram_command_registry() -> TelegramCommandRegistry:
    """Expose only commands backed by live handlers; no aspirational menu entries."""
    return TelegramCommandRegistry((
        TelegramCommandSpec(
            "start",
            "Start or confirm the Aether session",
            "start_command",
            category="session",
        ),
        TelegramCommandSpec(
            "help",
            "Show available commands",
            "help_command",
            category="session",
        ),
        TelegramCommandSpec(
            "new",
            "Start a fresh conversation context",
            "clear_command",
            aliases=("clear",),
            category="session",
        ),
        TelegramCommandSpec(
            "status",
            "Show current Aether and approval status",
            "status_command",
            category="system",
        ),
        TelegramCommandSpec(
            "model",
            "View or set the session model route",
            "model_command",
            category="cognition",
        ),
        TelegramCommandSpec(
            "approvals",
            "List pending governed actions",
            "approvals_command",
            operator_only=True,
            category="governance",
        ),
        TelegramCommandSpec(
            "yes",
            "Approve the only pending action in this chat",
            "yes_command",
            operator_only=True,
            category="governance",
        ),
        TelegramCommandSpec(
            "no",
            "Reject the only pending action in this chat",
            "no_command",
            operator_only=True,
            category="governance",
        ),
        TelegramCommandSpec(
            "approve",
            "Approve an action by exact ID",
            "approve_command",
            operator_only=True,
            menu_visible=False,
            category="governance",
        ),
        TelegramCommandSpec(
            "reject",
            "Reject an action by exact ID",
            "reject_command",
            operator_only=True,
            menu_visible=False,
            category="governance",
        ),
    ))
