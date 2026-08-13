"""APCB Herdr execution adapter — narrow deterministic glue over the Herdr CLI.

Contract reference: project-docs/architecture/APCB_V0_1_IMPLEMENTATION_CONTRACT.md
Section 8 (Herdr adapter boundary). Preferred surface: Herdr CLI wrappers for
simple request/response operations (option 1 in the contract). The adapter
normalizes Herdr workspace/tab/pane identifiers into opaque execution
references stored as bridge metadata.

The reference live adapter this mirrors is `herdr_dispatch.py` (task -> pane
worker, contract `opencode.ok/exit/output`). The methods are synchronous
(subprocess calls) so Slice B stays deterministic; the async Protocol shape in
the contract can wrap these trivially later without changing behavior.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from aether.apcb.conformance import AdapterConformanceStatus

LOG = logging.getLogger("aether.apcb.herdr")

HERDR_BIN = os.environ.get(
    "HERDR_BIN",
    r"C:\Users\aethers\AppData\Local\Programs\Herdr\bin\herdr.exe",
)

# freebuff/jcode tidak terdeteksi oleh `herdr agent` -> pakai pane send-text.
PANE_SEND_AGENTS = frozenset({"freebuff", "jcode"})


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    """Run a single herdr CLI invocation; injectable for deterministic tests."""

    def run(self, args: list[str], timeout: float = 30.0) -> CommandResult: ...


def _real_runner(bin_path: str = HERDR_BIN) -> CommandRunner:
    return _SubprocessRunner(bin_path)


class _SubprocessRunner:
    """Run herdr.exe with HERDR_ENV/HERDR_PANE_ID cleared (nested-herdr guard)."""

    def __init__(self, bin_path: str = HERDR_BIN) -> None:
        self.bin_path = bin_path

    def _resolve(self) -> str:
        if Path(self.bin_path).exists():
            return self.bin_path
        found = shutil.which("herdr")
        if found:
            return found
        raise FileNotFoundError(f"herdr binary not found: {self.bin_path}")

    def run(self, args: list[str], timeout: float = 30.0) -> CommandResult:
        env = os.environ.copy()
        env.pop("HERDR_ENV", None)
        env.pop("HERDR_PANE_ID", None)
        proc = subprocess.run(
            [self._resolve(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )


@dataclass(frozen=True)
class AgentObservation:
    """Normalized observation of one herdr agent/pane execution."""

    agent_ref: str
    status: str  # idle|working|done|blocked|unknown|missing|terminated
    output: str = ""
    is_terminal: bool = False
    error: str | None = None
    observed_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agent_ref": self.agent_ref,
            "status": self.status,
            "output": self.output,
            "is_terminal": self.is_terminal,
            "error": self.error,
            "observed_at": self.observed_at,
            "metadata": self.metadata,
        }


class HerdrExecutionAdapter:
    """Narrow adapter over the Herdr CLI (workspace/agent/prompt/read/recover).

    All identifiers returned are opaque execution references suitable for
    bridge metadata; the caller never sees raw Herdr pane coordinates.
    """

    def __init__(
        self,
        runner: CommandRunner | None = None,
        pane_resolver: Callable[[str], str | None] | None = None,
        pane_send_agents: frozenset[str] = PANE_SEND_AGENTS,
    ) -> None:
        self.runner = runner or _real_runner()
        self.pane_resolver = pane_resolver or _default_pane_resolver()
        self.pane_send_agents = pane_send_agents

    # -- workspace --------------------------------------------------------

    def ensure_workspace(self, workspace_ref: str) -> str:
        """Resolve a workspace ref into an opaque, normalized workspace id.

        Does not create directories: APCB observes bound workspaces, it does
        not provision them. Raises FileNotFoundError when the workspace does
        not exist on disk (fail-closed).
        """
        raw = str(workspace_ref).strip()
        if not raw:
            raise ValueError("workspace_ref must not be empty")
        p = Path(raw)
        if p.exists() and not p.is_dir():
            raise ValueError(f"workspace_ref is not a directory: {raw}")
        if not p.exists():
            raise FileNotFoundError(f"workspace not found: {raw}")
        return p.resolve().as_posix()

    # -- agent ------------------------------------------------------------

    def ensure_agent(self, workspace_ref: str, principal_id: str, herdr_agent_kind: str | None = None) -> str:
        """Resolve a principal to a live Herdr pane/execution ref.

        The pane resolver is injected (default: reads a JSON map from
        APCB_HERDR_PANE_MAP, else None). Returns an opaque ref like
        'herdr://pane/w7:p3', or 'herdr://pane/send/w7:p7' for agents that
        herdr cannot detect as agents (freebuff/jcode) and therefore need the
        raw terminal send path.
        """
        pane = self.pane_resolver(principal_id)
        if not pane:
            raise LookupError(f"no herdr pane bound for principal '{principal_id}'")
        if herdr_agent_kind and herdr_agent_kind in self.pane_send_agents:
            return f"herdr://pane/send/{pane}"
        return f"herdr://pane/{pane}"

    def prompt_agent(self, agent_ref: str, task_context: str) -> str:
        """Dispatch a task to a live agent pane; returns a prompt ref."""
        pane = self._pane_of(agent_ref)
        if self._is_pane_send(agent_ref):
            r1 = self.runner.run(["pane", "send-text", pane, task_context], timeout=15)
            r2 = self.runner.run(["pane", "send-keys", pane, "enter"], timeout=15)
            if r1.returncode != 0 or r2.returncode != 0:
                raise RuntimeError(
                    f"pane send failed: {(r1.stderr + r2.stderr).strip()[:500]}"
                )
        else:
            r = self.runner.run(["agent", "prompt", pane, task_context], timeout=30)
            if r.returncode != 0:
                raise RuntimeError(f"agent prompt failed: {r.stderr.strip()[:500]}")
        return f"herdr://prompt/{pane}"

    def observe_agent(self, agent_ref: str) -> AgentObservation:
        """Query current agent lifecycle status for a pane."""
        pane = self._pane_of(agent_ref)
        if self._is_pane_send(agent_ref):
            # freebuff/jcode are not herdr agents: no lifecycle to query.
            # Observation is bounded-settle + read (see wait_agent).
            return AgentObservation(
                agent_ref=agent_ref, status="unknown", is_terminal=False,
                error="pane-send agent: no lifecycle; use bounded settle + read",
            )
        r = self.runner.run(["agent", "get", pane], timeout=15)
        if r.returncode != 0:
            return AgentObservation(
                agent_ref=agent_ref, status="missing", is_terminal=True,
                error=r.stderr.strip()[:500],
            )
        try:
            body = json.loads(r.stdout)
            agent = (body.get("result") or {}).get("agent", {})
            status = agent.get("agent_status", "unknown")
        except (json.JSONDecodeError, AttributeError):
            status = "unknown"
        return AgentObservation(
            agent_ref=agent_ref,
            status=status,
            is_terminal=status in ("done", "blocked", "terminated"),
        )

    def wait_agent(self, agent_ref: str, timeout_seconds: float) -> AgentObservation:
        """Poll observe until terminal status or timeout; bounded settle."""
        if self._is_pane_send(agent_ref):
            # freebuff/jcode: no herdr lifecycle (ADR-0057 K1). A bounded settle
            # is NOT an observed completion: return unknown + non-terminal so
            # the caller MUST reconcile and verify the artifact on disk before
            # any terminal outcome is recorded. Never fabricate "done".
            settle = min(300.0, max(0.0, float(timeout_seconds)))
            time.sleep(settle)
            output = self.read_agent(agent_ref, limit_bytes=8192)
            return AgentObservation(
                agent_ref=agent_ref,
                status="unknown",
                output=output,
                is_terminal=False,
                error="pane-send agent: no lifecycle; caller must reconcile + verify artifact",
            )
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            obs = self.observe_agent(agent_ref)
            if obs.is_terminal or obs.status == "idle":
                return obs
            time.sleep(min(2.0, max(0.1, deadline - time.monotonic())))
        last = self.observe_agent(agent_ref)
        return AgentObservation(
            agent_ref=agent_ref,
            status="unknown",
            output=last.output,
            is_terminal=False,
            error="wait timeout",
            metadata={"timeout_seconds": timeout_seconds},
        )

    def read_agent(self, agent_ref: str, limit_bytes: int = 8192) -> str:
        """Read recent-unwrapped output of a pane, bounded by limit_bytes."""
        pane = self._pane_of(agent_ref)
        r = self.runner.run(["agent", "read", pane, "--source", "recent-unwrapped", "--lines", "120"], timeout=30)
        if r.returncode != 0:
            r = self.runner.run(["pane", "read", pane, "--source", "visible", "--lines", "120"], timeout=30)
        text = r.stdout.strip()
        if len(text.encode("utf-8")) > limit_bytes:
            text = text.encode("utf-8")[:limit_bytes].decode("utf-8", errors="replace")
        return text

    def recover_agent(self, agent_ref: str) -> AgentObservation:
        """Attempt recovery: re-resolve the pane and re-observe."""
        pane = self._pane_of(agent_ref)
        if not self._pane_alive(pane):
            return AgentObservation(
                agent_ref=agent_ref, status="missing", is_terminal=True,
                error=f"pane {pane} not alive after recover attempt",
            )
        return self.observe_agent(agent_ref)

    # -- capability detection ---------------------------------------------

    def detect_adapter(self, herdr_agent_kind: str) -> AdapterConformanceStatus:
        """Probe whether the herdr CLI can currently drive this agent kind.

        This is the AgentKindProbe for the ConformanceGate: herdr binary
        present + invocation works -> HEALTHY; binary missing -> MISSING;
        invocation error/timeout -> UNAVAILABLE; a stale/penalized binding is
        reported EXPIRED by the probe.
        """
        try:
            r = self.runner.run(["--version"], timeout=10)
        except FileNotFoundError:
            return AdapterConformanceStatus.MISSING
        except (subprocess.TimeoutExpired, OSError):
            return AdapterConformanceStatus.UNAVAILABLE
        if r.returncode != 0:
            return AdapterConformanceStatus.UNAVAILABLE
        if not r.stdout.strip() and not r.stderr.strip():
            return AdapterConformanceStatus.UNAVAILABLE
        return AdapterConformanceStatus.HEALTHY

    # -- internals --------------------------------------------------------

    @staticmethod
    def _pane_of(agent_ref: str) -> str:
        if not agent_ref or not agent_ref.startswith("herdr://"):
            raise ValueError(f"invalid agent_ref: {agent_ref!r}")
        return agent_ref.rsplit("/", 1)[-1]

    def _is_pane_send(self, agent_ref: str) -> bool:
        return agent_ref.startswith("herdr://pane/send/")

    def _pane_alive(self, pane: str) -> bool:
        r = self.runner.run(["agent", "get", pane], timeout=15)
        return r.returncode == 0


def _default_pane_resolver() -> Callable[[str], str | None]:
    """Resolve principal -> pane from a JSON map file (APCB_HERDR_PANE_MAP).

    The map shape is {"panes": {"<principal_id>": "<pane>"}} and is expected
    to mirror convmap.json's panes section on the host.
    """

    def resolve(principal_id: str) -> str | None:
        path = os.environ.get("APCB_HERDR_PANE_MAP")
        if not path:
            return None
        try:
            data = json.loads(Path(path).read_text("utf-8-sig"))
            panes = data.get("panes", {})
            for pid, info in panes.items():
                if pid == principal_id:
                    if isinstance(info, str):
                        return info
                    if isinstance(info, dict) and info.get("agent") == principal_id:
                        return pid
            return panes.get(principal_id) if isinstance(panes.get(principal_id), str) else None
        except (OSError, json.JSONDecodeError) as exc:
            LOG.warning(f"APCB_HERDR_PANE_MAP resolve failed: {exc}")
            return None

    return resolve


class PaneUniquenessError(RuntimeError):
    """Raised when the pane map is not injective over principals (WORK-5 K4):
    two sovereign principals must never share a pane in a no-message-bus design
    where pane identity is part of authority."""


def validate_pane_map_unique(
    pane_map_path: str | None = None,
    *,
    sovereign_principals: set[str] | None = None,
) -> dict[str, str]:
    """Validate apcb_pane_map.json is injective over (sovereign) principals.

    Fail-closed: raises PaneUniquenessError on any collision, missing map, or
    malformed shape. Returns the {principal -> pane} mapping on success.

    This is a startup validator (WORK-5 K4): call it once before any dispatch.
    """
    path = pane_map_path or os.environ.get("APCB_HERDR_PANE_MAP")
    if not path:
        raise PaneUniquenessError("APCB_HERDR_PANE_MAP not set; cannot validate pane uniqueness")
    try:
        data = json.loads(Path(path).read_text("utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaneUniquenessError(f"cannot read pane map {path}: {exc}") from exc
    panes = data.get("panes")
    if not isinstance(panes, dict):
        raise PaneUniquenessError(f"pane map {path} has no 'panes' mapping")
    resolved: dict[str, str] = {}
    for pid, info in panes.items():
        if isinstance(info, str):
            pane = info
        elif isinstance(info, dict) and isinstance(info.get("pane"), str):
            pane = info["pane"]
        else:
            raise PaneUniquenessError(f"pane map entry for '{pid}' has no pane id")
        if not pane.strip():
            raise PaneUniquenessError(f"pane map entry for '{pid}' is empty")
        resolved[pid] = pane

    if sovereign_principals is not None:
        missing = sorted(sovereign_principals - set(resolved))
        if missing:
            raise PaneUniquenessError(
                f"pane map missing sovereign principals: {missing}"
            )

    by_pane: dict[str, str] = {}
    for pid, pane in sorted(resolved.items()):
        if pane in by_pane:
            raise PaneUniquenessError(
                f"pane collision: '{by_pane[pane]}' and '{pid}' both map to {pane}"
            )
        by_pane[pane] = pid
    return resolved
