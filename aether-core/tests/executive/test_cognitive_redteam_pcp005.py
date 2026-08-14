"""MISSION-PCP-005 WORK-4 — red-team adversarial checklist (Gate 6).

Adversarial review of the multi-principal changes (WORK-1/2/3). COORD-authored
deterministic tests that probe the fail-closed invariants:

  R-PCP005-1  a step whose per-step execution_profile is NOT registered to its
              principal must be rejected at plan-time validate(profiles=...),
              not silently remapped at dispatch (G6-A).
  R-PCP005-2  legacy multi-step with a shared principal stays valid (no
              require_distinct_principals) — backward compat.
  R-PCP005-3  every per-principal step in a 5-step plan carries a DIFFERENT
              registered principal and a profile that belongs to it.
  R-PCP005-4  a failed mid-chain step stops the loop; later principals never
              dispatched (no cross-principal cascade).
  R-PCP005-5  artifact chain crosses principals: step N+1 prompt names step N's
              artifact and step N+1 is executed by a different principal.
  R-PCP005-6  governance remains exactly once even with 5 distinct principals.

Deterministic: fake registry + MockHerdrAdapter, no network, no herdr.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from aether.executive.cognitive_reasoner import (
    CognitiveDirective,
    CognitiveStepSpec,
    RuleBasedReasoner,
)

_PRINCIPALS = ("claude", "gemini", "qwen", "deepseek", "chatgpt")
_PROFILE_BY_PRINCIPAL = {
    "claude": "herdr:freebuff",
    "gemini": "herdr:claude",
    "qwen": "herdr:cline",
    "deepseek": "herdr:kilo",
    "chatgpt": "herdr:opencode",
}


class _FakeRegistry:
    def __init__(self, entries):
        self._entries = entries

    def get_principal(self, pid):
        return self._entries.get(pid)


def _registry():
    return _FakeRegistry(
        {
            pid: SimpleNamespace(
                model_provider=f"mp-{pid}",
                execution_profiles=(_PROFILE_BY_PRINCIPAL[pid],),
            )
            for pid in _PRINCIPALS
        }
    )


def _directive(**overrides) -> CognitiveDirective:
    fields = {
        "objective": "multi-principal adversarial mission",
        "expected_artifact": "WORK-PCP-005.md",
        "principal_id": "chatgpt",
        "execution_profile": "herdr:opencode",
        "workspace_id": "workspace://pcp-005",
        "max_steps": 5,
        "steps": tuple(
            CognitiveStepSpec(
                step_id=f"step-{i}",
                work_id=f"WORK-PCP-005-S{i}",
                objective=f"step {i}",
                expected_artifact=f"WORK-PCP-005-S{i}.md",
                depends_on=(f"step-{i - 1}",) if i > 1 else (),
                principal_id=p,
                execution_profile=_PROFILE_BY_PRINCIPAL[p],
            )
            for i, p in enumerate(_PRINCIPALS, start=1)
        ),
    }
    fields.update(overrides)
    return CognitiveDirective(**fields)


# ---------------------------------------------------------------------------
# R-PCP005-1: per-step profile must belong to the step's principal (fail-closed)
# ---------------------------------------------------------------------------
def test_redteam_rejects_step_profile_not_registered_to_principal():
    directive = _directive(
        steps=(
            CognitiveStepSpec(
                "step-1", "WORK-PCP-005-S1", "s1", "WORK-PCP-005-S1.md",
                principal_id="claude", execution_profile="herdr:kilo",
            ),
        )
    )
    blockers = directive.validate(profiles=_registry())
    assert any("profile" in b and "not registered" in b for b in blockers), blockers


def test_redteam_rejects_step_profile_belongs_to_wrong_principal():
    # claude + herdr:opencode: herdr:opencode is a real profile but belongs to
    # chatgpt, not claude. Must be a blocker, not a silent dispatch remap.
    directive = _directive(
        steps=(
            CognitiveStepSpec(
                "step-1", "WORK-PCP-005-S1", "s1", "WORK-PCP-005-S1.md",
                principal_id="claude", execution_profile="herdr:opencode",
            ),
        )
    )
    blockers = directive.validate(profiles=_registry())
    assert any("herdr:opencode" in b for b in blockers), blockers


# ---------------------------------------------------------------------------
# R-PCP005-2: legacy shared-principal multi-step stays valid
# ---------------------------------------------------------------------------
def test_redteam_legacy_shared_principal_still_valid():
    directive = _directive(
        steps=tuple(
            CognitiveStepSpec(
                step_id=f"step-{i}",
                work_id=f"W-{i}",
                objective=f"s{i}",
                expected_artifact=f"W-{i}.md",
                depends_on=(f"step-{i - 1}",) if i > 1 else (),
                principal_id="chatgpt",
                execution_profile="herdr:opencode",
            )
            for i in range(1, 4)
        ),
        require_distinct_principals=False,
    )
    assert directive.validate(profiles=_registry()) == []


# ---------------------------------------------------------------------------
# R-PCP005-3: distinct registered principals with owning profiles
# ---------------------------------------------------------------------------
def test_redteam_all_steps_distinct_registered_with_owning_profiles():
    directive = _directive(require_distinct_principals=True)
    reg = _registry()
    assert directive.validate(profiles=reg) == []
    principals = [s.principal_id for s in directive.steps]
    assert len(set(principals)) == 5
    for spec in directive.steps:
        owner = reg.get_principal(spec.principal_id)
        assert spec.execution_profile in owner.execution_profiles


# ---------------------------------------------------------------------------
# R-PCP005-4/5/6: loop behavior with distinct principals (executive)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_redteam_multi_principal_loop_invariants(tmp_path: Path):
    import sys

    sys.path.insert(0, r"C:\aether\aether-ai-os\aether-core\src")
    sys.path.insert(0, r"C:\aether\aether-ai-os\aether-core\tests")
    import executive.test_cognitive_executive as T
    from aether.executive.cognitive_executive import CognitiveExecutive
    from aether.executive.cognitive_observer import CognitiveObserver
    from aether.executive.cognitive_planner import CognitivePlanner
    from aether.executive.cognitive_reasoner import RuleBasedReasoner
    from aether.apcb.receipt_store import ReceiptStore
    from aether.missions.orchestrator import MissionOrchestrator

    runner = T.make_runner(tmp_path)
    adapter = T.MockHerdrAdapter(wait_status="done", expected_artifact=None)
    ws = str(Path(runner.workspace_override))
    executive = T.make_executive(runner, adapter, max_steps=5)
    result = await executive.run_closed_loop(_directive(workspace_id=ws))
    assert result.completed is True
    assert result.governance_count == 1  # R-PCP005-6
    assert len(result.steps_executed) == 5
    principals = [ev["principal_id"] for ev in result.evidence_evaluations]
    assert principals == list(_PRINCIPALS)  # R-PCP005-3
    assert len(set(principals)) == 5
    # R-PCP005-5: artifact chain crosses principals.
    assert len(adapter.prompts) == 5
    for index in (1, 2, 3, 4):
        assert f"WORK-PCP-005-S{index}.md" in adapter.prompts[index]


@pytest.mark.asyncio
async def test_redteam_mid_chain_failure_stops_later_principals(tmp_path: Path):
    import sys

    sys.path.insert(0, r"C:\aether\aether-ai-os\aether-core\src")
    sys.path.insert(0, r"C:\aether\aether-ai-os\aether-core\tests")
    import executive.test_cognitive_executive as T

    runner = T.make_runner(tmp_path)
    adapter = T.MockHerdrAdapter(
        wait_status="done",
        expected_artifact=None,
        fail_work_ids=("WORK-PCP-005-S3",),
    )
    ws = str(Path(runner.workspace_override))
    executive = T.make_executive(runner, adapter, max_steps=5)
    result = await executive.run_closed_loop(_directive(workspace_id=ws))
    assert result.completed is False
    # R-PCP005-4: step-3 (qwen) is attempted and fails -> stop; deepseek+chatgpt
    # (steps 4-5) are never dispatched.
    assert adapter.calls.count("prompt_agent") == 3
    assert result.decisions[-1]["step_id"] == "step-3"
    assert result.decisions[-1]["action"] == "stop"
    # Only claude + gemini actually executed; deepseek/chatgpt never dispatched.
    assert result.steps_executed == ("step-1", "step-2")
