"""Local benchmark and runtime projection adapters for Aether-owned skills.

Filesystem-copy sandboxing is not equivalent to container/VM isolation. Commands
are allowlisted and never executed through a shell.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

from aether.contracts.evolution import EvolutionCheckResult
from aether.contracts.skills import (
    SkillBenchmark, SkillCandidate, SkillInstallReceipt, SkillRecord,
    canonical_manifest_payload,
)
from aether.utils.ids import new_id


class SkillWorkspaceError(RuntimeError):
    pass


def _slug(name: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in name).strip("-")
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    if not normalized:
        raise SkillWorkspaceError("skill name cannot be converted to a safe slug")
    return normalized


def _ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {".git", ".pytest_cache", "__pycache__", "dist", "build", ".mypy_cache", ".ruff_cache"}
    return {name for name in names if name in ignored or name.endswith(".pyc")}


class LocalSkillBenchmarkSandbox:
    adapter_id = "aether.skills.sandbox.local-filesystem"

    def __init__(self, workspace_root: Path, sandbox_root: Path, *, max_output_chars: int = 12000) -> None:
        self.workspace_root = workspace_root.resolve()
        self.sandbox_root = sandbox_root.resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.max_output_chars = max_output_chars

    async def benchmark(self, candidate: SkillCandidate, baseline: SkillRecord | None = None) -> SkillBenchmark:
        sandbox_id = new_id("skill-sandbox")
        base_dir = self.sandbox_root / sandbox_id
        baseline_dir = base_dir / "baseline"
        candidate_dir = base_dir / "candidate"
        shutil.copytree(self.workspace_root, baseline_dir, ignore=_ignore)
        shutil.copytree(self.workspace_root, candidate_dir, ignore=_ignore)
        if baseline is not None:
            self._write_artifact(baseline_dir, baseline.manifest.name, canonical_manifest_payload(baseline.manifest))
        self._write_artifact(candidate_dir, candidate.manifest.name, canonical_manifest_payload(candidate.manifest))

        results: list[EvolutionCheckResult] = []
        for phase, root in (("baseline", baseline_dir), ("candidate", candidate_dir)):
            for command in (*candidate.deterministic_checks, *candidate.heldout_checks):
                results.append(await self._run(command, root, phase))

        baseline_results = [item for item in results if item.phase == "baseline"]
        candidate_results = [item for item in results if item.phase == "candidate"]
        baseline_score = sum(item.passed for item in baseline_results) / max(1, len(baseline_results))
        candidate_score = sum(item.passed for item in candidate_results) / max(1, len(candidate_results))
        regressions = sum(
            before.passed and not after.passed
            for before, after in zip(baseline_results, candidate_results, strict=True)
        )
        blockers: list[str] = []
        if not all(item.passed for item in candidate_results):
            blockers.append("candidate skill did not pass every deterministic and held-out check")
        if regressions:
            blockers.append(f"candidate skill introduced {regressions} regression(s)")
        return SkillBenchmark(
            candidate_id=candidate.candidate_id,
            sandbox_id=sandbox_id,
            baseline_score=baseline_score,
            candidate_score=candidate_score,
            improvement=candidate_score - baseline_score,
            regression_count=regressions,
            checks=tuple(results),
            passed=not blockers,
            blockers=tuple(blockers),
            metadata={
                "adapter_id": self.adapter_id,
                "baseline_dir": str(baseline_dir),
                "candidate_dir": str(candidate_dir),
                "artifact_relative_path": str(self._artifact_relative(candidate.manifest.name)),
                "isolation": "filesystem-copy-plus-command-allowlist",
                "network_isolation": False,
            },
        )

    @staticmethod
    def _artifact_relative(name: str) -> Path:
        return Path(".aether") / "skills" / f"{_slug(name)}.json"

    def _write_artifact(self, root: Path, name: str, payload: dict) -> Path:
        path = root / self._artifact_relative(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return path

    async def _run(self, command, cwd: Path, phase: str) -> EvolutionCheckResult:
        argv = self._validated_argv(tuple(command.argv))
        started = time.monotonic()
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=command.timeout_seconds)
            exit_code = int(process.returncode or 0)
        except asyncio.TimeoutError:
            if process is not None:
                process.kill()
                await process.wait()
            stdout, stderr, exit_code = b"", b"command timed out", 124
        duration = time.monotonic() - started
        return EvolutionCheckResult(
            name=command.name,
            kind=command.kind,
            phase=phase,
            passed=exit_code == 0,
            exit_code=exit_code,
            duration_seconds=duration,
            stdout=stdout.decode("utf-8", errors="replace")[-self.max_output_chars:],
            stderr=stderr.decode("utf-8", errors="replace")[-self.max_output_chars:],
        )

    @staticmethod
    def _validated_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
        if len(argv) < 3:
            raise SkillWorkspaceError("skill benchmark command is incomplete")
        executable = argv[0]
        if executable in {"{python}", "python", "python3", sys.executable}:
            executable = sys.executable
        else:
            raise SkillWorkspaceError("only the configured Python interpreter may run skill benchmarks")
        if argv[1] != "-m" or argv[2] not in {"pytest", "unittest", "compileall"}:
            raise SkillWorkspaceError("only python -m pytest|unittest|compileall benchmarks are allowed")
        if any(item in {"-c", "--pdb", "--trace"} for item in argv[3:]):
            raise SkillWorkspaceError("unsafe Python benchmark option is not allowed")
        return (executable, *argv[1:])


class LocalRuntimeSkillInstaller:
    """Projects Aether skill manifests into a local runtime directory.

    Projection files are retained on archive or rollback. Only the active pointer
    changes, satisfying the no-automatic-deletion invariant.
    """

    adapter_id = "aether.skills.installer.local-runtime"

    def __init__(self, registry_root: Path) -> None:
        self.registry_root = registry_root.resolve()
        self.registry_root.mkdir(parents=True, exist_ok=True)
        (self.registry_root / "active").mkdir(exist_ok=True)
        (self.registry_root / "inactive").mkdir(exist_ok=True)

    async def install(self, candidate: SkillCandidate) -> SkillInstallReceipt:
        slug = _slug(candidate.manifest.name)
        version_dir = self.registry_root / "artifacts" / slug
        version_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = version_dir / f"{candidate.manifest.version}-{candidate.artifact_hash[:12]}.json"
        if not artifact_path.exists():
            artifact_path.write_text(
                json.dumps(canonical_manifest_payload(candidate.manifest), indent=2, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        pointer = self.registry_root / "active" / f"{slug}.json"
        previous = pointer.read_text(encoding="utf-8") if pointer.exists() else None
        payload = {
            "candidate_id": candidate.candidate_id,
            "artifact_hash": candidate.artifact_hash,
            "artifact_path": str(artifact_path),
            "name": candidate.manifest.name,
            "version": candidate.manifest.version,
            "adapter_id": self.adapter_id,
        }
        temporary = pointer.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temporary, pointer)
        return SkillInstallReceipt(
            adapter_id=self.adapter_id,
            install_path=str(artifact_path),
            activation_pointer=str(pointer),
            previous_pointer_content=previous,
            metadata={"retention": "no-automatic-deletion"},
        )

    async def deactivate(self, record: SkillRecord, *, reason: str) -> None:
        pointer = Path(record.install_receipt.activation_pointer)
        inactive = self.registry_root / "inactive" / f"{record.skill_id}.json"
        inactive.write_text(json.dumps({
            "skill_id": record.skill_id,
            "artifact_hash": record.artifact_hash,
            "install_path": record.install_receipt.install_path,
            "reason": reason,
            "status": "archived",
        }, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        if pointer.exists():
            current = json.loads(pointer.read_text(encoding="utf-8"))
            if current.get("artifact_hash") == record.artifact_hash:
                pointer.write_text(json.dumps({
                    "name": record.manifest.name,
                    "status": "archived",
                    "last_artifact_hash": record.artifact_hash,
                    "retained_artifact": record.install_receipt.install_path,
                }, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    async def rollback_install(self, receipt: SkillInstallReceipt) -> None:
        pointer = Path(receipt.activation_pointer)
        if receipt.previous_pointer_content is not None:
            pointer.write_text(receipt.previous_pointer_content, encoding="utf-8")
        elif pointer.exists():
            pointer.write_text(json.dumps({
                "status": "rollback-no-active-skill",
                "retained_artifact": receipt.install_path,
            }, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
