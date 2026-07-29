from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "START_AETHER_WINDOWS_ALPHA.ps1"
MIGRATION = ROOT / "MIGRATE_EXISTING_WINDOWS_RELEASE.ps1"


def main() -> int:
    launcher = LAUNCHER.read_text(encoding="utf-8")
    migration = MIGRATION.read_text(encoding="utf-8")

    assertions = {
        "child output is not assigned as exit code": "$code = Invoke-Bringup" not in launcher,
        "exit code has a dedicated script variable": "$script:LastBringupExitCode" in launcher,
        "external process exit code is cast to int": "$exitCode = [int]$LASTEXITCODE" in launcher,
        "doctor reads dedicated exit code": "Invoke-Bringup @('doctor')\n    $code = $script:LastBringupExitCode" in launcher,
        "smoke reads dedicated exit code": "Invoke-Bringup @('smoke')\n    $code = $script:LastBringupExitCode" in launcher,
        "migration stops old gateway by pid": ".aether-windows\\gateway.pid" in migration,
        "migration does not invoke legacy launcher stop": "& $oldLauncher -Action Stop" not in migration,
    }
    failed = [name for name, passed in assertions.items() if not passed]
    for name, passed in assertions.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    if failed:
        raise SystemExit(f"Windows launcher contract failed: {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
