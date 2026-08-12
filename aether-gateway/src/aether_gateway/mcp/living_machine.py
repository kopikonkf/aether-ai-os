"""Bounded capability plane for the live Aether machine."""
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
from pathlib import Path
from typing import Any, Iterable, Mapping

from aether.contracts import ActionProposal, ActionRisk, ActionScope, ActionTarget
from aether.contracts.coding_runtime import WorkspaceBinding

_SECRET_NAME = re.compile(r"(^|[._-])(\.env|env|secret|credential|credentials|token|password|passwd|apikey|api-key|private-key|id_rsa|id_ed25519)($|[._-])", re.I)
_SECRET_TEXT = re.compile(r"(authorization\s*:\s*bearer\s+|api[_-]?key\s*[:=]\s*|token\s*[:=]\s*|password\s*[:=]\s*)[^\s,;]+", re.I)


class LivingMachinePolicyError(PermissionError):
    """MCP request violates the live-machine capability boundary."""


def redact(text: str) -> str:
    return _SECRET_TEXT.sub(r"\1[REDACTED]", text)


def safe_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [safe_json(v) for v in value]
    if hasattr(value, "value"):
        return safe_json(value.value)
    if isinstance(value, Path):
        return str(value)
    return value


class LivingMachineMCPService:
    schema = "aether.mcp.living-machine.v1"

    def __init__(self, *, project_root: Path, aether_home: Path, workspace_roots: Iterable[Path], workspace_bindings: Any, runtime_registry: Any, runtime_telemetry: Any, action_path: Any, coding_runtime_key: str | None = None) -> None:
        self.project_root = project_root.resolve()
        self.aether_home = aether_home.resolve()
        self.roots = tuple(dict.fromkeys([p.expanduser().resolve() for p in workspace_roots] + [self.project_root, self.aether_home]))
        self.bindings = workspace_bindings
        self.registry = runtime_registry
        self.telemetry = runtime_telemetry
        self.action_path = action_path
        self.coding_runtime_key = coding_runtime_key
        self.max_file_bytes = int(os.getenv("AETHER_MCP_MAX_FILE_BYTES", "262144"))
        self.max_results = int(os.getenv("AETHER_MCP_MAX_RESULTS", "100"))
        self.max_log_bytes = int(os.getenv("AETHER_MCP_MAX_LOG_BYTES", "262144"))
        self.max_log_lines = int(os.getenv("AETHER_MCP_MAX_LOG_LINES", "500"))
        configured_logs = [Path(x).expanduser().resolve() for x in os.getenv("AETHER_MCP_LOG_ROOTS", "").split(os.pathsep) if x.strip()]
        self.log_roots = tuple(configured_logs or [self.aether_home / "logs", self.aether_home / "runtime"])

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _secret_path(path: Path) -> bool:
        return any(_SECRET_NAME.search(part) for part in path.parts)

    def _path(self, raw: str, *, exists: bool = False, file: bool | None = None) -> Path:
        value = str(raw or "").strip()
        if not value:
            raise LivingMachinePolicyError("path is required")
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.project_root / path
        path = path.resolve(strict=False)
        if not any(self._inside(path, root) for root in self.roots):
            raise LivingMachinePolicyError("path is outside allowed Aether roots")
        if self._secret_path(path):
            raise LivingMachinePolicyError("secret-bearing paths are denied")
        if exists and not path.exists():
            raise LivingMachinePolicyError("path does not exist")
        if file is True and not path.is_file():
            raise LivingMachinePolicyError("path must be a file")
        if file is False and not path.is_dir():
            raise LivingMachinePolicyError("path must be a directory")
        return path

    def capability_manifest(self) -> dict[str, Any]:
        return {"schema": self.schema, "authority": "Aether governance", "capability_classes": ["READ", "DIAGNOSTIC", "VERIFY", "MUTATE"], "default_remote_scopes": ["read", "diagnostic"], "mutation_authority": "operator token submission + GovernedActionPath + Trusted Approval Inbox (human decision required)", "shell": False, "secrets": False, "tools": ["workspace_list", "workspace_tree", "file_read", "file_search", "file_glob", "file_hash", "runtime_status", "runtime_health", "runtime_adapters", "runtime_telemetry", "service_status", "logs_tail", "run_verification", "get_verification_receipt", "get_runtime_task", "workspace_edit", "workspace_apply_patch", "workspace_rollback", "git_status", "git_diff", "git_log"], "resources": ["aether://runtime/status", "aether://runtime/adapters", "aether://runtime/telemetry", "aether://workspace/{workspace_id}/manifest"]}

    @staticmethod
    def binding_dict(binding: WorkspaceBinding) -> dict[str, Any]:
        return {"workspace_id": binding.workspace_id, "binding_id": binding.binding_id, "root_path": binding.root_path, "allowed_relative_paths": list(binding.allowed_relative_paths), "writable": binding.writable, "metadata": safe_json(binding.metadata)}

    def workspace_list(self, limit: int = 100) -> dict[str, Any]:
        rows = self.bindings.list_bindings(limit=max(1, min(int(limit), 1000)))
        return {"count": len(rows), "workspaces": [self.binding_dict(x) for x in rows]}

    def workspace_manifest(self, workspace_id: str, session_id: str | None = None) -> dict[str, Any]:
        for binding in self.bindings.list_bindings(limit=1000):
            if binding.workspace_id == workspace_id:
                if session_id and binding.session_id != session_id:
                    raise LivingMachinePolicyError("workspace belongs to another session")
                return self.binding_dict(binding)
        raise LivingMachinePolicyError("workspace binding not found")

    def workspace_tree(self, path: str = ".", depth: int = 3, limit: int = 200) -> dict[str, Any]:
        root = self._path(path, exists=True, file=False); depth = max(0, min(int(depth), 8)); limit = max(1, min(int(limit), self.max_results))
        items = []
        for item in sorted(root.rglob("*"), key=lambda p: str(p).casefold()):
            if len(items) >= limit or self._secret_path(item): continue
            resolved = item.resolve(strict=False)
            if not self._inside(resolved, root): continue
            rel = resolved.relative_to(root)
            if len(rel.parts) <= depth: items.append({"path": rel.as_posix(), "kind": "directory" if item.is_dir() else "file"})
        return {"root": str(root), "items": items, "truncated": len(items) >= limit}

    def file_read(self, path: str, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
        target = self._path(path, exists=True, file=True)
        if target.stat().st_size > self.max_file_bytes: raise LivingMachinePolicyError("file exceeds size limit")
        text = target.read_text(encoding="utf-8", errors="replace"); lines = text.splitlines(); start = max(1, int(start_line)); end = len(lines) if end_line is None else min(len(lines), max(start, int(end_line)))
        return {"path": str(target), "start_line": start, "end_line": end, "content": "\n".join(lines[start-1:end]), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}

    def file_hash(self, path: str) -> dict[str, Any]:
        target = self._path(path, exists=True, file=True); digest = hashlib.sha256(); size = 0
        with target.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""): size += len(chunk); digest.update(chunk)
        return {"path": str(target), "size_bytes": size, "sha256": digest.hexdigest()}

    def file_glob(self, pattern: str, root: str = ".", limit: int = 100) -> dict[str, Any]:
        base = self._path(root, exists=True, file=False); limit = max(1, min(int(limit), self.max_results)); hits = []
        if len(pattern) > 300: raise LivingMachinePolicyError("glob pattern too long")
        for item in base.rglob("*"):
            if len(hits) >= limit or self._secret_path(item): continue
            resolved = item.resolve(strict=False)
            if self._inside(resolved, base) and fnmatch.fnmatch(resolved.relative_to(base).as_posix(), pattern): hits.append(resolved.relative_to(base).as_posix())
        return {"root": str(base), "pattern": pattern, "matches": hits, "truncated": len(hits) >= limit}

    def file_search(self, query: str, root: str = ".", limit: int = 50) -> dict[str, Any]:
        query = str(query or "").strip(); base = self._path(root, exists=True, file=False); limit = max(1, min(int(limit), self.max_results))
        if not query or len(query) > 500: raise LivingMachinePolicyError("query is required and bounded")
        needle = query.casefold(); hits = []
        for item in base.rglob("*"):
            if len(hits) >= limit or self._secret_path(item) or not item.is_file() or item.stat().st_size > self.max_file_bytes: continue
            try: text = item.read_text(encoding="utf-8", errors="replace")
            except OSError: continue
            if needle in text.casefold() or needle in item.name.casefold(): hits.append({"path": item.relative_to(base).as_posix(), "line": next((i for i, line in enumerate(text.splitlines(), 1) if needle in line.casefold()), 0)})
        return {"root": str(base), "query": query, "matches": hits, "truncated": len(hits) >= limit}

    async def runtime_adapters(self) -> dict[str, Any]:
        descriptors = await self.registry.discover(); return {"count": len(descriptors), "adapters": [safe_json(x) for x in descriptors]}

    async def runtime_status(self) -> dict[str, Any]:
        return {"schema": self.schema, "telemetry": dict(self.telemetry.status()), "adapters": (await self.runtime_adapters())["adapters"]}

    async def runtime_health(self) -> dict[str, Any]:
        return await self.runtime_adapters()

    def runtime_telemetry(self, limit: int = 50) -> dict[str, Any]:
        rows = self.telemetry.list_invocations(limit=max(1, min(int(limit), 200))); return {"count": len(rows), "invocations": [safe_json(x) for x in rows]}

    def service_status(self) -> dict[str, Any]:
        from urllib.request import urlopen
        url = os.getenv("AETHER_MCP_GATEWAY_HEALTH_URL", "http://127.0.0.1:8000/health")
        try:
            with urlopen(url, timeout=2) as response: return {"gateway": {"ok": response.status < 500, "status_code": response.status}}
        except Exception as exc: return {"gateway": {"ok": False, "error": type(exc).__name__}}

    def logs_tail(self, component: str, lines: int = 200, since: str | None = None) -> dict[str, Any]:
        name = str(component or "").strip(); lines = max(1, min(int(lines), self.max_log_lines))
        if not name or _SECRET_NAME.search(name): raise LivingMachinePolicyError("invalid log component")
        candidates = [p for root in self.log_roots if root.is_dir() for p in root.rglob("*") if p.is_file() and name.casefold() in p.name.casefold() and not self._secret_path(p)]
        if not candidates: return {"component": name, "found": False, "lines": []}
        target = max(candidates, key=lambda p: p.stat().st_mtime); raw = target.read_bytes()[-self.max_log_bytes:]
        return {"component": name, "path": str(target), "lines": [redact(x) for x in raw.decode("utf-8", errors="replace").splitlines()[-lines:]], "truncated": len(raw) >= self.max_log_bytes}

    def _git(self, args: list[str], maximum: int = 30000) -> dict[str, Any]:
        proc = subprocess.run(["git", "-C", str(self.project_root), *args], capture_output=True, text=True, timeout=10, check=False)
        return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": redact(proc.stdout[-maximum:]), "stderr": redact(proc.stderr[-maximum:])}

    def git_status(self) -> dict[str, Any]: return self._git(["status", "--short", "--branch"])
    def git_diff(self, staged: bool = False, path: str | None = None) -> dict[str, Any]: return self._git(["diff"] + (["--cached"] if staged else []) + (["--", path] if path else []))
    def git_log(self, limit: int = 20) -> dict[str, Any]: return self._git(["log", "-n", str(max(1, min(int(limit), 100))), "--oneline", "--decorate"])

    async def run_verification(self, workspace_id: str, session_id: str, verification_id: str) -> dict[str, Any]:
        registry = json.loads(os.getenv("AETHER_MCP_VERIFICATIONS", "{}")); spec = registry.get(verification_id)
        if not isinstance(spec, Mapping) or not isinstance(spec.get("argv"), list): raise LivingMachinePolicyError("verification is not registered")
        binding = self.bindings.resolve(workspace_id, session_id); argv = tuple(str(x) for x in spec["argv"])
        if not argv or any(not x.strip() for x in argv): raise LivingMachinePolicyError("invalid verification")
        started = time.monotonic(); proc = await asyncio.create_subprocess_exec(*argv, cwd=binding.root_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=self._sanitized_env())
        timeout = min(300.0, max(1.0, float(spec.get("timeout_seconds", 120))))
        try: out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill(); await proc.communicate(); return {"ok": False, "timed_out": True, "verification_id": verification_id, "duration_seconds": time.monotonic() - started}
        return {"ok": proc.returncode == 0, "verification_id": verification_id, "exit_code": proc.returncode, "stdout": redact(out.decode(errors="replace")[-16000:]), "stderr": redact(err.decode(errors="replace")[-16000:]), "duration_seconds": time.monotonic() - started}

    def get_verification_receipt(self, invocation_id: str) -> dict[str, Any]:
        for row in self.telemetry.list_invocations(limit=1000):
            if row.get("invocation_id") == invocation_id: return {"found": True, "receipt": safe_json(row)}
        return {"found": False, "invocation_id": invocation_id}

    def get_runtime_task(self, task_id: str) -> dict[str, Any]:
        for row in self.telemetry.list_invocations(limit=1000):
            if row.get("task_id") == task_id: return {"found": True, "task": safe_json(row)}
        return {"found": False, "task_id": task_id}

    async def workspace_edit(self, *, workspace_id: str, session_id: str, edits: list[Mapping[str, Any]], verification_commands: list[Mapping[str, Any]], reason: str, operator: str, operator_token: str | None) -> dict[str, Any]:
        # The operator token is request-level authentication: it authorizes the
        # right to SUBMIT a mutation, never to approve one. No ActionApproval is
        # synthesized here - if one were constructed from the operator token the
        # ActionGovernor would classify it as "human-approved" even though no
        # human decided anything (requester and approver would be the same entity).
        #
        # Instead the proposal is submitted WITHOUT an approval. Because
        # `write`/`execute` scopes are in action_policy.yaml approval_required and
        # the policy default is deny, the GovernedActionPath (which carries a
        # PendingActionStore) enqueues a durable pending-approval record. Only a
        # trusted human decision through the Trusted Approval Inbox / Telegram
        # may execute the edit. This is the same governed path used by every other
        # Aether mutation.
        self._operator(operator_token); binding = self.bindings.resolve(workspace_id, session_id)
        metadata: dict[str, Any] = {"mcp": True, "workspace_id": workspace_id, "channel": "mcp", "operator": operator, "session_id": session_id}
        if self.coding_runtime_key:
            metadata["runtime_id"] = self.coding_runtime_key
        proposal = ActionProposal(target=ActionTarget.RUNTIME, operation="coding.task.execute", arguments={"task": {"task_id": __import__("uuid").uuid4().hex, "workspace_id": workspace_id, "session_id": session_id, "edits": edits, "verification_commands": verification_commands}, "workspace_binding": safe_json(binding)}, required_scopes=(ActionScope.WRITE, ActionScope.EXECUTE), reason=reason, risk=ActionRisk.MEDIUM, reversible=True, metadata=metadata)
        result = await self.action_path.execute(proposal, None)
        if isinstance(result, Mapping):
            return result
        return {
            "action_id": result.action_id,
            "ok": bool(result.ok),
            "status": str(result.status),
            "error": result.error,
            "failure_fingerprint": result.failure_fingerprint,
            "metadata": safe_json(result.metadata),
        }

    async def workspace_apply_patch(self, **kwargs: Any) -> dict[str, Any]: return await self.workspace_edit(**kwargs)

    async def workspace_rollback(self, task_id: str, workspace_id: str, session_id: str, reason: str, operator: str, operator_token: str | None) -> dict[str, Any]:
        # The existing coding runtime performs atomic rollback automatically when verification fails.
        # Do not synthesize a second filesystem writer here; return the authoritative receipt.
        self._operator(operator_token); result = self.get_runtime_task(task_id)
        if not result.get("found"): raise LivingMachinePolicyError("runtime task not found")
        payload = result["task"].get("payload", {}) if isinstance(result.get("task"), Mapping) else {}
        if not payload.get("rollback_performed"): raise LivingMachinePolicyError("task has no runtime rollback receipt")
        return {"ok": True, "task_id": task_id, "rollback_performed": True, "receipt": result["task"]}

    @staticmethod
    def _sanitized_env() -> dict[str, str]:
        allow = {"PATH", "SystemRoot", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "PYTHONPATH", "VIRTUAL_ENV"}
        return {k: v for k, v in os.environ.items() if k in allow}

    @staticmethod
    def _operator(token: str | None) -> None:
        expected = os.getenv("AETHER_MCP_OPERATOR_TOKEN", "").strip()
        if not expected or not token or not hmac.compare_digest(token, expected): raise LivingMachinePolicyError("explicit MCP operator authorization required")
