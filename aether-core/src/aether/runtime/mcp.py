"""Aether MCP activation surface.

This module intentionally keeps the first MCP surface dependency-free. It
implements the JSON-RPC tool handshake needed by stdio MCP clients and backs
every live tool with the Aether mind daemon. When the mind is unreachable, tool
calls fail safe and write receipts under AETHER_HOME.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, TextIO
from urllib import error, request

from aether.runtime.paths import AetherHome, get_aether_home


MCP_ACTIVATION_SCHEMA = "aether.mcp.activation.v1"
DEFAULT_MIND_URL = "http://127.0.0.1:8765"
DEFAULT_SERVER_NAME = "aether-mcp"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
REQUIRED_AETHER_MCP_TOOLS = (
    "aether_who_am_i",
    "aether_north_star_evaluate",
    "aether_believe",
    "aether_sleep",
    "aether_run_task",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _compact_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _write_text(stream: Any, text: str) -> None:
    try:
        stream.write(text)
    except TypeError:
        stream.write(text.encode("utf-8"))


@dataclass(frozen=True)
class AetherMcpConfig:
    aether_home: Path
    mind_url: str = DEFAULT_MIND_URL
    server_name: str = DEFAULT_SERVER_NAME
    protocol_version: str = DEFAULT_PROTOCOL_VERSION
    transport: str = "stdio-jsonrpc"
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AetherMcpConfig":
        env = os.environ if environ is None else environ
        return cls(
            aether_home=Path(env.get("AETHER_HOME") or get_aether_home()),
            mind_url=env.get("AETHER_MIND_URL") or env.get("AETHER_DAEMON_URL") or DEFAULT_MIND_URL,
            server_name=env.get("AETHER_MCP_SERVER_NAME", DEFAULT_SERVER_NAME),
            protocol_version=env.get("AETHER_MCP_PROTOCOL_VERSION", DEFAULT_PROTOCOL_VERSION),
            timeout_seconds=float(env.get("AETHER_MCP_TIMEOUT_SECONDS", "5.0")),
        )


class AetherMcpMindClient(Protocol):
    def is_alive(self) -> bool: ...

    def who_am_i(self) -> dict[str, Any]: ...

    def north_star_evaluate(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def believe(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def run_task(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...


class HttpAetherMcpMindClient:
    """Small stdlib HTTP client for the Aether mind daemon."""

    def __init__(self, base_url: str = DEFAULT_MIND_URL, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str) -> dict[str, Any]:
        with request.urlopen(f"{self.base_url}{path}", timeout=self.timeout) as response:
            return dict(json.loads(response.read().decode("utf-8")))

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        req = request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(dict(payload)).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            return dict(json.loads(response.read().decode("utf-8")))

    def is_alive(self) -> bool:
        try:
            health = self._get("/health")
        except (OSError, error.URLError, json.JSONDecodeError, ValueError):
            return False
        return health.get("status") == "ok" and health.get("mind_ready", True) is not False

    def who_am_i(self) -> dict[str, Any]:
        return self._get("/v1/who_am_i")

    def north_star_evaluate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._post("/v1/north_star_evaluate", payload)

    def believe(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._post("/v1/believe", payload)

    def run_task(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._post("/v1/run_task", payload)


MCP_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "aether_who_am_i",
        "description": "Return Aether mind identity and current narrative.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "aether_north_star_evaluate",
        "description": "Ask Aether North Star governance to evaluate a proposed action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "reason": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "amount_usd": {"type": "number", "minimum": 0},
                "proposal_type": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["action", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "aether_believe",
        "description": "Submit a claim and evidence to Aether's belief/doubt surface.",
        "input_schema": {
            "type": "object",
            "properties": {
                "claim": {"type": "string"},
                "evidence": {"type": "string"},
                "strength": {"type": "number", "minimum": 0, "maximum": 1},
                "source": {"type": "string"},
            },
            "required": ["claim", "evidence"],
            "additionalProperties": False,
        },
    },
    {
        "name": "aether_sleep",
        "description": "Queue an Aether sleep/reflection cycle through the mind task surface.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "context": {"type": "object"},
                "max_amount_usd": {"type": "number", "minimum": 0},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "aether_run_task",
        "description": "Queue a body task request through the Aether mind daemon.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "context": {"type": "object"},
                "max_amount_usd": {"type": "number", "minimum": 0},
            },
            "required": ["goal"],
            "additionalProperties": False,
        },
    },
    {
        "name": "aether_mcp_status",
        "description": "Return local MCP activation status and manifest paths.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
)


def _mcp_tool_spec(tool: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": tool["name"],
        "description": tool["description"],
        "inputSchema": tool["input_schema"],
    }


def _require_string(args: Mapping[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


class AetherMcpActivation:
    """Persistent MCP activation and tool dispatcher."""

    def __init__(self, config: AetherMcpConfig, mind_client: AetherMcpMindClient | None = None):
        self.config = config
        self.home = AetherHome(config.aether_home)
        self.home.ensure()
        self.mind = mind_client or HttpAetherMcpMindClient(config.mind_url, config.timeout_seconds)

    @property
    def tool_names(self) -> list[str]:
        return [str(tool["name"]) for tool in MCP_TOOL_DEFINITIONS]

    def status(self) -> dict[str, Any]:
        activation = _read_json(self.home.mcp_latest_activation)
        return {
            "schema": MCP_ACTIVATION_SCHEMA,
            "activated": bool(activation and activation.get("activated")),
            "server_name": self.config.server_name,
            "transport": self.config.transport,
            "protocol_version": self.config.protocol_version,
            "mind_url": self.config.mind_url,
            "aether_home": str(self.config.aether_home),
            "manifest_path": str(self.home.mcp_manifest),
            "activation_path": str(self.home.mcp_latest_activation),
            "receipts_path": str(self.home.mcp_receipts),
            "tools": self.tool_names,
            "required_tools": list(REQUIRED_AETHER_MCP_TOOLS),
            "last_activation": activation,
        }

    def activate(self) -> dict[str, Any]:
        manifest = {
            "schema": MCP_ACTIVATION_SCHEMA,
            "mcpServers": {
                "aether": {
                    "command": "aether-mcp",
                    "transport": self.config.transport,
                    "env": {
                        "AETHER_HOME": str(self.config.aether_home),
                        "AETHER_MIND_URL": self.config.mind_url,
                    },
                }
            },
            "tools": [_mcp_tool_spec(tool) for tool in MCP_TOOL_DEFINITIONS],
        }
        self.home.mcp_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        record = {
            "schema": MCP_ACTIVATION_SCHEMA,
            "activation_id": uuid.uuid4().hex,
            "activated": True,
            "activated_at": _utc_now(),
            "server_name": self.config.server_name,
            "transport": self.config.transport,
            "protocol_version": self.config.protocol_version,
            "mind_url": self.config.mind_url,
            "manifest_path": str(self.home.mcp_manifest),
            "receipts_path": str(self.home.mcp_receipts),
            "tools": self.tool_names,
            "required_tools": list(REQUIRED_AETHER_MCP_TOOLS),
        }
        receipt = self.record_receipt("mcp.activation.completed", record)
        record["receipt_id"] = receipt["receipt_id"]
        self.home.mcp_latest_activation.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return record

    def record_receipt(self, event: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        receipt = {
            "receipt_id": uuid.uuid4().hex,
            "ts": _utc_now(),
            "event": event,
            "server": self.config.server_name,
            "payload": dict(payload or {}),
        }
        line = json.dumps(receipt, sort_keys=True)
        self.home.mcp_receipts.parent.mkdir(parents=True, exist_ok=True)
        with self.home.mcp_receipts.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return receipt

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        if name == "aether_mcp_status":
            return {"ok": True, "status": "ok", "tool": name, "result": self.status()}
        if name not in self.tool_names:
            receipt = self.record_receipt("mcp.tool.refused", {"tool": name, "reason": "unknown_tool"})
            return {
                "ok": False,
                "status": "error",
                "tool": name,
                "reason": "unknown_tool",
                "receipt_id": receipt["receipt_id"],
            }
        if not self.mind.is_alive():
            receipt = self.record_receipt("mcp.tool.refused", {"tool": name, "reason": "mind_unreachable_fail_safe"})
            return {
                "ok": False,
                "status": "fail_safe",
                "tool": name,
                "reason": "mind_unreachable_fail_safe",
                "receipt_id": receipt["receipt_id"],
            }
        try:
            result = self._dispatch_tool(name, args)
        except Exception as exc:
            receipt = self.record_receipt("mcp.tool.failed", {"tool": name, "reason": str(exc)})
            return {
                "ok": False,
                "status": "error",
                "tool": name,
                "reason": str(exc),
                "receipt_id": receipt["receipt_id"],
            }
        receipt = self.record_receipt("mcp.tool.completed", {"tool": name, "result": result})
        return {
            "ok": True,
            "status": "ok",
            "tool": name,
            "result": result,
            "receipt_id": receipt["receipt_id"],
        }

    def _dispatch_tool(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if name == "aether_who_am_i":
            return self.mind.who_am_i()
        if name == "aether_north_star_evaluate":
            payload = {
                "action": _require_string(args, "action"),
                "reason": _require_string(args, "reason"),
                "confidence": float(args.get("confidence", 0.5)),
                "amount_usd": float(args.get("amount_usd", 0.0)),
                "proposal_type": str(args.get("proposal_type") or "other"),
                "metadata": dict(args.get("metadata") or {}),
            }
            return self.mind.north_star_evaluate(payload)
        if name == "aether_believe":
            payload = {
                "claim": _require_string(args, "claim"),
                "evidence": _require_string(args, "evidence"),
                "strength": float(args.get("strength", 0.3)),
                "source": str(args.get("source") or "mcp"),
            }
            return self.mind.believe(payload)
        if name == "aether_sleep":
            context = {"source": "aether_mcp", "cycle": "sleep"}
            context.update(dict(args.get("context") or {}))
            return self.mind.run_task(
                {
                    "goal": str(args.get("reason") or "Run Aether sleep/reflection cycle."),
                    "context": context,
                    "max_amount_usd": float(args.get("max_amount_usd", 0.0)),
                }
            )
        if name == "aether_run_task":
            return self.mind.run_task(
                {
                    "goal": _require_string(args, "goal"),
                    "context": dict(args.get("context") or {}),
                    "max_amount_usd": float(args.get("max_amount_usd", 0.0)),
                }
            )
        raise ValueError(f"unsupported tool: {name}")


class AetherMcpJsonRpcServer:
    """Tiny JSON-RPC dispatcher for stdio MCP clients."""

    def __init__(self, activation: AetherMcpActivation):
        self.activation = activation

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")
        if request_id is None and isinstance(method, str) and method.startswith("notifications/"):
            return None
        try:
            if method == "initialize":
                record = self.activation.activate()
                return self._result(
                    request_id,
                    {
                        "protocolVersion": self.activation.config.protocol_version,
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": self.activation.config.server_name,
                            "version": "0.1.0",
                        },
                        "activation": record,
                    },
                )
            if method == "ping":
                return self._result(request_id, {})
            if method == "tools/list":
                return self._result(
                    request_id,
                    {"tools": [_mcp_tool_spec(tool) for tool in MCP_TOOL_DEFINITIONS]},
                )
            if method == "tools/call":
                params = message.get("params") or {}
                if not isinstance(params, Mapping):
                    raise ValueError("params must be an object")
                name = _require_string(params, "name")
                args = params.get("arguments") or {}
                if not isinstance(args, Mapping):
                    raise ValueError("arguments must be an object")
                result = self.activation.call_tool(name, args)
                return self._result(
                    request_id,
                    {
                        "content": [{"type": "text", "text": json.dumps(result, sort_keys=True)}],
                        "isError": not bool(result.get("ok")),
                    },
                )
            if method == "resources/list":
                return self._result(request_id, {"resources": []})
            return self._error(request_id, -32601, f"method not found: {method}")
        except Exception as exc:
            return self._error(request_id, -32602, str(exc))

    @staticmethod
    def _result(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve_stdio(
    activation: AetherMcpActivation,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    input_stream = sys.stdin.buffer if stdin is None else getattr(stdin, "buffer", stdin)
    output_stream = sys.stdout if stdout is None else stdout
    server = AetherMcpJsonRpcServer(activation)
    framed_output = False
    for raw in input_stream:
        if isinstance(raw, bytes):
            stripped = raw.strip()
        else:
            stripped = raw.strip().encode("utf-8")
        if not stripped:
            continue
        try:
            if stripped.lower().startswith(b"content-length:"):
                framed_output = True
                try:
                    length = int(stripped.split(b":", 1)[1].strip())
                except ValueError as exc:
                    raise ValueError("invalid content-length header") from exc
                while True:
                    header = input_stream.readline()
                    if not header or header in (b"\r\n", b"\n", "\r\n", "\n"):
                        break
                body = input_stream.read(length)
                if not body:
                    break
                raw_json = body.decode("utf-8")
            else:
                raw_json = stripped.decode("utf-8")
            message = json.loads(raw_json)
            if not isinstance(message, Mapping):
                raise ValueError("message must be a JSON object")
            response = server.handle(message)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            payload = _compact_json(response)
            if framed_output:
                encoded = payload.encode("utf-8")
                sink = getattr(output_stream, "buffer", None)
                framed = f"Content-Length: {len(encoded)}\r\n\r\n".encode("utf-8") + encoded
                if sink is None:
                    _write_text(output_stream, framed.decode("utf-8"))
                else:
                    sink.write(framed)
            else:
                _write_text(output_stream, payload + "\n")
            output_stream.flush()


def build_activation(environ: Mapping[str, str] | None = None) -> AetherMcpActivation:
    return AetherMcpActivation(AetherMcpConfig.from_env(environ))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Aether MCP stdio server and activation tool")
    parser.add_argument("command", nargs="?", default="stdio", choices=("stdio", "status", "activate"))
    args = parser.parse_args(argv)
    activation = build_activation()
    if args.command == "status":
        print(json.dumps(activation.status(), indent=2, sort_keys=True))
        return
    if args.command == "activate":
        print(json.dumps(activation.activate(), indent=2, sort_keys=True))
        return
    serve_stdio(activation)


if __name__ == "__main__":
    main()
