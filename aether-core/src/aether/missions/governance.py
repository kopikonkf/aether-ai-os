"""Governance rules for opportunity briefs and mission plans."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import yaml

from aether.contracts.missions import ExpectedValueBrief, MissionLane, MissionPlan, MissionRisk
from aether.dna.loader import DNALoader


class MissionGovernor:
    governor_id = "aether.mission-governor"

    def __init__(self, policy_path: Path | None = None) -> None:
        path = policy_path or Path(__file__).with_name("mission_orchestrator.yaml")
        self.policy = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        northstar = DNALoader().load_north_star()
        self.principle_ids = {str(item.get("id")) for item in northstar.get("sacred_principles", [])}
        self.strategy_ids = {str(item) for item in northstar.get("strategies", [])}
        self.trusted_principals = set(self.policy.get("governance", {}).get("trusted_principals", ["founder", "operator"]))

    def validate_brief(self, brief: ExpectedValueBrief) -> tuple[str, ...]:
        blockers: list[str] = []
        if not brief.title.strip() or not brief.problem_statement.strip() or not brief.value_proposition.strip():
            blockers.append("title, problem statement, and value proposition are required")
        if not 0 <= brief.probability_success <= 1:
            blockers.append("probability_success must be between 0 and 1")
        if not 0 <= brief.confidence <= 1:
            blockers.append("confidence must be between 0 and 1")
        if brief.upside_usd < 0 or brief.estimated_cost_usd < 0 or brief.estimated_duration_hours < 0:
            blockers.append("upside, cost, and duration cannot be negative")
        for item in brief.evidence:
            if not item.source.strip() or not item.statement.strip():
                blockers.append(f"evidence {item.evidence_id} requires source and statement")
            if brief.lane == MissionLane.EXTERNAL_VALUE and item.stance.value == "supports" and not item.external_reference:
                blockers.append(f"external supporting evidence {item.evidence_id} requires an external reference")
        min_sources = int(self.policy.get("opportunity", {}).get("minimum_independent_sources", 2))
        if brief.lane == MissionLane.EXTERNAL_VALUE and brief.independent_support_count < min_sources:
            blockers.append(f"external-value opportunity requires at least {min_sources} independent supporting sources")
        if brief.contradiction_evidence_ids:
            blockers.append("opportunity has unresolved contradiction evidence")
        if brief.lane == MissionLane.EXTERNAL_VALUE and not brief.revenue_hypothesis.strip():
            blockers.append("external-value opportunity requires a measurable revenue hypothesis")
        return tuple(blockers)

    def validate_plan(self, plan: MissionPlan, brief: ExpectedValueBrief) -> tuple[str, ...]:
        blockers = list(self.validate_brief(brief))
        try:
            plan.budget.validate()
        except ValueError as exc:
            blockers.append(str(exc))
        if plan.lane != brief.lane:
            blockers.append("mission lane must match opportunity brief lane")
        if not plan.objective.strip() or not plan.northstar_alignment.strip():
            blockers.append("objective and explicit Northstar alignment are required")
        if not set(plan.northstar_principle_ids) & self.principle_ids:
            blockers.append("mission must bind at least one canonical Northstar sacred principle")
        if plan.lane == MissionLane.EXTERNAL_VALUE and not set(plan.strategy_tags) & self.strategy_ids:
            blockers.append("external-value mission must bind at least one canonical business strategy")
        if not plan.steps:
            blockers.append("mission requires at least one bounded step")
        maximum_steps = int(self.policy.get("execution", {}).get("maximum_steps", 20))
        if len(plan.steps) > maximum_steps:
            blockers.append(f"mission exceeds maximum step count {maximum_steps}")
        step_ids = [item.step_id for item in plan.steps]
        if len(step_ids) != len(set(step_ids)):
            blockers.append("mission step ids must be unique")
        known = set(step_ids)
        for step in plan.steps:
            if not step.title.strip() or not step.success_criteria:
                blockers.append(f"step {step.step_id} requires title and success criteria")
            if step.max_attempts < 1:
                blockers.append(f"step {step.step_id} max_attempts must be positive")
            if step.estimated_cost_usd < 0:
                blockers.append(f"step {step.step_id} estimated cost cannot be negative")
            missing = set(step.depends_on) - known
            if missing:
                blockers.append(f"step {step.step_id} has unknown dependencies: {', '.join(sorted(missing))}")
            if step.step_id in step.depends_on:
                blockers.append(f"step {step.step_id} cannot depend on itself")
        if self._has_cycle(plan):
            blockers.append("mission step dependency graph contains a cycle")
        if brief.expected_net_value_usd < plan.budget.minimum_expected_value_usd:
            blockers.append("expected net value is below the mission budget minimum")
        if sum(item.estimated_cost_usd for item in plan.steps) > plan.budget.max_cost_usd:
            blockers.append("estimated step cost exceeds mission cost budget")
        high_risk = sum(item.action.risk.value in {MissionRisk.HIGH.value, MissionRisk.CRITICAL.value} for item in plan.steps)
        if high_risk > plan.budget.max_high_risk_actions:
            blockers.append("high-risk action count exceeds mission budget")
        return tuple(dict.fromkeys(blockers))

    def validate_decision(self, *, principal: str, reason: str) -> tuple[str, ...]:
        blockers: list[str] = []
        if principal.strip().casefold() not in {item.casefold() for item in self.trusted_principals}:
            blockers.append("mission decision requires a trusted Founder/operator principal")
        if not reason.strip():
            blockers.append("mission decision reason is required")
        return tuple(blockers)

    @staticmethod
    def _has_cycle(plan: MissionPlan) -> bool:
        graph = {item.step_id: tuple(item.depends_on) for item in plan.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visited:
                return False
            if node in visiting:
                return True
            visiting.add(node)
            for dep in graph.get(node, ()):  # dependency edges
                if visit(dep):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in graph)
