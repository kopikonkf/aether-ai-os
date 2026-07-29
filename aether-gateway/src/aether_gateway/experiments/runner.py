"""Concrete no-shell reversible experiment runner with private preview deployment."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import secrets
import shutil
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from aether.contracts import (
    ExperimentArtifactReceipt, ExperimentBlocked, ExperimentRunReceipt, ExperimentStatus,
    ExperimentStepKind, ExperimentStepReceipt, ExperimentStepStatus,
    PreviewDeploymentReceipt, ReversibleExperimentPlan,
)
from aether.experiments import ReversibleExperimentEngine, SQLiteExperimentStore
from aether.utils.time import utc_now


def _safe_relative(value: str) -> Path:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise ExperimentBlocked((f"unsafe experiment path: {value}",))
    return Path(*candidate.parts)


class ReversibleExperimentRunner:
    """Executes a fixed operation set in disposable workspaces; never invokes arbitrary shell."""

    def __init__(self, root: str | Path, engine: ReversibleExperimentEngine) -> None:
        self.root = Path(root)
        self.engine = engine
        self.store: SQLiteExperimentStore = engine.store
        self.runs_root = self.root / "runs"
        self.previews_root = self.root / "previews"
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.previews_root.mkdir(parents=True, exist_ok=True)

    async def run(self, plan_id: str) -> tuple[ExperimentRunReceipt, str | None]:
        plan = self.store.get_plan(plan_id)
        existing = next((item for item in self.store.runs(limit=1000) if item.plan_id == plan_id and item.status in {ExperimentStatus.COMPLETED, ExperimentStatus.PREVIEW_READY}), None)
        if existing:
            return existing, None
        run_id = f"experiment-run-{secrets.token_hex(8)}"
        workspace = self.runs_root / run_id / "workspace"
        workspace.mkdir(parents=True, exist_ok=False)
        started = utc_now()
        started_monotonic = time.monotonic()
        receipt_ids: list[str] = []
        artifact_ids: list[str] = []
        preview_id: str | None = None
        preview_token: str | None = None
        total_cost = 0.0
        total_bytes = 0
        artifact_paths: set[str] = set()
        status = ExperimentStatus.RUNNING
        stop_reason = None
        try:
            for step in plan.steps:
                step_started = utc_now()
                step_status = ExperimentStepStatus.COMPLETED
                output: dict[str, Any] = {}
                error = None
                try:
                    if time.monotonic() - started_monotonic > plan.maximum_duration_seconds:
                        raise ExperimentBlocked(("experiment duration budget exceeded",))
                    if total_cost + step.estimated_cost_usd > plan.maximum_cost_usd:
                        raise ExperimentBlocked(("experiment budget exhausted before next step",))
                    if step.kind == ExperimentStepKind.WRITE_ARTIFACT:
                        files = dict(step.payload.get("files", {}))
                        if not files:
                            raise ExperimentBlocked(("write-artifact step requires files",))
                        for relative, content in files.items():
                            if time.monotonic() - started_monotonic > plan.maximum_duration_seconds:
                                raise ExperimentBlocked(("experiment duration budget exceeded",))
                            safe_path = _safe_relative(str(relative)).as_posix()
                            if safe_path not in artifact_paths and len(artifact_paths) >= plan.maximum_artifact_files:
                                raise ExperimentBlocked(("artifact file budget exceeded",))
                            target = (workspace / Path(safe_path)).resolve()
                            if workspace.resolve() not in target.parents:
                                raise ExperimentBlocked(("artifact escaped experiment workspace",))
                            encoded = str(content).encode("utf-8")
                            total_bytes += len(encoded)
                            if total_bytes > plan.maximum_artifact_bytes:
                                raise ExperimentBlocked(("artifact byte budget exceeded",))
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(encoded)
                            artifact_paths.add(safe_path)
                            artifact = self.store.add_artifact(ExperimentArtifactReceipt(
                                run_id=run_id, relative_path=target.relative_to(workspace).as_posix(),
                                content_hash=hashlib.sha256(encoded).hexdigest(), size_bytes=len(encoded),
                                media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                                validation_status="created", created_at=utc_now(), metadata={"step_id": step.step_id},
                            ))
                            artifact_ids.append(artifact.artifact_id)
                        output = {"files_written": len(files), "total_bytes": total_bytes}
                    elif step.kind == ExperimentStepKind.VERIFY_ARTIFACT:
                        required = [str(item) for item in step.payload.get("required_files", [])]
                        contains = dict(step.payload.get("contains", {}))
                        failures = []
                        for relative in required:
                            path = workspace / _safe_relative(relative)
                            if not path.is_file():
                                failures.append(f"missing {relative}")
                        for relative, needles in contains.items():
                            path = workspace / _safe_relative(str(relative))
                            text = path.read_text(encoding="utf-8") if path.is_file() else ""
                            for needle in needles if isinstance(needles, list) else [needles]:
                                if str(needle) not in text:
                                    failures.append(f"{relative} missing required content: {needle}")
                        if failures:
                            raise ExperimentBlocked(tuple(failures))
                        output = {"verified_files": len(required), "checks": sum(len(v) if isinstance(v, list) else 1 for v in contains.values())}
                    elif step.kind == ExperimentStepKind.PRIVATE_PREVIEW:
                        index_file = str(step.payload.get("index_file", "index.html"))
                        if not (workspace / _safe_relative(index_file)).is_file():
                            raise ExperimentBlocked(("private preview requires an index file",))
                        preview_token = secrets.token_urlsafe(24)
                        token_hash = hashlib.sha256(preview_token.encode()).hexdigest()
                        preview_root = self.previews_root / run_id
                        shutil.copytree(workspace, preview_root, dirs_exist_ok=False)
                        now = datetime.now(timezone.utc)
                        preview = self.store.add_preview(PreviewDeploymentReceipt(
                            run_id=run_id, artifact_ids=tuple(artifact_ids), preview_root=str(preview_root),
                            token_hash=token_hash, private=True, created_at=now.isoformat().replace("+00:00", "Z"),
                            expires_at=(now + timedelta(seconds=int(step.payload.get("ttl_seconds", 86400)))).isoformat().replace("+00:00", "Z"),
                        ))
                        preview_id = preview.preview_id
                        status = ExperimentStatus.PREVIEW_READY
                        output = {"preview_id": preview.preview_id, "private": True, "index_file": index_file}
                    elif step.kind == ExperimentStepKind.MEASURE_DEMAND:
                        output = {"measurement_surface_ready": True, "signals_recorded": 0, "synthetic_is_not_measured": True}
                    elif step.kind == ExperimentStepKind.EXTERNAL_ACTION:
                        review = self.engine.request_external_review(
                            run_id=run_id, step_id=step.step_id,
                            action_summary=str(step.payload.get("action_summary", step.name)),
                            consequence=str(step.payload.get("consequence", "external side effect")),
                            requested_by=plan.planner_id,
                        )
                        step_status = ExperimentStepStatus.BLOCKED
                        status = ExperimentStatus.WAITING_EXTERNAL_REVIEW
                        output = {"review_id": review.review_id}
                        stop_reason = "external action review required"
                    else:
                        raise ExperimentBlocked((f"unsupported step kind: {step.kind.value}",))
                    total_cost += step.estimated_cost_usd
                except Exception as exc:
                    step_status = ExperimentStepStatus.FAILED
                    error = f"{type(exc).__name__}: {exc}"
                    status = ExperimentStatus.FAILED
                    stop_reason = error
                receipt = self.store.add_step_receipt(ExperimentStepReceipt(
                    run_id=run_id, step_id=step.step_id, status=step_status,
                    started_at=step_started, completed_at=utc_now(), cost_usd=step.estimated_cost_usd if step_status == ExperimentStepStatus.COMPLETED else 0.0,
                    output=output, error=error,
                ))
                receipt_ids.append(receipt.receipt_id)
                if step_status in {ExperimentStepStatus.FAILED, ExperimentStepStatus.BLOCKED}:
                    break
            if status == ExperimentStatus.RUNNING:
                status = ExperimentStatus.COMPLETED
        finally:
            completed = utc_now()
        run = self.engine.record_run(ExperimentRunReceipt(
            plan_id=plan.plan_id, candidate_id=plan.candidate_id, mandate_id=plan.mandate_id,
            status=status, workspace_path=str(workspace), started_at=started, completed_at=completed,
            cost_usd=total_cost, step_receipt_ids=tuple(receipt_ids), artifact_ids=tuple(artifact_ids),
            preview_id=preview_id, stop_reason=stop_reason,
            metadata={
                "shell_execution": False, "network_execution": False, "production_write": False,
                "artifact_bytes": total_bytes, "artifact_files": len(artifact_paths),
                "duration_seconds": round(time.monotonic() - started_monotonic, 6),
            },
            run_id=run_id,
        ))
        return run, preview_token

    def resolve_preview_file(self, preview_id: str, token: str, relative_path: str = "index.html") -> Path:
        preview = self.store.get_preview(preview_id)
        if hashlib.sha256(token.encode()).hexdigest() != preview.token_hash:
            raise ExperimentBlocked(("invalid private preview token",))
        if datetime.now(timezone.utc) >= datetime.fromisoformat(preview.expires_at.replace("Z", "+00:00")):
            raise ExperimentBlocked(("private preview expired",))
        root = Path(preview.preview_root).resolve()
        target = (root / _safe_relative(relative_path)).resolve()
        if root not in target.parents and target != root:
            raise ExperimentBlocked(("preview path escaped root",))
        if not target.is_file():
            raise ExperimentBlocked(("preview file not found",))
        return target
