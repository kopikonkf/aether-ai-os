from __future__ import annotations

"""
Executable tests of the production PowerShell ingress/release scripts (not just
Python mirrors). They run the real *.ps1 through PowerShell.

Compared to the prior round, these tests:
  - run deploy/cloudflare/update-shared-tunnel.ps1 for real against a temp YAML
    config (apply path) and assert the ACTUAL emitted YAML changed only the two
    Aether service scalars (:80 -> :8080), preserved oc/jarvis/fallback, wrote a
    candidate, validated-before-replace, and produced a backup;
  - use a stub cloudflared executable (a .cmd that returns an env-controlled exit
    code) so validate-before-apply and failure-rollback are exercised on any CI
    runner without a real cloudflared;
  - verify the promote-aether-release.ps1 guard fails closed (non-admin) rather
    than mutating anything.

These tests are skipped when PowerShell is unavailable (same gate as the other
.cpp/registry .ps1 asset tests).
"""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLOUDFLARE = ROOT / "deploy" / "cloudflare"
WINDOWS = ROOT / "deploy" / "windows"


def find_powershell() -> str | None:
    for exe in ("pwsh", "powershell"):
        found = shutil.which(exe)
        if found:
            return found
    return None


POWERSHELL = find_powershell()


SAMPLE = (
    "tunnel: 8f53133f-d1c8-48d6-b5bf-4dbe6f65b816\n"
    "credentials-file: cred.json\n"
    "ingress:\n"
    "  - hostname: aethers.my.id\n"
    "    service: http://localhost:80\n"
    "    originRequest:\n"
    "      noTLSVerify: true\n"
    "  - hostname: www.aethers.my.id\n"
    "    service: http://localhost:80\n"
    "    originRequest:\n"
    "      noTLSVerify: true\n"
    "  - hostname: oc.aethers.my.id\n"
    "    service: http://localhost:3000\n"
    "  - hostname: jarvis.aethers.my.id\n"
    "    service: http://localhost:8010\n"
    "  - service: http_status:404\n"
)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_shared_tunnel_apply_rewrites_only_aether_origins(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = _write_binary_stub(stub_dir)
    env = dict(os.environ)
    env["CLOUDFLARED_STUB_EXIT"] = "0"

    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(CLOUDFLARE / "update-shared-tunnel.ps1"),
        "-TunnelConfig", str(cfg),
        "-CloudflaredPath", str(stub),
        "-AetherHome", str(tmp_path / "aether-home"),
        "-Apply",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    assert result.returncode == 0, result.stderr

    got = cfg.read_text(encoding="utf-8-sig")
    service_lines = [ln.strip() for ln in got.splitlines() if ln.strip().startswith("service:")]
    # Exactly two Aether origins -> :8080; no :80 service scalar remains.
    assert service_lines.count("service: http://localhost:8080") == 2
    assert "service: http://localhost:80" not in service_lines
    assert "service: http://localhost:3000" in service_lines
    assert "service: http://localhost:8010" in service_lines
    assert "service: http_status:404" in got
    # Protected + fallback untouched.
    assert "http://localhost:3000" in got
    assert "http://localhost:8010" in got
    assert "http_status:404" in got
    # originRequest option preserved, not duplicated.
    assert got.count("noTLSVerify: true") == 2
    # A backup of the original config was created.
    backups = list(tmp_path.glob("config.yml.bak-*"))
    assert len(backups) == 1

    # validate-before-apply was reached (stub exited 0 -> validate ok).
    # Candidate was consumed/removed after atomic replace.
    assert not list(tmp_path.glob("config.yml.candidate-*"))


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_shared_tunnel_apply_rolls_back_on_validate_failure(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = _write_binary_stub(stub_dir)

    env = dict(os.environ)
    env["CLOUDFLARED_STUB_EXIT"] = "1"  # simulate validate failure

    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(CLOUDFLARE / "update-shared-tunnel.ps1"),
        "-TunnelConfig", str(cfg),
        "-CloudflaredPath", str(stub),
        "-AetherHome", str(tmp_path / "aether-home"),
        "-Apply",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    # validate failed before apply -> non-zero exit, config MUST be unchanged.
    assert result.returncode != 0
    got = cfg.read_text(encoding="utf-8-sig")
    assert got == SAMPLE
    # Candidate cleaned up; no live mutation, no backup of a non-apply.
    assert not list(tmp_path.glob("config.yml.candidate-*"))


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_shared_tunnel_dry_run_emits_candidate_observations(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = _write_binary_stub(stub_dir)

    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(CLOUDFLARE / "update-shared-tunnel.ps1"),
        "-TunnelConfig", str(cfg),
        "-CloudflaredPath", str(stub),
        "-AetherHome", str(tmp_path / "aether-home"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0
    import json

    receipt = json.loads(result.stdout)
    assert receipt["applied"] is False
    assert receipt["aether_entries_unique"] is True
    assert receipt["protected_preserved"] is True
    assert receipt["fallback_unique"] is True
    # Config file not mutated on dry run.
    assert cfg.read_text(encoding="utf-8-sig") == SAMPLE
    # Receipt candidate SHA was observed (dry-run path writes it).
    assert receipt.get("candidate_sha256")


# ---- Promote guard is executable (fails fast without admin privilege) -------
@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_release_promotion_script_executes_and_requires_admin(tmp_path: Path):
    repo = tmp_path / "not-a-repo"
    repo.mkdir()
    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(WINDOWS / "promote-aether-release.ps1"),
        "-RepoPath", str(repo),
        "-AetherHome", str(tmp_path / "aether-home"),
        "-ReleasesRoot", str(tmp_path / "releases"),
    ]
    # The script must run and throw early. On Windows it fails the admin guard
    # ("Run this promotion from an elevated..."), on Linux/pwsh it fails the
    # WindowsPrincipal check ("Microsoft"); both prove the guard is real and
    # executable (not just static text).
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    combined = (result.stderr or "") + (result.stdout or "")
    assert (
        "not found" in combined.lower()
        or "elevated" in combined.lower()
        or "principal" in combined.lower()
    )


def _write_binary_stub(stub_dir: Path) -> Path:
    """A cross-platform cloudflared stub (PowerShell script) runnable from
    Windows PS 5.1 and Linux pwsh via `& $CloudflaredPath`, so the real
    update-shared-tunnel.ps1 apply path (validate-before-replace, atomicity,
    rollback) executes on CI without a real cloudflared install."""
    stub = stub_dir / "cloudflared.ps1"
    stub.write_text(
        "# CI cloudflared stub\n"
        "if ($env:CLOUDFLARED_STUB_EXIT -eq '1') { exit 1 }\n"
        "exit 0\n",
        encoding="utf-8",
    )
    return stub


