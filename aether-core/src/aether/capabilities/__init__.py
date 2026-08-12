"""Capability routing from cognitive requirements to governed Aether skills.

Also hosts the deterministic capability lifecycle tracker (ADR-0055 P4):
mutation-surface lifecycle per principal with observation-derived evidence
and the single-principal gate.
"""
from .lifecycle import (
    CapabilityLifecycle,
    CapabilityLifecycleBlocked,
    CapabilityLifecycleRecord,
    LifecycleTransition,
    MUTATION_SURFACE_LIVING_MCP,
    validate_evidence,
)
from .router import (
    CapabilityRouter,
    CapabilityRouterBlocked,
    CapabilityRouterPolicy,
    RoutedActionExecutor,
)

__all__ = [
    "CapabilityLifecycle",
    "CapabilityLifecycleBlocked",
    "CapabilityLifecycleRecord",
    "LifecycleTransition",
    "MUTATION_SURFACE_LIVING_MCP",
    "CapabilityRouter",
    "CapabilityRouterBlocked",
    "CapabilityRouterPolicy",
    "RoutedActionExecutor",
    "validate_evidence",
]
