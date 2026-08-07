from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "deploy" / "cloudflare" / "probe-cloudflare-ingress.ps1"


def find_powershell() -> str | None:
    for exe in ("pwsh", "powershell"):
        found = shutil.which(exe)
        if found:
            return found
    return None


def extract_function(src: str, name: str) -> str:
    m = re.search(
        rf"function {re.escape(name)}\s*\{{(.*?)\n\}}",
        src,
        flags=re.S,
    )
    if not m:
        raise AssertionError(f"function {name} not found in probe")
    return "function " + name + " {\n" + m.group(1) + "\n}\n"


CASES = [
    # status, location, expected_protected
    (302, "https://aether-team.cloudflareaccess.com/cdn-cgi/access/login?x=1", True),
    (302, "https://app.aethers.my.id/some/redirect", False),
    (307, "https://example.org/elsewhere", False),
    (401, "", True),
    (403, "", True),
    (200, "", False),
    (500, "", False),
    (302, "", False),
]


@pytest.mark.skipif(find_powershell() is None, reason="PowerShell not available")
def test_probe_access_protection_behavior_rejects_unrelated_redirect():
    ps = find_powershell()
    src = PROBE.read_text(encoding="utf-8")
    fn = extract_function(src, "Test-AetherAccessProtected")

    lines = [fn, r"$fail = @()"]
    for idx, (code, location, expected) in enumerate(CASES):
        escaped = location.replace("'", "''")
        bool_lit = "$true" if expected else "$false"
        lines.append(
            rf"$got = Test-AetherAccessProtected -StatusCode {code} -Location '{escaped}'"
        )
        lines.append(
            rf"if ($got -ne {bool_lit}) {{ $fail += 'case{idx}: code={code} expect={expected} got=' + $got }}"
        )
    lines.append(r'if ($fail.Count -gt 0) { Write-Error ($fail -join ", "); exit 1 }')
    lines.append(r'Write-Output "probe classification OK"')

    script = "\n".join(lines)
    tmp = ROOT / "tests" / "_probe_behavior.ps1"
    tmp.write_text(script, encoding="utf-8")

    proc = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    tmp.unlink(missing_ok=True)
    assert proc.returncode == 0, f"PS failed rc={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"


@pytest.mark.skipif(find_powershell() is None, reason="PowerShell not available")
def test_install_acl_requires_both_sids_with_fullcontrol():
    install = (ROOT / "deploy" / "cloudflare" / "install-cloudflare-ingress.ps1").read_text(encoding="utf-8")
    assert "required_sid_missing" in install
    assert "required_rule_incomplete" in install
    assert "S-1-5-18" in install
    assert "S-1-5-32-544" in install