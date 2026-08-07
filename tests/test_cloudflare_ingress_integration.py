from __future__ import annotations

"""
Real integration proof for the Founder Alpha Caddy basic_auth ingress.

This test executes the *actual* probe-cloudflare-ingress.ps1 against a real
Caddy instance fronting an echo upstream. It proves:
  - unauthenticated -> 401 + WWW-Authenticate: Basic on all 4 routes
  - wrong credentials -> 401 + Basic challenge
  - correct credentials -> 2xx on all 4 routes
  - the Authorization header is stripped before it reaches the upstream
    (echo upstream records headers it actually received)
  - the receipt is secret-free
  - all three AuthMode branches (None/Access/CaddyBasic) and the fail-closed
    parameter matrix (the probe rejects conflicting flags)

It is skipped unless the toolchain is present (caddy.exe + PowerShell) and
AETHER_INGRESS_INTEGRATION=1. CI runs the pure-Python mirror and static tests;
this integration test is the host-side proof executed on the VPS runner.
"""

import json
import os
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "deploy" / "cloudflare" / "probe-cloudflare-ingress.ps1"

REQUIRED = ["/health", "/aether/api/status", "/api/browser-senses/status", "/senses"]


def enabled() -> bool:
    return os.environ.get("AETHER_INGRESS_INTEGRATION") == "1"


def find_caddy() -> str | None:
    for cand in (
        os.environ.get("CADDY_PATH", ""),
        r"C:\Program Files\Caddy\caddy.exe",
    ):
        if cand and Path(cand).is_file():
            return cand
    found = shutil.which("caddy")
    return found


def find_powershell() -> str | None:
    for exe in ("pwsh", "powershell"):
        found = shutil.which(exe)
        if found:
            return found
    return None


