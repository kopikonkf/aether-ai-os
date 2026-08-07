from __future__ import annotations

"""
Real integration proof for the Founder Alpha Caddy basic_auth ingress.

This test executes the *actual* probe-cloudflare-ingress.ps1 against a real
Caddy instance fronting an echo upstream. It proves, using the real probe (not
a Python mirror):

  - None mode:      unauth requests reach an open upstream (2xx on every route)
  - Access mode:    an Access-like upstream denies without a CF cookie and
                    serves the required routes when the cookie is present
  - CaddyBasic mode:
      unauthenticated -> 401 + WWW-Authenticate: Basic on all 4 routes
      wrong credentials -> 401 + Basic challenge
      correct credentials -> 2xx on all 4 routes
  - the receipt's `authorization_forwarded_to_upstream` is DERIVED FROM the
    echo upstream observation (what the echo server actually received) - never
    from an inspection of Caddy `/config/`
  - the receipt is secret-free
  - the fail-closed parameter matrix (the probe rejects conflicting and partial
    flags)

Passwords are only ever provided to the probe over stdin (or as a PSCredential
object); never as a command-line argument. This mirrors the interface contract.

It requires the real toolchain (caddy + a PowerShell) and
AETHER_INGRESS_INTEGRATION=1. CI installs caddy + pwsh and sets the env var so
this boundary proof is COLLECTED and EXECUTED (not skipped) on the CI job that
is gated on it.
"""

import json
import os
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "deploy" / "cloudflare" / "probe-cloudflare-ingress.ps1"

REQUIRED = ["/health", "/aether/api/status", "/api/browser-senses/status", "/senses"]
ECHO_ROUTE = "/__aether_echo"


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
    """Echo upstream: returns the exact headers it received as JSON."""

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


