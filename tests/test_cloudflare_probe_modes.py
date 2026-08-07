from __future__ import annotations

# Mirror of the probe-cloudflare-ingress.ps1 decision semantics so they can be
# executed (not string-scanned) on a plain Python CI runner.


def basic_challenge(status_code: int | None, www_authenticate: str | None) -> bool:
    return status_code == 401 and bool(www_authenticate) and "basic" in www_authenticate.lower()


def access_protected(status_code: int | None, location: str | None) -> bool:
    if status_code in (401, 403):
        return True
    if not (status_code and 300 <= status_code <= 399):
        return False
    if not location:
        return False
    try:
        from urllib.parse import urlsplit

        host = (urlsplit(location).hostname or "").lower()
    except Exception:
        return False
    return host.endswith(".cloudflareaccess.com") or "cdn-cgi/access/" in location.lower()


def required_denied(results: list[dict], auth_mode: str) -> bool:
    if auth_mode == "CaddyBasic":
        return all(r["basic_challenge"] for r in results)
    return all(r["access_protected"] for r in results)


def routes_ok(results: list[dict]) -> bool:
    return len(results) > 0 and all(r["ok"] for r in results)


def validate_flags(
    auth_mode: str,
    access_cookie: bool,
    credential: bool,
    enforce: bool,
    wrong_cred: bool = False,
    echo_route: bool = False,
    credential_partial: bool = False,
    wrong_credential_partial: bool = False,
) -> list[str]:
    """Mirror of the probe's fail-closed flag validation.

    `credential` means a complete credential surface (username + password
    source). `credential_partial` means a username OR password source without
    the other, which the real probe rejects before making any request.
    """
    errs = []
    if credential_partial or wrong_credential_partial:
        errs.append("partial credential surface rejected")
    if auth_mode == "None" and (access_cookie or credential or wrong_cred or enforce):
        errs.append("AuthMode=None rejects credential/access flags")
    if auth_mode == "CaddyBasic" and enforce:
        errs.append("ExpectAccessEnforcement is Access-only; cannot combine with CaddyBasic")
    if auth_mode == "CaddyBasic" and access_cookie:
        errs.append("AccessCookie is Access-only; cannot combine with CaddyBasic")
    if auth_mode == "Access" and (credential or wrong_cred):
        errs.append("Credential/WrongCredential are CaddyBasic-only; cannot combine with Access")
    if auth_mode == "Access" and enforce and access_cookie:
        errs.append("ExpectAccessEnforcement expects no AccessCookie")
    if auth_mode != "CaddyBasic" and echo_route:
        errs.append("EchoRoute is CaddyBasic-only (header-strip observation)")
    return errs


def result(status_code: int | None, ok: bool, www: str | None = None, location: str | None = None) -> dict:
    return {
        "status_code": status_code,
        "ok": ok,
        "www_authenticate": www,
        "basic_challenge": basic_challenge(status_code, www),
        "access_protected": access_protected(status_code, location),
    }


RN = result  # alias


def test_unauth_caddybasic_requires_exact_401_and_basic_challenge():
    # 403 without a Basic challenge must NOT count as denied for CaddyBasic.
    routes = [
        result(401, ok=False, www="Basic realm=\"Aether Founder Alpha\""),
        result(401, ok=False, www="Basic"),
        result(403, ok=False),
        result(200, ok=True),
    ]
    assert not required_denied(routes, "CaddyBasic")

    # Even a 403 would be accepted by Access mode, but not by CaddyBasic.
    access_mixed = [result(403, ok=False), result(401, ok=False, www="Basic")]
    assert required_denied(access_mixed, "Access")
    assert not required_denied(access_mixed, "CaddyBasic")


def test_unauth_caddybasic_all_401_basic_passes():
    routes = [
        result(401, ok=False, www="Basic realm=\"Auth\""),
        result(401, ok=False, www="Basic"),
        result(401, ok=False, www="Basic"),
        result(401, ok=False, www="basic"),
    ]
    assert required_denied(routes, "CaddyBasic")


def test_authenticated_requires_2xx():
    routes = [result(200, ok=True), result(201, ok=True), result(204, ok=True), result(200, ok=True)]
    assert routes_ok(routes)
    mixed = [result(200, ok=True), result(401, ok=False, www="Basic")]
    assert not routes_ok(mixed)


def test_incompatible_flags_rejected():
    assert validate_flags("CaddyBasic", False, False, True)  # enforce + caddy
    assert validate_flags("None", True, True, False)  # creds + none
    assert validate_flags("None", False, True, False, wrong_cred=True)  # none + wrong cred
    assert validate_flags("Access", False, True, False)  # access + credential
    assert validate_flags("Access", False, False, False, wrong_cred=True)  # access + wrong cred
    assert validate_flags("CaddyBasic", True, False, False)  # caddy + access cookie
    assert validate_flags("Access", True, False, True)  # access + enforce + cookie
    assert validate_flags("None", False, False, False) == []
    assert validate_flags("CaddyBasic", False, True, False) == []
    assert validate_flags("Access", True, False, False) == []


def test_partial_credential_surfaces_rejected():
    # username without a password source, or password-only, in any mode.
    assert validate_flags("CaddyBasic", False, False, False, credential_partial=True)
    assert validate_flags("CaddyBasic", False, False, False, wrong_credential_partial=True)
    assert validate_flags("CaddyBasic", False, False, False, credential_partial=True, wrong_credential_partial=True)
    assert validate_flags("None", False, False, False, credential_partial=True)
    assert validate_flags("Access", False, False, False, wrong_credential_partial=True)
    # complete surfaces are fine for their own mode
    assert validate_flags("CaddyBasic", False, True, False) == []
    assert validate_flags("CaddyBasic", False, False, False, wrong_cred=True) == []


def test_echo_route_only_for_caddybasic():
    assert validate_flags("Access", False, False, False, echo_route=True)
    assert validate_flags("None", False, False, False, echo_route=True)
    assert validate_flags("CaddyBasic", False, True, False, echo_route=True) == []


def test_access_protected_rejects_unrelated_redirect_and_accepts_cf_redirect():
    assert access_protected(302, "https://aether-team.cloudflareaccess.com/cdn-cgi/access/login") is True
    assert access_protected(302, "https://app.aethers.my.id/x") is False
    assert access_protected(307, "https://example.org/x") is False
    assert access_protected(401, None) is True
    assert access_protected(403, None) is True
    assert access_protected(200, None) is False