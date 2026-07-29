import os
import shlex
import subprocess
from pathlib import Path

from aether_tools.base import Tool, ToolResult


class BashTool(Tool):
    """Legacy-named platform shell primitive with bounded policy enforcement."""

    name = "bash"
    spec = 'cmd="command here" timeout=30'

    def __init__(
        self,
        cwd: Path | str | None = None,
        blocked: list[str] | None = None,
        timeout_max: int = 60,
        output_max: int = 8000,
    ):
        self.cwd = Path(cwd) if isinstance(cwd, str) else (cwd or Path.cwd())
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.blocked = {item.lower() for item in (blocked or [
            "sudo", "curl", "wget", "nc", "format", "del", "rmdir",
            "chmod", "chown", "dd", "mkfs", "mount", "shutdown", "reboot",
        ])}
        self.timeout_max = timeout_max
        self.output_max = output_max

    @staticmethod
    def _command_name(token: str) -> str:
        name = Path(token.strip('"\'')).name.lower()
        for suffix in (".exe", ".cmd", ".bat", ".ps1"):
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        return name

    def validate(self, cmd: str = "", timeout: int = 30, **kwargs) -> ToolResult:
        if not cmd:
            return ToolResult(False, "", None, "cmd required")
        try:
            parts = shlex.split(cmd, posix=(os.name != "nt"))
        except ValueError as exc:
            return ToolResult(False, "", None, f"Command parse error: {exc}")
        if not parts:
            return ToolResult(False, "", None, "cmd required")
        executable = self._command_name(parts[0])
        if executable in self.blocked:
            return ToolResult(False, "", {"command": executable}, f"Command blocked: {executable}")
        try:
            bounded_timeout = min(max(1, int(timeout)), self.timeout_max)
        except (TypeError, ValueError):
            return ToolResult(False, "", None, "timeout must be an integer")
        return ToolResult(True, "Shell preflight passed.", {"timeout": bounded_timeout, "cwd": str(self.cwd)})

    def __call__(self, cmd: str = "", timeout: int = 30, **kwargs) -> ToolResult:
        preflight = self.validate(cmd=cmd, timeout=timeout)
        if not preflight.ok:
            return preflight
        bounded_timeout = int((preflight.data or {})["timeout"])
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=bounded_timeout,
            )
            output = (result.stdout + result.stderr)[:self.output_max]
            return ToolResult(result.returncode == 0, output, {"returncode": result.returncode, "cwd": str(self.cwd)})
        except subprocess.TimeoutExpired:
            return ToolResult(False, "", None, f"Command timed out after {bounded_timeout}s")
        except Exception as exc:
            return ToolResult(False, "", None, str(exc))
