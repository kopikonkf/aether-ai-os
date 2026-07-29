import asyncio
from pathlib import Path

from aether.capabilities import CapabilityRouter, RoutedActionExecutor
from aether.contracts import (
    ActionCapability, ActionProposal, ActionResult, ActionScope, ActionTarget,
    CapabilityRequirement, CapabilityRouteStatus, RuntimeSkillProfile,
    SkillCandidate, SkillInstallReceipt, SkillLifecycleAction, SkillLifecycleEvent,
    SkillManifest, SkillProvenance, SkillRecord, SkillTriggerType, SkillUsageContract,
    skill_candidate_semantic_hash,
)
from aether.contracts.evolution import EvolutionCheckKind, EvolutionCommand
from aether.skills import SQLiteSkillStore


class Executor:
    def __init__(self, outcomes=None):
        self.outcomes = dict(outcomes or {})
        self.calls = []
        self.continuations = []

    async def capabilities(self):
        return (
            ActionCapability(ActionTarget.RUNTIME, "skill.execute", "hidden", (ActionScope.EXECUTE,), routing_key="skill-template"),
            ActionCapability(ActionTarget.RUNTIME, "echo", "public", (ActionScope.EXECUTE,), routing_key="default"),
        )

    async def execute(self, proposal, approval=None):
        self.calls.append(proposal)
        skill_id = str(proposal.arguments.get("skill_id") or "")
        outcome = self.outcomes.get(skill_id, "success")
        if outcome == "pending":
            return ActionResult(proposal.action_id, False, "pending-approval", error="approval", metadata={"approval_id": "ap-1"})
        if outcome == "failure":
            return ActionResult(proposal.action_id, False, "failed", error="failed", failure_fingerprint="fp-failed")
        return ActionResult(proposal.action_id, True, "completed", output={"text": skill_id}, metadata={"event_id": "evt-done"})

    async def save_continuation(self, approval_id, continuation):
        self.continuations.append((approval_id, continuation))


def _command(kind):
    return EvolutionCommand(("{python}", "-m", "compileall", "."), kind, kind.value)


