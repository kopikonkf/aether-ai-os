from __future__ import annotations

import pytest

from aether_gateway.adapters.telegram_commands import (
    TelegramCommandRegistry,
    TelegramCommandSpec,
    default_telegram_command_registry,
)


def test_default_registry_exposes_only_wired_founder_commands() -> None:
    registry = default_telegram_command_registry()
    bindings = dict(registry.bindings())
    assert bindings["start"] == "start_command"
    assert bindings["help"] == "help_command"
    assert bindings["new"] == "clear_command"
    assert bindings["clear"] == "clear_command"
    assert "restart" not in bindings  # avoid implying a Gateway/service restart
    assert bindings["approvals"] == "approvals_command"
    assert bindings["yes"] == "yes_command"
    assert bindings["no"] == "no_command"

    menu = dict(registry.menu_items())
    assert "approve" not in menu
    assert "reject" not in menu
    assert "voice" not in menu  # not exposed until a real handler exists
    assert "runtime" not in menu
    assert "skills" not in menu

    help_text = registry.help_text()
    assert "/help" in help_text
    assert "/approvals" in help_text
    assert "Natural language remains the primary interface" in help_text


def test_registry_rejects_duplicates_and_invalid_commands() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        TelegramCommandRegistry((
            TelegramCommandSpec("status", "Status", "status_command"),
            TelegramCommandSpec("health", "Health", "status_command", aliases=("status",)),
        ))

    with pytest.raises(ValueError, match="invalid Telegram command"):
        TelegramCommandSpec("Bad-Command", "Invalid", "handler")
