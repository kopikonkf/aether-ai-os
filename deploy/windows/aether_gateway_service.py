#!/usr/bin/env python3
"""Windows Service host for the Aether Gateway.

The service delegates lifecycle to the Windows Service Control Manager while the
Gateway itself remains the normal uvicorn process. SCM recovery restarts this
service if the child exits unexpectedly.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Mapping

SERVICE_NAME = "AetherGateway"
SERVICE_DISPLAY_NAME = "Aether Gateway"
SERVICE_DESCRIPTION = "Aether AI OS Gateway and communication surfaces"


def release_root() -> Path:
    configured = os.environ.get("AETHER_RELEASE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def service_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    root = release_root()
    env.setdefault("AETHER_RELEASE_ROOT", str(root))
    env.setdefault("AETHER_HOME", r"C:\ProgramData\Aether")
    env.setdefault("AETHER_GATEWAY_HOST", "127.0.0.1")
    env.setdefault("AETHER_GATEWAY_PORT", "8000")
    python_paths = [
        str(root / "aether-core" / "src"),
        str(root / "aether-tools" / "src"),
        str(root / "aether-gateway" / "src"),
    ]
    existing = env.get("PYTHONPATH", "").strip()
    if existing:
        python_paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    return env


def gateway_command(python_executable: str | None = None) -> list[str]:
    env = service_environment()
    return [
        python_executable or sys.executable,
        "-m",
        "uvicorn",
        "aether_gateway.api.server:app",
        "--host",
        env["AETHER_GATEWAY_HOST"],
        "--port",
        env["AETHER_GATEWAY_PORT"],
        "--no-access-log",
    ]


def log_paths() -> tuple[Path, Path]:
    root = Path(os.environ.get("AETHER_LOG_ROOT", r"C:\ProgramData\Aether\logs"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "gateway-service.stdout.log", root / "gateway-service.stderr.log"


if os.name == "nt":  # pragma: no cover - exercised on the Windows VPS acceptance gate
    import win32event
    import win32service
    import win32serviceutil

    class AetherGatewayService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY_NAME
        _svc_description_ = SERVICE_DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._stop_requested = threading.Event()
            self._child: subprocess.Popen[str] | None = None
            self._stdout = None
            self._stderr = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self._stop_requested.set()
            win32event.SetEvent(self._stop_event)
            self._terminate_child()

        def SvcDoRun(self):
            root = release_root()
            stdout_path, stderr_path = log_paths()
            self._stdout = stdout_path.open("a", encoding="utf-8", buffering=1)
            self._stderr = stderr_path.open("a", encoding="utf-8", buffering=1)
            env = service_environment()
            self._child = subprocess.Popen(
                gateway_command(),
                cwd=root,
                env=env,
                stdout=self._stdout,
                stderr=self._stderr,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            while not self._stop_requested.wait(1.0):
                returncode = self._child.poll()
                if returncode is not None:
                    self._stderr.write(f"Gateway child exited unexpectedly with code {returncode}\n")
                    raise RuntimeError(f"Gateway child exited with code {returncode}")
            self._terminate_child()

        def _terminate_child(self) -> None:
            if self._child is None or self._child.poll() is not None:
                return
            self._child.terminate()
            try:
                self._child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._child.kill()
                self._child.wait(timeout=5)


    def main() -> None:
        win32serviceutil.HandleCommandLine(AetherGatewayService)

else:
    def main() -> None:  # pragma: no cover
        raise SystemExit("AetherGateway Windows Service can only be managed on Windows")


if __name__ == "__main__":
    main()
