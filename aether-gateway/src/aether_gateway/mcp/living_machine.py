"""Bounded capability plane for inspecting and governing the living Aether machine.

This module is intentionally an interface layer. File mutation and coding
verification are delegated to the existing runtime/governance primitives.
"""
from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import hmac
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from aether.contracts import ActionApproval, ActionProposal, ActionRisk, ActionScope, ActionTarget, RuntimeCommand
from aether.contracts.coding_runtime import WorkspaceBinding


_SECRET_NAME = re.compile(
    r"(^|[._-])(\.env|env|secret|credential|credentials|token|password|passwd|apikey|api-key|private-key|id_rsa|id_ed25519)($|[._-])",
    re.IGNORECASE,
)
_SECRET_TEXT = re.compile(
    r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+|(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+|(?i)(token\s*[:=]\s*)[^\s,;]+|(?i)(password\s*[:=]\s*)[^\s,;]+",
)


def _json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_json(v) for v in value]
    if hasattr(value, "value"):
        return _json(value.value)
    if isinstance(value, Path):
        return str(value)
    return value


def redact(value: str) -> str:
    return _SECRET_TEXT.sub(r"\1[REDACTED]", value)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


class LivingMachinePolicyError(PermissionError):
    pass


class LivingMachineMCPService:
    """Application service shared by MCP tools and resources."""

    schema = "aether.mcp.living-machine.v1"

    def __init__(
        self,
        *,
        project_root: Path,
        aether_home: Path,
        workspace_roots: Iterable[Path],
        workspace_bindings: Any,
        runtime_registry: Any,
        runtime_telemetry: Any,
        action_path: Any,
    ) -> None:
        self.project_root = project_root.resolve()
        self.aether_home = aether_home.resolve()
        self.workspace_roots = tuple(dict.fromkeys(
            [p.expanduser().resolve() for p in workspace_roots] + [self.aether_home, self.project_root]
        ))
        self.workspace_bindings = workspace_bindings
        self.runtime_registry = runtime_registry
        self.runtime_telemetry = runtime_telemetry
        self.action_path = action_path
        self.max_file_bytes = int(os.environ.get("AETHER_MCP_MAX_FILE_BYTES", "262144"))
        self.max_search_results = int(os.environ.get("AETHER_MCP_MAX_SEARCH_RESULTS", "100"))
        self.max_log_bytes = int(os.environ.get("AETHER_MCP_MAX_LOG_BYTES", "262144"))
        self.max_log_lines = int(os.environ.get("AETHER_MCP_MAX_LOG_LINES", "500"))
        self.log_roots = tuple(Path(p).expanduser().resolve() for p in os.environ.get("AETHER_MCP_LOG_ROOTS", "").split(os.pathsep) if p.strip())
        if not self.log_roots:
            self.log_roots = (self.aether_home / "logs", self.aether_home / "runtime")

    def _safe_path(self, raw: str, *, must_exist: bool = False, directory: bool | None = None) -> Path:
        value = str(raw or "").strip()
        if not value:
            raise LivingMachinePolicyError("path is required")
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        candidate = candidate.resolve(strict=False)
        if not any(self._within(candidate, root) for root in self.workspace_roots):
            raise LivingMachinePolicyError("path is outside Aether allowed roots")
        if self._secret_path(candidate):
            raise LivingMachinePolicyError("secret-bearing paths are denied")
        if must_exist and not candidate.exists():
            raise LivingMachinePolicyError("path does not exist")
        if directory is True and not candidate.is_dir():
            raise LivingMachinePolicyError("path must be a directory")
        if directory is False and not candidate.is_file():
            raise LivingMachinePolicyError("path must be a regular file")
        return candidate

    @staticmethod
    def _within(candidate: Path, root: Path) -> bool:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _secret_path(path: Path) -> bool:
        return any(_SECRET_NAME.search(part) for part in path.parts)

    def capability_manifest(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authority": "Aether governance remains authoritative",
            "capability_classes": ["READ", "DIAGNOSTIC", "VERIFY", "MUTATE"],
            "default_remote_scopes": ["read", "diagnostic"],
            "mutation": "requires dedicated mutation/operator credential and GovernedActionPath approval",
            "shell": False,
            "secrets": False,
            "workspace_roots": [str(p) for p in self.workspace_roots],
            "tools": [
                "workspace_list", "workspace_tree", "file_read", "file_search", "file_glob", "file_hash",
                "runtime_status", "runtime_health", "runtime_adapters", "runtime_telemetry",
                "service_status", "logs_tail", "run_verification", "get_verification_receipt", "get_runtime_task",
                "workspace_edit", "workspace_apply_patch", "workspace_rollback", "git_status", "git_diff", "git_log",
            ],
            "resources": [
                "aether://runtime/status", "aether://runtime/adapters", "aether://runtime/telemetry",
                "aether://workspace/{workspace_id}/manifest",
            ],
        }

    def workspace_list(self, limit: int = 100) -> dict[str, Any]:
        bindings = self.workspace_bindings.list_bindings(limit=max(1, min(int(limit), 1000)))
        return {"count": len(bindings), "workspaces": [self._binding_dict(b) for b in bindings]}

    def _binding_dict(self, binding: WorkspaceBinding) -> dict[str, Any]:
        return {
            "workspace_id": binding.workspace_id,
            "binding_id": binding.binding_id,
            "root_path": binding.root_path,
            "allowed_relative_paths": list(binding.allowed_relative_paths),
            "writable": bool(binding.writable),
            "metadata": _json(binding.metadata),
        }

    def workspace_manifest(self, workspace_id: str, session_id: str | None = None) -> dict[str, Any]:
        bindings = self.workspace_bindings.list_bindings(limit=1000)
        for binding in bindings:
            if binding.workspace_id == workspace_id:
                if session_id and binding.session_id != session_id:
                    raise LivingMachinePolicyError("workspace binding belongs to another session")
                return self._binding_dict(binding)
        raise LivingMachinePolicyError("workspace binding not found")

    def workspace_tree(self, path: str = ".", depth: int = 3, limit: int = 200) -> dict[str, Any]:
        root = self._safe_path(path, must_exist=True, directory=True)
        depth = max(0, min(int(depth), 8)); limit = max(1, min(int(limit), self.max_search_results * 5))
        items: list[dict[str, Any]] = []
        for candidate in sorted(root.rglob("*"), key=lambda p: str(p).casefold()):
            if len(items) >= limit:
                break
            if self._secret_path(candidate) or not self._within(candidate.resolve(strict=False), root):
                continue
            try:
                rel = candidate.relative_to(root)
            except ValueError:
                continue
            if len(rel.parts) > depth:
                continue
            items.append({"path": rel.as_posix(), "kind": "directory" if candidate.is_dir() else "file"})
        return {"root": str(root), "items": items, "truncated": len(items) >= limit}

    def file_read(self, path: str, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
        candidate = self._safe_path(path, must_exist=True, directory=False)
        if candidate.stat().st_size > self.max_file_bytes:
            raise LivingMachinePolicyError("file exceeds MCP read size limit")
        text = candidate.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(1, int(start_line)); end = len(lines) if end_line is None else max(start, min(int(end_line), start + 5000))
        return {"path": str(candidate), "start_line": start, "end_line": min(end, len(lines)), "content": "\n".join(lines[start-1:end]), "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}

    def file_hash(self, path: str) -> dict[str, Any]:
        candidate = self._safe_path(path, must_exist=True, directory=False)
        digest = hashlib.sha256(); size = 0
        with candidate.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                size += len(chunk); digest.update(chunk)
        return {"path": str(candidate), "size_bytes": size, "sha256": digest.hexdigest()}

    def file_glob(self, pattern: str, root: str = ".", limit: int = 100) -> dict[str, Any]:
        base = self._safe_path(root, must_exist=True, directory=True)
        if len(pattern) > 300 or pattern.startswith("/"):
            raise LivingMachinePolicyError("invalid glob pattern")
        hits: list[str] = []
        for candidate in base.rglob("*"):
            if len(hits) >= min(max(1, int(limit)), self.max_search_results): break
            if self._secret_path(candidate): continue
            if self._within(candidate.resolve(strict=False), base) and fnmatch.fnmatch(candidate.relative_to(base).as_posix(), pattern):
                hits.append(candidate.relative_to(base).as_posix())
        return {"root": str(base), "pattern": pattern, "matches": hits, "truncated": len(hits) >= limit}

    def file_search(self, query: str, root: str = ".", limit: int = 50) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query or len(query) > 500: raise LivingMachinePolicyError("query is required and bounded")
        base = self._safe_path(root, must_exist=True, directory=True)
        hits: list[dict[str, Any]] = []
        needle = query.casefold()
        for candidate in base.rglob("*"):
            if len(hits) >= min(max(1, int(limit)), self.max_search_results) or self._secret_path(candidate) or not candidate.is_file(): continue
            if candidate.stat().st_size > self.max_file_bytes: continue
            try: text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError: continue
            if needle in text.casefold() or needle in candidate.name.casefold():
                line = next((i for i, v in enumerate(text.splitlines(), 1) if needle in v.casefold()), 0)
                hits.append({"path": candidate.relative_to(base).as_posix(), "line": line})
        return {"root": str(base), "query": query, "matches": hits, "truncated": len(hits) >= limit}

    async def runtime_adapters(self) -> dict[str, Any]:
        descriptors = await self.runtime_registry.discover()
        return {"count": len(descriptors), "adapters": [_json(d) for d in descriptors]}

    def runtime_telemetry(self, limit: int = 50) -> dict[str, Any]:
        rows = self.runtime_telemetry.list_invocations(limit=max(1, min(int(limit), 200)))
        return {"count": len(rows), "invocations": [redact(json.dumps(_json(r), ensure_ascii=False)) for r in rows]}

    async def runtime_health(self) -> dict[str, Any]:
        return await self.runtime_adapters()

    async def runtime_status(self) -> dict[str, Any]:
        adapters = await self.runtime_adapters()
        return {"schema": self.schema, "telemetry": dict(self.runtime_telemetry.status()), "adapters": adapters}

    def service_status(self) -> dict[str, Any]:
        services: list[dict[str, Any]] = []
        for name, url in (("gateway", os.environ.get("AETHER_MCP_GATEWAY_HEALTH_URL", "http://127.0.0.1:8000/health")),):
            try:
                from urllib.request import urlopen
                with urlopen(url, timeout=2) as response:
                    services.append({"name": name, "ok": response.status < 500, "status_code": response.status})
            except Exception as exc:
                services.append({"name": name, "ok": False, "error": type(exc).__name__})
        return {"services": services}

    def logs_tail(self, component: str, lines: int = 200, since: str | None = None) -> dict[str, Any]:
        lines = max(1, min(int(lines), self.max_log_lines)); needle = str(component or "").strip()
        if not needle or _SECRET_NAME.search(needle): raise LivingMachinePolicyError("invalid component")
        candidates: list[Path] = []
        for root in self.log_roots:
            if root.is_dir():
                candidates.extend(p for p in root.rglob("*") if p.is_file() and needle.casefold() in p.name.casefold() and not self._secret_path(p))
        if not candidates: return {"component": component, "found": False, "lines": [], "reason": "log-not-found"}
        target = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        raw = target.read_bytes()[-self.max_log_bytes:]
        content = raw.decode("utf-8", errors="replace").splitlines()[-lines:]
        return {"component": component, "path": str(target), "lines": [redact(x) for x in content], "truncated": len(raw) >= self.max_log_bytes}

    def git_status(self) -> dict[str, Any]:
        return self._git(["status", "--short", "--branch"])

    def git_diff(self, staged: bool = False, path: str | None = None) -> dict[str, Any]:
        args = ["diff"] + (["--cached"] if staged else []) + (["--", path] if path else [])
        result = self._git(args, max_output=30000)
        return result

    def git_log(self, limit: int = 20) -> dict[str, Any]:
        return self._git(["log", "-n", str(max(1, min(int(limit), 100))), "--oneline", "--decorate"])

    def _git(self, args: list[str], max_output: int = 10000) -> dict[str, Any]:
        proc = subprocess.run(["git", "-C", str(self.project_root), *args], capture_output=True, text=True, timeout=10, check=False)
        return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": redact(proc.stdout[-max_output:]), "stderr": redact(proc.stderr[-max_output:])}

    async def run_verification(self, workspace_id: str, session_id: str, verification_id: str) -> dict[str, Any]:
        # Verification is deliberately allowlisted by configuration. The MCP surface never accepts arbitrary shell text.
        raw = os.environ.get("AETHER_MCP_VERIFICATIONS", "{}"); registry = json.loads(raw or "{}")
        spec = registry.get(verification_id)
        if not isinstance(spec, Mapping) or not isinstance(spec.get("argv"), list):
            raise LivingMachinePolicyError("verification_id is not registered")
        binding = self.workspace_bindings.resolve(workspace_id, session_id)
        argv = tuple(str(x) for x in spec["argv"])
        if not argv or any(not x.strip() for x in argv): raise LivingMachinePolicyError("invalid verification argv")
        # Execute only the exact configured argv; no shell and bounded output.
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(*argv, cwd=binding.root_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=self._sanitized_env())
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=min(300.0, max(1.0, float(spec.get("timeout_seconds", 120)))))
        except asyncio.TimeoutError:
            proc.kill(); await proc.communicate()
            return {"ok": False, "verification_id": verification_id, "timed_out": True, "duration_seconds": time.monotonic() - started}
        return {"ok": proc.returncode == 0, "verification_id": verification_id, "exit_code": proc.returncode, "stdout": redact(out.decode(errors="replace")[-16000:]), "stderr": redact(err.decode(errors="replace")[-16000:]), "duration_seconds": time.monotonic() - started}

    def get_verification_receipt(self, invocation_id: str) -> dict[str, Any]:
        for row in self.runtime_telemetry.list_invocations(limit=1000):
            if row.get("invocation_id") == invocation_id:
                return {"found": True, "receipt": redact(json.dumps(_json(row), ensure_ascii=False))}
        return {"found": False, "invocation_id": invocation_id}

    def get_runtime_task(self, task_id: str) -> dict[str, Any]:
        for row in self.runtime_telemetry.list_invocations(limit=1000):
            if row.get("task_id") == task_id:
                return {"found": True, "task": redact(json.dumps(_json(row), ensure_ascii=False))}
        return {"found": False, "task_id": task_id}

    async def workspace_edit(self, *, workspace_id: str, session_id: str, edits: list[Mapping[str, Any]], verification_commands: list[Mapping[str, Any]], reason: str, operator: str, approval_token: str | None) -> dict[str, Any]:
        binding = self.workspace_bindings.resolve(workspace_id, session_id)
        self._require_operator(approval_token)
        proposal = ActionProposal(
            target=ActionTarget.RUNTIME, operation="coding.task.execute",
            arguments={"task": {"task_id": uuid.uuid4().hex, "workspace_id": workspace_id, "session_id": session_id, "edits": edits, "verification_commands": verification_commands}, "workspace_binding": _json(binding)},
            required_scopes=(ActionScope.WRITE, ActionScope.EXECUTE), reason=reason,
            risk=ActionRisk.MEDIUM, reversible=True, metadata={"mcp": True, "workspace_id": workspace_id},
        )
        approval = ActionApproval(
            principal=operator, scopes=(ActionScope.WRITE, ActionScope.EXECUTE), reason="explicit MCP operator authorization",
            action_hash=__import__("aether.contracts.actions", fromlist=["canonical_action_hash"]).canonical_action_hash(proposal),
            channel="mcp",
        )
        result = await self.action_path.execute(proposal, approval)
        return _json(result)

    async def workspace_apply_patch(self, **kwargs: Any) -> dict[str, Any]:
        return await self.workspace_edit(**kwargs)

    async def workspace_rollback(self, task_id: str, workspace_id: str, session_id: str, reason: str, operator: str, approval_token: str | None) -> dict[str, Any]:
        # Rollback is intentionally a governed coding operation rather than a filesystem delete.
        task = self.get_runtime_task(task_id)
        if not task.get("found"):
            raise LivingMachinePolicyError("runtime task not found")
        raise LivingMachinePolicyError("rollback is evidence-bound to the runtime task and is only exposed after a governed failed verification; use the task receipt's rollback_performed result")

    def _require_operator(self, supplied: str | None) -> None:
        expected = os.environ.get("AETHER_MCP_OPERATOR_TOKEN", "").strip()
        if not expected or not supplied or not hmac.compare_digest(supplied, expected):
            raise LivingMachinePolicyError("explicit MCP operator authorization required")

    @staticmethod
    def _sanitized_env() -> dict[str, str]:
        allow = {"PATH", "SystemRoot", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "PYTHONPATH", "VIRTUAL_ENV"}
        return {k: v for k, v in os.environ.items() if k in allow}