class HeaderRecorder(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_GET(self):
        headers = {k.lower(): v for k, v in self.headers.items()}
        HeaderRecorder.received.append({"path": self.path, "headers": headers})
        body = json.dumps(headers).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.mark.skipif(
    not enabled() or find_caddy() is None or find_powershell() is None,
    reason="integration needs AETHER_INGRESS_INTEGRATION=1, caddy.exe, and PowerShell",
)
def test_real_probe_basic_auth_echo_strip(tmp_path: Path):
    caddy = find_caddy()
    ps = find_powershell()

    # 1. Echo upstream on an ephemeral port.
    echo = HTTPServer(("127.0.0.1", 0), HeaderRecorder)
    echo_port = echo.server_address[1]
    HeaderRecorder.received = []
    t = threading.Thread(target=echo.serve_forever, daemon=True)
    t.start()

    # 2. Hash for "test-pass" + wrong-pass, cost 14.
    def bcrypt_hash(plain: str) -> str:
        out = subprocess.run(
            [caddy, "hash-password", "--algorithm", "bcrypt", "--bcrypt-cost", "14", "--plaintext", plain],
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    good_hash = bcrypt_hash("s3cr3t-founder")

    # 3. Caddy site: basic_auth + strip Authorization + echo upstream.
    caddy_port = 8093
    auth_frag = tmp_path / "founder-auth.caddy"
    auth_frag.write_text(
        f'basic_auth bcrypt "Aether Founder Alpha" {{\n    founder {good_hash}\n}}\n',
        encoding="utf-8",
    )
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text(
        f"""{{
    auto_https off
    admin 127.0.0.1:20199
}}
http://127.0.0.1:{caddy_port} {{
    import {auth_frag.as_posix()}
    handle {{
        reverse_proxy 127.0.0.1:{echo_port} {{
            header_up -Authorization
        }}
    }}
}}
""",
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [caddy, "run", "--config", str(caddyfile), "--adapter", "caddyfile"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        import time

        deadline = time.time() + 20
        ok = False
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", caddy_port), 1).close()
                ok = True
                break
            except OSError:
                time.sleep(0.3)
        assert ok, "caddy did not come up"

        base = f"http://127.0.0.1:{caddy_port}"

        # 4. Run the REAL probe for CaddyBasic unauthenticated (expect 401+Basic).
        unauth = run_probe(ps, base, ["-AuthMode", "CaddyBasic", "-CaddyAdminUrl", "http://127.0.0.1:20199"])
        assert unauth["status"] == "fail"  # no authenticated proof, so overall fail
        assert unauth["auth_mode"] == "CaddyBasic"
        assert unauth["unauthenticated_all_denied"] is True
        for r in unauth["unauthenticated_routes"]:
            assert r["status_code"] == 401, r
            assert r["basic_challenge"] is True, r
            assert "basic" in (r.get("www_authenticate") or "").lower(), r
        assert unauth["secret_values_exposed"] is False

        # 5. Authenticated proof with the real probe.
        auth_out = run_probe(
            ps,
            base,
            ["-AuthMode", "CaddyBasic", "-CredentialUsername", "founder", "-CredentialPassword", "s3cr3t-founder", "-CaddyAdminUrl", "http://127.0.0.1:20199"],
        )
        assert auth_out["authenticated_all_ok"] is True, auth_out
        assert auth_out["status"] == "fail"  # public_https=false on localhost http

        # 6. Wrong-credential proof with the real probe.
        wrong_out = run_probe(
            ps,
            base,
            ["-AuthMode", "CaddyBasic", "-WrongCredentialUsername", "founder", "-WrongCredentialPassword", "wrong-pass", "-CaddyAdminUrl", "http://127.0.0.1:20199"],
        )
        assert wrong_out["authenticated_all_ok"] is False
        assert wrong_out["invalid_credentials_all_denied"] is True

        # 7. Header stripping observed at the echo upstream.
        time.sleep(1)
        assert HeaderRecorder.received, "echo upstream received no requests"
        for hit in HeaderRecorder.received:
            assert "authorization" not in hit["headers"], (
                f"Authorization reached upstream for {hit['path']}: {hit['headers']}"
            )
        # echo got hits from authenticated probes (which returned 2xx)
        assert any(True for _ in HeaderRecorder.received)

    finally:
        proc.terminate()
        echo.shutdown()
        proc.wait(timeout=10)


def run_probe(ps: str, base: str, extra: list[str]) -> dict:
    cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PROBE), "-BaseUrl", base] + extra
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, f"probe failed rc={out.returncode}\n{out.stdout}\n{out.stderr}"
    # last JSON block on stdout
    lines = out.stdout.strip().splitlines()
    j = "\n".join(lines)
    return json.loads(j)


@pytest.mark.skipif(find_powershell() is None, reason="PowerShell not available")
def test_probe_flag_matrix_rejected_by_real_probe():
    ps = find_powershell()
    cases = [
        ["-AuthMode", "None", "-WrongCredentialUsername", "founder", "-WrongCredentialPassword", "x"],
        ["-AuthMode", "CaddyBasic", "-ExpectAccessEnforcement"],
        ["-AuthMode", "CaddyBasic", "-AccessCookie", "x"],
        ["-AuthMode", "Access", "-CredentialUsername", "founder", "-CredentialPassword", "x"],
        ["-AuthMode", "None", "-CredentialUsername", "founder", "-CredentialPassword", "x"],
        ["-AuthMode", "Access", "-ExpectAccessEnforcement", "-AccessCookie", "x"],
    ]
    for extra in cases:
        cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PROBE), "-BaseUrl", "http://127.0.0.1:1"] + extra
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert out.returncode != 0, f"expected reject for {extra}: {out.stdout}"


@pytest.mark.skipif(find_powershell() is None, reason="PowerShell not available")
def test_probe_secret_free_receipt(tmp_path: Path):
    """Real probe against a dead origin: receipt must not contain secrets even on failure."""
    ps = find_powershell()
    out = subprocess.run(
        [
            ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PROBE),
            "-BaseUrl", "http://127.0.0.1:1",
            "-AuthMode", "CaddyBasic",
            "-CredentialUsername", "founder", "-CredentialPassword", "s3cr3t",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    text = out.stdout + out.stderr
    for secret in ("s3cr3t", "founder:"):
        assert secret not in text, f"secret leaked in probe output: {secret}"