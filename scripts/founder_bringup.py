#!/usr/bin/env python3
"""Cross-platform Founder Bring-Up utility for Aether OS v0.19.2."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / "aether-core" / ".env.example"
ENV_FILE = ROOT / "aether-core" / ".env"
SOURCE_PATHS = (
    ROOT / "aether-core" / "src",
    ROOT / "aether-tools" / "src",
    ROOT / "aether-gateway" / "src",
)
CLI = ROOT / "aether_cli.py"

REQUIRED_MODULES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "requests": "requests",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
}
OPTIONAL_MODULES = {
    "telegram": "python-telegram-bot",
    "mcp": "mcp",
    "gtts": "gTTS",
    "crawl4ai": "crawl4ai",
    "livekit.agents": "livekit-agents",
    "livekit.api": "livekit-api",
}


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    # Mirror python-dotenv semantics without exposing values in argv/logs.
    for key, value in _load_env_values().items():
        env.setdefault(key, value)
    current = env.get("PYTHONPATH", "")
    joined = os.pathsep.join(str(path) for path in SOURCE_PATHS)
    env["PYTHONPATH"] = joined + (os.pathsep + current if current else "")
    return env


def _load_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _replace_env_value(text: str, key: str, value: str) -> str:
    rows = text.splitlines()
    prefix = f"{key}="
    for index, row in enumerate(rows):
        if row.startswith(prefix):
            rows[index] = prefix + value
            break
    else:
        rows.append(prefix + value)
    return "\n".join(rows) + "\n"


def init_environment(args: argparse.Namespace) -> int:
    if not ENV_EXAMPLE.exists():
        raise FileNotFoundError(ENV_EXAMPLE)
    if ENV_FILE.exists() and not args.force:
        print(json.dumps({
            "status": "exists",
            "env_file": str(ENV_FILE),
            "message": "Existing .env preserved. Use --force only to recreate it.",
        }, indent=2))
        return 0

    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    configured_home = os.environ.get("AETHER_HOME") or os.environ.get("HERMES_HOME")
    if configured_home:
        aether_home = Path(configured_home).expanduser()
    elif os.name == "nt":
        aether_home = Path(r"C:\aether\home")
    else:
        aether_home = Path.home() / ".aether"
    text = _replace_env_value(text, "AETHER_HOME", str(aether_home.resolve()))
    text = _replace_env_value(text, "HOST", "127.0.0.1")
    text = _replace_env_value(text, "PORT", str(args.port))
    text = _replace_env_value(text, "AUTH_SECRET_KEY", secrets.token_urlsafe(48))
    text = _replace_env_value(text, "AETHER_OPERATOR_ID", args.operator_id)
    text = _replace_env_value(text, "AETHER_OPERATOR_TOKEN", secrets.token_urlsafe(48))
    text = _replace_env_value(text, "AETHER_BROWSER_SENSE_SECRET", secrets.token_urlsafe(48))
    text = _replace_env_value(text, "AETHER_SENSE_WORKER_TOKEN", secrets.token_urlsafe(48))
    ENV_FILE.write_text(text, encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    print(json.dumps({
        "status": "created",
        "env_file": str(ENV_FILE),
        "gateway": f"http://127.0.0.1:{args.port}",
        "next": [
            "Add exactly one model-provider API key to aether-core/.env for live cognition.",
            "Optionally enable Telegram and set TELEGRAM_BOT_TOKEN plus TELEGRAM_ALLOWED_USER_IDS.",
            "Run: python scripts/founder_bringup.py doctor",
            "Run: python scripts/founder_bringup.py smoke",
            "Configure LiveKit values for realtime voice, then run: python scripts/founder_bringup.py senses",
            "Run: python scripts/founder_bringup.py start",
        ],
    }, indent=2))
    return 0


def doctor(_: argparse.Namespace) -> int:
    values = _load_env_values()
    required = {name: _module_available(name) for name in REQUIRED_MODULES}
    optional = {name: _module_available(name) for name in OPTIONAL_MODULES}
    provider_keys = [
        name for name in ("ARZASTORE_API_KEY", "OPENAGENTIC_API_KEY", "KENARI_API_KEY", "GEMINI_API_KEY")
        if values.get(name)
    ]
    runtime_bins: dict[str, str | None] = {}
    for env_name, fallback in (
        ("AETHER_OPENCODE_BIN", "opencode"),
        ("AETHER_GEMINI_BIN", "gemini"),
        ("AETHER_CLAUDE_BIN", "claude"),
        ("AETHER_CODEX_BIN", "codex"),
    ):
        configured = values.get(env_name)
        runtime_bins[env_name] = configured or shutil.which(fallback)

    report: dict[str, Any] = {
        "release": "0.19.2",
        "python": {
            "version": sys.version.split()[0],
            "supported": sys.version_info >= (3, 11),
        },
        "source_tree": all(path.exists() for path in SOURCE_PATHS),
        "environment": {
            "exists": ENV_FILE.exists(),
            "path": str(ENV_FILE),
            "operator_token_configured": bool(values.get("AETHER_OPERATOR_TOKEN")),
            "gateway": f"http://{values.get('HOST') or '127.0.0.1'}:{values.get('PORT') or '8000'}",
        },
        "dependencies": {
            "required": required,
            "optional": optional,
            "missing_required_packages": [REQUIRED_MODULES[name] for name, ready in required.items() if not ready],
        },
        "mind": {
            "live_model_ready": bool(provider_keys),
            "configured_provider_key_names": provider_keys,
        },
        "senses": {
            "telegram_enabled": values.get("TELEGRAM_ENABLED", "false").lower() == "true",
            "telegram_token_configured": bool(values.get("TELEGRAM_BOT_TOKEN")),
            "telegram_operator_allowlist_configured": bool(values.get("TELEGRAM_ALLOWED_USER_IDS")),
            "browser_session_secret_configured": bool(values.get("AETHER_BROWSER_SENSE_SECRET")),
            "sense_worker_token_configured": bool(values.get("AETHER_SENSE_WORKER_TOKEN")),
            "browser_text": True,
            "browser_camera_keyframes": True,
            "browser_native_stt_tts_fallback": True,
            "livekit_environment_configured": all(bool(values.get(name)) for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")),
            "livekit_sdk_installed": bool(optional.get("livekit.agents") and optional.get("livekit.api")),
            "live_microphone_stt": bool(
                all(bool(values.get(name)) for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))
                and optional.get("livekit.agents")
                and optional.get("livekit.api")
                and values.get("AETHER_SENSE_WORKER_TOKEN")
            ),
            "live_tts_provider": bool(
                all(bool(values.get(name)) for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))
                and optional.get("livekit.agents")
            ),
            "camera_vision_adapter": True,
            "secure_context_required": True,
        },
        "body": {
            "bounded_local_tool_runtime": True,
            "runtime_binaries": runtime_bins,
            "live_runtime_ready": any(runtime_bins.values()),
        },
        "web_intelligence": {
            "crawl4ai_installed": optional["crawl4ai"],
            "live_source_requires_conformance": True,
        },
    }
    report["base_ready"] = bool(
        report["python"]["supported"]
        and report["source_tree"]
        and ENV_FILE.exists()
        and report["environment"]["operator_token_configured"]
        and report["senses"]["browser_session_secret_configured"]
        and report["senses"]["sense_worker_token_configured"]
        and all(required.values())
    )
    print(json.dumps(report, indent=2))
    return 0 if report["base_ready"] else 2


def _run_cli(arguments: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        cwd=ROOT,
        env=_subprocess_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def smoke(_: argparse.Namespace) -> int:
    commands = [
        ["boot"],
        ["identity"],
        ["verify"],
        ["cognitive-demo", "--text", "Founder first pulse", "--session", "founder:bringup"],
        ["sense-demo", "--text", "Aether, dengarkan saya.", "--source", "founder-microphone"],
        ["browser-sense-demo", "--text", "Aether browser senses first pulse"],
        ["telegram-demo", "--text", "Aether, status sistem.", "--chat-id", "1001", "--user-id", "1001"],
        ["action-demo", "--mode", "tool"],
        ["action-demo", "--mode", "runtime"],
        ["memory-demo"],
        ["evolution-demo"],
        ["opportunity-demo"],
        ["experiment-demo"],
    ]
    results: list[dict[str, Any]] = []
    failed = False
    for command in commands:
        completed = _run_cli(command)
        results.append({
            "command": " ".join(command),
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-1200:],
            "stderr_tail": completed.stderr[-1200:],
        })
        if completed.returncode != 0:
            failed = True
            break
    print(json.dumps({
        "status": "failed" if failed else "completed",
        "checks_completed": len(results),
        "checks_planned": len(commands),
        "results": results,
    }, indent=2))
    return 1 if failed else 0


def senses(_: argparse.Namespace) -> int:
    completed = _run_cli(["senses-status", "--gateway", f"http://{_load_env_values().get('HOST') or '127.0.0.1'}:{_load_env_values().get('PORT') or '8000'}"])
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    return completed.returncode


def start(_: argparse.Namespace) -> int:
    if not ENV_FILE.exists():
        print("Missing aether-core/.env. Run founder_bringup.py init first.", file=sys.stderr)
        return 2
    os.execve(
        sys.executable,
        [sys.executable, "-m", "aether_gateway.api.server"],
        _subprocess_env(),
    )
    return 0


def live_chat(args: argparse.Namespace) -> int:
    command = ["chat", "--text", args.text, "--session", args.session]
    if args.model:
        command.extend(["--model", args.model])
    completed = _run_cli(command)
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aether OS v0.19.2 Founder Bring-Up")
    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init", help="Create a secure local .env without overwriting existing secrets")
    init_cmd.add_argument("--operator-id", default="founder")
    init_cmd.add_argument("--port", type=int, default=8000)
    init_cmd.add_argument("--force", action="store_true")
    init_cmd.set_defaults(handler=init_environment)

    doctor_cmd = sub.add_parser("doctor", help="Report Soul/Mind/Body/Senses readiness")
    doctor_cmd.set_defaults(handler=doctor)

    smoke_cmd = sub.add_parser("smoke", help="Run the deterministic first-pulse sequence")
    smoke_cmd.set_defaults(handler=smoke)

    senses_cmd = sub.add_parser("senses", help="Inspect browser microphone/camera/speaker and LiveKit readiness")
    senses_cmd.set_defaults(handler=senses)

    start_cmd = sub.add_parser("start", help="Start Aether Gateway and optional Telegram polling")
    start_cmd.set_defaults(handler=start)

    chat_cmd = sub.add_parser("chat", help="Send one live turn through the configured model provider")
    chat_cmd.add_argument("--text", required=True)
    chat_cmd.add_argument("--session", default="founder:live")
    chat_cmd.add_argument("--model")
    chat_cmd.set_defaults(handler=live_chat)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
