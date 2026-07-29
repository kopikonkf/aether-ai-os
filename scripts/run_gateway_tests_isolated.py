#!/usr/bin/env python3
"""Run Gateway pytest modules in isolated processes.

The Gateway test suite contains composition-root and process-lifecycle tests that
must not share one Python process. This runner is the canonical local/CI entry
point until those tests are fully hermetic.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests-root", default="aether-gateway/tests")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", default="gateway-test-receipt.json")
    args = parser.parse_args()

    root = Path(args.tests_root)
    modules = sorted(root.glob("test_*.py"))
    started = time.time()
    results: list[dict[str, object]] = []
    passed_tests = 0
    skipped_tests = 0

    for module in modules:
        command = [sys.executable, "-m", "pytest", "-q", str(module)]
        try:
            completed = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=args.timeout,
                env=os.environ.copy(),
                check=False,
            )
            output = completed.stdout
            returncode = completed.returncode
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + "\nTIMEOUT"
            returncode = 124
            timed_out = True

        passed_tests += sum(int(value) for value in re.findall(r"(\d+) passed", output))
        skipped_tests += sum(int(value) for value in re.findall(r"(\d+) skipped", output))
        results.append(
            {
                "module": module.as_posix(),
                "returncode": returncode,
                "timed_out": timed_out,
                "output_tail": "\n".join(output.splitlines()[-40:]),
            }
        )
        print(f"[{returncode}] {module}", flush=True)

    failed = [result for result in results if result["returncode"] != 0]
    receipt = {
        "schema": "aether.gateway-isolated-tests.v1",
        "python": sys.version,
        "modules": len(modules),
        "tests_passed": passed_tests,
        "tests_skipped": skipped_tests,
        "failed_modules": len(failed),
        "duration_seconds": round(time.time() - started, 3),
        "results": results,
    }
    Path(args.output).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("modules", "tests_passed", "tests_skipped", "failed_modules", "duration_seconds")}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
