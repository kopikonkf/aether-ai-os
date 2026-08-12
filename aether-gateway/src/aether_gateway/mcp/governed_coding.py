"""MCP-to-coding bridge; no filesystem implementation lives here."""
from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from aether.contracts import ActionProposal, ActionResult, RuntimeHealthStatus


class GovernedMCPActionPath:
    """Bind MCP coding proposals to Aether's existing runtime dispatcher."""

    def __init__(self, action_path: Any, runtime_registry: Any, dispatch_routing_key: str) -> None:
        self.action_path = action_path
        self.runtime_registry = runtime_registry
        self.dispatch_routing_key = dispatch_routing_key

    async def execute(self, proposal: ActionProposal, approval: Any = None) -> ActionResult:
        if proposal.operation != "coding.task.execute":
            return await self.action_path.execute(proposal, approval)
        descriptors = await self.runtime_registry.discover()
        candidates = [
            asdict(item)
            for item in descriptors
            if item.health_status == RuntimeHealthStatus.HEALTHY
            and "coding.task.execute" in item.operations
        ]
        if not candidates:
            return ActionResult(proposal.action_id, False, "no-runtime", error="No healthy registered coding runtime is available")
        arguments = dict(proposal.arguments)
        arguments["runtime_candidates"] = candidates
        metadata = {**dict(proposal.metadata), "runtime_id": self.dispatch_routing_key, "runtime_candidate_ids": [item["adapter_id"] for item in candidates]}
        bound = replace(proposal, arguments=arguments, metadata=metadata)
        return await self.action_path.execute(bound, approval)

    async def save_continuation(self, approval_id: str, continuation: dict[str, Any]) -> None:
        await self.action_path.save_continuation(approval_id, continuation)
