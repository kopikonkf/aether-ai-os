"""Cross-platform local adapters for governed internal evolution.

This is filesystem/process isolation, not a security boundary equivalent to a
container or VM. Commands are allowlisted and never executed through a shell.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

from aether.contracts.evolution import (
    EvolutionCandidate, EvolutionCheckResult, EvolutionEvaluation, EvolutionLineage,
    PromotionReceipt, content_hash,
)
from aether.utils.ids import new_id


class EvolutionWorkspaceError(RuntimeError):
    pass


def _safe_target(root: Path, relative: str) -> Path:
    root = root.resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise EvolutionWorkspaceError("target escapes the configured evolution workspace") from exc
    if target.is_symlink():
        raise EvolutionWorkspaceError("symlink targets are not allowed")
    return target


def _ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {".git", ".pytest_cache", "__pycache__", "dist", "build", ".mypy_cache", ".ruff_cache"}
    return {name for name in names if name in ignored or name.endswith(".pyc")}


class LocalEvolutionSandbox:
    adapter_id = "aether.evolution.sandbox.local-filesystem"

    def __init__(self, workspace_root: Path, sandbox_root: Path, *, max_output_chars: int = 12000) -> None:
        self.workspace_root = workspace_root.resolve()
        self.sandbox_root = sandbox_root.resolve()
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.max_output_chars = max_output_chars

    async def evaluate(self, candidate: EvolutionCandidate) -> EvolutionEvaluation:
        source_target = _safe_target(self.workspace_root, candidate.target_path)
        if not source_target.is_file():
            raise EvolutionWorkspaceError(f"target does not exist: {candidate.target_path}")
        actual = source_target.read_text(encoding="utf-8")
        if content_hash(actual) != candidate.baseline_hash:
            raise EvolutionWorkspaceError("workspace baseline changed after candidate proposal")

        sandbox_id = new_id("evo-sandbox")
        base_dir = self.sandbox_root / sandbox_id
        baseline_dir = base_dir / "baseline"
        candidate_dir = base_dir / "candidate"
        shutil.copytree(self.workspace_root, baseline_dir, ignore=_ignore)
        shutil.copytree(self.workspace_root, candidate_dir, ignore=_ignore)
        candidate_target = _safe_target(candidate_dir, candidate.target_path)
        candidate_target.parent.mkdir(parents=True, exist_ok=True)
        candidate_target.write_text(candidate.candidate_content, encoding="utf-8")

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
            blockers.append("candidate did not pass every deterministic and held-out check")
        if regressions:
            blockers.append(f"candidate introduced {regressions} regression(s)")
        return EvolutionEvaluation(
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
                "isolation": "filesystem-copy-plus-command-allowlist",
                "network_isolation": False,
            },
        )

    async def _run(self, command, cwd: Path, phase: str) -> EvolutionCheckResult:
        argv = self._validated_argv(tuple(command.argv))
        started = time.monotonic()
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
            raise EvolutionWorkspaceError("evolution check command is incomplete")
        executable = argv[0]
        if executable in {"{python}", "python", "python3", sys.executable}:
            executable = sys.executable
        else:
            raise EvolutionWorkspaceError("only the configured Python interpreter may run evolution checks")
        if argv[1] != "-m" or argv[2] not in {"pytest", "unittest", "compileall"}:
            raise EvolutionWorkspaceError("only python -m pytest|unittest|compileall checks are allowed")
        if any(item in {"-c", "--pdb", "--trace"} for item in argv[3:]):
            raise EvolutionWorkspaceError("unsafe Python check option is not allowed")
        return (executable, *argv[1:])


class LocalArtifactPromoter:
    adapter_id = "aether.evolution.promoter.local-atomic"

    def __init__(self, workspace_root: Path, backup_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self.backup_root = backup_root.resolve()
        self.backup_root.mkdir(parents=True, exist_ok=True)

    async def promote(self, candidate: EvolutionCandidate) -> PromotionReceipt:
        target = _safe_target(self.workspace_root, candidate.target_path)
        if not target.is_file():
            raise EvolutionWorkspaceError(f"target does not exist: {candidate.target_path}")
        baseline = target.read_text(encoding="utf-8")
        if content_hash(baseline) != candidate.baseline_hash:
            raise EvolutionWorkspaceError("production baseline changed; candidate must be regenerated")
        if content_hash(candidate.candidate_content) != candidate.candidate_hash:
            raise EvolutionWorkspaceError("candidate content hash mismatch")

        backup = self.backup_root / candidate.candidate_id / candidate.target_path
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(baseline, encoding="utf-8")
        temporary = target.with_name(f".{target.name}.{candidate.candidate_id}.tmp")
        temporary.write_text(candidate.candidate_content, encoding="utf-8")
        os.replace(temporary, target)
        return PromotionReceipt(
            target_path=candidate.target_path,
            parent_hash=candidate.baseline_hash,
            promoted_hash=candidate.candidate_hash,
            backup_path=str(backup),
        )

    async def rollback(self, lineage: EvolutionLineage) -> None:
        target = _safe_target(self.workspace_root, lineage.target_path)
        if not target.is_file():
            raise EvolutionWorkspaceError("promoted target no longer exists")
        current = target.read_text(encoding="utf-8")
        if content_hash(current) != lineage.promoted_hash:
            raise EvolutionWorkspaceError("current artifact diverged after promotion; automatic rollback is blocked")
        backup = Path(lineage.backup_path)
        if not backup.is_file():
            raise EvolutionWorkspaceError("rollback backup is missing")
        baseline = backup.read_text(encoding="utf-8")
        if content_hash(baseline) != lineage.parent_hash:
            raise EvolutionWorkspaceError("rollback backup hash mismatch")
        temporary = target.with_name(f".{target.name}.{lineage.lineage_id}.rollback.tmp")
        temporary.write_text(baseline, encoding="utf-8")
        os.replace(temporary, target)
