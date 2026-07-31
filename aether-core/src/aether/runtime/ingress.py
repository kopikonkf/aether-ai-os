"""Cloudflare one-domain ingress receipts.

This module does not create Cloudflare resources. It gives the host a small,
secret-safe way to probe the public tunnel and persist evidence under
``AETHER_HOME`` so Founder acceptance and MVP release packets can read the same
proof later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib import error, parse, request

from aether.runtime.paths import AetherHome, get_aether_home


CLOUDFLARE_INGRESS_SCHEMA = "aether.cloudflare-ingress.v1"
REQUIRED_CLOUDFLARE_ROUTES = (
    "/health",
    "/aether/api/status",
    "/api/browser-senses/status",
    "/senses",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path) -> dict[str, Any] | None:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _append_jsonl(path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(data), sort_keys=True) + "\n")


def _public_origin(url: str) -> dict[str, Any]:
    parsed = parse.urlsplit(url)
    return {
        "scheme": parsed.scheme,
        "hostname_sha256": hashlib.sha256((parsed.hostname or "").encode("utf-8")).hexdigest() if parsed.hostname else None,
        "hostname": parsed.hostname,
        "port": parsed.port,
    }


def _route_ok(route: Mapping[str, Any]) -> bool:
    status_code = route.get("status_code")
    try:
        status_code_int = int(status_code)
    except (TypeError, ValueError):
        status_code_int = 0
    return bool(route.get("ok")) and 200 <= status_code_int < 400


def _normalize_probe(raw: Mapping[str, Any]) -> dict[str, Any]:
    base_url = str(raw.get("base_url") or raw.get("url") or "").rstrip("/")
    routes = list(raw.get("routes", [])) if isinstance(raw.get("routes"), list) else []
    route_by_path = {str(item.get("path") or ""): item for item in routes if isinstance(item, Mapping)}
    required = tuple(str(item) for item in raw.get("required_routes", REQUIRED_CLOUDFLARE_ROUTES))
    required_ok = all(_route_ok(route_by_path.get(path, {})) for path in required)
    public_https = base_url.startswith("https://")
    service_status = str(raw.get("service_status") or raw.get("cloudflared_service_status") or "").lower()
    tunnel_running = raw.get("cloudflare_tunnel") is True or service_status in {"running", "active", "ok"}
    ok = public_https and required_ok and (tunnel_running or raw.get("cloudflare_tunnel") is True)
    return {
        "schema": CLOUDFLARE_INGRESS_SCHEMA,
        "event": "cloudflare.ingress.probed",
        "observed_at": str(raw.get("observed_at") or _utc_now()),
        "status": "ok" if ok else "fail",
        "base_url": base_url,
        "public_origin": _public_origin(base_url),
        "public_https": public_https,
        "cloudflare_tunnel": tunnel_running or raw.get("cloudflare_tunnel") is True,
        "cloudflared_service_status": raw.get("cloudflared_service_status") or raw.get("service_status"),
        "required_routes": list(required),
        "routes": routes,
        "required_routes_ok": required_ok,
        "receipt_source": str(raw.get("receipt_source") or "aether-cloudflare-ingress"),
        "secret_values_exposed": False,
    }


@dataclass(frozen=True)
class AetherCloudflareIngress:
    """Read and write Cloudflare ingress evidence under AETHER_HOME."""

    home: AetherHome

    def __init__(self, aether_home=None):
        object.__setattr__(self, "home", aether_home if isinstance(aether_home, AetherHome) else AetherHome(aether_home))
        self.home.ensure()

    def latest_probe(self) -> dict[str, Any] | None:
        return _read_json(self.home.cloudflare_ingress_latest_probe)

    def status(self) -> dict[str, Any]:
        latest = self.latest_probe()
        return {
            "schema": CLOUDFLARE_INGRESS_SCHEMA,
            "status": latest.get("status") if latest else "pending",
            "ready": bool(latest and latest.get("status") == "ok"),
            "required_routes": list(REQUIRED_CLOUDFLARE_ROUTES),
            "latest_probe_path": str(self.home.cloudflare_ingress_latest_probe),
            "probe_log_path": str(self.home.cloudflare_ingress_probes),
            "latest_probe": latest,
        }

    def record_probe(self, probe: Mapping[str, Any]) -> dict[str, Any]:
        record = _normalize_probe(probe)
        self.home.cloudflare_ingress.mkdir(parents=True, exist_ok=True)
        self.home.cloudflare_ingress_latest_probe.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _append_jsonl(self.home.cloudflare_ingress_probes, record)
        return record


def probe_public_base_url(base_url: str, *, timeout_seconds: float = 8.0) -> dict[str, Any]:
    base = base_url.rstrip("/")
    routes: list[dict[str, Any]] = []
    for path in REQUIRED_CLOUDFLARE_ROUTES:
        url = f"{base}{path}"
        started = datetime.now(timezone.utc)
        status_code = None
        ok = False
        err = None
        try:
            with request.urlopen(url, timeout=timeout_seconds) as response:
                status_code = int(response.status)
                ok = 200 <= status_code < 400
        except error.HTTPError as exc:
            status_code = int(exc.code)
            err = f"HTTPError: {exc.code}"
        except OSError as exc:
            err = f"{type(exc).__name__}: {exc}"
        elapsed_ms = round((datetime.now(timezone.utc) - started).total_seconds() * 1000, 1)
        routes.append({"path": path, "status_code": status_code, "ok": ok, "latency_ms": elapsed_ms, "error": err})
    return {
        "base_url": base,
        "cloudflare_tunnel": True,
        "required_routes": list(REQUIRED_CLOUDFLARE_ROUTES),
        "routes": routes,
        "observed_at": _utc_now(),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Record or probe Aether Cloudflare ingress evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Print latest ingress status.")

    record = subparsers.add_parser("record", help="Record a probe JSON file as latest evidence.")
    record.add_argument("--probe-json", required=True)

    probe = subparsers.add_parser("probe", help="Probe the public base URL and persist the receipt.")
    probe.add_argument("--base-url", required=True)
    probe.add_argument("--timeout-seconds", type=float, default=8.0)

    args = parser.parse_args(argv)
    ingress = AetherCloudflareIngress(get_aether_home())

    if args.command == "status":
        result = ingress.status()
    elif args.command == "record":
        result = ingress.record_probe(json.loads(open(args.probe_json, encoding="utf-8").read()))
    else:
        result = ingress.record_probe(probe_public_base_url(args.base_url, timeout_seconds=args.timeout_seconds))

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