class OpenUpstream(BaseHTTPRequestHandler):
    """Plain 200 for every route (None AuthMode valid flow)."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


class AccessShim(BaseHTTPRequestHandler):
    """Access-like edge: 302 to cloudflare access login without a matching
    CF_Authorization cookie; 200 with it."""

    cookie_value = "s3cr3t-access-cookie"

    def do_GET(self):
        cookie = (self.headers.get("Cookie") or "") + (self.headers.get("cookie") or "")
        if f"CF_Authorization={self.cookie_value}" in cookie:
            self.send_response(200)
            self.send_header("Content-Length", "0")
        else:
            self.send_response(302)
            self.send_header(
                "Location",
                "https://aether-team.cloudflareaccess.com/cdn-cgi/access/login",
            )
            self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


class _ThreadedServer:
    def __init__(self, handler):
        self.httpd = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()

    def shutdown(self):
        self.httpd.shutdown()


def wait_port(host: str, port: int, timeout: float = 20.0) -> bool:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection((host, port), 1).close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


def bcrypt_hash(caddy: str, plain: str) -> str:
    out = subprocess.run(
        [caddy, "hash-password", "--algorithm", "bcrypt", "--bcrypt-cost", "14", "--plaintext", plain],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def run_probe(ps: str, base: str, extra: list[str], stdin: str | None = None, home: str | None = None) -> dict:
    cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PROBE), "-BaseUrl", base]
    if home:
        cmd += ["-AetherHome", home]
    cmd += extra
    out = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        input=stdin,
    )
    assert out.returncode == 0, f"probe failed rc={out.returncode}\n{out.stdout}\n{out.stderr}"
    lines = out.stdout.strip().splitlines()
    return json.loads("\n".join(lines))


def _real_toolchain() -> bool:
    return enabled() and find_caddy() is not None and find_powershell() is not None


REAL_TOOLCHAIN = pytest.mark.skipif(
    not _real_toolchain(),
    reason="integration needs AETHER_INGRESS_INTEGRATION=1 and caddy + PowerShell on PATH",
)


@REAL_TOOLCHAIN
def test_real_probe_valid_flow_none(tmp_path: Path):
    ps = find_powershell()
    up = _ThreadedServer(OpenUpstream)
    try:
        base = f"http://127.0.0.1:{up.port}"
        home = str(tmp_path / "home-none")
        receipt = run_probe(ps, base, ["-AuthMode", "None"], home=home)
        assert receipt["auth_mode"] == "None"
        assert receipt["unauthenticated_all_denied"] is False
        assert all(r["ok"] for r in receipt["unauthenticated_routes"]), receipt
        assert receipt["required_routes_ok"] is True
        assert receipt["authorization_forwarded_to_upstream"] is None
    finally:
        up.shutdown()


@REAL_TOOLCHAIN
def test_real_mode_access_valid_and_unauthenticated_denial(tmp_path: Path):
    ps = find_powershell()
    up = _ThreadedServer(AccessShim)
    try:
        base = f"http://127.0.0.1:{up.port}"
        home = str(tmp_path / "home-access")

        # Valid Access flow: matching CF_Authorization cookie -> 2xx on all routes.
        valid = run_probe(ps, base, ["-AuthMode", "Access", "-AccessCookie", AccessShim.cookie_value], home=home)
        assert valid["authenticated_all_ok"] is True, valid
        assert valid["unauthenticated_all_denied"] is True, valid

        # Unauthenticated Access enforcement flow -> 401/403 or CF redirect.
        enforce = run_probe(ps, base, ["-AuthMode", "Access", "-ExpectAccessEnforcement"], home=str(tmp_path / "home-access-enforce"))
        assert enforce["unauthenticated_all_denied"] is True, enforce
    finally:
        up.shutdown()


@REAL_TOOLCHAIN
def test_real_mode_caddybasic_auth_and_echo_derived_strip(tmp_path: Path):
    caddy = find_caddy()
    ps = find_powershell()

    up = _ThreadedServer(HeaderRecorder)
    HeaderRecorder.received = []

    caddy_port = 8093
    auth_frag = tmp_path / "founder-auth.caddy"
    auth_frag.write_text(
        f'basic_auth bcrypt "Aether Founder Alpha" {{\n    founder {bcrypt_hash(caddy, "s3cr3t-founder")}\n}}\n',
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
        reverse_proxy 127.0.0.1:{up.port} {{
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
        assert wait_port("127.0.0.1", caddy_port), "caddy did not come up"
        base = f"http://127.0.0.1:{caddy_port}"
        home = str(tmp_path / "home-caddy")

        # Unauthenticated -> 401 + Basic on every route.
        unauth = run_probe(ps, base, ["-AuthMode", "CaddyBasic", "-EchoRoute", ECHO_ROUTE], home=home)
        assert unauth["auth_mode"] == "CaddyBasic"
        assert unauth["unauthenticated_all_denied"] is True
        for r in unauth["unauthenticated_routes"]:
            assert r["status_code"] == 401, r
            assert r["basic_challenge"] is True, r
            assert "basic" in (r.get("www_authenticate") or "").lower(), r
        assert unauth["secret_values_exposed"] is False

        # Authenticated: password from stdin (never in argv).
        auth_out = run_probe(
            ps,
            base,
            ["-AuthMode", "CaddyBasic", "-CredentialUsername", "founder", "-CredentialPasswordStdin", "-EchoRoute", ECHO_ROUTE],
            stdin="s3cr3t-founder\n",
            home=str(tmp_path / "home-caddy-auth"),
        )
        assert auth_out["authenticated_all_ok"] is True, auth_out
        # HEADER STRIP MUST BE DERIVED FROM THE ECHO UPSTREAM, not Caddy /config/.
        assert auth_out["header_strip_observed"] is True, auth_out
        assert auth_out["authorization_forwarded_to_upstream"] is False, auth_out

        # Wrong credentials via stdin -> rejected with a Basic challenge.
        wrong = run_probe(
            ps,
            base,
            ["-AuthMode", "CaddyBasic", "-WrongCredentialUsername", "founder", "-WrongCredentialPasswordStdin"],
            stdin="wrong-pass\n",
            home=str(tmp_path / "home-caddy-wrong"),
        )
        assert wrong["authenticated_all_ok"] is False
        assert wrong["invalid_credentials_all_denied"] is True

        # Cross-check against what the echo server itself received.
        assert HeaderRecorder.received, "echo upstream received no requests"
        for hit in HeaderRecorder.received:
            assert "authorization" not in hit["headers"], f"Authorization reached upstream: {hit['headers']}"
    finally:
        proc.terminate()
        up.shutdown()
        try:
            proc.wait(timeout=10)
        except Exception:
            pass


@REAL_TOOLCHAIN
def test_probe_flag_matrix_rejected_by_real_probe(tmp_path: Path):
    ps = find_powershell()
    home = str(tmp_path / "home-matrix")
    cases = [
        ["-AuthMode", "None", "-WrongCredentialUsername", "founder", "-WrongCredentialPasswordStdin"],
        ["-AuthMode", "CaddyBasic", "-ExpectAccessEnforcement"],
        ["-AuthMode", "CaddyBasic", "-AccessCookie", "x"],
        ["-AuthMode", "Access", "-CredentialUsername", "founder", "-CredentialPasswordStdin"],
        ["-AuthMode", "None", "-CredentialUsername", "founder", "-CredentialPasswordStdin"],
        ["-AuthMode", "Access", "-ExpectAccessEnforcement", "-AccessCookie", "x"],
        ["-AuthMode", "CaddyBasic", "-AccessCookie", "x", "-CredentialUsername", "founder"],
        ["-AuthMode", "Access", "-WrongCredentialUsername", "founder", "-WrongCredentialPasswordStdin"],
        ["-AuthMode", "None", "-AccessCookie", "x"],
        ["-AuthMode", "CaddyBasic", "-EchoRoute", ECHO_ROUTE, "-AccessCookie", "x"],
    ]
    for extra in cases:
        cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PROBE), "-BaseUrl", "http://127.0.0.1:1", "-AetherHome", home] + extra
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert out.returncode != 0, f"expected reject for {extra}: {out.stdout}"


@REAL_TOOLCHAIN
def test_probe_rejects_partial_credential_surfaces(tmp_path: Path):
    ps = find_powershell()
    home = str(tmp_path / "home-partial")
    partial_cases = [
        ["-AuthMode", "CaddyBasic", "-CredentialUsername", "founder"],
        ["-AuthMode", "CaddyBasic", "-CredentialPasswordStdin"],
        ["-AuthMode", "CaddyBasic", "-WrongCredentialUsername", "founder"],
        ["-AuthMode", "CaddyBasic", "-WrongCredentialPasswordStdin"],
    ]
    for extra in partial_cases:
        cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PROBE), "-BaseUrl", "http://127.0.0.1:1", "-AetherHome", home] + extra
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert out.returncode != 0, f"expected partial reject for {extra}: {out.stdout}"


@REAL_TOOLCHAIN
def test_probe_secret_free_receipt(tmp_path: Path):
    """Real probe against a dead origin: receipt must not contain secrets even on failure."""
    ps = find_powershell()
    home = str(tmp_path / "home-secretfree")
    out = subprocess.run(
        [
            ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PROBE),
            "-BaseUrl", "http://127.0.0.1:1",
            "-AetherHome", home,
            "-AuthMode", "CaddyBasic",
            "-CredentialUsername", "founder", "-CredentialPasswordStdin",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        input="s3cr3t\n",
    )
    text = out.stdout + out.stderr
    for secret in ("s3cr3t", "founder:"):
        assert secret not in text, f"secret leaked in probe output: {secret}"
