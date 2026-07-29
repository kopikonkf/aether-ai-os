#!/usr/bin/env python3
r"""Executable capability/wiring audit for Aether OS v0.19.2.

Run from the canonical release root after installing the v0.19.2 wheels:
    .\.venv\Scripts\python.exe AETHER_CAPABILITY_WIRING_AUDIT.py

The audit does not mutate Aether state. It distinguishes implementation,
registration, health, conformance, activation, and live-proof status.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
for source in (ROOT / "aether-core" / "src", ROOT / "aether-tools" / "src", ROOT / "aether-gateway" / "src"):
    if source.exists():
        sys.path.insert(0, str(source))

# Safe import defaults for a fresh audit environment. Existing values win.
os.environ.setdefault("AETHER_OPERATOR_TOKEN", "audit-only-operator-token")
os.environ.setdefault("AETHER_BROWSER_SESSION_SECRET", "audit-only-browser-secret")
os.environ.setdefault("AETHER_SENSE_WORKER_TOKEN", "audit-only-worker-token")
if "AETHER_HOME" not in os.environ:
    os.environ["AETHER_HOME"] = tempfile.mkdtemp(prefix="aether-wiring-audit-")


def state(label: str, *, evidence: list[str] | None = None, blockers: list[str] | None = None) -> dict[str, Any]:
    return {"state": label, "evidence": evidence or [], "blockers": blockers or []}


async def main() -> int:
    from aether_gateway.api import server

    route_paths = {route.path for route in server.app.routes}
    tool_names = sorted(tool.name for tool in server.tool_registry.all())
    source_status = {item.adapter_id: item for item in await server.source_mesh.status()}
    source_configs = {item.adapter_id: item for item in server.web_intelligence_store.configurations()}
    adapters = {item.manifest.adapter_id: item for item in server.source_mesh.adapters()}

    required_routes = {
        "cognition": "/api/chat",
        "browser_senses": "/api/browser-senses/text",
        "approvals": "/api/approvals",
        "knowledge": "/api/knowledge/proposals",
        "evolution": "/api/evolution/status",
        "skills": "/api/skills",
        "runtime": "/api/runtime-drivers/status",
        "missions": "/api/missions",
        "opportunities": "/api/opportunity-intelligence/scout-runs",
        "web_intelligence": "/api/web-intelligence/acquire",
        "experiments": "/api/experiments/plans",
    }

    capabilities: dict[str, Any] = {}
    for name, path in required_routes.items():
        capabilities[name] = state(
            "WIRED" if path in route_paths else "BROKEN",
            evidence=[f"FastAPI route registered: {path}"] if path in route_paths else [],
            blockers=[] if path in route_paths else [f"missing route: {path}"],
        )

    expected_tools = {"read", "write", "edit", "grep", "glob", "bash", "webfetch", "memory"}
    missing_tools = sorted(expected_tools - set(tool_names))
    capabilities["governed_tools"] = state(
        "WIRED" if not missing_tools else "BROKEN",
        evidence=[f"registered tools: {', '.join(tool_names)}"],
        blockers=[f"missing tools: {', '.join(missing_tools)}"] if missing_tools else [],
    )

    nutrition: dict[str, Any] = {}

    # Agent-Reach is an architectural reference only in v0.19.2.
    agent_reach_importable = importlib.util.find_spec("agent_reach") is not None
    nutrition["agent_reach"] = {
        "state": "INSTALLED_EXTERNAL_NOT_WIRED" if agent_reach_importable else "REFERENCE_ONLY",
        "registered_adapter": False,
        "package_importable": agent_reach_importable,
        "active": False,
        "notes": [
            "SourceCapabilityMesh is Agent-Reach-inspired.",
            "No Agent-Reach adapter, CLI bridge, doctor bridge, or skill projection is registered in v0.19.2.",
        ],
    }

    crawl_id = "source.adapter.crawl4ai-restricted"
    crawl_status = source_status.get(crawl_id)
    crawl_config = source_configs.get(crawl_id)
    crawl_receipt = server.web_intelligence_store.latest_conformance(crawl_id)
    crawl_active = bool(
        crawl_status
        and crawl_status.health.value == "healthy"
        and crawl_config
        and crawl_config.enabled
        and crawl_receipt
        and crawl_receipt.state.value == "passed"
    )
    nutrition["crawl4ai"] = {
        "state": "ACTIVE" if crawl_active else "WIRED_DORMANT",
        "registered_adapter": crawl_id in adapters,
        "package_importable": importlib.util.find_spec("crawl4ai") is not None,
        "health": crawl_status.health.value if crawl_status else "missing",
        "health_reason": crawl_status.reason if crawl_status else "adapter not registered",
        "configured": bool(crawl_config and crawl_config.endpoint != "local:unconfigured"),
        "enabled": bool(crawl_config and crawl_config.enabled),
        "conformance": crawl_receipt.state.value if crawl_receipt else "none",
        "active": crawl_active,
    }

    public_id = "source.adapter.public-http"
    public_status = source_status.get(public_id)
    public_config = source_configs.get(public_id)
    public_receipt = server.web_intelligence_store.latest_conformance(public_id)
    public_active = bool(
        public_status
        and public_status.health.value == "healthy"
        and public_config
        and public_config.enabled
        and public_receipt
        and public_receipt.state.value == "passed"
    )
    nutrition["public_http"] = {
        "state": "ACTIVE" if public_active else "WIRED_DORMANT",
        "registered_adapter": public_id in adapters,
        "health": public_status.health.value if public_status else "missing",
        "configured": bool(public_config and public_config.endpoint != "local:unconfigured"),
        "enabled": bool(public_config and public_config.enabled),
        "conformance": public_receipt.state.value if public_receipt else "none",
        "active": public_active,
    }

    for key, adapter_id in (
        ("ai_treasurebox", "source.adapter.ai-treasurebox"),
        ("awesome_ai_agents", "source.adapter.awesome-ai-agents"),
    ):
        status = source_status.get(adapter_id)
        nutrition[key] = {
            "state": "STATIC_CATALOG_ACTIVE" if status and status.health.value == "healthy" else "BROKEN",
            "registered_adapter": adapter_id in adapters,
            "health": status.health.value if status else "missing",
            "active": bool(status and status.health.value == "healthy"),
            "live_refresh": False,
            "notes": [
                "Registered at Gateway startup as StaticCatalogAdapter.",
                "Current content is a small hard-coded seed snapshot, not a live GitHub ingestion pipeline.",
            ],
        }

    runtime_statuses = []
    try:
        for item in server.runtime_driver_pack.status():
            runtime_statuses.append({
                "driver_id": item.driver_id,
                "available": item.available,
                "reason": item.reason,
            })
    except Exception as exc:  # diagnostic must not hide partial state
        runtime_statuses.append({"error": f"{type(exc).__name__}: {exc}"})

    result = {
        "release": "0.19.2",
        "audit_schema": "aether.capability-wiring.v1",
        "aether_home": os.environ.get("AETHER_HOME"),
        "summary": {
            "route_count": len(route_paths),
            "registered_tools": tool_names,
            "registered_source_adapters": sorted(adapters),
            "crawl4ai_importable": importlib.util.find_spec("crawl4ai") is not None,
            "agent_reach_importable": agent_reach_importable,
        },
        "capabilities": capabilities,
        "external_nutrition": nutrition,
        "runtime_drivers": runtime_statuses,
        "truth_model": {
            "IMPLEMENTED": "code and contract exist",
            "WIRED": "constructed and reachable from runtime/API",
            "CONFORMED": "exact environment adapter canary has passed",
            "ACTIVE": "enabled and eligible for execution",
            "FOUNDER_PROVEN": "real user-facing execution receipt exists",
        },
    }
    print(json.dumps(result, indent=2, default=str))

    broken = [name for name, item in capabilities.items() if item["state"] == "BROKEN"]
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