def add_skill(store: SQLiteSkillStore, *, name: str, capability: str = "greet", runtime_requirements=("aether.template-v1",), lifecycle=None):
    candidate = SkillCandidate(
        manifest=SkillManifest(
            name=name,
            version="1.0.0",
            summary="A routed test skill",
            instructions="Render a greeting.",
            usage=SkillUsageContract(
                capabilities=(capability,),
                input_schema={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
                output_schema={"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
                runtime_requirements=runtime_requirements,
            ),
            metadata={"execution": {"kind": "template-v1", "template": "Hello {name}"}},
        ),
        provenance=SkillProvenance(
            trigger_type=SkillTriggerType.CAPABILITY_GAP,
            trigger_fingerprint=f"gap:{name}",
            evidence_ids=("evt-1",),
            observed_count=1,
            successful_count=0,
        ),
        deterministic_checks=(_command(EvolutionCheckKind.DETERMINISTIC),),
        heldout_checks=(_command(EvolutionCheckKind.HELDOUT),),
        rationale="Test route candidate.",
    )
    store.add_candidate(candidate, skill_candidate_semantic_hash(candidate))
    record = store.add_record(SkillRecord(
        candidate_id=candidate.candidate_id,
        manifest=candidate.manifest,
        provenance=candidate.provenance,
        artifact_hash=candidate.artifact_hash,
        principal="founder",
        reason="Activated for capability routing tests.",
        install_receipt=SkillInstallReceipt("installer.test", "/tmp/artifact", "/tmp/pointer"),
    ))
    if lifecycle:
        store.add_lifecycle(SkillLifecycleEvent(record.skill_id, lifecycle, "founder", "test", "Explicit lifecycle test state."))
    return store.get_record(record.skill_id)


def profile(**overrides):
    data = dict(
        routing_key="skill-template",
        adapter_id="runtime.skill.test",
        operations=("skill.execute",),
        runtime_features=("aether.template-v1", "json-io"),
        supported_side_effects=(),
        healthy=True,
        priority=10,
    )
    data.update(overrides)
    return RuntimeSkillProfile(**data)


def test_routes_only_active_exact_compatible_skill(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    active = add_skill(store, name="greeter")
    add_skill(store, name="archived-greeter", lifecycle=SkillLifecycleAction.ARCHIVE)
    executor = Executor()
    router = CapabilityRouter(store, executor, [profile()])
    execution = asyncio.run(router.execute(CapabilityRequirement("greet", {"name": "Aether"}, reason="Render greeting.")))
    assert execution.ok is True
    assert execution.selected_skill_id == active.skill_id
    assert executor.calls[0].operation == "skill.execute"
    assert executor.calls[0].metadata["runtime_id"] == "skill-template"


def test_blocks_incompatible_runtime_and_invalid_input(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    add_skill(store, name="greeter")
    router = CapabilityRouter(store, Executor(), [profile(runtime_features=("json-io",))])
    incompatible = router.route(CapabilityRequirement("greet", {"name": "Aether"}))
    assert incompatible.status == CapabilityRouteStatus.BLOCKED
    assert any("missing features" in item for item in incompatible.blockers)
    valid_router = CapabilityRouter(store, Executor(), [profile()])
    invalid = valid_router.route(CapabilityRequirement("greet", {}))
    assert invalid.status == CapabilityRouteStatus.BLOCKED
    assert any("input.name is required" in item for item in invalid.blockers)


def test_fallback_uses_next_compatible_skill(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    first = add_skill(store, name="a-first")
    second = add_skill(store, name="b-second")
    executor = Executor({first.skill_id: "failure", second.skill_id: "success"})
    router = CapabilityRouter(store, executor, [profile()])
    result = asyncio.run(router.execute(CapabilityRequirement("greet", {"name": "Aether"}, reason="Fallback test.")))
    assert result.status == CapabilityRouteStatus.FALLBACK_COMPLETED
    assert result.selected_skill_id == second.skill_id
    assert len(result.attempts) == 2


def test_pending_approval_does_not_fallback(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    first = add_skill(store, name="a-first")
    add_skill(store, name="b-second")
    executor = Executor({first.skill_id: "pending"})
    router = CapabilityRouter(store, executor, [profile()])
    result = asyncio.run(router.execute(CapabilityRequirement("greet", {"name": "Aether"}, reason="Approval test.")))
    assert result.status == CapabilityRouteStatus.PENDING_APPROVAL
    assert len(executor.calls) == 1


def test_no_match_returns_stable_failure_fingerprint(tmp_path: Path):
    router = CapabilityRouter(SQLiteSkillStore(tmp_path / "skills.sqlite3"), Executor(), [profile()])
    first = router.route(CapabilityRequirement("missing", {"x": 1}))
    second = router.route(CapabilityRequirement("missing", {"x": 1}))
    assert first.status == CapabilityRouteStatus.NOT_FOUND
    assert first.failure_fingerprint == second.failure_fingerprint


def test_routed_action_executor_hides_direct_skill_execution(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    add_skill(store, name="greeter")
    base = Executor()
    routed = RoutedActionExecutor(base, CapabilityRouter(store, base, [profile()]))
    capabilities = asyncio.run(routed.capabilities())
    operations = {item.operation for item in capabilities}
    assert "skill.execute" not in operations
    assert "capability.route" in operations
    proposal = ActionProposal(
        ActionTarget.RUNTIME,
        "capability.route",
        {"capability": "greet", "input": {"name": "Aether"}},
        reason="Use the governed capability router.",
    )
    result = asyncio.run(routed.execute(proposal))
    assert result.ok is True
    assert result.metadata["selected_skill_id"]
