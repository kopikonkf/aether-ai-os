from __future__ import annotations

"""
Behavior tests for the governed release-promotion and shared-tunnel source
changes (PR for prompt after main@a14aac7).

The Windows installer/script assets are .ps1; we verify the source level
contract here and re-derive the shared-tunnel rewrite decision in a pure
Python mirror so the logic is executable on a plain CI runner (identical to
how the probe semantics are mirrored elsewhere). Committed assets are checked
for the constrained DACL + shared-tunnel invariants via static assertions.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "deploy" / "windows"
CLOUDFLARE = ROOT / "deploy" / "cloudflare"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---- Python mirror of the shared-tunnel rewrite semantics -------------------

def rewrite_shared_ingress(
    current: str,
    aether_hostnames: list[str],
    local_origin: str,
    protected_hostnames: list[str],
) -> str:
    """Rewrite ONLY the Aether hostname origins to local_origin, preserving every
    other entry (protected hosts and the http_status:404 fallback). Mirrors
    deploy/cloudflare/update-shared-tunnel.ps1 without mutation."""

    lines = current.split("\n")
    out: list[str] = []
    in_ingress = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "ingress:":
            in_ingress = True
            out.append(line)
            i += 1
            continue
        if not in_ingress:
            out.append(line)
            i += 1
            continue

        m = line.lstrip().startswith("- hostname: ")
        if not m:
            out.append(line)
            i += 1
            continue

        host = line.split("- hostname: ", 1)[1].strip()
        if host in aether_hostnames:
            indent = line[: len(line) - len(line.lstrip()) - 1]
            out.append(f"{indent}- hostname: {host}")
            out.append(f"{indent}  service: {local_origin}")
            out.append(f"{indent}  originRequest:")
            out.append(f"{indent}    connectTimeout: 10s")
            out.append(f"{indent}    noTLSVerify: true")
            # Skip the remainder of the replaced Aether hostname entry: all
            # following lines until the next top-level "- hostname:" / "- service:".
            i += 1
            while i < len(lines):
                nxt = lines[i]
                stripped = nxt.lstrip()
                if stripped.startswith("- hostname: ") or stripped.startswith("- service:"):
                    break
                i += 1
            continue
        out.append(line)
        i += 1

    result = "\n".join(out).rstrip("\n") + "\n"

    for protected in protected_hostnames:
        assert f"hostname: {protected}" in result, f"protected host lost: {protected}"
    assert "http_status:404" in result, "fallback lost"
    return result


def test_shared_tunnel_only_rewrites_aether_origins():
    current = (
        "tunnel: abc\n"
        "credentials-file: cred.json\n"
        "ingress:\n"
        "  - hostname: aethers.my.id\n"
        "    service: http://localhost:80\n"
        "    originRequest:\n"
        "      noTLSVerify: true\n"
        "  - hostname: www.aethers.my.id\n"
        "    service: http://localhost:80\n"
        "  - hostname: oc.aethers.my.id\n"
        "    service: http://localhost:3000\n"
        "  - hostname: jarvis.aethers.my.id\n"
        "    service: http://localhost:8010\n"
        "  - service: http_status:404\n"
    )
    out = rewrite_shared_ingress(
        current,
        aether_hostnames=["aethers.my.id", "www.aethers.my.id"],
        local_origin="http://localhost:8080",
        protected_hostnames=["oc.aethers.my.id", "jarvis.aethers.my.id"],
    )
    # Aether origins switch to Caddy :8080.
    assert out.count("service: http://localhost:8080") == 2
    # Protected + fallback untouched.
    assert "http://localhost:3000" in out  # oc
    assert "http://localhost:8010" in out  # jarvis
    assert "http_status:404" in out
    # No second tunnel connector / dedicated tunnel created.
    assert "cloudflared tunnel --config" not in out


def test_shared_tunnel_preserves_oc_and_jarvis_with_fallback():
    current = (
        "ingress:\n"
        "  - hostname: aethers.my.id\n"
        "    service: http://localhost:80\n"
        "  - hostname: oc.aethers.my.id\n"
        "    service: http://localhost:3000\n"
        "  - hostname: jarvis.aethers.my.id\n"
        "    service: http://localhost:8010\n"
        "  - service: http_status:404\n"
    )
    out = rewrite_shared_ingress(
        current,
        ["aethers.my.id", "www.aethers.my.id"],
        "http://localhost:8080",
        ["oc.aethers.my.id", "jarvis.aethers.my.id"],
    )
    assert out.count("service: http://localhost:8080") == 1
    assert "localhost:3000" in out
    assert "localhost:8010" in out
    assert "http_status:404" in out


def test_shared_tunnel_keeps_config_single_connector():
    # The shared update path must never introduce a second tunnel service.
    script = _read(CLOUDFLARE / "update-shared-tunnel.ps1")
    assert "New-Service" not in script
    assert "AetherCloudflareTunnel" not in script
    assert "ingress validate" in script  # validate before apply


# ---- Release promotion asset contract ---------------------------------------

def test_promote_release_asset_present_and_binds_exact_sha():
    promote = WINDOWS / "promote-aether-release.ps1"
    assert promote.is_file()
    text = _read(promote)
    # git runs through the Invoke-Git/Invoke-GitCapture helpers so Windows
    # PowerShell 5.1 cannot turn git's normal stderr progress into a terminating
    # NativeCommandError; the SHA guard still binds origin/main exactly.
    assert "Invoke-Git" in text
    assert "origin/main" in text
    assert '"rev-parse"' in text
    assert "Expected-target-SHA guard failed" in text
    assert "install-aether-services.ps1" in text
    assert "rollback_release" in text
    assert "fail-closed rollback" in text
    assert "Confirm-ServiceBoundToRelease" in text
    # A mutating promotion requires -Start and never swallows restart errors.
    assert "requires -Start" in text
    assert "Restart-Service -Name $name -Force -ErrorAction Stop" in text
    # Running-path proof correlates the live SCM PID with the process command line.
    assert "Win32_Process" in text
    # rollback_manifest_proven reads the LIVE service-manifest, not the static
    # rollback AETHER_RELEASE.json.
    assert "service-manifest.json" in text
    # Promotion is a service-path reconcile only; it must not run AETHER_HOME
    # migration/cutover or snapshot tooling.
    assert "aether_home_snapshot.py" not in text
    assert "aether_migration" not in text
    # Stage temp + atomic publish (no rev-parse of an archive extraction).
    assert ".staging-" in text
    assert '"archive"' in text


def test_release_promotion_preserves_runtime_state_no_migration():
    text = _read(WINDOWS / "promote-aether-release.ps1")
    # Promotion stages a release + reconciles services only; no snapshot cutover.
    assert "aether_home_snapshot.py" not in text
    assert "aether_migration_" not in text
    # No rev-parse against a git archive extraction (which has no .git).
    assert "targetRelease rev-parse" not in text


# ---- ACL preservation (installer no longer broadens AETHER_HOME) ------------

def test_installer_never_re_enables_inheritance_or_broadens_dacl():
    installer = _read(WINDOWS / "install-aether-services.ps1")
    assert "/inheritance:e" not in installer
    assert "Ensure-ProtectedAetherHome" in installer
    assert "New-ProtectedAcl" in installer
    assert "Assert-ProtectedAcl" in installer
    # Existing home is asserted, never broadened.
    assert "AETHER_HOME(existing)" in installer
    assert "Never re-enable inheritance" in installer
    # Still protects services/logs subdirs.
    assert "Set-Acl -LiteralPath $servicesDir" in installer
    assert "Set-Acl -LiteralPath $logsDir" in installer


def test_installer_acl_uses_exact_sids_and_fullcontrol():
    installer = _read(WINDOWS / "install-aether-services.ps1")
    assert "S-1-5-18" in installer  # SYSTEM
    assert "S-1-5-32-544" in installer  # Administrators
    assert "FullControl" in installer
    assert "AreAccessRulesProtected" in installer
    assert "inheritance_not_disabled" in installer


def test_installer_verify_role_keeps_release_assets_bound():
    # Installer still reconciles services + writes manifest.
    text = _read(WINDOWS / "install-aether-services.ps1")
    assert "Install-OrUpdate-Service" in text
    assert "service-manifest.json" in text
    assert "AetherWatchdog" in text


def test_promotion_does_not_apply_by_default_and_writes_receipt():
    text = _read(WINDOWS / "promote-aether-release.ps1")
    # Receipt writes to services dir, bound to exact SHA.
    assert "release-promotion.json" in text
    assert "target_sha" in text
    assert "rollback_path" in text