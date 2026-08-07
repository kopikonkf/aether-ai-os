from __future__ import annotations

"""
Executable tests of the production PowerShell ingress/release scripts (not just
Python mirrors). They run the real *.ps1 through PowerShell.

Round-6 additions (review #4885016717):
  - update-shared-tunnel.ps1 now binds the SCM connector via
    Win32_Service.ProcessId / Win32_Process.CommandLine (exact CIM), compares
    the exact config-derived tunnel UUID, stops ONLY governed PIDs (SCM + a
    positively matched stale direct connector) while preserving unrelated
    connectors, requires elevation before mutation, and initializes every
    receipt field.
  - promote-aether-release.ps1 now wraps EVERY failure after service
    configuration mutation in one universal rollback envelope and never deletes
    the target release once services may reference it.
  - Executable fault-injection tests traverse the real success/failure branches
    through documented, env-gated observation hooks. The default (unset) path
    is always the real CIM/SCM/service-control behaviour.

These tests run the real *.ps1 through PowerShell on any runner (pwsh on Linux
CI, powershell.exe on Windows). Windows-only SCM recovery tests remain gated to
Windows hosts.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLOUDFLARE = ROOT / "deploy" / "cloudflare"
WINDOWS = ROOT / "deploy" / "windows"

TUNNEL_ID = "8f53133f-d1c8-48d6-b5bf-4dbe6f65b816"
ROLL = "a" * 40
_IS_WINDOWS = os.name == "nt"


def _host_is_windows_admin() -> bool:
    if not _IS_WINDOWS:
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# The elevation gate can only be observed to fail from a non-elevated host; an
# elevated shell legitimately passes it. On Linux the gate can never pass.
_WINDOWS_ELEVATED = _host_is_windows_admin()


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


def _write_binary_stub(stub_dir: Path) -> Path:
    """A cross-platform cloudflared stub (PowerShell script) runnable from
    Windows PS 5.1 and Linux pwsh via `& $CloudflaredPath`, so the real
    update-shared-tunnel.ps1 apply path (validate-before-replace, atomicity,
    rollback) executes on CI without a real cloudflared install."""
    stub_dir.mkdir(parents=True, exist_ok=True)
    stub = stub_dir / "cloudflared.ps1"
    stub.write_text(
        "# CI cloudflared stub\n"
        "if ($env:CLOUDFLARED_STUB_EXIT -eq '1') { exit 1 }\n"
        "exit 0\n",
        encoding="utf-8",
    )
    return stub


def _governed_cmdline(cfg: Path) -> str:
    # A governed connector command line references the exact config path and the
    # parameterized metrics endpoint. The tunnel UUID binding is config-derived
    # (read from the config file), mirroring production cloudflared behaviour.
    return (
        f"cloudflared.exe tunnel --config {cfg} run "
        "--metrics 127.0.0.1:20120"
    )


def _unrelated_cmdline() -> str:
    return "cloudflared.exe tunnel run --metrics 127.0.0.1:20999"


def _write_tunnel_observer(cfg: Path, observer_path: Path, procs) -> Path:
    observer_path.write_text(
        json.dumps(
            {
                "scm": {
                    "name": "Cloudflared",
                    "processId": 100,
                    "pathName": "C:\\cloudflared.exe",
                    "state": "Running",
                },
                "processes": procs,
            }
        ),
        encoding="utf-8",
    )
    return observer_path


def _write_start_seam(start_path: Path, body: str) -> Path:
    start_path.write_text(body, encoding="utf-8")
    return start_path


# ---------------------------------------------------------------------------
# Basic apply / dry-run / elevation-gate coverage.
# ---------------------------------------------------------------------------


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
        "-AllowNonElevated",
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
        "-AllowNonElevated",
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
    receipt = json.loads(result.stdout)
    assert receipt["applied"] is False
    assert receipt["schema"] == "aether.shared-tunnel.v4"
    assert receipt["protected_hostnames"] == ["oc.aethers.my.id", "jarvis.aethers.my.id"]
    assert receipt["connector_count_after"] is None
    assert receipt["connector_mutation_started"] is False
    assert receipt["connector_bound"] is False
    # Config-derived exact tunnel UUID is observed in the receipt.
    assert receipt["tunnel_id"] == TUNNEL_ID
    # Config file not mutated on dry run.
    assert cfg.read_text(encoding="utf-8-sig") == SAMPLE
    # Receipt candidate SHA was observed (dry-run path writes it).
    assert receipt.get("candidate_sha256")


@pytest.mark.skipif(
    POWERSHELL is None or _WINDOWS_ELEVATED,
    reason="elevation gate observable only from non-elevated hosts",
)
def test_shared_tunnel_apply_requires_elevation_by_default(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = _write_binary_stub(stub_dir)

    # -AllowNonElevated is off by default; mutation must be refused before any
    # file is written. Non-elevated sessions prove the gate on Windows; on
    # Linux the gate is reached before the platform-specific CIM path.
    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(CLOUDFLARE / "update-shared-tunnel.ps1"),
        "-TunnelConfig", str(cfg),
        "-CloudflaredPath", str(stub),
        "-AetherHome", str(tmp_path / "aether-home"),
        "-Apply",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    combined = (result.stderr or "") + (result.stdout or "")
    assert (
        "elevated" in combined.lower()
        or "principal" in combined.lower()
        or "windowsidentity" in combined.lower()
        or "not supported" in combined.lower()
    )
    # Config untouched because the elevation gate ran before mutation.
    assert cfg.read_text(encoding="utf-8-sig") == SAMPLE


# ---------------------------------------------------------------------------
# Executable fault-injection: connector binding + governed handoff + recovery.
# These traverse the real update-shared-tunnel.ps1 -Apply/-Start branches on any
# runner through the documented observation seams. The default (unset) path
# still uses real CIM/SCM.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_shared_tunnel_start_success_binding_and_stale_direct_handoff(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    stub = _write_binary_stub(tmp_path / "bin")

    governed = _governed_cmdline(cfg)
    observer = tmp_path / "observer-before.json"
    _write_tunnel_observer(
        cfg, observer,
        [
            {"processId": 100, "commandLine": governed},  # SCM-managed governed
            {"processId": 200, "commandLine": governed},  # stale direct governed
            {"processId": 300, "commandLine": _unrelated_cmdline()},  # unrelated
        ],
    )

    start_seam = _write_start_seam(
        tmp_path / "start.ps1",
        # Rewrite the observer to the post-handoff state: only the SCM governed
        # process and the unrelated connector remain.
        (
            "$obs = @{ scm = @{ name='Cloudflared'; processId=100; "
            "pathName='C:\\cloudflared.exe'; state='Running' }; processes = @("
            f"@{{ processId=100; commandLine='{governed}' }}, "
            f"@{{ processId=300; commandLine='{_unrelated_cmdline()}' }}"
            ") } | ConvertTo-Json -Depth 6\n"
            f"Set-Content -LiteralPath '{observer}' -Value $obs\n"
            "exit 0\n"
        ),
    )

    env = dict(os.environ)
    env["CLOUDFLARED_STUB_EXIT"] = "0"
    env["AETHER_TUNNEL_OBSERVER_JSON"] = str(observer)
    env["AETHER_TUNNEL_START_CMD"] = str(start_seam)
    env["AETHER_TUNNEL_READINESS"] = "true"

    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(CLOUDFLARE / "update-shared-tunnel.ps1"),
        "-TunnelConfig", str(cfg),
        "-CloudflaredPath", str(stub),
        "-AetherHome", str(tmp_path / "aether-home"),
        "-AllowNonElevated",
        "-Apply", "-Start",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    assert result.returncode == 0, result.stderr

    receipt = json.loads(result.stdout)
    assert receipt["applied"] is True
    assert receipt["connector_mutation_started"] is True
    assert receipt["connector_bound"] is True
    assert receipt["connector_count_after"] == 1
    assert receipt["connector_service_pid"] == 100
    # Governed stop set: SCM PID + positively matched stale direct PID.
    assert sorted(receipt["governed_pids_before"]) == [100, 200]
    # Unrelated connector preserved.
    assert receipt["preserved_pids_before"] == [300]
    assert receipt["connector_readiness"] is True
    assert receipt["recovery_proven"] is None
    # Config did change to :8080.
    got = cfg.read_text(encoding="utf-8-sig")
    service_lines = [ln.strip() for ln in got.splitlines() if ln.strip().startswith("service:")]
    assert service_lines.count("service: http://localhost:8080") == 2
    assert "service: http://localhost:80" not in service_lines


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_shared_tunnel_start_restart_failure_restores_config_recovery_unproven(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    stub = _write_binary_stub(tmp_path / "bin")

    governed = _governed_cmdline(cfg)
    observer = tmp_path / "observer.json"
    _write_tunnel_observer(
        cfg, observer,
        [
            {"processId": 100, "commandLine": governed},
            {"processId": 200, "commandLine": governed},
        ],
    )
    start_seam = _write_start_seam(tmp_path / "start.ps1", "exit 1\n")

    env = dict(os.environ)
    env["CLOUDFLARED_STUB_EXIT"] = "0"
    env["AETHER_TUNNEL_OBSERVER_JSON"] = str(observer)
    env["AETHER_TUNNEL_START_CMD"] = str(start_seam)
    env["AETHER_TUNNEL_READINESS"] = "false"

    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(CLOUDFLARE / "update-shared-tunnel.ps1"),
        "-TunnelConfig", str(cfg),
        "-CloudflaredPath", str(stub),
        "-AetherHome", str(tmp_path / "aether-home"),
        "-AllowNonElevated",
        "-Apply", "-Start",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    # SCM start failed after live replace -> fail closed: config restored,
    # exit non-zero, recovery NOT proven because the connector reconcile could
    # not be observed as healthy.
    assert result.returncode != 0
    assert cfg.read_text(encoding="utf-8-sig") == SAMPLE

    receipt_file = tmp_path / "aether-home" / "runtime" / "ingress" / "shared-tunnel-receipt.json"
    assert receipt_file.is_file()
    receipt = json.loads(receipt_file.read_text(encoding="utf-8-sig"))
    assert receipt["rollback_triggered"] is True
    assert receipt["connector_mutation_started"] is True
    assert receipt["recovery_proven"] is False
    assert receipt.get("error")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_shared_tunnel_start_readiness_failure_recovers_connector(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    stub = _write_binary_stub(tmp_path / "bin")

    governed = _governed_cmdline(cfg)
    observer = tmp_path / "observer.json"
    _write_tunnel_observer(
        cfg, observer,
        [
            {"processId": 100, "commandLine": governed},
            {"processId": 200, "commandLine": governed},
        ],
    )
    counter = tmp_path / "start-counter.txt"
    # First invocation (promote phase) simulates a connector that comes up but
    # fails the readiness probe; the restore pass rewrites the observer to the
    # post-handoff state and reports readiness so recovery is observed as real.
    start_seam = _write_start_seam(
        tmp_path / "start.ps1",
        (
            "$f = '" + str(counter) + "'\n"
            "$n = 0\n"
            "if (Test-Path -LiteralPath $f) { $n = [int](Get-Content -LiteralPath $f) }\n"
            "$n++\n"
            "Set-Content -LiteralPath $f -Value $n\n"
            "$obs = @{ scm = @{ name='Cloudflared'; processId=100; "
            "pathName='C:\\cloudflared.exe'; state='Running' }; processes = @("
            f"@{{ processId=100; commandLine='{governed}' }}, "
            f"@{{ processId=300; commandLine='{_unrelated_cmdline()}' }}"
            ") } | ConvertTo-Json -Depth 6\n"
            f"Set-Content -LiteralPath '{observer}' -Value $obs\n"
            "if ($n -eq 1) { $env:AETHER_TUNNEL_READINESS = 'false' } "
            "else { $env:AETHER_TUNNEL_READINESS = 'true' }\n"
            "exit 0\n"
        ),
    )

    env = dict(os.environ)
    env["CLOUDFLARED_STUB_EXIT"] = "0"
    env["AETHER_TUNNEL_OBSERVER_JSON"] = str(observer)
    env["AETHER_TUNNEL_START_CMD"] = str(start_seam)

    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(CLOUDFLARE / "update-shared-tunnel.ps1"),
        "-TunnelConfig", str(cfg),
        "-CloudflaredPath", str(stub),
        "-AetherHome", str(tmp_path / "aether-home"),
        "-AllowNonElevated",
        "-Apply", "-Start",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    # Promote-phase readiness failed after live replace -> config restored and
    # the connector was reconciled back to a single governed process whose
    # readiness was observed, so recovery_proven is TRUE.
    assert result.returncode != 0
    assert cfg.read_text(encoding="utf-8-sig") == SAMPLE

    receipt_file = tmp_path / "aether-home" / "runtime" / "ingress" / "shared-tunnel-receipt.json"
    assert receipt_file.is_file()
    receipt = json.loads(receipt_file.read_text(encoding="utf-8-sig"))
    assert receipt["rollback_triggered"] is True
    assert receipt["recovery_proven"] is True


@pytest.mark.skipif(
    POWERSHELL is None or not _IS_WINDOWS,
    reason="connector -Start recovery needs Windows SCM",
)
def test_shared_tunnel_start_missing_service_rolls_back_config(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = _write_binary_stub(stub_dir)

    env = dict(os.environ)
    env["CLOUDFLARED_STUB_EXIT"] = "0"  # validate would succeed

    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(CLOUDFLARE / "update-shared-tunnel.ps1"),
        "-TunnelConfig", str(cfg),
        "-CloudflaredPath", str(stub),
        "-AetherHome", str(tmp_path / "aether-home"),
        "-ConnectorServiceName", "AetherTestMissingSvc",
        "-AllowNonElevated",
        "-Apply", "-Start",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    # The connector service is missing -> fail after live replace -> the script
    # must restore the backup config and exit non-zero (fail closed).
    assert result.returncode != 0
    assert cfg.read_text(encoding="utf-8-sig") == SAMPLE


@pytest.mark.skipif(
    POWERSHELL is None or not _IS_WINDOWS,
    reason="connector -Start recovery needs Windows SCM",
)
def test_shared_tunnel_start_asserts_single_connector_receipt(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = _write_binary_stub(stub_dir)
    aether_home = tmp_path / "aether-home"

    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(CLOUDFLARE / "update-shared-tunnel.ps1"),
        "-TunnelConfig", str(cfg),
        "-CloudflaredPath", str(stub),
        "-AetherHome", str(aether_home),
        "-ConnectorServiceName", "AetherTestMissingSvc",
        "-AllowNonElevated",
        "-Apply", "-Start",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode != 0
    # Fail-closed: live config must be restored even though -Start failed.
    assert cfg.read_text(encoding="utf-8-sig") == SAMPLE
    # The observation-derived failure receipt is written to AETHER_HOME.
    receipt_file = aether_home / "runtime" / "ingress" / "shared-tunnel-receipt.json"
    assert receipt_file.is_file(), "failure receipt not written"
    receipt = json.loads(receipt_file.read_text(encoding="utf-8-sig"))
    assert receipt["schema"] == "aether.shared-tunnel.v4"
    assert receipt["rollback_triggered"] is True
    assert receipt.get("error")


# ---------------------------------------------------------------------------
# Promotion: guard + provenance + universal rollback (executable fault
# injection through the documented AETHER_PROMO_* observation hooks).
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return result.stdout.strip()


def _make_promotion_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "ci@test", cwd=repo)
    _git("config", "user.name", "CI", cwd=repo)
    (repo / "README.md").write_text("aether promotion fixture\n", encoding="utf-8")
    # The target release extracted by `git archive` must carry the installer,
    # exactly as the real production repo does (universal-rollback preflight).
    installer = repo / "deploy" / "windows" / "install-aether-services.ps1"
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_text("# installer stub\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "fixture", cwd=repo)
    sha = _git("rev-parse", "HEAD", cwd=repo)
    remote = tmp_path / "remote.git"
    _git("clone", "-q", "--bare", str(repo), str(remote), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=repo)
    _git("push", "-q", "origin", "main", cwd=repo)
    return repo, sha


def _make_rollback_release(releases: Path) -> None:
    roll = releases / ROLL
    (roll / "deploy" / "windows").mkdir(parents=True, exist_ok=True)
    (roll / "deploy" / "windows" / "install-aether-services.ps1").write_text(
        "# rollback installer stub\n", encoding="utf-8"
    )
    (roll / "AETHER_RELEASE.json").write_text(
        json.dumps({"schema": "aether.release.v1", "target_sha": ROLL}),
        encoding="utf-8",
    )


def _promotion_env(install_seam: Path | None = None, health_seam: Path | None = None,
                   service_seam: Path | None = None) -> dict:
    env = dict(os.environ)
    if install_seam is not None:
        env["AETHER_PROMO_INSTALL_CMD"] = str(install_seam)
    if health_seam is not None:
        env["AETHER_PROMO_HEALTH_CMD"] = str(health_seam)
    if service_seam is not None:
        env["AETHER_PROMO_SERVICE_CMD"] = str(service_seam)
    return env


def _write_install_seam(tmp_path: Path, mode: str, log: Path, health_file: Path) -> Path:
    seam = tmp_path / "install.ps1"
    body = (
        "param([string]$ReleasePath, [string]$TargetSha, [string]$AetherHome, "
        "[string]$HostAddress, [string]$Port, [string]$Phase)\n"
        "Add-Content -Path '@LOG@' -Value \"$Phase|$ReleasePath\"\n"
        "if ($Phase -eq 'rollback') { Set-Content -LiteralPath '@HEALTH@' -Value 'true' }\n"
        "if ($Phase -eq 'promote' -and '@MODE@' -in @('target-fail','both-fail')) { exit 1 }\n"
        "if ($Phase -eq 'rollback' -and '@MODE@' -in @('rollback-fail','both-fail')) { exit 1 }\n"
        "exit 0\n"
    )
    body = (
        body.replace("@LOG@", str(log))
        .replace("@HEALTH@", str(health_file))
        .replace("@MODE@", mode)
    )
    seam.write_text(body, encoding="utf-8")
    return seam


def _write_health_seam(health_file: Path) -> Path:
    seam = Path(str(health_file) + ".health.ps1")
    body = (
        "if (Test-Path -LiteralPath '@HEALTH@') "
        "{ (Get-Content -LiteralPath '@HEALTH@').Trim() } "
        "else { 'false' }\n"
    ).replace("@HEALTH@", str(health_file))
    seam.write_text(body, encoding="utf-8")
    return seam


def _write_service_seam(tmp_path: Path, target_release: str, fail_target: bool) -> Path:
    seam = tmp_path / "service.ps1"
    body = "param([string]$ReleasePath)\n$running = $true\n"
    if fail_target:
        body += f"if ($ReleasePath -eq '{target_release}') {{ $running = $false }}\n"
    body += (
        "@(\n"
        "  @{ name='AetherGateway'; running=$running; path=$ReleasePath },\n"
        "  @{ name='AetherWatchdog'; running=$running; path=$ReleasePath }\n"
        ") | ConvertTo-Json -Compress\n"
    )
    seam.write_text(body, encoding="utf-8")
    return seam


def _promote_cmd(repo: Path, aether_home: Path, releases: Path, sha: str) -> list[str]:
    return [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(WINDOWS / "promote-aether-release.ps1"),
        "-RepoPath", str(repo),
        "-AetherHome", str(aether_home),
        "-ReleasesRoot", str(releases),
        "-RollbackRelease", ROLL,
        "-ExpectedTargetSha", sha,
        "-AllowNonElevated",
        "-SkipAclCheck",
        "-Start",
        "-HealthAttempts", "1",
        "-HealthTimeoutSeconds", "1",
    ]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_release_promotion_script_executes_and_requires_admin(tmp_path: Path):
    repo = tmp_path / "not-a-repo"
    repo.mkdir()
    sha = "a" * 40
    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(WINDOWS / "promote-aether-release.ps1"),
        "-RepoPath", str(repo),
        "-AetherHome", str(tmp_path / "aether-home"),
        "-ReleasesRoot", str(tmp_path / "releases"),
        "-ExpectedTargetSha", sha,
    ]
    # The script must run and throw early. On Windows it fails the admin guard
    # ("Run this promotion from an elevated..." or "Windows Principal"); on
    # Linux it fails the WindowsPrincipal check. Both prove the guard is real
    # and executable (not just static text).
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    combined = (result.stderr or "") + (result.stdout or "")
    assert (
        "not found" in combined.lower()
        or "elevated" in combined.lower()
        or "principal" in combined.lower()
        or "windowsidentity" in combined.lower()
    )


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_release_promotion_requires_expected_target_sha(tmp_path: Path):
    repo = tmp_path / "not-a-repo"
    repo.mkdir()
    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(WINDOWS / "promote-aether-release.ps1"),
        "-RepoPath", str(repo),
        "-AetherHome", str(tmp_path / "aether-home"),
        "-ReleasesRoot", str(tmp_path / "releases"),
    ]
    # -ExpectedTargetSha is mandatory; omitting it must be rejected by the
    # parameter binder before any logic runs (on every platform).
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    combined = (result.stderr or "") + (result.stdout or "")
    assert "expectedtargetsha" in combined.lower() or "mandatory" in combined.lower()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_release_promotion_success_publishes_and_proves(tmp_path: Path):
    repo, sha = _make_promotion_repo(tmp_path)
    aether_home = tmp_path / "aether-home"
    aether_home.mkdir()
    releases = tmp_path / "releases"
    _make_rollback_release(releases)

    health_file = tmp_path / "health.txt"
    health_file.write_text("true", encoding="utf-8")
    install_seam = _write_install_seam(tmp_path, "ok", tmp_path / "install.log", health_file)
    health_seam = _write_health_seam(health_file)
    service_seam = _write_service_seam(tmp_path, str(releases / sha), fail_target=False)

    result = subprocess.run(
        _promote_cmd(repo, aether_home, releases, sha),
        capture_output=True, text=True, timeout=120,
        env=_promotion_env(install_seam, health_seam, service_seam),
    )
    assert result.returncode == 0, result.stderr

    receipt = json.loads((aether_home / "services" / "release-promotion.json").read_text(encoding="utf-8-sig"))
    assert receipt["success"] is True
    assert receipt["target_sha"] == sha
    assert receipt["published_this_run"] is True
    assert receipt["running_paths_proven"] is True
    assert receipt["reconciled"] == ["AetherGateway", "AetherWatchdog"]
    # Target release was published and never removed.
    assert (releases / sha / "AETHER_RELEASE.json").is_file()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_release_promotion_reuses_matching_existing_release(tmp_path: Path):
    repo, sha = _make_promotion_repo(tmp_path)
    aether_home = tmp_path / "aether-home"
    aether_home.mkdir()
    releases = tmp_path / "releases"
    _make_rollback_release(releases)

    # Pre-existing published release with matching manifest SHA.
    target = releases / sha
    target.mkdir(parents=True)
    (target / "AETHER_RELEASE.json").write_text(
        json.dumps({"schema": "aether.release.v1", "target_sha": sha}), encoding="utf-8"
    )

    health_file = tmp_path / "health.txt"
    health_file.write_text("true", encoding="utf-8")
    install_seam = _write_install_seam(tmp_path, "ok", tmp_path / "install.log", health_file)
    health_seam = _write_health_seam(health_file)
    service_seam = _write_service_seam(tmp_path, str(target), fail_target=False)

    result = subprocess.run(
        _promote_cmd(repo, aether_home, releases, sha),
        capture_output=True, text=True, timeout=120,
        env=_promotion_env(install_seam, health_seam, service_seam),
    )
    assert result.returncode == 0, result.stderr

    receipt = json.loads((aether_home / "services" / "release-promotion.json").read_text(encoding="utf-8-sig"))
    assert receipt["success"] is True
    assert receipt["reused_existing"] is True
    assert receipt["published_this_run"] is False


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_release_promotion_target_installer_failure_universal_rollback(tmp_path: Path):
    repo, sha = _make_promotion_repo(tmp_path)
    aether_home = tmp_path / "aether-home"
    aether_home.mkdir()
    releases = tmp_path / "releases"
    _make_rollback_release(releases)

    health_file = tmp_path / "health.txt"
    install_seam = _write_install_seam(tmp_path, "target-fail", tmp_path / "install.log", health_file)
    health_seam = _write_health_seam(health_file)
    service_seam = _write_service_seam(tmp_path, str(releases / sha), fail_target=False)

    result = subprocess.run(
        _promote_cmd(repo, aether_home, releases, sha),
        capture_output=True, text=True, timeout=120,
        env=_promotion_env(install_seam, health_seam, service_seam),
    )
    assert result.returncode != 0

    # The failed promotion triggered a universal rollback that was proven.
    receipt = json.loads(
        (aether_home / "services" / "release-promotion-failure.json").read_text(encoding="utf-8-sig")
    )
    assert receipt["success"] is False
    assert receipt["service_mutation_started"] is True
    assert receipt["rollback_triggered"] is True
    assert receipt["rollback_proven"] is True
    assert receipt["rollback_running_path_proven"] is True
    assert receipt["rollback_manifest_proven"] is True
    assert receipt["partial_publish_removed"] is False
    # The target release MUST NOT be deleted once services may reference it.
    assert (releases / sha / "AETHER_RELEASE.json").is_file()
    # Both phases were attempted by the installer hook.
    phases = (tmp_path / "install.log").read_text(encoding="utf-8-sig")
    assert "promote|" in phases
    assert "rollback|" in phases


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_release_promotion_rollback_failure_keeps_target_and_reports_false(tmp_path: Path):
    repo, sha = _make_promotion_repo(tmp_path)
    aether_home = tmp_path / "aether-home"
    aether_home.mkdir()
    releases = tmp_path / "releases"
    _make_rollback_release(releases)

    health_file = tmp_path / "health.txt"
    install_seam = _write_install_seam(tmp_path, "both-fail", tmp_path / "install.log", health_file)
    health_seam = _write_health_seam(health_file)
    service_seam = _write_service_seam(tmp_path, str(releases / sha), fail_target=False)

    result = subprocess.run(
        _promote_cmd(repo, aether_home, releases, sha),
        capture_output=True, text=True, timeout=120,
        env=_promotion_env(install_seam, health_seam, service_seam),
    )
    assert result.returncode != 0

    receipt = json.loads(
        (aether_home / "services" / "release-promotion-failure.json").read_text(encoding="utf-8-sig")
    )
    assert receipt["rollback_triggered"] is True
    assert receipt["rollback_proven"] is False
    assert receipt.get("rollback_error")
    # Never delete the target release after service mutation.
    assert (releases / sha / "AETHER_RELEASE.json").is_file()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_release_promotion_health_failure_rolls_back_proven(tmp_path: Path):
    repo, sha = _make_promotion_repo(tmp_path)
    aether_home = tmp_path / "aether-home"
    aether_home.mkdir()
    releases = tmp_path / "releases"
    _make_rollback_release(releases)

    # Installer succeeds on both phases; the health file stays 'false' after
    # the target install (promote-phase readiness probe fails) and the rollback
    # install flips it to 'true' so the rollback itself is proven healthy.
    health_file = tmp_path / "health.txt"
    health_file.write_text("false", encoding="utf-8")
    install_seam = _write_install_seam(tmp_path, "ok", tmp_path / "install.log", health_file)
    health_seam = _write_health_seam(health_file)
    service_seam = _write_service_seam(tmp_path, str(releases / sha), fail_target=False)

    result = subprocess.run(
        _promote_cmd(repo, aether_home, releases, sha),
        capture_output=True, text=True, timeout=120,
        env=_promotion_env(install_seam, health_seam, service_seam),
    )
    assert result.returncode != 0

    receipt = json.loads(
        (aether_home / "services" / "release-promotion-failure.json").read_text(encoding="utf-8-sig")
    )
    assert receipt["running_paths_proven"] is True
    assert receipt["rollback_triggered"] is True
    assert receipt["rollback_proven"] is True
    assert receipt["rollback_reason"] == "health_failure_after_promote"
    assert (releases / sha / "AETHER_RELEASE.json").is_file()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")
def test_release_promotion_running_path_failure_rolls_back_proven(tmp_path: Path):
    repo, sha = _make_promotion_repo(tmp_path)
    aether_home = tmp_path / "aether-home"
    aether_home.mkdir()
    releases = tmp_path / "releases"
    _make_rollback_release(releases)

    health_file = tmp_path / "health.txt"
    health_file.write_text("true", encoding="utf-8")
    install_seam = _write_install_seam(tmp_path, "ok", tmp_path / "install.log", health_file)
    health_seam = _write_health_seam(health_file)
    # The target running-path assertion fails (services not bound to the target
    # release), forcing the universal rollback envelope.
    service_seam = _write_service_seam(tmp_path, str(releases / sha), fail_target=True)

    result = subprocess.run(
        _promote_cmd(repo, aether_home, releases, sha),
        capture_output=True, text=True, timeout=120,
        env=_promotion_env(install_seam, health_seam, service_seam),
    )
    assert result.returncode != 0

    receipt = json.loads(
        (aether_home / "services" / "release-promotion-failure.json").read_text(encoding="utf-8-sig")
    )
    assert receipt["rollback_triggered"] is True
    assert receipt["rollback_proven"] is True
    assert receipt["rollback_running_path_proven"] is True
    assert receipt["rollback_reason"] == "post_mutation_failure"
    assert (releases / sha / "AETHER_RELEASE.json").is_file()
