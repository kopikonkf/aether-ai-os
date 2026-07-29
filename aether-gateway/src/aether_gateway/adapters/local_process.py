"""Cross-platform external-process runtime with a strict command allowlist."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Mapping

from aether.contracts.runtime import RuntimeAdapter, RuntimeCommand, RuntimeResult


class LocalProcessRuntimeAdapter(RuntimeAdapter):
    """Minimal real body adapter.

    This adapter intentionally exposes only ``echo`` in MVP v0.4. It creates an
    external process without a shell, proving runtime delegation while keeping
    arbitrary command execution outside the trusted boundary.
    """

    def __init__(self, *, cwd: Path | None = None, timeout_seconds: float = 10.0):
        self.cwd = cwd
        self.timeout_seconds = timeout_seconds

    @property
    def adapter_id(self) -> str:
        return "runtime.local-process"

    async def capabilities(self) -> set[str]:
        return {"echo"}

    async def health(self) -> Mapping[str, Any]:
        return {"ok": True, "adapter_id": self.adapter_id, "python": sys.executable, "cwd": str(self.cwd) if self.cwd else None}

    async def execute(self, command: RuntimeCommand) -> RuntimeResult:
        if command.command != "echo":
            return RuntimeResult(False, error=f"Command is not allowlisted: {command.command}", metadata={"error_type": "CommandDenied"})
        text = str(command.arguments.get("text") or "")
        if not text:
            return RuntimeResult(False, error="echo requires a non-empty text argument", metadata={"error_type": "InvalidArguments"})
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import sys; print(sys.argv[1])",
            text,
            cwd=str(self.cwd) if self.cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timeout = min(command.timeout_seconds, self.timeout_seconds)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return RuntimeResult(False, error=f"Runtime timed out after {timeout}s", metadata={"error_type": "Timeout"})
        output = stdout.decode("utf-8", errors="replace").rstrip("\r\n")
        error_text = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            return RuntimeResult(False, error=error_text or f"Runtime exited with {process.returncode}", metadata={"error_type": "ProcessExit", "returncode": process.returncode})
        return RuntimeResult(True, output=output, metadata={"adapter_id": self.adapter_id, "returncode": process.returncode, "shell": False})
