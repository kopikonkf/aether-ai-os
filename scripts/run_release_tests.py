#!/usr/bin/env python3
"""Cross-platform isolated test runner for Aether releases.

Each Gateway file runs in its own process and AETHER_HOME. Timed-out processes
are terminated as a process group so runtime subprocesses cannot retain pipes or
FastAPI lifespan state after pytest exits.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COUNT_RE = re.compile(r"(?P<count>\d+) (?P<kind>passed|skipped)")


def _run_isolated(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> tuple[int, str]:
    # A file sink avoids deadlocks when runtime grandchildren inherit stdout
    # after pytest itself has exited or been terminated.
    log_path = Path(tempfile.mkstemp(prefix="aether-pytest-", suffix=".log")[1])
    kwargs: dict = {"cwd": str(cwd), "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, text=True, **kwargs)
        timed_out = False
        try:
            returncode = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                proc.kill()
            else:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                returncode = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                returncode = 124
        finally:
            # A successful pytest process may leave optional runtime helpers or
            # FastAPI lifecycle children in its dedicated process group. Kill
            # only that isolated group after pytest exits so the next file sees
            # a clean environment and release verification stays deterministic.
            if os.name != "nt":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    output = log_path.read_text(encoding="utf-8", errors="replace")
    log_path.unlink(missing_ok=True)
    if timed_out:
        output += f"\nTEST PROCESS GROUP TIMED OUT AFTER {timeout} SECONDS\n"
        returncode = 124
    return returncode, output


def run_one(label: str, cwd: Path, target: str, env: dict[str, str], timeout: int) -> dict:
    home = Path(tempfile.mkdtemp(prefix=f"aether-tests-{label.replace(':', '-')}-"))
    child_env = dict(env)
    child_env["AETHER_HOME"] = str(home)
    returncode, output = _run_isolated(
        [sys.executable, "-m", "pytest", "-q", target], cwd=cwd, env=child_env, timeout=timeout,
    )
    counts = {"passed": 0, "skipped": 0}
    for match in COUNT_RE.finditer(output):
        counts[match.group("kind")] = max(counts[match.group("kind")], int(match.group("count")))
    return {"label": label, "ok": returncode == 0, "returncode": returncode, "output": output.rstrip(), **counts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--workers", type=int, default=1, help="Retained for CLI compatibility; execution is sequential")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([
        str(ROOT / "aether-core" / "src"),
        str(ROOT / "aether-tools" / "src"),
        str(ROOT / "aether-gateway" / "src"),
    ])
    jobs: list[tuple[str, Path, str, dict[str, str], int]] = [
        ("core", ROOT / "aether-core", "tests", env, args.timeout),
        ("tools", ROOT / "aether-tools", "tests", env, args.timeout),
    ]
    jobs.extend(
        (f"gateway:{test_file.name}", ROOT / "aether-gateway", str(test_file), env, args.timeout)
        for test_file in sorted((ROOT / "aether-gateway" / "tests").glob("test_*.py"))
    )
    # Sequential isolation is intentionally preferred over parallel pytest.
    # Several Gateway tests create process trees and FastAPI lifespans; running
    # them concurrently makes timing, not behavior, the dominant variable.
    results: list[dict] = []
    for job in jobs:
        item = run_one(*job)
        results.append(item)
        print(f"== {item['label']} ==", flush=True)
        print(item["output"], flush=True)
    summary = {
        "ok": all(item["ok"] for item in results),
        "passed": sum(item["passed"] for item in results),
        "skipped": sum(item["skipped"] for item in results),
        "results": [{key: value for key, value in item.items() if key != "output"} for item in results],
    }
    rendered = json.dumps(summary, indent=2)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
