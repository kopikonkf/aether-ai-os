#!/usr/bin/env python3
"""Verify the frozen Aether laptop baseline from one source tree.

Gateway files run in isolated pytest processes because several tests import the
Gateway composition root and intentionally create process/lifespan state. File
isolation prevents one test module from contaminating the next while still
executing every collected test.
"""
from __future__ import annotations

import argparse
import compileall
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

import yaml


def run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(command, cwd=cwd, env=env, timeout=timeout, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "seconds": round(time.monotonic() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--gateway-timeout", type=int, default=120)
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    pythonpath = os.pathsep.join(str(root / part / "src") for part in ("aether-core", "aether-tools", "aether-gateway"))
    env = os.environ.copy()
    env["PYTHONPATH"] = pythonpath
    env.setdefault("DD_TRACE_ENABLED", "false")

    report: dict[str, Any] = {
        "schema": "aether.frozen-release-verification.v1",
        "root": str(root),
        "python": sys.version,
        "checks": [],
        "ok": True,
    }

    source_dirs = [root / part / "src" for part in ("aether-core", "aether-tools", "aether-gateway")]
    compile_ok = all(compileall.compile_dir(path, quiet=1, force=True) for path in source_dirs)
    report["checks"].append({"name": "python-compile", "ok": compile_ok})

    parse_errors: list[str] = []
    for path in sorted(root.rglob("*.json")):
        if any(part in {".venv", ".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            parse_errors.append(f"{path.relative_to(root)}: {type(exc).__name__}: {exc}")
    for suffix in ("*.yaml", "*.yml"):
        for path in sorted(root.rglob(suffix)):
            if any(part in {".venv", ".pytest_cache", "__pycache__"} for part in path.parts):
                continue
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception as exc:
                parse_errors.append(f"{path.relative_to(root)}: {type(exc).__name__}: {exc}")
    report["checks"].append({"name": "json-yaml-parse", "ok": not parse_errors, "errors": parse_errors})

    node = shutil.which("node")
    if node:
        js = root / "aether-gateway" / "src" / "aether_gateway" / "aionui_senses_console" / "app.js"
        node_check = run([node, "--check", str(js)], cwd=root, env=env, timeout=30)
        node_check["name"] = "browser-senses-javascript-syntax"
        node_check["ok"] = node_check["returncode"] == 0
        report["checks"].append(node_check)
    else:
        report["checks"].append({"name": "browser-senses-javascript-syntax", "ok": None, "reason": "node unavailable"})

    for name, target in (("core-tests", "aether-core/tests"), ("tools-tests", "aether-tools/tests")):
        check = run([sys.executable, "-m", "pytest", "-q", target], cwd=root, env=env, timeout=180)
        check["name"] = name
        check["ok"] = check["returncode"] == 0
        report["checks"].append(check)

    gateway_results: list[dict[str, Any]] = []
    for test_file in sorted((root / "aether-gateway" / "tests").glob("test_*.py")):
        rel = str(test_file.relative_to(root))
        try:
            result = run(
                [sys.executable, "-m", "pytest", "-q", rel],
                cwd=root,
                env=env,
                timeout=max(30, args.gateway_timeout),
            )
            result["ok"] = result["returncode"] == 0
        except subprocess.TimeoutExpired:
            result = {"command": [sys.executable, "-m", "pytest", "-q", rel], "returncode": None, "ok": False, "timeout": True}
        result["file"] = rel
        gateway_results.append(result)
    report["checks"].append({
        "name": "gateway-tests-isolated",
        "ok": all(item["ok"] for item in gateway_results),
        "files": len(gateway_results),
        "results": gateway_results,
    })

    required_wheels = (
        root / "dist" / "aether_core-0.19.2-py3-none-any.whl",
        root / "dist" / "aether_tools-0.3.0-py3-none-any.whl",
        root / "dist" / "aether_gateway-0.19.2-py3-none-any.whl",
    )
    report["checks"].append({
        "name": "release-wheels-present",
        "ok": all(path.is_file() and path.stat().st_size > 0 for path in required_wheels),
        "wheels": [str(path.relative_to(root)) for path in required_wheels],
    })

    report["ok"] = all(item.get("ok") is not False for item in report["checks"])
    output = args.output or root / "project-docs" / "FROZEN_BASELINE_VERIFICATION.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(output), "checks": [{"name": x["name"], "ok": x.get("ok")} for x in report["checks"]]}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
