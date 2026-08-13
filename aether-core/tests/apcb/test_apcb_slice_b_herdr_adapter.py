"""APCB Slice B — herdr adapter pane-send routing (freebuff/jcode).

Deterministic, mock CommandRunner. Regression for the Gate 3 bug where
`prompt_agent` compared the pane id against the pane-send agent kinds
(`w7:p7` vs `freebuff`), so freebuff/jcode never used the raw terminal
send path and `agent prompt` failed with `agent_not_found`.
"""
from __future__ import annotations

from pathlib import Path

from aether.apcb.herdr_adapter import HerdrExecutionAdapter


class RecordingRunner:
    """Deterministic fake CommandRunner that records herdr invocations."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.agent_get_body = {
            "id": "cli:agent:get",
            "result": {"agent": {"agent_status": "done"}},
        }
        self.fail_agent_get = False

    def run(self, args: list[str], timeout: float = 30.0):
        self.calls.append(args)
        if args[0] == "--version":
            return _Result(0, "herdr 1.0.0\n", "")
        if args[0] == "agent" and args[1] == "get":
            if self.fail_agent_get:
                return _Result(1, "", '{"error":{"code":"agent_not_found"}}')
            import json
            return _Result(0, json.dumps(self.agent_get_body), "")
        if args[0] == "agent" and args[1] == "read":
            return _Result(0, "[pane-send] worker reply", "")
        if args[0] == "pane" and args[1] == "read":
            return _Result(0, "[pane-send] worker reply", "")
        return _Result(0, "", "")


class _Result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _resolver(pane: str):
    return lambda principal_id: pane


def test_ensure_agent_pane_send_ref_for_freebuff():
    runner = RecordingRunner()
    adapter = HerdrExecutionAdapter(runner=runner, pane_resolver=_resolver("w7:p7"))
    ref = adapter.ensure_agent("ws", "claude", herdr_agent_kind="freebuff")
    assert ref == "herdr://pane/send/w7:p7"
    # non pane-send kind keeps the plain ref
    ref2 = adapter.ensure_agent("ws", "chatgpt", herdr_agent_kind="opencode")
    assert ref2 == "herdr://pane/w7:p7"


def test_prompt_agent_pane_send_uses_raw_terminal():
    runner = RecordingRunner()
    adapter = HerdrExecutionAdapter(runner=runner, pane_resolver=_resolver("w7:p7"))
    ref = adapter.ensure_agent("ws", "claude", herdr_agent_kind="freebuff")
    adapter.prompt_agent(ref, "task text")
    text_calls = [c for c in runner.calls if c[0] == "pane" and c[1] == "send-text"]
    key_calls = [c for c in runner.calls if c[0] == "pane" and c[1] == "send-keys"]
    assert len(text_calls) == 1 and text_calls[0][2] == "w7:p7"
    assert text_calls[0][3] == "task text"
    assert len(key_calls) == 1 and key_calls[0][2] == "w7:p7"
    assert not any(c[0] == "agent" and c[1] == "prompt" for c in runner.calls)


def test_prompt_agent_regular_agent_uses_agent_prompt():
    runner = RecordingRunner()
    adapter = HerdrExecutionAdapter(runner=runner, pane_resolver=_resolver("w7:p3"))
    ref = adapter.ensure_agent("ws", "chatgpt", herdr_agent_kind="opencode")
    adapter.prompt_agent(ref, "task text")
    assert any(c[0] == "agent" and c[1] == "prompt" for c in runner.calls)
    assert not any(c[0] == "pane" and c[1] == "send-text" for c in runner.calls)


def test_wait_agent_pane_send_bounded_settle_terminal():
    runner = RecordingRunner()
    adapter = HerdrExecutionAdapter(runner=runner, pane_resolver=_resolver("w7:p7"))
    ref = adapter.ensure_agent("ws", "claude", herdr_agent_kind="freebuff")
    obs = adapter.wait_agent(ref, timeout_seconds=0.01)
    assert obs.is_terminal is True
    assert obs.status == "done"
    # observed via pane read (fallback read path), not agent lifecycle
    assert any(c[0] == "agent" and c[1] == "read" for c in runner.calls) or any(
        c[0] == "pane" and c[1] == "read" for c in runner.calls
    )


def test_observe_agent_pane_send_no_lifecycle():
    runner = RecordingRunner()
    adapter = HerdrExecutionAdapter(runner=runner, pane_resolver=_resolver("w7:p7"))
    ref = adapter.ensure_agent("ws", "claude", herdr_agent_kind="freebuff")
    obs = adapter.observe_agent(ref)
    assert obs.is_terminal is False
    assert obs.status == "unknown"
