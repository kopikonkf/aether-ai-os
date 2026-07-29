#!/usr/bin/env python3
"""Cross-platform supervisor for Aether Gateway, optional LiveKit worker, and AionUi.

This is intended for local/VM bring-up. Production VPS deployments should use
systemd or Docker Compose so the operating system owns restart policy.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "aether-core" / ".env"


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    if ENV_FILE.is_file():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip())
    env.setdefault("AETHER_GATEWAY_URL", f"http://127.0.0.1:{env.get('PORT', '8000')}")
    return env


def is_livekit_ready(env: dict[str, str]) -> bool:
    return bool(
        all(env.get(name) for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "AETHER_SENSE_WORKER_TOKEN"))
        and importlib.util.find_spec("livekit.agents")
        and importlib.util.find_spec("livekit.api")
    )


def command(value: str) -> list[str]:
    return shlex.split(value, posix=os.name != "nt")


def health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Aether v0.19.2 sidecar supervisor")
    parser.add_argument("--aionui-command", default=os.environ.get("AIONUI_COMMAND", ""))
    parser.add_argument("--without-aionui", action="store_true")
    parser.add_argument("--without-livekit", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    env = load_env()
    gateway_url = env["AETHER_GATEWAY_URL"].rstrip("/")
    readiness = {
        "release": "0.19.2",
        "gateway_url": gateway_url,
        "gateway_online": health(gateway_url + "/api/status"),
        "livekit_worker_ready": is_livekit_ready(env),
        "aionui_command_configured": bool(args.aionui_command),
        "one_domain_target": env.get("AETHER_PUBLIC_BASE_URL", ""),
    }
    if args.status:
        print(json.dumps(readiness, indent=2))
        return 0

    specs: list[tuple[str, list[str]]] = [
        ("aether-gateway", [sys.executable, "-m", "aether_gateway.api.server"]),
    ]
    if not args.without_livekit and readiness["livekit_worker_ready"]:
        specs.append(("aether-sense-worker", [sys.executable, "-m", "aether_gateway.browser_senses.worker", "start"]))
    if not args.without_aionui and args.aionui_command:
        specs.append(("aionui", command(args.aionui_command)))

    processes: dict[str, subprocess.Popen[bytes]] = {}
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        for name, argv in specs:
            processes[name] = subprocess.Popen(argv, cwd=ROOT, env=env, start_new_session=os.name != "nt")
        print(json.dumps({"status": "started", "processes": {name: proc.pid for name, proc in processes.items()}}, indent=2))
        while not stopping:
            for name, process in list(processes.items()):
                code = process.poll()
                if code is not None:
                    raise RuntimeError(f"{name} exited with status {code}")
            time.sleep(1)
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic() + 10
        for process in processes.values():
            remaining = max(0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
