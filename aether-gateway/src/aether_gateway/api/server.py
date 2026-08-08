"""Aether Gateway API: desktop/HTTP, Telegram, runtime delegation, and live status."""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import hashlib
import hmac
import json
import os
import sys
import sqlite3
import uuid
from dataclasses import asdict
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[4]
AETHER_CORE_DIR = PROJECT_ROOT / "aether-core"
AIONUI_CONSOLE_DIR = Path(__file__).resolve().parents[1] / "aionui_runtime_console"
AIONUI_MISSION_CONSOLE_DIR = Path(__file__).resolve().parents[1] / "aionui_mission_console"
AIONUI_OPPORTUNITY_CONSOLE_DIR = Path(__file__).resolve().parents[1] / "aionui_opportunity_console"
AIONUI_EXPERIMENT_CONSOLE_DIR = Path(__file__).resolve().parents[1] / "aionui_experiment_console"
AIONUI_SENSES_CONSOLE_DIR = Path(__file__).resolve().parents[1] / "aionui_senses_console"
# Preserve caller-provided AETHER_HOME so VPS shell values win.
load_dotenv(AETHER_CORE_DIR / ".env", override=False)

from aether.actions import (
    ApprovalNotFound, ApprovalStateError, FailureFingerprintStore, GovernedActionPath,
    PendingActionStore, TrustedApprovalInbox,
)
from aether.cognition import AetherCognitiveGateway, SQLiteConversationStore
from aether.capabilities import CapabilityRouter, RoutedActionExecutor
from aether.runtimes import CodingRuntimeRouter, CodingRoutedActionExecutor
from aether.contracts import (
    ActionProposal, ActionRisk, ActionScope, ActionTarget, ApprovalStatus,
    FleetIncidentState, FleetJobKind,
    ExpectedValueBrief, MissionBlocked, MissionBudget, MissionDecisionConflict, MissionLane, MissionNotFound,
    MissionRisk, MissionStatus, MissionStep, MissionValueKind, OpportunityEvidence, OpportunityEvidenceStance, opportunity_brief_payload,
    AutonomyLevel, ClaimStance, ContentSnapshot, EvidenceStrength, ExtractedClaim, OpportunityBlocked,
    OpportunityNotFound, PortfolioDecisionConflict, PortfolioDecisionType, PortfolioPolicy, ScoutQuery,
    SourceAdapterManifest, SourceCapability, SourceKind, opportunity_candidate_payload, experiment_mandate_payload,
    EvidenceFreshnessPolicy, LiveSourceConfiguration, SourceDiscoveryState,
    live_source_configuration_payload, source_conformance_receipt_payload, freshness_record_payload, source_discovery_candidate_payload,
    DemandEvidenceState, DemandSignal, DemandSignalKind, ExperimentStep, ExperimentStepKind,
    ReversibleExperimentPlan, experiment_plan_payload, experiment_run_payload, demand_signal_payload,
    CapabilityRequirement, CapabilityRouteStatus, CodingEdit, CodingExecutionStatus, CodingTask, VerificationCommand,
    KnowledgeDecisionConflict, KnowledgePromotionBlocked, KnowledgeProposalNotFound, KnowledgeProposalStatus,
    MemoryQuery, ModelRequest, Perception, BrowserSenseCapability, MediaTrackKind,
    EvolutionCheckKind, EvolutionCommand, EvolutionTargetType, EvolutionTrigger, EvolutionTriggerType,
    SkillLifecycleAction, SkillLifecycleStatus, SkillManifest, SkillProvenance, SkillTriggerType,
    SkillUsageContract, SkillUsageEvent, EventType,
)
from aether.events import EventBus
from aether.executive.engine import CircadianExecutiveEngine
from aether.evolution import (EvolutionBlocked, EvolutionDecisionConflict, EvolutionNotFound, InternalEvolutionEngine, SQLiteEvolutionStore, capability_gap, evolution_fingerprint)
from aether.governance import ActionGovernor
from aether.paths import AetherPaths, get_aether_home
from aether.senses import SenseEventPath
from aether.memory import AetherMemoryFabric, ObsidianMemoryProjector, SQLiteCanonicalMemoryStore, SQLiteLexicalMemoryProvider
from aether.knowledge import MemoryCurator, ObsidianKnowledgeProjector, SQLiteKnowledgeProposalStore
from aether.missions import MissionGovernor, MissionOrchestrator, SQLiteMissionStore
from aether.opportunities import OpportunityGovernor, OpportunityIntelligenceEngine, SQLiteOpportunityStore
from aether.web_intelligence import SQLiteWebIntelligenceStore, WebIntelligenceEngine, WebIntelligenceGovernor
from aether.experiments import ExperimentGovernor, ReversibleExperimentEngine, SQLiteExperimentStore
from aether.skills import SkillDecisionConflict, SkillFactory, SkillFactoryBlocked, SkillNotFound, SQLiteSkillStore
from aether_gateway.actions import RegistryToolExecutor
from aether_gateway.approvals import (
    ApprovalCoordinator, ApprovalInboxService, OperatorAuthError, OperatorAuthenticator, pending_to_dict,
)
from aether_gateway.adapters import DirectTextSenseAdapter, LocalProcessRuntimeAdapter
from aether_gateway.adapters.telegram_bot import TelegramSenseAdapter
from aether_gateway.providers import ConfiguredModelProvider
from aether_gateway.evolution import EvolutionWorkspaceError, LocalArtifactPromoter, LocalEvolutionSandbox
from aether_gateway.runtime_drivers import RuntimeConformanceError, RuntimeDriverPack
from aether_gateway.runtime_operations import FleetOperationsStore, RuntimeFleetOperationsService, RuntimeFleetScheduler, load_fleet_policy
from aether_gateway.missions import GovernedMissionActionAdapter
from aether_gateway.opportunities import (AutonomousOpportunityScout, Crawl4AIRestrictedAdapter, GenericPublicHttpAdapter, OpportunityMissionBridge, SourceCapabilityMesh, StaticCatalogAdapter)
from aether_gateway.web_intelligence import AdaptiveSourceDiscovery, EvidenceFreshnessScheduler, LiveWebAcquisitionService, SourceConformanceService
from aether_gateway.experiments import ReversibleExperimentRunner
from aether_gateway.browser_senses import (
    BootstrapError,
    BootstrapRateLimitError,
    BootstrapStateError,
    BrowserSenseAuthError,
    BrowserSenseActionProjector,
    BrowserSenseBootstrapService,
    BrowserSenseService,
    BrowserSessionTokenCodec,
    DeviceCredentialError,
    LiveKitTokenIssuer,
    SessionCredentialError,
    TurnClaimConflict,
    VisionConsentError,
    VisionDeletionError,
    VisionFrameValidationError,
)
from aether_gateway.runtime_sdk import (
    CodingRuntimeDispatchAdapter, ExternalStreamingCodingRuntimeAdapter, LocalStructuredCodingRuntimeAdapter, RuntimeAdapterRegistry, RuntimeTelemetryStore,
    SQLiteWorkspaceBindingStore, WorkspaceBindingError,
)
from aether_gateway.skills import (
    LocalProjectedSkillRuntimeAdapter, LocalRuntimeSkillInstaller, LocalSkillBenchmarkSandbox,
    SkillWorkspaceError,
)
from aether_tools import BehaviorMonitor, ToolRegistry
from aether_tools.primitives import EditTool, GlobTool, GrepTool, MemoryTool, ReadTool, WriteTool
from aether_tools.primitives.bash import BashTool
from aether_tools.primitives.webfetch import WebFetchTool

root_dir = get_aether_home()
root_dir.mkdir(parents=True, exist_ok=True)
paths = AetherPaths(root_dir)
db_path = str(root_dir / "aether_hub.db")


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _load_system_prompt() -> str:
    data = _load_yaml(AETHER_CORE_DIR / "configs" / "persona.yaml")
    return str(data.get("system_prompt") or "You are Aether, a governed cognitive operating system.").strip()


model_provider = ConfiguredModelProvider()
conversation_store = SQLiteConversationStore(paths.cognitive_sessions_db, max_messages=48)
memory_event_bus = EventBus(root_dir / "events" / "memory-fabric.jsonl")
canonical_memory = SQLiteCanonicalMemoryStore(paths.canonical_memory_db)
retrieval_memory = SQLiteLexicalMemoryProvider(paths.retrieval_index_db, canonical_memory)
memory_fabric = AetherMemoryFabric(
    canonical_memory,
    retrieval_memory,
    event_bus=memory_event_bus,
    obsidian=ObsidianMemoryProjector(paths.obsidian_vault),
)
knowledge_event_bus = EventBus(root_dir / "events" / "knowledge-curator.jsonl")
knowledge_proposals = SQLiteKnowledgeProposalStore(paths.knowledge_proposals_db)
knowledge_curator = MemoryCurator(
    canonical_memory,
    knowledge_proposals,
    memory_fabric,
    event_bus=knowledge_event_bus,
    projector=ObsidianKnowledgeProjector(paths.obsidian_vault),
)

evolution_workspace = Path(os.environ.get("AETHER_EVOLUTION_WORKSPACE", str(root_dir / "workspace"))).expanduser().resolve()
evolution_workspace.mkdir(parents=True, exist_ok=True)
evolution_event_bus = EventBus(root_dir / "events" / "internal-evolution.jsonl")
evolution_store = SQLiteEvolutionStore(root_dir / "evolution" / "internal-evolution.sqlite3")
evolution_engine = InternalEvolutionEngine(evolution_store, event_bus=evolution_event_bus)
evolution_sandbox = LocalEvolutionSandbox(evolution_workspace, root_dir / "evolution" / "sandboxes")
evolution_promoter = LocalArtifactPromoter(evolution_workspace, root_dir / "evolution" / "backups")

skill_workspace = Path(os.environ.get("AETHER_SKILL_WORKSPACE", str(root_dir / "workspace"))).expanduser().resolve()
skill_workspace.mkdir(parents=True, exist_ok=True)
skill_event_bus = EventBus(root_dir / "events" / "skill-factory.jsonl")
skill_store = SQLiteSkillStore(paths.skill_factory_db)
skill_factory = SkillFactory(skill_store, event_bus=skill_event_bus)
skill_sandbox = LocalSkillBenchmarkSandbox(skill_workspace, root_dir / "skills" / "sandboxes")
skill_installer = LocalRuntimeSkillInstaller(paths.skill_registry)
skill_runtime_event_bus = EventBus(root_dir / "events" / "runtime-skill-projection.jsonl")
skill_runtime_adapter = LocalProjectedSkillRuntimeAdapter(
    skill_store,
    skill_factory,
    root_dir / "skills" / "runtime-projections" / "local-template",
    event_bus=skill_runtime_event_bus,
)

coding_runtime_event_bus = EventBus(root_dir / "events" / "coding-runtime.jsonl")
coding_workspace_default = (root_dir / "workspace").resolve()
coding_workspace_default.mkdir(parents=True, exist_ok=True)
_coding_roots_raw = os.environ.get("AETHER_CODING_WORKSPACE_ROOTS", str(coding_workspace_default))
coding_allowed_roots = tuple(Path(item).expanduser().resolve() for item in _coding_roots_raw.split(os.pathsep) if item.strip())
workspace_bindings = SQLiteWorkspaceBindingStore(
    root_dir / "runtime" / "workspace-bindings.sqlite3", coding_allowed_roots,
)
runtime_telemetry = RuntimeTelemetryStore(root_dir / "runtime" / "runtime-telemetry.sqlite3")
coding_runtime_adapter = LocalStructuredCodingRuntimeAdapter(
    root_dir / "runtime" / "local-structured", runtime_telemetry,
    allowed_workspace_roots=coding_allowed_roots, event_bus=coding_runtime_event_bus,
)
runtime_registry = RuntimeAdapterRegistry(event_bus=coding_runtime_event_bus)
runtime_registry.register(coding_runtime_adapter, coding_runtime_adapter.descriptor)

reference_external_runtime = ExternalStreamingCodingRuntimeAdapter(
    (sys.executable, "-m", "aether_gateway.runtime_sdk.reference_external_runtime"),
    root_dir / "runtime" / "external-jsonl-reference",
    runtime_telemetry,
    allowed_workspace_roots=coding_allowed_roots,
    event_bus=coding_runtime_event_bus,
    priority=10,
)
runtime_registry.register(reference_external_runtime, reference_external_runtime.descriptor)

runtime_driver_pack = RuntimeDriverPack(
    root_dir / "runtime" / "driver-pack",
    runtime_telemetry,
    allowed_workspace_roots=coding_allowed_roots,
    event_bus=coding_runtime_event_bus,
)
for _driver_adapter in runtime_driver_pack.build_live_adapters():
    runtime_registry.register(_driver_adapter, _driver_adapter.descriptor)

_external_argv_raw = os.environ.get("AETHER_EXTERNAL_CODING_RUNTIME_ARGV", "").strip()
if _external_argv_raw:
    try:
        _external_argv = json.loads(_external_argv_raw)
        if not isinstance(_external_argv, list) or not _external_argv or not all(isinstance(item, str) and item.strip() for item in _external_argv):
            raise ValueError("AETHER_EXTERNAL_CODING_RUNTIME_ARGV must be a JSON array of non-empty argv strings")
        configured_external_runtime = ExternalStreamingCodingRuntimeAdapter(
            tuple(_external_argv),
            root_dir / "runtime" / "external-jsonl-configured",
            runtime_telemetry,
            allowed_workspace_roots=coding_allowed_roots,
            event_bus=coding_runtime_event_bus,
            routing_key=os.environ.get("AETHER_EXTERNAL_CODING_RUNTIME_ROUTING_KEY", "runtime://coding/external-jsonl-configured"),
            adapter_id=os.environ.get("AETHER_EXTERNAL_CODING_RUNTIME_ADAPTER_ID", "runtime.coding.external-jsonl-configured"),
            display_name=os.environ.get("AETHER_EXTERNAL_CODING_RUNTIME_NAME", "Configured External JSONL Coding Runtime"),
            priority=int(os.environ.get("AETHER_EXTERNAL_CODING_RUNTIME_PRIORITY", "5")),
        )
        runtime_registry.register(configured_external_runtime, configured_external_runtime.descriptor)
    except Exception as exc:
        coding_runtime_event_bus.emit(
            EventType.RUNTIME_ADAPTER_DISCOVERED,
            actor="aether.gateway.runtime-config",
            payload={"configured": False, "error": f"{type(exc).__name__}: {exc}"},
            severity="error",
        )

fleet_policy = load_fleet_policy()
fleet_store = FleetOperationsStore(root_dir / "runtime" / "fleet-operations.sqlite3")
fleet_service = RuntimeFleetOperationsService(
    runtime_driver_pack,
    runtime_telemetry,
    fleet_store,
    evolution_engine=evolution_engine,
    event_bus=coding_runtime_event_bus,
    policy=fleet_policy,
)
fleet_scheduler = RuntimeFleetScheduler(
    fleet_service,
    poll_interval_seconds=int(os.environ.get(
        "AETHER_FLEET_POLL_INTERVAL_SECONDS",
        str(fleet_policy.get("scheduler", {}).get("poll_interval_seconds", 10)),
    )),
    enabled=os.environ.get("AETHER_FLEET_SCHEDULER_ENABLED", "true").strip().casefold()
    not in {"0", "false", "no", "off", "disabled"},
)
coding_dispatch_adapter = CodingRuntimeDispatchAdapter(
    runtime_registry,
    event_bus=coding_runtime_event_bus,
    maximum_attempts=fleet_service.budget_policy.maximum_fallback_attempts,
)

security_profiles_path = AETHER_CORE_DIR / "configs" / "security_profiles.yaml"
quarantine_state_path = root_dir / "runtime_state" / "quarantine_state.json"
behavior_monitor = BehaviorMonitor(security_profiles_path, quarantine_state_path)
tool_registry = ToolRegistry(behavior_monitor=behavior_monitor)
tool_policy = _load_yaml(AETHER_CORE_DIR / "configs" / "tool_policy.yaml")


def _resolve_policy_roots(key: str, default: list[str]) -> list[Path]:
    raw_list = tool_policy.get("file", {}).get(key, default)
    result: list[Path] = []
    for raw in raw_list:
        value = str(raw).replace("${AETHER_HOME}", str(root_dir)).replace("${AETHER_CORE}", str(AETHER_CORE_DIR))
        result.append(Path(value))
    return result


write_roots = _resolve_policy_roots("write_roots", [str(root_dir)])
read_roots = _resolve_policy_roots("read_roots", [str(root_dir)])
bash_cwd = str(tool_policy.get("bash", {}).get("cwd", root_dir / "workspace"))
bash_cwd = bash_cwd.replace("${AETHER_HOME}", str(root_dir)).replace("${AETHER_CORE}", str(AETHER_CORE_DIR))
bash_blocked = tool_policy.get(
    "bash", {},
).get("blocked", ["rm", "sudo", "curl", "wget", "nc", "format", "del", "rmdir", "chmod"])
bash_timeout_max = int(tool_policy.get("bash", {}).get("timeout_max", 60))
web_max_bytes = int(tool_policy.get("web", {}).get("max_bytes", 1048576))
web_https_only = bool(tool_policy.get("web", {}).get("https_only", True))
max_read_lines = int(tool_policy.get("file", {}).get("max_read_lines", 500))

for tool in [
    ReadTool(read_roots, max_lines=max_read_lines),
    WriteTool(write_roots),
    EditTool(write_roots),
    GrepTool(read_roots),
    GlobTool(read_roots),
    BashTool(cwd=bash_cwd, blocked=bash_blocked, timeout_max=bash_timeout_max),
    WebFetchTool(max_bytes=web_max_bytes, https_only=web_https_only),
    MemoryTool(db_path),
]:
    tool_registry.register(tool)

runtime_adapter = LocalProcessRuntimeAdapter(cwd=root_dir / "workspace")
action_event_bus = EventBus(root_dir / "events" / "action-path.jsonl")
pending_action_store = PendingActionStore(
    root_dir / "governance" / "pending-actions.sqlite3",
    default_ttl_seconds=int(os.environ.get("AETHER_APPROVAL_TTL_SECONDS", "900")),
)
action_path = GovernedActionPath(
    action_event_bus,
    ActionGovernor(),
    FailureFingerprintStore(root_dir / "evolution" / "action-failures.jsonl"),
    tool_executor=RegistryToolExecutor(tool_registry),
    runtimes={
        "default": runtime_adapter,
        skill_runtime_adapter.routing_key: skill_runtime_adapter,
        coding_dispatch_adapter.routing_key: coding_dispatch_adapter,
    },
    pending_store=pending_action_store,
    approval_ttl_seconds=int(os.environ.get("AETHER_APPROVAL_TTL_SECONDS", "900")),
    hidden_runtime_ids={skill_runtime_adapter.routing_key, coding_dispatch_adapter.routing_key},
)
capability_event_bus = EventBus(root_dir / "events" / "capability-router.jsonl")
capability_router = CapabilityRouter(
    skill_store,
    action_path,
    [skill_runtime_adapter.profile],
    event_bus=capability_event_bus,
)
skill_routed_action_executor = RoutedActionExecutor(action_path, capability_router)
coding_router = CodingRuntimeRouter(
    runtime_registry, workspace_bindings, action_path, event_bus=coding_runtime_event_bus,
    dispatch_routing_key=coding_dispatch_adapter.routing_key,
)
routed_action_executor = CodingRoutedActionExecutor(skill_routed_action_executor, coding_router)
mission_event_bus = EventBus(root_dir / "events" / "mission-orchestrator.jsonl")
mission_store = SQLiteMissionStore(paths.mission_orchestrator_db)
mission_action_adapter = GovernedMissionActionAdapter(routed_action_executor, pending_action_store)
mission_orchestrator = MissionOrchestrator(
    mission_store,
    mission_action_adapter,
    governor=MissionGovernor(),
    event_bus=mission_event_bus,
    memory_fabric=memory_fabric,
    evolution_engine=evolution_engine,
    maximum_steps_per_run=int(os.environ.get("AETHER_MISSION_MAX_STEPS_PER_RUN", "5")),
)
opportunity_event_bus = EventBus(root_dir / "events" / "opportunity-intelligence.jsonl")
opportunity_store = SQLiteOpportunityStore(root_dir / "opportunities" / "opportunity-intelligence.sqlite3")
opportunity_intelligence = OpportunityIntelligenceEngine(
    opportunity_store, governor=OpportunityGovernor(), event_bus=opportunity_event_bus,
)
source_mesh = SourceCapabilityMesh()
source_mesh.register(Crawl4AIRestrictedAdapter())
source_mesh.register(GenericPublicHttpAdapter())
for _catalog_adapter in (
    StaticCatalogAdapter(
        SourceAdapterManifest(
            source_id="source.catalog.ai-treasurebox", adapter_id="source.adapter.ai-treasurebox",
            name="AI TreasureBox Ecosystem Curriculum", kind=SourceKind.CATALOG,
            capabilities=(SourceCapability.SEARCH, SourceCapability.FETCH, SourceCapability.CATALOG), priority=30,
            forbidden_capabilities=("credential-export", "external-write"),
            metadata={"role": "continuous-technology-curriculum"},
        ),
        (
            ("https://github.com/superiorlu/AITreasureBox", "AI ecosystem tools and repositories", "AI tools, repositories, public APIs, workflow automation, web data APIs, coding agents, and free developer infrastructure are growing rapidly."),
            ("https://github.com/superiorlu/AITreasureBox#business", "Business automation signals", "Lead generation, sales automation, customer operations, content workflows, and vertical AI products show recurring integration and operational pain."),
        ),
    ),
    StaticCatalogAdapter(
        SourceAdapterManifest(
            source_id="source.catalog.awesome-ai-agents", adapter_id="source.adapter.awesome-ai-agents",
            name="Awesome AI Agents Market Taxonomy", kind=SourceKind.CATALOG,
            capabilities=(SourceCapability.SEARCH, SourceCapability.FETCH, SourceCapability.CATALOG), priority=31,
            forbidden_capabilities=("credential-export", "external-write"),
            metadata={"role": "market-and-capability-taxonomy"},
        ),
        (
            ("https://github.com/jim-schwoebel/awesome_ai_agents", "AI agent market taxonomy", "Sales, lead generation, recruiting, customer service, research, web scraping, marketing, shopping, and operations agents reveal a broad market taxonomy."),
            ("https://github.com/jim-schwoebel/awesome_ai_agents#building", "Agent infrastructure gaps", "Agent deployment, observability, testing, memory, security, and workflow tooling remain recurring capability categories."),
        ),
    ),
):
    source_mesh.register(_catalog_adapter)
    opportunity_intelligence.register_source(_catalog_adapter.manifest)
for _source_adapter in source_mesh.adapters():
    if _source_adapter.manifest.adapter_id not in {item.adapter_id for item in opportunity_store.manifests()}:
        opportunity_intelligence.register_source(_source_adapter.manifest)
opportunity_scout = AutonomousOpportunityScout(source_mesh, opportunity_intelligence, event_bus=opportunity_event_bus)
opportunity_mission_bridge = OpportunityMissionBridge(opportunity_intelligence, mission_orchestrator)
web_intelligence_store = SQLiteWebIntelligenceStore(root_dir / "web-intelligence" / "live-web-intelligence.sqlite3")
web_intelligence = WebIntelligenceEngine(web_intelligence_store, governor=WebIntelligenceGovernor())
for _live_adapter_id in ("source.adapter.crawl4ai-restricted", "source.adapter.public-http"):
    if web_intelligence_store.latest_configuration(_live_adapter_id) is None:
        _adapter = source_mesh.get(_live_adapter_id)
        web_intelligence.configure_source(LiveSourceConfiguration(
            adapter_id=_adapter.manifest.adapter_id, source_id=_adapter.manifest.source_id,
            endpoint="local:unconfigured", allowed_domains=(), enabled=False,
            maximum_pages=int(_adapter.manifest.metadata.get("maximum_pages", 10)),
            maximum_depth=int(_adapter.manifest.metadata.get("maximum_depth", 3)),
            maximum_bytes=int(_adapter.manifest.metadata.get("maximum_bytes", 2_000_000)),
            metadata={"bootstrap_placeholder": True, "requires_operator_configuration": True},
        ), principal="founder")
source_conformance_service = SourceConformanceService(source_mesh, web_intelligence)
source_mesh.set_eligibility_guard(lambda manifest: (
    True if web_intelligence_store.latest_configuration(manifest.adapter_id) is None else
    bool(web_intelligence_store.latest_configuration(manifest.adapter_id).enabled) and
    web_intelligence.effective_conformance(manifest.adapter_id, manifest_hash=manifest.manifest_hash).value == "passed"
))
live_web_acquisition = LiveWebAcquisitionService(source_mesh, web_intelligence, opportunity_intelligence)
freshness_scheduler = EvidenceFreshnessScheduler(opportunity_store, web_intelligence)
adaptive_source_discovery = AdaptiveSourceDiscovery(opportunity_store, web_intelligence)
experiment_store = SQLiteExperimentStore(root_dir / "experiments" / "reversible-experiments.sqlite3")
experiment_engine = ReversibleExperimentEngine(experiment_store, opportunity_store, governor=ExperimentGovernor())
experiment_runner = ReversibleExperimentRunner(root_dir / "experiments", experiment_engine)
cognitive_gateway = AetherCognitiveGateway(
    model_provider,
    conversation_store=conversation_store,
    system_prompt=_load_system_prompt(),
    action_executor=routed_action_executor,
    memory_fabric=memory_fabric,
)
event_bus = EventBus(root_dir / "events" / "sense-path.jsonl")
sense_path = SenseEventPath(event_bus, cognitive_gateway)
browser_sense_event_bus = EventBus(root_dir / "events" / "browser-senses.jsonl")
_browser_secret = str(os.environ.get("AETHER_BROWSER_SENSE_SECRET") or os.environ.get("AUTH_SECRET_KEY") or os.environ.get("AETHER_OPERATOR_TOKEN") or "aether-browser-senses-development-secret")
if len(_browser_secret.encode("utf-8")) < 32:
    _browser_secret = hashlib.sha256(_browser_secret.encode("utf-8")).hexdigest()
browser_sense_service = BrowserSenseService(
    root_dir / "senses", sense_path, event_bus=browser_sense_event_bus,
    token_codec=BrowserSessionTokenCodec(_browser_secret), livekit_issuer=LiveKitTokenIssuer(),
    maximum_frame_bytes=int(os.environ.get("AETHER_VISION_MAX_FRAME_BYTES", "750000")),
    default_ttl_seconds=int(os.environ.get("AETHER_BROWSER_SENSE_TTL_SECONDS", "3600")),
)
_senses_origin = str(os.environ.get("AETHER_SENSES_ORIGIN") or "https://aethers.my.id").strip().rstrip("/")
browser_sense_bootstrap = BrowserSenseBootstrapService(
    root_dir / "senses" / "browser-senses-auth.sqlite3",
    event_bus=browser_sense_event_bus,
    secret=_browser_secret,
    allowed_origin=_senses_origin,
)
trusted_approval_inbox = TrustedApprovalInbox(pending_action_store, action_path, action_event_bus)
approval_coordinator = ApprovalCoordinator(trusted_approval_inbox, cognitive_gateway)
approval_inbox = ApprovalInboxService(approval_coordinator)
browser_sense_service.set_action_projector(BrowserSenseActionProjector(
    action_event_bus,
    routed_action_executor,
    approval_inbox,
))
operator_authenticator = OperatorAuthenticator()


def _executive_reasoner(prompt: str) -> str:
    response = model_provider.invoke_sync(
        ModelRequest(
            capability="reason",
            messages=[
                {"role": "system", "content": _load_system_prompt()},
                {"role": "user", "content": prompt},
            ],
        )
    )
    return str(response.content)


executive_engine = CircadianExecutiveEngine(root_dir, reasoner=_executive_reasoner)
telegram_adapter = TelegramSenseAdapter(
    sense_path,
    behavior_monitor=behavior_monitor,
    session_reset=cognitive_gateway.clear_session,
    approval_inbox=approval_inbox,
)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


async def circadian_loop() -> None:
    while True:
        await asyncio.sleep(14400)
        try:
            await asyncio.to_thread(executive_engine.run_daily_cycle)
        except Exception as exc:
            print(f"Circadian Loop Error: {exc}")


async def vision_orphan_sweeper_loop() -> None:
    while True:
        await asyncio.sleep(5)
        try:
            await asyncio.to_thread(browser_sense_service.sweep_orphan_frames)
        except Exception as exc:
            browser_sense_event_bus.emit(
                EventType.BROWSER_SENSE_VISION_FRAME_SWEPT,
                actor="aether.browser-senses",
                payload={"sweep_error": type(exc).__name__},
                severity="error",
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    circadian_task = asyncio.create_task(circadian_loop())
    telegram_task = asyncio.create_task(telegram_adapter.start_polling())
    fleet_task = asyncio.create_task(fleet_scheduler.run_forever())
    vision_sweeper_task = asyncio.create_task(vision_orphan_sweeper_loop())
    try:
        yield
    finally:
        for task in (circadian_task, telegram_task, fleet_task, vision_sweeper_task):
            task.cancel()
        for task in (circadian_task, telegram_task, fleet_task, vision_sweeper_task):
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="Aether Gateway API", version="0.19.2", lifespan=lifespan)
_cors_extra_origins = tuple(
    item.strip().rstrip("/")
    for item in os.environ.get("AETHER_CORS_ALLOWED_ORIGINS", "").split(",")
    if item.strip()
)
if "*" in _cors_extra_origins:
    raise RuntimeError("AETHER_CORS_ALLOWED_ORIGINS must not contain a wildcard")
_cors_origins = tuple(dict.fromkeys((
    _senses_origin,
    *_cors_extra_origins,
)))
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def browser_senses_response_boundary(request: Request, call_next):
    path = request.url.path
    if (
        path.startswith("/api/browser-senses/")
        and not path.startswith("/api/browser-senses/worker/")
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
    ):
        origin = str(request.headers.get("origin") or "").strip().rstrip("/")
        fetch_site = str(request.headers.get("sec-fetch-site") or "").strip().casefold()
        if origin != browser_sense_bootstrap.allowed_origin or fetch_site != "same-origin":
            return JSONResponse(
                status_code=403,
                content={"detail": "Browser sense request origin is not permitted"},
                headers={"Cache-Control": "no-store"},
            )
    response = await call_next(request)
    if (
        path == "/health"
        or path == "/senses"
        or path.startswith(("/senses/", "/api/", "/aether/api/"))
    ):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    if path == "/senses" or path.startswith("/senses/"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; worker-src 'self'; "
            "manifest-src 'self'; "
            "connect-src 'self' https://*.livekit.cloud wss://*.livekit.cloud; "
            "img-src 'self' data: blob:; media-src 'self' blob:; object-src 'none'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "microphone=(self), camera=(self), display-capture=(self)"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response

GATEWAY_STARTED_AT = datetime.datetime.now(datetime.UTC)


def _health_timestamp(value: datetime.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class ChatRequest(BaseModel):
    message: str
    session_id: str = "http:default"
    fuel: str | None = None


class BrowserSenseSessionRequest(BaseModel):
    display_name: str = "Founder"
    capabilities: list[str] = Field(default_factory=lambda: ["text", "microphone", "speaker", "camera", "screen-share"])
    ttl_seconds: int = Field(default=3600, ge=300, le=3600)
    challenge_id: str = Field(min_length=1, max_length=200)
    device_signature: str = Field(min_length=1, max_length=512)


class BrowserSenseBootstrapRequest(BaseModel):
    device_label: str = Field(min_length=1, max_length=120)
    client_mode: str = Field(default="browser", min_length=1, max_length=32)
    capabilities: list[str] = Field(default_factory=lambda: ["text", "microphone", "speaker", "camera", "screen-share"])
    public_key_jwk: dict
    verifier_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class BrowserSenseBootstrapExchangeRequest(BaseModel):
    verifier: str = Field(min_length=1, max_length=256)
    device_signature: str = Field(min_length=1, max_length=512)


class BrowserSenseBootstrapDecisionRequest(BaseModel):
    approved: bool
    reason: str = Field(min_length=1, max_length=500)


class BrowserSenseSessionStateRequest(BaseModel):
    transport: str | None = None
    reason: str | None = None


class BrowserSenseTrackRequest(BaseModel):
    track_sid: str = Field(min_length=1, max_length=200)
    kind: str
    source: str = Field(default="browser", min_length=1, max_length=100)
    muted: bool = False
    metadata: dict = Field(default_factory=dict)


class BrowserSenseTurnIdentityRequest(BaseModel):
    turn_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    correlation_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    generation: int = Field(default=0, ge=0, le=2_147_483_647)
    retry_of_turn_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class BrowserSenseTextRequest(BrowserSenseTurnIdentityRequest):
    text: str = Field(min_length=1, max_length=20000)


class BrowserSenseVisionRequest(BrowserSenseTurnIdentityRequest):
    consent_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    source: str = Field(pattern=r"^(camera|screen)$")
    sequence_number: int = Field(ge=1, le=2_147_483_647)
    captured_at: str = Field(min_length=20, max_length=40)
    data_base64: str = Field(min_length=1)
    content_type: str = "image/jpeg"
    prompt: str = Field(default="Describe materially relevant objects, people, text, and changes visible in this frame.", max_length=4000)
    width: int = Field(ge=1, le=4096)
    height: int = Field(ge=1, le=4096)


class BrowserSenseVisionConsentRequest(BaseModel):
    source: str = Field(pattern=r"^(camera|screen)$")
    mode: str = Field(pattern=r"^(one-shot|bounded)$")


class BrowserSenseVisionConsentRevokeRequest(BaseModel):
    reason: str = Field(default="explicit-stop", min_length=1, max_length=160)


class BrowserSenseWorkerChatRequest(BrowserSenseTurnIdentityRequest):
    room_name: str = Field(min_length=1, max_length=200)
    participant_identity: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20000)


class BrowserSenseInterruptRequest(BaseModel):
    correlation_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    previous_generation: int = Field(ge=0, le=2_147_483_647)
    next_generation: int = Field(ge=1, le=2_147_483_647)
    reason: str = Field(
        pattern=r"^(user_barge_in|explicit_stop|competing_input|disconnect|suspend)$"
    )
    delivered_audio_ms: int | None = Field(default=None, ge=0)
    livekit_control_sent: bool = False
    browser_audio_stopped: bool = False


class BrowserSenseWorkerInterruptRequest(BrowserSenseInterruptRequest):
    room_name: str = Field(min_length=1, max_length=200)
    provider_cancel_supported: bool
    provider_cancelled: bool


class DelegateRequest(BaseModel):
    task: str
    worker: str = "local-process"
    target_project: str | None = None


class ApprovalDecisionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    expected_action_hash: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$"
    )


class RuntimeConformanceRequest(BaseModel):
    ttl_hours: int = Field(default=24, ge=1, le=168)


class RuntimeOperationsRefreshRequest(BaseModel):
    renew_due_receipts: bool = True
    ttl_hours: int = Field(default=24, ge=1, le=168)


class FleetJobUpdateRequest(BaseModel):
    interval_seconds: int | None = Field(default=None, ge=5, le=604800)
    enabled: bool | None = None
    run_immediately: bool = False


class FleetIncidentDecisionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class FleetCostEventRequest(BaseModel):
    driver_id: str = Field(min_length=1, max_length=200)
    task_id: str | None = None
    cost_usd: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    source: str = Field(default="operator", min_length=1, max_length=100)
    metadata: dict = Field(default_factory=dict)


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 6
    namespaces: list[str] = ["episodes", "knowledge"]
    session_id: str | None = None


class KnowledgeProposalRequest(BaseModel):
    claim: str
    evidence_record_ids: list[str]
    claim_key: str | None = None
    polarity: int = 0
    contradicting_record_ids: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class KnowledgeDecisionRequest(BaseModel):
    reason: str
    confidence: float | None = None


class KnowledgeCurateRequest(BaseModel):
    limit: int = 500


class EvolutionTriggerRequest(BaseModel):
    trigger_type: str = "capability-gap"
    summary: str
    target: str
    fingerprint: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class EvolutionCommandRequest(BaseModel):
    name: str
    argv: list[str]
    timeout_seconds: int = 120


class EvolutionCandidateRequest(BaseModel):
    trigger_id: str
    target_type: str = "code"
    target_path: str
    candidate_content: str
    rationale: str
    generator_id: str
    deterministic_checks: list[EvolutionCommandRequest]
    heldout_checks: list[EvolutionCommandRequest]
    retry_reason: str | None = None
    metadata: dict = Field(default_factory=dict)


class EvolutionDecisionRequest(BaseModel):
    reason: str


class EvolutionRollbackRequest(BaseModel):
    reason: str


class SkillCandidateRequest(BaseModel):
    name: str
    version: str
    summary: str
    instructions: str
    capabilities: list[str]
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    side_effects: list[str] = Field(default_factory=list)
    runtime_requirements: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    trigger_type: str = "capability-gap"
    trigger_fingerprint: str
    evidence_ids: list[str]
    observed_count: int = 1
    successful_count: int = 0
    source_workflow: str | None = None
    generator_id: str = "external"
    prior_skill_id: str | None = None
    rationale: str
    retry_reason: str | None = None
    deterministic_checks: list[EvolutionCommandRequest]
    heldout_checks: list[EvolutionCommandRequest]
    metadata: dict = Field(default_factory=dict)


class SkillDecisionRequest(BaseModel):
    reason: str


class SkillUsageRequest(BaseModel):
    runtime_id: str
    success: bool
    duration_seconds: float = 0.0
    session_id: str | None = None
    event_id: str | None = None
    error_fingerprint: str | None = None
    metadata: dict = Field(default_factory=dict)


class SkillReviewRequest(BaseModel):
    apply: bool = True


class CapabilityExecuteRequest(BaseModel):
    capability: str
    input: dict = Field(default_factory=dict)
    required_runtime_features: list[str] = Field(default_factory=list)
    allowed_side_effects: list[str] = Field(default_factory=list)
    reason: str = "Execute a governed Aether capability requirement."
    risk: str = "low"
    reversible: bool = True
    allow_fallback: bool = True
    session_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class WorkspaceBindRequest(BaseModel):
    root_path: str
    session_id: str
    workspace_id: str | None = None
    allowed_relative_paths: list[str] = Field(default_factory=lambda: ["."])
    writable: bool = True
    metadata: dict = Field(default_factory=dict)


class CodingEditRequest(BaseModel):
    path: str
    content: str
    expected_sha256: str | None = None


class CodingVerificationRequest(BaseModel):
    argv: list[str]
    timeout_seconds: float = 120.0
    label: str = "verification"


class CodingTaskRequest(BaseModel):
    objective: str
    workspace_id: str
    session_id: str
    edits: list[CodingEditRequest] = Field(default_factory=list)
    verification_commands: list[CodingVerificationRequest] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=lambda: ["coding.edit"])
    required_runtime_features: list[str] = Field(default_factory=list)
    max_artifacts: int = 10
    max_total_bytes: int = 262144
    allow_fallback: bool = True
    metadata: dict = Field(default_factory=dict)


def _authenticate_operator(token: str | None):
    try:
        return operator_authenticator.authenticate(token, channel="http")
    except OperatorAuthError as exc:
        status = 503 if not operator_authenticator.configured else 401
        raise HTTPException(status_code=status, detail=str(exc)) from exc


class TaskUpdate(BaseModel):
    status: str


class ScoutRunRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=500)
    queries: list[str] = Field(min_length=1, max_length=20)
    source_kinds: list[str] = Field(default_factory=list)
    maximum_sources: int = Field(default=12, ge=1, le=50)
    maximum_snapshots: int = Field(default=40, ge=1, le=200)
    maximum_bytes: int = Field(default=4000000, ge=1024, le=50000000)
    maximum_duration_seconds: int = Field(default=300, ge=1, le=3600)
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    autonomy_level: str = "observe"
    metadata: dict = Field(default_factory=dict)


class OpportunityCandidateRequest(BaseModel):
    title: str
    problem_statement: str
    beneficiary: str
    value_proposition: str
    revenue_hypothesis: str
    category: str
    claim_ids: list[str] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    expected_upside_usd: float = Field(ge=0.0)
    probability_success: float = Field(ge=0.0, le=1.0)
    estimated_cost_usd: float = Field(ge=0.0)
    estimated_duration_hours: float = Field(ge=0.0)
    risk: str = "medium"
    strategic_alignment: float = Field(default=0.7, ge=0.0, le=1.0)
    reversibility: float = Field(default=0.8, ge=0.0, le=1.0)
    time_to_validation: float = Field(default=0.7, ge=0.0, le=1.0)
    legal_risk_penalty: float = Field(default=0.1, ge=0.0, le=1.0)
    platform_dependency_penalty: float = Field(default=0.1, ge=0.0, le=1.0)
    saturation_penalty: float = Field(default=0.2, ge=0.0, le=1.0)
    strategy_tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class PortfolioPolicyRequest(BaseModel):
    maximum_selected_candidates: int = Field(default=3, ge=1, le=20)
    maximum_total_experiment_budget_usd: float = Field(default=100.0, ge=0.0)
    maximum_high_risk_candidates: int = Field(default=1, ge=0, le=20)
    maximum_single_category_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    minimum_independent_sources: int = Field(default=2, ge=1, le=20)
    minimum_evidence_confidence: float = Field(default=0.45, ge=0.0, le=1.0)
    minimum_utility_score: float = 0.0
    reserved_exploration_fraction: float = Field(default=0.2, ge=0.0, le=1.0)


class PortfolioDecisionRequest(BaseModel):
    decision: str
    reason: str = Field(min_length=12, max_length=1000)
    allocated_budget_usd: float = Field(default=0.0, ge=0.0)


class ExperimentMandateRequest(BaseModel):
    autonomy_level: str = "sandbox-experiment"
    allowed_capabilities: list[str]
    maximum_cost_usd: float = Field(ge=0.0)
    maximum_external_actions: int = Field(default=0, ge=0, le=1000)
    maximum_duration_seconds: int = Field(default=3600, ge=1, le=604800)
    expires_in_seconds: int = Field(default=86400, ge=60, le=2592000)
    reversible_only: bool = True
    forbidden_capabilities: list[str] = Field(default_factory=lambda: ["credential-export", "self-approval", "northstar-modification", "legal-commitment"])
    reason: str = Field(min_length=12, max_length=1000)


class LiveSourceConfigurationRequest(BaseModel):
    adapter_id: str
    source_id: str
    endpoint: str
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    credential_handle: str | None = None
    maximum_pages: int = Field(default=10, ge=1, le=500)
    maximum_depth: int = Field(default=3, ge=0, le=20)
    maximum_bytes: int = Field(default=2000000, ge=1024, le=100000000)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    enabled: bool = True
    metadata: dict = Field(default_factory=dict)


class LiveAcquisitionRequest(BaseModel):
    adapter_id: str
    url: str
    title: str = ""
    objective: str = Field(min_length=3, max_length=500)


class SourceConformanceRequest(BaseModel):
    ttl_seconds: int = Field(default=86400, ge=60, le=2592000)


class FreshnessRunRequest(BaseModel):
    fresh_for_seconds: int = Field(default=86400, ge=1)
    aging_for_seconds: int = Field(default=259200, ge=1)
    maximum_stale_fraction: float = Field(default=0.35, ge=0, le=1)
    refresh_batch_size: int = Field(default=25, ge=1, le=1000)
    evaluated_at: str | None = None


class SourceDiscoveryRunRequest(BaseModel):
    minimum_mentions: int = Field(default=1, ge=1, le=100)
    maximum_candidates: int = Field(default=50, ge=1, le=500)


class SourceDiscoveryDecisionRequest(BaseModel):
    decision: str
    reason: str = Field(min_length=12, max_length=1000)


class ExperimentStepRequest(BaseModel):
    name: str
    kind: str
    capability: str
    payload: dict = Field(default_factory=dict)
    estimated_cost_usd: float = Field(default=0, ge=0)
    reversible: bool = True
    external_actions: int = Field(default=0, ge=0, le=1000)


class ReversibleExperimentPlanRequest(BaseModel):
    candidate_id: str
    mandate_id: str
    objective: str
    hypothesis: str
    success_metrics: list[str] = Field(min_length=1)
    stop_conditions: list[str] = Field(min_length=1)
    steps: list[ExperimentStepRequest] = Field(min_length=1, max_length=50)
    maximum_cost_usd: float = Field(ge=0)
    maximum_duration_seconds: int = Field(default=3600, ge=1, le=604800)
    maximum_artifact_bytes: int = Field(default=2000000, ge=1024, le=100000000)
    maximum_artifact_files: int = Field(default=50, ge=1, le=50)
    private_preview: bool = True
    planner_id: str = "aether.experiment-planner"
    metadata: dict = Field(default_factory=dict)


class DemandSignalRequest(BaseModel):
    kind: str
    state: str
    quantity: float = Field(ge=0)
    unit: str
    measured_at: str = ""
    source: str
    external_reference: str | None = None
    verifier: str | None = None
    metadata: dict = Field(default_factory=dict)


class ExternalReviewRequest(BaseModel):
    step_id: str
    action_summary: str
    consequence: str
    ttl_seconds: int = Field(default=3600, ge=60, le=604800)


class ExternalReviewDecisionRequest(BaseModel):
    approved: bool
    reason: str = Field(min_length=12, max_length=1000)


class OpportunityEvidenceRequest(BaseModel):
    source: str
    statement: str
    stance: str = "supports"
    observed_at: str = ""
    external_reference: str | None = None
    independent_source_id: str | None = None
    verified: bool = False
    metadata: dict = Field(default_factory=dict)


class OpportunityIntakeRequest(BaseModel):
    title: str
    lane: str = "external-value"
    problem_statement: str
    beneficiary: str
    value_proposition: str
    probability_success: float = Field(ge=0.0, le=1.0)
    upside_usd: float = Field(ge=0.0)
    estimated_cost_usd: float = Field(ge=0.0)
    estimated_duration_hours: float = Field(ge=0.0)
    revenue_hypothesis: str = ""
    assumptions: list[str] = Field(default_factory=list)
    evidence: list[OpportunityEvidenceRequest] = Field(default_factory=list)
    risk: str = "medium"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: dict = Field(default_factory=dict)


class MissionBudgetRequest(BaseModel):
    max_cost_usd: float = Field(default=10.0, ge=0.0)
    max_duration_seconds: int = Field(default=3600, ge=1)
    max_step_attempts: int = Field(default=10, ge=1)
    max_high_risk_actions: int = Field(default=0, ge=0)
    minimum_expected_value_usd: float = 0.0


class MissionStepRequest(BaseModel):
    title: str
    target: str = "tool"
    operation: str
    arguments: dict = Field(default_factory=dict)
    required_scopes: list[str] = Field(default_factory=list)
    reason: str
    risk: str = "low"
    reversible: bool = True
    success_criteria: list[str]
    depends_on: list[str] = Field(default_factory=list)
    max_attempts: int = Field(default=1, ge=1)
    stop_on_failure: bool = True
    explicit_retry_reason: str | None = None
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    metadata: dict = Field(default_factory=dict)
    step_id: str | None = None


class MissionPlanRequest(BaseModel):
    brief_id: str
    objective: str
    northstar_alignment: str
    northstar_principle_ids: list[str]
    strategy_tags: list[str] = Field(default_factory=list)
    steps: list[MissionStepRequest]
    budget: MissionBudgetRequest = Field(default_factory=MissionBudgetRequest)
    stop_conditions: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class MissionDecisionRequest(BaseModel):
    reason: str


class MissionRunRequest(BaseModel):
    maximum_steps: int = Field(default=5, ge=1, le=20)


class MissionValueEvidenceRequest(BaseModel):
    kind: str
    description: str
    source: str
    amount_usd: float | None = Field(default=None, ge=0.0)
    external_reference: str | None = None
    related_evidence_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class MissionOutcomeRequest(BaseModel):
    achieved: bool
    summary: str
    lessons: list[str] = Field(default_factory=list)


@app.get("/health")
def get_health():
    checked_at = datetime.datetime.now(datetime.UTC)
    return {
        "status": "ok",
        "service": "aether-gateway",
        "version": app.version,
        "started_at": _health_timestamp(GATEWAY_STARTED_AT),
        "checked_at": _health_timestamp(checked_at),
        "uptime_seconds": round((checked_at - GATEWAY_STARTED_AT).total_seconds(), 3),
        "aether_home": str(root_dir),
    }


@app.get("/api/status")
async def get_status():
    return {
        "status": "online",
        "aether_home": str(root_dir),
        "cognition": cognitive_gateway.adapter_id,
        "model_provider": model_provider.provider_id,
        "sense_event_count": len(event_bus.replay()),
        "action_event_count": len(action_event_bus.replay()),
        "pending_approval_count": len(approval_inbox.list(ApprovalStatus.PENDING)),
        "runtime": runtime_adapter.adapter_id,
        "available_tools": [tool.name for tool in tool_registry.all()],
        "security": behavior_monitor.get_status(),
        "memory": await memory_fabric.stats(),
        "knowledge": {
            "proposed": len(knowledge_proposals.list(KnowledgeProposalStatus.PROPOSED)),
            "promoted": len(knowledge_proposals.list(KnowledgeProposalStatus.PROMOTED)),
            "rejected": len(knowledge_proposals.list(KnowledgeProposalStatus.REJECTED)),
        },
        "evolution": {**evolution_engine.status(), "workspace": str(evolution_workspace)},
        "skills": {**skill_factory.status(), "workspace": str(skill_workspace), "installer": skill_installer.adapter_id},
        "missions": {**mission_store.status(), "event_count": len(mission_event_bus.replay())},
        "opportunity_intelligence": {**opportunity_store.status(), "event_count": len(opportunity_event_bus.replay())},
        "browser_senses": browser_sense_service.status(),
        "capability_router": {
            "policy_id": "aether.capability-router.v1",
            "runtime_profiles": [
                {
                    "adapter_id": profile.adapter_id,
                    "routing_key": profile.routing_key,
                    "features": list(profile.runtime_features),
                    "supported_side_effects": list(profile.supported_side_effects),
                    "healthy": profile.healthy,
                }
                for profile in capability_router.runtime_profiles
            ],
            "event_count": len(capability_event_bus.replay()),
        },
        "coding_runtime": {
            "policy_id": "aether.runtime-adapter-sdk.v1",
            "allowed_workspace_roots": [str(item) for item in coding_allowed_roots],
            "telemetry": runtime_telemetry.status(),
            "event_count": len(coding_runtime_event_bus.replay()),
        },
    }


def _browser_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing browser sense bearer token")
    return authorization[7:].strip()


def _authenticate_sense_worker(authorization: str | None) -> None:
    configured = str(os.environ.get("AETHER_SENSE_WORKER_TOKEN") or "")
    supplied = _browser_bearer(authorization) if authorization else ""
    if not configured or not hmac.compare_digest(configured, supplied):
        raise HTTPException(status_code=401, detail="Invalid sense worker credential")


def _require_senses_origin(request: Request) -> None:
    origin = str(request.headers.get("origin") or "").strip().rstrip("/")
    fetch_site = str(request.headers.get("sec-fetch-site") or "").strip().casefold()
    if origin != browser_sense_bootstrap.allowed_origin or fetch_site != "same-origin":
        raise HTTPException(status_code=403, detail="Browser sense request origin is not permitted")


def _senses_source(request: Request) -> str:
    if os.environ.get("AETHER_TRUST_CLOUDFLARE_HEADERS", "false").strip().casefold() in {"1", "true", "yes", "on"}:
        candidate = str(request.headers.get("cf-connecting-ip") or "").strip()
        if candidate:
            return candidate
    return str(request.client.host if request.client else "network-unavailable")


def _set_device_cookie(response: Response, credential: str) -> None:
    response.set_cookie(
        "__Host-aether_device", credential,
        max_age=browser_sense_bootstrap.device_absolute_seconds,
        secure=True, httponly=True, samesite="strict", path="/",
    )


def _set_session_cookie(response: Response, credential: str) -> None:
    response.set_cookie(
        "__Host-aether_senses", credential,
        max_age=browser_sense_bootstrap.session_absolute_seconds,
        secure=True, httponly=True, samesite="strict", path="/",
    )


def _bootstrap_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Browser sense bootstrap resource not found")
    if isinstance(exc, BootstrapRateLimitError):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, (DeviceCredentialError, SessionCredentialError, PermissionError)):
        status = 403 if "CSRF" in str(exc) else 401
        return HTTPException(status_code=status, detail=str(exc))
    if isinstance(exc, BootstrapStateError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


_BROWSER_SENSE_PROTOCOL_ERRORS = (BootstrapError, KeyError, PermissionError, ValueError)


def _browser_cookie_auth(
    request: Request,
    csrf_nonce: str | None,
    *,
    require_csrf: bool = True,
) -> tuple[str, dict, object]:
    _require_senses_origin(request)
    credential = str(request.cookies.get("__Host-aether_senses") or "")
    try:
        binding = browser_sense_bootstrap.authenticate_session(
            credential, csrf_nonce=csrf_nonce, require_csrf=require_csrf,
        )
        session = browser_sense_service.authenticate(credential)
    except (BrowserSenseAuthError, SessionCredentialError) as exc:
        raise _bootstrap_error(exc) from exc
    if session.session_id != binding["session_id"]:
        raise HTTPException(status_code=401, detail="Browser sense session binding mismatch")
    return credential, binding, session


@app.get("/api/browser-senses/status")
def browser_senses_status():
    return {**browser_sense_service.status(), "bootstrap": browser_sense_bootstrap.status_summary()}


@app.post("/api/browser-senses/bootstrap/requests", status_code=201)
def create_browser_sense_bootstrap(
    req: BrowserSenseBootstrapRequest,
    request: Request,
):
    _require_senses_origin(request)
    try:
        return browser_sense_bootstrap.request_pairing(
            public_key_jwk=req.public_key_jwk,
            verifier_hash=req.verifier_hash,
            device_label=req.device_label,
            client_mode=req.client_mode,
            capabilities=req.capabilities,
            source=_senses_source(request),
        )
    except _BROWSER_SENSE_PROTOCOL_ERRORS as exc:
        raise _bootstrap_error(exc) from exc


@app.post("/api/browser-senses/bootstrap/requests/{bootstrap_id}/status")
def browser_sense_bootstrap_status(
    bootstrap_id: str,
    request: Request,
    x_aether_bootstrap_proof: str | None = Header(default=None),
):
    _require_senses_origin(request)
    try:
        return browser_sense_bootstrap.status(
            bootstrap_id, client_proof=x_aether_bootstrap_proof or "",
        )
    except _BROWSER_SENSE_PROTOCOL_ERRORS as exc:
        raise _bootstrap_error(exc) from exc


@app.get("/api/browser-senses/bootstrap/requests")
def list_browser_sense_bootstraps(
    request: Request,
    status: str = Query(default="pending"),
    x_aether_operator_token: str | None = Header(default=None),
):
    _require_senses_origin(request)
    _authenticate_operator(x_aether_operator_token)
    if status not in {"pending", "approved", "denied", "expired", "exchanged", "all"}:
        raise HTTPException(status_code=400, detail="Unknown browser sense pairing status")
    return {"requests": browser_sense_bootstrap.list_requests(state=status)}


@app.post("/api/browser-senses/bootstrap/requests/{bootstrap_id}/decision")
def decide_browser_sense_bootstrap(
    bootstrap_id: str,
    req: BrowserSenseBootstrapDecisionRequest,
    request: Request,
    x_aether_operator_token: str | None = Header(default=None),
):
    _require_senses_origin(request)
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        return browser_sense_bootstrap.decide(
            bootstrap_id,
            approved=req.approved,
            principal=operator.principal,
            reason=req.reason,
            channel=operator.channel,
        )
    except _BROWSER_SENSE_PROTOCOL_ERRORS as exc:
        raise _bootstrap_error(exc) from exc


@app.post("/api/browser-senses/bootstrap/requests/{bootstrap_id}/exchange")
def exchange_browser_sense_bootstrap(
    bootstrap_id: str,
    req: BrowserSenseBootstrapExchangeRequest,
    request: Request,
    response: Response,
    x_aether_bootstrap_proof: str | None = Header(default=None),
):
    _require_senses_origin(request)
    try:
        result = browser_sense_bootstrap.exchange(
            bootstrap_id,
            client_proof=x_aether_bootstrap_proof or "",
            verifier=req.verifier,
            device_signature=req.device_signature,
            principal=operator_authenticator.principal,
        )
    except _BROWSER_SENSE_PROTOCOL_ERRORS as exc:
        raise _bootstrap_error(exc) from exc
    _set_device_cookie(response, result.pop("credential"))
    return result


@app.delete("/api/browser-senses/devices/{device_id}")
def revoke_browser_sense_device(
    device_id: str,
    request: Request,
    x_aether_operator_token: str | None = Header(default=None),
):
    _require_senses_origin(request)
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        result = browser_sense_bootstrap.revoke_device(
            device_id, principal=operator.principal, reason="explicit-operator-revocation",
        )
        for session_id in result["sessions_closed"]:
            browser_sense_service.close_session(session_id, reason="device-revoked")
    except _BROWSER_SENSE_PROTOCOL_ERRORS as exc:
        raise _bootstrap_error(exc) from exc
    return {
        **result,
        "session_ids_closed": result["sessions_closed"],
        "sessions_closed": len(result["sessions_closed"]),
    }


@app.post("/api/browser-senses/session/challenges", status_code=201)
def create_browser_sense_session_challenge(request: Request):
    _require_senses_origin(request)
    try:
        return browser_sense_bootstrap.create_session_challenge(
            str(request.cookies.get("__Host-aether_device") or "")
        )
    except _BROWSER_SENSE_PROTOCOL_ERRORS as exc:
        raise _bootstrap_error(exc) from exc


@app.post("/api/browser-senses/session")
def create_browser_sense_session(
    req: BrowserSenseSessionRequest,
    request: Request,
    response: Response,
):
    _require_senses_origin(request)
    try:
        device = browser_sense_bootstrap.consume_session_challenge(
            str(request.cookies.get("__Host-aether_device") or ""),
            challenge_id=req.challenge_id,
            device_signature=req.device_signature,
        )
        capabilities = tuple(BrowserSenseCapability(item) for item in req.capabilities)
        issued = browser_sense_service.issue_session(
            principal=device["principal"], display_name=req.display_name, capabilities=capabilities,
            ttl_seconds=req.ttl_seconds,
            metadata={"channel": "paired-device", "device_id": device["device_id"]},
        )
        session_credential = issued.pop("browser_session_token")
        csrf_nonce = browser_sense_bootstrap.bind_session(
            session_id=issued["session"]["session_id"],
            device_id=device["device_id"],
            session_credential=session_credential,
            expires_at=issued["session"]["expires_at"],
        )
    except _BROWSER_SENSE_PROTOCOL_ERRORS as exc:
        raise _bootstrap_error(exc) from exc
    _set_session_cookie(response, session_credential)
    return {**issued, "csrf_nonce": csrf_nonce}


@app.post("/api/browser-senses/session/active")
def activate_browser_sense_session(
    req: BrowserSenseSessionStateRequest,
    request: Request,
    x_aether_csrf: str | None = Header(default=None),
):
    token, binding, _ = _browser_cookie_auth(request, x_aether_csrf)
    try:
        session = browser_sense_service.mark_active(token, metadata={"transport": req.transport})
        browser_sense_bootstrap.mark_session_state(binding["session_id"], "active")
        return browser_sense_service._session_dict(session)
    except BrowserSenseAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/api/browser-senses/session/status")
def authenticated_browser_sense_session_status(
    request: Request,
    x_aether_csrf: str | None = Header(default=None),
):
    _, _, session = _browser_cookie_auth(request, x_aether_csrf)
    return browser_sense_service._session_dict(session)


@app.post("/api/browser-senses/session/close")
def close_browser_sense_session(
    req: BrowserSenseSessionStateRequest,
    request: Request,
    response: Response,
    x_aether_csrf: str | None = Header(default=None),
):
    token, binding, _ = _browser_cookie_auth(request, x_aether_csrf)
    try:
        reason = req.reason or "client-disconnected"
        session = browser_sense_service.close(token, reason=reason)
        browser_sense_bootstrap.close_session(binding["session_id"], reason=reason)
        response.delete_cookie(
            "__Host-aether_senses", path="/", secure=True, httponly=True, samesite="strict",
        )
        return browser_sense_service._session_dict(session)
    except BrowserSenseAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/api/browser-senses/tracks")
async def record_browser_sense_track(
    req: BrowserSenseTrackRequest,
    request: Request,
    x_aether_csrf: str | None = Header(default=None),
):
    token, _, _ = _browser_cookie_auth(request, x_aether_csrf)
    try:
        receipt = browser_sense_service.record_track(
            token, track_sid=req.track_sid, kind=MediaTrackKind(req.kind),
            source=req.source, muted=req.muted, metadata=req.metadata,
        )
        return asdict(receipt)
    except (BrowserSenseAuthError, ValueError) as exc:
        raise HTTPException(status_code=401 if isinstance(exc, BrowserSenseAuthError) else 400, detail=str(exc)) from exc


@app.post("/api/browser-senses/text")
async def browser_sense_text(
    req: BrowserSenseTextRequest,
    request: Request,
    x_aether_csrf: str | None = Header(default=None),
):
    token, _, _ = _browser_cookie_auth(request, x_aether_csrf)
    try:
        return await browser_sense_service.handle_text(
            token,
            req.text,
            turn_id=req.turn_id,
            correlation_id=req.correlation_id,
            generation=req.generation,
            retry_of_turn_id=req.retry_of_turn_id,
        )
    except BrowserSenseAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except TurnClaimConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Browser cognition failed: {type(exc).__name__}: {exc}") from exc


@app.post("/api/browser-senses/vision/consents", status_code=201)
def grant_browser_sense_vision_consent(
    req: BrowserSenseVisionConsentRequest,
    request: Request,
    x_aether_csrf: str | None = Header(default=None),
):
    token, binding, _ = _browser_cookie_auth(request, x_aether_csrf)
    try:
        return browser_sense_service.grant_vision_consent(
            token,
            device_id=binding["device_id"],
            source=req.source,
            mode=req.mode,
        )
    except BrowserSenseAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except VisionConsentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/browser-senses/vision/consents/{consent_id}/revoke")
def revoke_browser_sense_vision_consent(
    consent_id: str,
    req: BrowserSenseVisionConsentRevokeRequest,
    request: Request,
    x_aether_csrf: str | None = Header(default=None),
):
    token, binding, _ = _browser_cookie_auth(request, x_aether_csrf)
    try:
        return browser_sense_service.revoke_vision_consent(
            token,
            device_id=binding["device_id"],
            consent_id=consent_id,
            reason=req.reason,
        )
    except BrowserSenseAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except VisionConsentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/browser-senses/vision")
async def browser_sense_vision(
    req: BrowserSenseVisionRequest,
    request: Request,
    x_aether_csrf: str | None = Header(default=None),
):
    token, binding, _ = _browser_cookie_auth(request, x_aether_csrf)
    try:
        return await browser_sense_service.handle_vision(
            token, device_id=binding["device_id"], consent_id=req.consent_id,
            source=req.source, sequence_number=req.sequence_number,
            captured_at=req.captured_at, data_base64=req.data_base64,
            content_type=req.content_type,
            prompt=req.prompt, width=req.width, height=req.height,
            turn_id=req.turn_id, correlation_id=req.correlation_id,
            generation=req.generation, retry_of_turn_id=req.retry_of_turn_id,
        )
    except BrowserSenseAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except TurnClaimConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except VisionConsentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (VisionFrameValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VisionDeletionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Vision cognition failed: {type(exc).__name__}: {exc}") from exc


@app.post("/api/browser-senses/worker/chat")
async def browser_sense_worker_chat(req: BrowserSenseWorkerChatRequest, authorization: str | None = Header(default=None)):
    _authenticate_sense_worker(authorization)
    try:
        return await browser_sense_service.handle_worker_transcript(
            room_name=req.room_name,
            participant_identity=req.participant_identity,
            text=req.text,
            turn_id=req.turn_id,
            correlation_id=req.correlation_id,
            generation=req.generation,
            retry_of_turn_id=req.retry_of_turn_id,
        )
    except TurnClaimConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Voice cognition failed: {type(exc).__name__}: {exc}") from exc


@app.post("/api/browser-senses/turns/{turn_id}/status")
def browser_sense_turn_status(
    turn_id: str,
    request: Request,
    x_aether_csrf: str | None = Header(default=None),
):
    token, _, _ = _browser_cookie_auth(request, x_aether_csrf)
    try:
        return browser_sense_service.turn_status(token, turn_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Browser sense turn was not found") from exc


@app.post("/api/browser-senses/actions/{action_id}/status")
async def browser_sense_action_status(
    action_id: str,
    request: Request,
    x_aether_csrf: str | None = Header(default=None),
):
    token, _, _ = _browser_cookie_auth(request, x_aether_csrf)
    try:
        return await browser_sense_service.action_status(token, action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Browser sense action was not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/browser-senses/turns/{turn_id}/interrupt")
async def interrupt_browser_sense_turn(
    turn_id: str,
    req: BrowserSenseInterruptRequest,
    request: Request,
    x_aether_csrf: str | None = Header(default=None),
):
    token, _, _ = _browser_cookie_auth(request, x_aether_csrf)
    try:
        return browser_sense_service.interrupt_turn(
            token,
            turn_id=turn_id,
            correlation_id=req.correlation_id,
            previous_generation=req.previous_generation,
            next_generation=req.next_generation,
            reason=req.reason,
            delivered_audio_ms=req.delivered_audio_ms,
            browser_audio_stopped=req.browser_audio_stopped,
            livekit_control_sent=req.livekit_control_sent,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Browser sense turn was not found") from exc
    except (TurnClaimConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/browser-senses/worker/turns/{turn_id}/interrupt")
async def interrupt_browser_sense_worker_turn(
    turn_id: str,
    req: BrowserSenseWorkerInterruptRequest,
    authorization: str | None = Header(default=None),
):
    _authenticate_sense_worker(authorization)
    try:
        return browser_sense_service.interrupt_worker_turn(
            room_name=req.room_name,
            turn_id=turn_id,
            correlation_id=req.correlation_id,
            previous_generation=req.previous_generation,
            next_generation=req.next_generation,
            reason=req.reason,
            delivered_audio_ms=req.delivered_audio_ms,
            provider_cancel_supported=req.provider_cancel_supported,
            provider_cancelled=req.provider_cancelled,
            livekit_control_sent=req.livekit_control_sent,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Browser sense turn was not found") from exc
    except (TurnClaimConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/senses", response_class=HTMLResponse, include_in_schema=False)
def senses_console():
    return FileResponse(AIONUI_SENSES_CONSOLE_DIR / "index.html", media_type="text/html")


@app.get("/senses/app.js", include_in_schema=False)
def senses_console_js():
    return FileResponse(AIONUI_SENSES_CONSOLE_DIR / "app.js", media_type="application/javascript")


@app.get("/senses/client_state.js", include_in_schema=False)
def senses_console_client_state_js():
    return FileResponse(
        AIONUI_SENSES_CONSOLE_DIR / "client_state.js",
        media_type="application/javascript",
    )


@app.get("/senses/capability_actions.js", include_in_schema=False)
def senses_console_capability_actions_js():
    return FileResponse(
        AIONUI_SENSES_CONSOLE_DIR / "capability_actions.js",
        media_type="application/javascript",
    )


@app.get("/senses/turn_generation.js", include_in_schema=False)
def senses_console_turn_generation_js():
    return FileResponse(
        AIONUI_SENSES_CONSOLE_DIR / "turn_generation.js",
        media_type="application/javascript",
    )


@app.get("/senses/vision_capture.js", include_in_schema=False)
def senses_console_vision_capture_js():
    return FileResponse(
        AIONUI_SENSES_CONSOLE_DIR / "vision_capture.js",
        media_type="application/javascript",
    )


@app.get("/senses/pwa_runtime.js", include_in_schema=False)
def senses_console_pwa_runtime_js():
    return FileResponse(
        AIONUI_SENSES_CONSOLE_DIR / "pwa_runtime.js",
        media_type="application/javascript",
    )


@app.get("/senses/pwa_cache_policy.js", include_in_schema=False)
def senses_console_pwa_cache_policy_js():
    return FileResponse(
        AIONUI_SENSES_CONSOLE_DIR / "pwa_cache_policy.js",
        media_type="application/javascript",
    )


@app.get("/senses/styles.css", include_in_schema=False)
def senses_console_css():
    return FileResponse(AIONUI_SENSES_CONSOLE_DIR / "styles.css", media_type="text/css")


@app.get("/senses/sw.js", include_in_schema=False)
def senses_console_service_worker():
    return FileResponse(
        AIONUI_SENSES_CONSOLE_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/senses"},
    )


@app.get("/senses/manifest.webmanifest", include_in_schema=False)
def senses_console_manifest():
    return FileResponse(
        AIONUI_SENSES_CONSOLE_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@app.get("/senses/manifest.json", include_in_schema=False)
def senses_console_manifest_compatibility_alias():
    return senses_console_manifest()


@app.get("/senses/vendor/livekit-client-2.17.2.esm.js", include_in_schema=False)
def senses_console_livekit_bundle():
    return FileResponse(
        AIONUI_SENSES_CONSOLE_DIR / "vendor" / "livekit-client-2.17.2.esm.js",
        media_type="application/javascript",
    )


_SENSES_PWA_ICONS = frozenset({
    "aether-senses-192-v1.png",
    "aether-senses-512-v1.png",
    "aether-senses-maskable-512-v1.png",
})


@app.get("/senses/icons/{icon_name}", include_in_schema=False)
def senses_console_icon(icon_name: str):
    if icon_name not in _SENSES_PWA_ICONS:
        raise HTTPException(status_code=404, detail="Unknown Senses PWA icon")
    return FileResponse(
        AIONUI_SENSES_CONSOLE_DIR / "icons" / icon_name,
        media_type="image/png",
    )


@app.get("/api/security/status")
def get_security_status():
    return behavior_monitor.get_status()


@app.get("/api/security/profile")
def get_security_profile():
    return {
        "current_profile": behavior_monitor.get_current_profile(),
        "config": behavior_monitor.get_profile_config(),
    }


@app.post("/api/chat")
async def chat_with_aether(req: ChatRequest):
    session_id = req.session_id.strip() or "http:default"
    if req.message.strip().lower() in {"/clear", "clear", "reset"}:
        await cognitive_gateway.clear_session(session_id)
        return {"response": "Conversation context cleared.", "session_id": session_id}

    adapter = DirectTextSenseAdapter(adapter_id="sense.http")
    metadata = {
        "channel": "http",
        "session_id": session_id,
        "response_modality": "text",
    }
    if req.fuel:
        metadata["preferred_model"] = req.fuel

    try:
        trace = await sense_path.handle(
            adapter,
            Perception(
                modality="http.text",
                content=req.message,
                source=session_id,
                metadata=metadata,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cognitive provider failed: {type(exc).__name__}") from exc

    expression = adapter.expressions[-1]
    return {
        "response": expression.content,
        "session_id": session_id,
        "provider_id": expression.metadata.get("provider_id"),
        "model_id": expression.metadata.get("model_id"),
        "trace": trace.__dict__,
        "pending_approval": expression.metadata.get("pending_approval"),
        "action_results": expression.metadata.get("action_results"),
    }


@app.get("/api/sessions")
async def list_cognitive_sessions(limit: int = Query(default=100, ge=1, le=500)):
    return {"sessions": list(await conversation_store.list_sessions(limit=limit))}


@app.get("/api/sessions/{session_id}")
async def get_cognitive_session(session_id: str):
    return {"session_id": session_id, "messages": list(await conversation_store.get(session_id))}


@app.post("/api/memory/search")
async def search_memory(req: MemorySearchRequest):
    context = await memory_fabric.retrieve(MemoryQuery(
        text=req.query,
        namespaces=tuple(req.namespaces),
        session_id=req.session_id,
        limit=max(1, min(req.limit, 20)),
    ))
    return {
        "query": req.query,
        "hits": [
            {
                "record_id": hit.record.record_id,
                "kind": hit.record.kind.value,
                "namespace": hit.record.namespace,
                "content": hit.record.content,
                "score": hit.score,
                "provenance": {
                    "source": hit.record.provenance.source,
                    "observed_at": hit.record.provenance.observed_at,
                    "session_id": hit.record.provenance.session_id,
                    "correlation_id": hit.record.provenance.correlation_id,
                } if hit.record.provenance else None,
                "content_hash": hit.record.content_hash,
            }
            for hit in context.hits
        ],
    }


@app.post("/api/memory/rebuild")
async def rebuild_memory_index(x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    count = await memory_fabric.rebuild_index()
    return {"status": "rebuilt", "records": count, "operator": operator.principal}


@app.post("/api/memory/project/{session_id}")
async def project_memory_session(
    session_id: str,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    path = await memory_fabric.project_session(session_id)
    return {"status": "projected", "session_id": session_id, "path": path, "operator": operator.principal}


def _knowledge_proposal_dict(proposal):
    decision = knowledge_proposals.get_decision(proposal.proposal_id)
    review = knowledge_curator.review(proposal.proposal_id)
    return {
        "proposal_id": proposal.proposal_id,
        "claim": proposal.claim,
        "claim_key": proposal.claim_key,
        "polarity": proposal.polarity,
        "status": proposal.status.value,
        "proposal_hash": proposal.proposal_hash,
        "duplicate_of": proposal.duplicate_of,
        "contradiction_ids": list(proposal.contradiction_ids),
        "evidence": [
            {
                "record_id": item.record_id,
                "content_hash": item.content_hash,
                "stance": item.stance.value,
                "source": item.source,
                "observed_at": item.observed_at,
                "excerpt": item.excerpt,
            }
            for item in proposal.evidence
        ],
        "blockers": list(review.blockers),
        "warnings": list(review.warnings),
        "created_at": proposal.created_at,
        "knowledge_record_id": proposal.knowledge_record_id,
        "decision": {
            "decision_id": decision.decision_id,
            "decision": decision.decision.value,
            "principal": decision.principal,
            "channel": decision.channel,
            "reason": decision.reason,
            "confidence": decision.confidence,
            "decided_at": decision.decided_at,
        } if decision else None,
    }


@app.get("/api/knowledge/proposals")
def list_knowledge_proposals(
    status: str = Query(default="proposed"),
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    try:
        normalized = None if status == "all" else KnowledgeProposalStatus(status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown knowledge status: {status}") from exc
    return {"proposals": [_knowledge_proposal_dict(item) for item in knowledge_proposals.list(normalized)]}


@app.get("/api/knowledge/proposals/{proposal_id}")
def get_knowledge_proposal(
    proposal_id: str,
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    try:
        return _knowledge_proposal_dict(knowledge_proposals.get(proposal_id))
    except KnowledgeProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="Knowledge proposal not found") from exc


@app.post("/api/knowledge/proposals")
async def create_knowledge_proposal(
    req: KnowledgeProposalRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        proposal = await knowledge_curator.propose(
            claim=req.claim,
            evidence_record_ids=req.evidence_record_ids,
            claim_key=req.claim_key,
            polarity=req.polarity,
            contradicting_record_ids=req.contradicting_record_ids,
            metadata={**req.metadata, "requested_by": operator.principal},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _knowledge_proposal_dict(proposal)


@app.post("/api/knowledge/curate")
async def run_memory_curator(
    req: KnowledgeCurateRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    proposals = await knowledge_curator.curate_explicit_candidates(limit=max(1, min(req.limit, 5000)))
    return {
        "operator": operator.principal,
        "proposals": [_knowledge_proposal_dict(item) for item in proposals],
    }


async def _decide_knowledge(
    proposal_id: str,
    req: KnowledgeDecisionRequest,
    approved: bool,
    token: str | None,
):
    operator = _authenticate_operator(token)
    try:
        review = await knowledge_curator.decide(
            proposal_id,
            approved=approved,
            principal=operator.principal,
            channel=operator.channel,
            reason=req.reason,
            confidence=req.confidence,
        )
    except KnowledgeProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="Knowledge proposal not found") from exc
    except KnowledgePromotionBlocked as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "blockers": list(exc.blockers)}) from exc
    except KnowledgeDecisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _knowledge_proposal_dict(review.proposal)


@app.post("/api/knowledge/proposals/{proposal_id}/approve")
async def approve_knowledge(
    proposal_id: str,
    req: KnowledgeDecisionRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    return await _decide_knowledge(proposal_id, req, True, x_aether_operator_token)


@app.post("/api/knowledge/proposals/{proposal_id}/reject")
async def reject_knowledge(
    proposal_id: str,
    req: KnowledgeDecisionRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    return await _decide_knowledge(proposal_id, req, False, x_aether_operator_token)


@app.post("/api/knowledge/project/{proposal_id}")
async def project_knowledge(
    proposal_id: str,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        path = await knowledge_curator.project(proposal_id)
    except KnowledgeProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="Knowledge proposal not found") from exc
    except KnowledgePromotionBlocked as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "blockers": list(exc.blockers)}) from exc
    return {"status": "projected", "proposal_id": proposal_id, "path": path, "operator": operator.principal}


@app.get("/api/knowledge")
async def list_promoted_knowledge(
    limit: int = Query(default=100, ge=1, le=500),
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    records = await canonical_memory.list(namespaces=("knowledge",), limit=limit)
    return {
        "knowledge": [
            {
                "record_id": item.record_id,
                "claim": item.content,
                "content_hash": item.content_hash,
                "metadata": dict(item.metadata),
                "evidence_links": list(item.provenance.evidence_links) if item.provenance else [],
            }
            for item in records
        ]
    }



def _evolution_command(item: EvolutionCommandRequest, kind: EvolutionCheckKind) -> EvolutionCommand:
    return EvolutionCommand(
        argv=tuple(item.argv),
        kind=kind,
        name=item.name,
        timeout_seconds=max(1, item.timeout_seconds),
    )


def _evolution_candidate_dict(candidate):
    evaluation = evolution_store.get_evaluation(candidate.candidate_id)
    decision = evolution_store.get_decision(candidate.candidate_id)
    lineage = evolution_store.lineage_for_candidate(candidate.candidate_id)
    return {
        "candidate_id": candidate.candidate_id,
        "trigger_id": candidate.trigger_id,
        "trigger_fingerprint": candidate.trigger_fingerprint,
        "target_type": candidate.target_type.value,
        "target_path": candidate.target_path,
        "baseline_hash": candidate.baseline_hash,
        "candidate_hash": candidate.candidate_hash,
        "diff": candidate.diff,
        "rationale": candidate.rationale,
        "generator_id": candidate.generator_id,
        "retry_reason": candidate.retry_reason,
        "status": candidate.status.value,
        "created_at": candidate.created_at,
        "evaluation": {
            "evaluation_id": evaluation.evaluation_id,
            "passed": evaluation.passed,
            "baseline_score": evaluation.baseline_score,
            "candidate_score": evaluation.candidate_score,
            "improvement": evaluation.improvement,
            "regression_count": evaluation.regression_count,
            "blockers": list(evaluation.blockers),
        } if evaluation else None,
        "decision": {
            "decision_id": decision.decision_id,
            "decision": decision.decision.value,
            "principal": decision.principal,
            "channel": decision.channel,
            "reason": decision.reason,
            "lineage_id": decision.lineage_id,
        } if decision else None,
        "lineage": {
            "lineage_id": lineage.lineage_id,
            "parent_hash": lineage.parent_hash,
            "promoted_hash": lineage.promoted_hash,
            "backup_path": lineage.backup_path,
            "promoted_at": lineage.promoted_at,
            "rolled_back_at": lineage.rolled_back_at,
        } if lineage else None,
    }


@app.get("/api/evolution/status")
def evolution_status(x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    return {**evolution_engine.status(), "workspace": str(evolution_workspace), "operator": operator.principal}


@app.get("/api/evolution/triggers")
def list_evolution_triggers(
    limit: int = Query(default=100, ge=1, le=500),
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    return {"triggers": [
        {
            "trigger_id": item.trigger_id,
            "trigger_type": item.trigger_type.value,
            "fingerprint": item.fingerprint,
            "summary": item.summary,
            "evidence_ids": list(item.evidence_ids),
            "prior_learning_ids": list(item.prior_learning_ids),
            "metadata": dict(item.metadata),
            "created_at": item.created_at,
        }
        for item in evolution_store.list_triggers(limit)
    ]}


@app.post("/api/evolution/triggers")
def create_evolution_trigger(
    req: EvolutionTriggerRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        trigger_type = EvolutionTriggerType(req.trigger_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown trigger type: {req.trigger_type}") from exc
    if trigger_type == EvolutionTriggerType.CAPABILITY_GAP:
        trigger = capability_gap(
            summary=req.summary,
            target=req.target,
            evidence_ids=tuple(req.evidence_ids),
            metadata={**req.metadata, "requested_by": operator.principal},
        )
    else:
        trigger = EvolutionTrigger(
            trigger_type=trigger_type,
            fingerprint=req.fingerprint or evolution_fingerprint(category="failure", summary=req.summary, target=req.target),
            summary=req.summary,
            evidence_ids=tuple(req.evidence_ids),
            metadata={"target": req.target, **req.metadata, "requested_by": operator.principal},
        )
    saved = evolution_engine.register_trigger(trigger)
    return {
        "trigger_id": saved.trigger_id,
        "fingerprint": saved.fingerprint,
        "prior_learning_ids": list(saved.prior_learning_ids),
        "operator": operator.principal,
    }


@app.get("/api/evolution/candidates")
def list_evolution_candidates(
    limit: int = Query(default=100, ge=1, le=500),
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    return {"candidates": [_evolution_candidate_dict(item) for item in evolution_store.list_candidates(limit)]}


@app.get("/api/evolution/candidates/{candidate_id}")
def get_evolution_candidate(
    candidate_id: str,
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    try:
        return _evolution_candidate_dict(evolution_store.get_candidate(candidate_id))
    except EvolutionNotFound as exc:
        raise HTTPException(status_code=404, detail="Evolution candidate not found") from exc


@app.post("/api/evolution/candidates")
def create_evolution_candidate(
    req: EvolutionCandidateRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    target = (evolution_workspace / req.target_path).resolve()
    try:
        target.relative_to(evolution_workspace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Target escapes the configured evolution workspace") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Evolution target not found")
    try:
        candidate = evolution_engine.propose_candidate(
            trigger_id=req.trigger_id,
            target_type=EvolutionTargetType(req.target_type),
            target_path=req.target_path,
            baseline_content=target.read_text(encoding="utf-8"),
            candidate_content=req.candidate_content,
            rationale=req.rationale,
            generator_id=req.generator_id,
            deterministic_checks=tuple(_evolution_command(item, EvolutionCheckKind.DETERMINISTIC) for item in req.deterministic_checks),
            heldout_checks=tuple(_evolution_command(item, EvolutionCheckKind.HELDOUT) for item in req.heldout_checks),
            retry_reason=req.retry_reason,
            metadata={**req.metadata, "proposed_via": operator.channel},
        )
    except (EvolutionBlocked, EvolutionWorkspaceError) as exc:
        blockers = list(getattr(exc, "blockers", (str(exc),)))
        raise HTTPException(status_code=409, detail={"message": str(exc), "blockers": blockers}) from exc
    except (EvolutionNotFound, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _evolution_candidate_dict(candidate)


@app.post("/api/evolution/candidates/{candidate_id}/evaluate")
async def evaluate_evolution_candidate(
    candidate_id: str,
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    try:
        await evolution_engine.evaluate(candidate_id, evolution_sandbox)
        return _evolution_candidate_dict(evolution_store.get_candidate(candidate_id))
    except EvolutionNotFound as exc:
        raise HTTPException(status_code=404, detail="Evolution candidate not found") from exc
    except (EvolutionBlocked, EvolutionWorkspaceError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _decide_evolution(candidate_id: str, req: EvolutionDecisionRequest, approved: bool, token: str | None):
    operator = _authenticate_operator(token)
    try:
        candidate = await evolution_engine.decide(
            candidate_id,
            approved=approved,
            principal=operator.principal,
            channel=operator.channel,
            reason=req.reason,
            promoter=evolution_promoter if approved else None,
        )
    except EvolutionNotFound as exc:
        raise HTTPException(status_code=404, detail="Evolution candidate not found") from exc
    except EvolutionDecisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (EvolutionBlocked, EvolutionWorkspaceError) as exc:
        blockers = list(getattr(exc, "blockers", (str(exc),)))
        raise HTTPException(status_code=409, detail={"message": str(exc), "blockers": blockers}) from exc
    return _evolution_candidate_dict(candidate)


@app.post("/api/evolution/candidates/{candidate_id}/approve")
async def approve_evolution_candidate(
    candidate_id: str,
    req: EvolutionDecisionRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    return await _decide_evolution(candidate_id, req, True, x_aether_operator_token)


@app.post("/api/evolution/candidates/{candidate_id}/reject")
async def reject_evolution_candidate(
    candidate_id: str,
    req: EvolutionDecisionRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    return await _decide_evolution(candidate_id, req, False, x_aether_operator_token)


@app.post("/api/evolution/lineage/{lineage_id}/rollback")
async def rollback_evolution_lineage(
    lineage_id: str,
    req: EvolutionRollbackRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        lineage = await evolution_engine.rollback(
            lineage_id,
            principal=operator.principal,
            channel=operator.channel,
            reason=req.reason,
            promoter=evolution_promoter,
        )
    except EvolutionNotFound as exc:
        raise HTTPException(status_code=404, detail="Evolution lineage not found") from exc
    except (EvolutionBlocked, EvolutionDecisionConflict, EvolutionWorkspaceError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "lineage_id": lineage.lineage_id,
        "candidate_id": lineage.candidate_id,
        "rolled_back_at": lineage.rolled_back_at,
        "rollback_principal": lineage.rollback_principal,
        "rollback_reason": lineage.rollback_reason,
    }



def _skill_candidate_dict(candidate):
    benchmark = skill_store.get_benchmark(candidate.candidate_id)
    decision = skill_store.get_decision(candidate.candidate_id)
    record = skill_store.get_record(candidate.skill_id) if candidate.skill_id else None
    return {
        "candidate_id": candidate.candidate_id,
        "name": candidate.manifest.name,
        "version": candidate.manifest.version,
        "summary": candidate.manifest.summary,
        "artifact_hash": candidate.artifact_hash,
        "status": candidate.status.value,
        "trigger_type": candidate.provenance.trigger_type.value,
        "trigger_fingerprint": candidate.provenance.trigger_fingerprint,
        "evidence_ids": list(candidate.provenance.evidence_ids),
        "observed_count": candidate.provenance.observed_count,
        "successful_count": candidate.provenance.successful_count,
        "success_rate": candidate.provenance.success_rate,
        "prior_skill_id": candidate.provenance.prior_skill_id,
        "generator_id": candidate.provenance.generator_id,
        "rationale": candidate.rationale,
        "created_at": candidate.created_at,
        "benchmark": {
            "benchmark_id": benchmark.benchmark_id,
            "baseline_score": benchmark.baseline_score,
            "candidate_score": benchmark.candidate_score,
            "improvement": benchmark.improvement,
            "regression_count": benchmark.regression_count,
            "passed": benchmark.passed,
            "blockers": list(benchmark.blockers),
        } if benchmark else None,
        "decision": {
            "decision_id": decision.decision_id,
            "decision": decision.decision.value,
            "principal": decision.principal,
            "channel": decision.channel,
            "reason": decision.reason,
            "skill_id": decision.skill_id,
            "decided_at": decision.decided_at,
        } if decision else None,
        "record": _skill_record_dict(record) if record else None,
    }


def _skill_record_dict(record):
    usages = skill_store.usages(record.skill_id)
    success_rate = sum(item.success for item in usages) / len(usages) if usages else 0.0
    return {
        "skill_id": record.skill_id,
        "candidate_id": record.candidate_id,
        "name": record.manifest.name,
        "version": record.manifest.version,
        "summary": record.manifest.summary,
        "artifact_hash": record.artifact_hash,
        "lifecycle_status": record.lifecycle_status.value,
        "capabilities": list(record.manifest.usage.capabilities),
        "side_effects": list(record.manifest.usage.side_effects),
        "runtime_requirements": list(record.manifest.usage.runtime_requirements),
        "install": {
            "adapter_id": record.install_receipt.adapter_id,
            "install_path": record.install_receipt.install_path,
            "activation_pointer": record.install_receipt.activation_pointer,
        },
        "activated_at": record.activated_at,
        "usage_count": len(usages),
        "success_rate": success_rate,
    }


def _skill_command(item: EvolutionCommandRequest, kind: EvolutionCheckKind) -> EvolutionCommand:
    return EvolutionCommand(
        argv=tuple(item.argv), kind=kind, name=item.name,
        timeout_seconds=max(1, min(item.timeout_seconds, 180)),
    )


@app.get("/api/skills/status")
def skill_status(x_aether_operator_token: str | None = Header(default=None)):
    _authenticate_operator(x_aether_operator_token)
    return {**skill_factory.status(), "workspace": str(skill_workspace), "installer": skill_installer.adapter_id}


@app.get("/api/skills/candidates")
def list_skill_candidates(
    x_aether_operator_token: str | None = Header(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    _authenticate_operator(x_aether_operator_token)
    return {"candidates": [_skill_candidate_dict(item) for item in skill_store.list_candidates(limit=limit)]}


@app.get("/api/skills/candidates/{candidate_id}")
def get_skill_candidate(candidate_id: str, x_aether_operator_token: str | None = Header(default=None)):
    _authenticate_operator(x_aether_operator_token)
    try:
        return _skill_candidate_dict(skill_store.get_candidate(candidate_id))
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail="Skill candidate not found") from exc


@app.post("/api/skills/candidates")
def create_skill_candidate(
    req: SkillCandidateRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        candidate = skill_factory.propose(
            manifest=SkillManifest(
                name=req.name, version=req.version, summary=req.summary, instructions=req.instructions,
                usage=SkillUsageContract(
                    capabilities=tuple(req.capabilities), input_schema=req.input_schema,
                    output_schema=req.output_schema, side_effects=tuple(req.side_effects),
                    runtime_requirements=tuple(req.runtime_requirements),
                ),
                tags=tuple(req.tags), metadata=req.metadata,
            ),
            provenance=SkillProvenance(
                trigger_type=SkillTriggerType(req.trigger_type), trigger_fingerprint=req.trigger_fingerprint,
                evidence_ids=tuple(req.evidence_ids), observed_count=req.observed_count,
                successful_count=req.successful_count, source_workflow=req.source_workflow,
                generator_id=req.generator_id, prior_skill_id=req.prior_skill_id,
                metadata={"requested_by": operator.principal},
            ),
            deterministic_checks=tuple(_skill_command(item, EvolutionCheckKind.DETERMINISTIC) for item in req.deterministic_checks),
            heldout_checks=tuple(_skill_command(item, EvolutionCheckKind.HELDOUT) for item in req.heldout_checks),
            rationale=req.rationale, retry_reason=req.retry_reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SkillFactoryBlocked as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "blockers": list(exc.blockers)}) from exc
    return _skill_candidate_dict(candidate)


@app.post("/api/skills/candidates/{candidate_id}/benchmark")
async def benchmark_skill_candidate(candidate_id: str, x_aether_operator_token: str | None = Header(default=None)):
    _authenticate_operator(x_aether_operator_token)
    try:
        await skill_factory.benchmark(candidate_id, skill_sandbox)
        return _skill_candidate_dict(skill_store.get_candidate(candidate_id))
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail="Skill candidate not found") from exc
    except (SkillFactoryBlocked, SkillWorkspaceError) as exc:
        blockers = list(getattr(exc, "blockers", (str(exc),)))
        raise HTTPException(status_code=409, detail={"message": str(exc), "blockers": blockers}) from exc


async def _decide_skill(candidate_id: str, req: SkillDecisionRequest, approved: bool, token: str | None):
    operator = _authenticate_operator(token)
    try:
        candidate = await skill_factory.decide(
            candidate_id, approved=approved, principal=operator.principal, channel=operator.channel,
            reason=req.reason, installer=skill_installer if approved else None,
        )
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail="Skill candidate not found") from exc
    except SkillDecisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (SkillFactoryBlocked, SkillWorkspaceError) as exc:
        blockers = list(getattr(exc, "blockers", (str(exc),)))
        raise HTTPException(status_code=409, detail={"message": str(exc), "blockers": blockers}) from exc
    return _skill_candidate_dict(candidate)


@app.post("/api/skills/candidates/{candidate_id}/activate")
async def activate_skill_candidate(candidate_id: str, req: SkillDecisionRequest, x_aether_operator_token: str | None = Header(default=None)):
    return await _decide_skill(candidate_id, req, True, x_aether_operator_token)


@app.post("/api/skills/candidates/{candidate_id}/reject")
async def reject_skill_candidate(candidate_id: str, req: SkillDecisionRequest, x_aether_operator_token: str | None = Header(default=None)):
    return await _decide_skill(candidate_id, req, False, x_aether_operator_token)


@app.get("/api/skills")
def list_skills(
    x_aether_operator_token: str | None = Header(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    _authenticate_operator(x_aether_operator_token)
    return {"skills": [_skill_record_dict(item) for item in skill_store.list_records(limit=limit)]}


@app.get("/api/skills/{skill_id}")
def get_skill(skill_id: str, x_aether_operator_token: str | None = Header(default=None)):
    _authenticate_operator(x_aether_operator_token)
    try:
        return _skill_record_dict(skill_store.get_record(skill_id))
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc


@app.post("/api/skills/{skill_id}/usage")
def record_skill_usage(
    skill_id: str,
    req: SkillUsageRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        usage = skill_factory.record_usage(SkillUsageEvent(
            skill_id=skill_id, runtime_id=req.runtime_id, success=req.success,
            duration_seconds=max(0.0, req.duration_seconds), session_id=req.session_id,
            event_id=req.event_id, error_fingerprint=req.error_fingerprint,
            metadata={**req.metadata, "reported_by": operator.principal},
        ))
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc
    except SkillFactoryBlocked as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "blockers": list(exc.blockers)}) from exc
    return {"usage_id": usage.usage_id, "used_at": usage.used_at, "success": usage.success}


@app.post("/api/skills/{skill_id}/review")
async def review_skill(
    skill_id: str,
    req: SkillReviewRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    try:
        review = skill_factory.review(skill_id)
        record = await skill_factory.apply_review(skill_id) if req.apply else skill_store.get_record(skill_id)
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc
    return {
        "review": {
            "current_status": review.current_status.value,
            "recommended_status": review.recommended_status.value,
            "usage_count": review.usage_count,
            "success_rate": review.success_rate,
            "last_used_at": review.last_used_at,
            "reasons": list(review.reasons),
        },
        "skill": _skill_record_dict(record),
    }


@app.post("/api/skills/{skill_id}/archive")
async def archive_skill(
    skill_id: str,
    req: SkillDecisionRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        record = await skill_factory.lifecycle(
            skill_id, action=SkillLifecycleAction.ARCHIVE, principal=operator.principal,
            channel=operator.channel, reason=req.reason, installer=skill_installer,
        )
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc
    except SkillFactoryBlocked as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "blockers": list(exc.blockers)}) from exc
    return _skill_record_dict(record)


def _capability_execution_dict(execution):
    return {
        "requirement_id": execution.requirement.requirement_id,
        "capability": execution.requirement.capability,
        "status": execution.status.value,
        "ok": execution.ok,
        "output": execution.output,
        "error": execution.error,
        "selected_skill_id": execution.selected_skill_id,
        "failure_fingerprint": execution.failure_fingerprint,
        "attempts": list(execution.attempts),
        "route": {
            "decision_id": execution.decision.decision_id,
            "status": execution.decision.status.value,
            "blockers": list(execution.decision.blockers),
            "candidates": [
                {
                    "skill_id": item.skill_id,
                    "candidate_id": item.candidate_id,
                    "skill_name": item.skill_name,
                    "skill_version": item.skill_version,
                    "artifact_hash": item.artifact_hash,
                    "runtime_adapter_id": item.runtime_adapter_id,
                    "score": item.score,
                    "usage_count": item.usage_count,
                    "success_rate": item.success_rate,
                    "blockers": list(item.blockers),
                }
                for item in execution.decision.candidates
            ],
        },
        "pending_approval": {
            "approval_id": execution.action_result.metadata.get("approval_id"),
            "action_hash": execution.action_result.metadata.get("action_hash"),
            "expires_at": execution.action_result.metadata.get("expires_at"),
        } if execution.action_result is not None and execution.action_result.status == "pending-approval" else None,
    }


@app.get("/api/capabilities/status")
def capability_status(x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    active = [item for item in skill_store.list_records(limit=5000) if item.lifecycle_status == SkillLifecycleStatus.ACTIVE]
    return {
        "operator": operator.principal,
        "active_skill_count": len(active),
        "capabilities": sorted({cap for item in active for cap in item.manifest.usage.capabilities}),
        "runtime_profiles": [
            {
                "adapter_id": profile.adapter_id,
                "routing_key": profile.routing_key,
                "features": list(profile.runtime_features),
                "supported_side_effects": list(profile.supported_side_effects),
                "healthy": profile.healthy,
            }
            for profile in capability_router.runtime_profiles
        ],
    }


@app.post("/api/capabilities/execute")
async def execute_capability(
    req: CapabilityExecuteRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        risk = ActionRisk(req.risk)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown risk: {req.risk}") from exc
    execution = await capability_router.execute(CapabilityRequirement(
        capability=req.capability,
        arguments=req.input,
        required_runtime_features=tuple(req.required_runtime_features),
        allowed_side_effects=tuple(req.allowed_side_effects),
        reason=req.reason,
        risk=risk,
        reversible=req.reversible,
        allow_fallback=req.allow_fallback,
        session_id=req.session_id,
        metadata={**req.metadata, "channel": "http", "user_id": operator.principal, "session_id": req.session_id},
    ))
    payload = _capability_execution_dict(execution)
    if execution.status in {CapabilityRouteStatus.NOT_FOUND, CapabilityRouteStatus.BLOCKED}:
        raise HTTPException(status_code=409, detail=payload)
    return payload


def _coding_execution_dict(execution):
    action = execution.action_result
    return {
        "task_id": execution.task.task_id,
        "status": execution.status.value,
        "ok": execution.ok,
        "selected_runtime_id": execution.selected_runtime_id,
        "result": execution.result,
        "blockers": list(execution.blockers),
        "failure_fingerprint": execution.failure_fingerprint,
        "attempts": list(execution.attempts),
        "pending_approval": {
            "approval_id": action.metadata.get("approval_id"),
            "action_hash": action.metadata.get("action_hash"),
            "expires_at": action.metadata.get("expires_at"),
        } if action is not None and action.status == "pending-approval" else None,
    }


@app.get("/api/runtimes/status")
async def coding_runtime_status(x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    status = await coding_router.status()
    return {
        "operator": operator.principal,
        **status,
        "workspace_bindings": len(workspace_bindings.list_bindings()),
        "allowed_workspace_roots": [str(item) for item in coding_allowed_roots],
        "telemetry": runtime_telemetry.status(),
        "driver_pack": runtime_driver_pack.as_dict(),
    }


@app.get("/api/runtime-drivers/status")
async def runtime_driver_status(x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    return {"operator": operator.principal, **runtime_driver_pack.as_dict()}


@app.get("/aionui/runtime-console", response_class=HTMLResponse, include_in_schema=False)
def aionui_runtime_console():
    return FileResponse(AIONUI_CONSOLE_DIR / "index.html", media_type="text/html")


@app.get("/aionui/runtime-console/app.js", include_in_schema=False)
def aionui_runtime_console_js():
    return FileResponse(AIONUI_CONSOLE_DIR / "app.js", media_type="text/javascript")


@app.get("/aionui/runtime-console/styles.css", include_in_schema=False)
def aionui_runtime_console_css():
    return FileResponse(AIONUI_CONSOLE_DIR / "styles.css", media_type="text/css")


@app.get("/aionui/runtime-console/manifest.json", include_in_schema=False)
def aionui_runtime_console_manifest():
    return FileResponse(AIONUI_CONSOLE_DIR / "manifest.json", media_type="application/json")


@app.get("/api/runtime-operations/console")
@app.get("/api/runtime-fleet/console")
async def runtime_operations_console(x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    return {
        "operator": operator.principal,
        "scheduler": fleet_scheduler.status(),
        **fleet_service.snapshot(),
    }


@app.post("/api/runtime-operations/refresh")
async def refresh_runtime_operations(
    req: RuntimeOperationsRefreshRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    renewed = ()
    if req.renew_due_receipts:
        renewed = await runtime_driver_pack.renew_due_receipts(principal=operator.principal, ttl_hours=req.ttl_hours)
    await fleet_service.run_job(FleetJobKind.HEALTH_PROBE, principal=operator.principal)
    await fleet_service.run_job(FleetJobKind.BUDGET_EVALUATION, principal=operator.principal)
    return {
        "operator": operator.principal,
        "renewed_receipts": [runtime_driver_pack._receipt_dict(item) for item in renewed],
        "scheduler": fleet_scheduler.status(),
        **fleet_service.snapshot(),
    }


@app.post("/api/runtime-fleet/run-due")
async def run_due_fleet_jobs(x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    runs = await fleet_service.run_due(principal=operator.principal)
    return {
        "operator": operator.principal,
        "runs": list(runs),
        "scheduler": fleet_scheduler.status(),
        **fleet_service.snapshot(),
    }


@app.post("/api/runtime-fleet/jobs/{job_kind}/run")
async def run_fleet_job(job_kind: str, x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        kind = FleetJobKind(job_kind)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"unknown fleet job: {job_kind}") from exc
    run = await fleet_service.run_job(kind, principal=operator.principal)
    return {"operator": operator.principal, "run": run, **fleet_service.snapshot()}


@app.patch("/api/runtime-fleet/jobs/{job_kind}")
def update_fleet_job(
    job_kind: str,
    req: FleetJobUpdateRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        kind = FleetJobKind(job_kind)
        job = fleet_service.update_job(
            kind,
            principal=operator.principal,
            interval_seconds=req.interval_seconds,
            enabled=req.enabled,
            run_immediately=req.run_immediately,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"unknown fleet job: {job_kind}") from exc
    return {"operator": operator.principal, "job": fleet_service._job_dict(job)}


@app.post("/api/runtime-fleet/incidents/{incident_id}/acknowledge")
def acknowledge_fleet_incident(
    incident_id: str,
    req: FleetIncidentDecisionRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        incident = fleet_service.acknowledge_incident(
            incident_id, principal=operator.principal, reason=req.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"incident not found: {incident_id}") from exc
    return {"operator": operator.principal, "incident": fleet_service._incident_dict(incident)}


@app.post("/api/runtime-fleet/incidents/{incident_id}/resolve")
def resolve_fleet_incident(
    incident_id: str,
    req: FleetIncidentDecisionRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        incident = fleet_service.resolve_incident(
            incident_id, principal=operator.principal, reason=req.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"incident not found: {incident_id}") from exc
    return {"operator": operator.principal, "incident": fleet_service._incident_dict(incident)}


@app.post("/api/runtime-fleet/cost-events")
def record_fleet_cost_event(
    req: FleetCostEventRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    event_id = fleet_service.record_cost(
        driver_id=req.driver_id,
        task_id=req.task_id,
        cost_usd=req.cost_usd,
        input_tokens=req.input_tokens,
        output_tokens=req.output_tokens,
        source=req.source,
        payload={**req.metadata, "recorded_by": operator.principal},
    )
    return {"operator": operator.principal, "cost_event_id": event_id, "budget": fleet_service.snapshot()["budget"]}


@app.get("/api/runtime-drivers/conformance")
async def runtime_driver_conformance(x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    return {
        "operator": operator.principal,
        "receipts": [runtime_driver_pack._receipt_dict(item) for item in runtime_driver_pack.conformance_store.list(limit=200)],
    }


@app.post("/api/runtime-drivers/{driver_id}/conform")
async def conform_runtime_driver(
    driver_id: str,
    req: RuntimeConformanceRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        receipt = await runtime_driver_pack.conform(driver_id, principal=operator.principal, ttl_hours=req.ttl_hours)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown runtime driver: {driver_id}") from exc
    except RuntimeConformanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "operator": operator.principal,
        "receipt": runtime_driver_pack._receipt_dict(receipt),
        "routing_eligible": receipt.passed,
    }


@app.get("/api/runtimes/workspaces")
def list_runtime_workspaces(
    session_id: str | None = Query(default=None),
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    return {"operator": operator.principal, "bindings": [asdict(item) for item in workspace_bindings.list_bindings(session_id=session_id)]}


@app.post("/api/runtimes/workspaces/bind")
def bind_runtime_workspace(
    req: WorkspaceBindRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        binding = workspace_bindings.bind(
            Path(req.root_path), req.session_id, workspace_id=req.workspace_id,
            allowed_relative_paths=tuple(req.allowed_relative_paths), writable=req.writable,
            metadata={**req.metadata, "bound_by": operator.principal, "channel": operator.channel},
        )
    except (WorkspaceBindingError, sqlite3.IntegrityError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    coding_runtime_event_bus.emit(
        EventType.RUNTIME_WORKSPACE_BOUND, actor="aether.gateway.operator",
        payload={"workspace_id": binding.workspace_id, "binding_id": binding.binding_id,
                 "session_id": binding.session_id, "writable": binding.writable},
    )
    return asdict(binding)


@app.post("/api/runtimes/coding/tasks")
async def execute_coding_task(
    req: CodingTaskRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    requested_capabilities = list(req.required_capabilities)
    requested_features = list(req.required_runtime_features)
    if not req.edits:
        for value in ("coding.patch-generation", "coding.verify", "coding.artifact-return"):
            if value not in requested_capabilities:
                requested_capabilities.append(value)
        for value in ("vendor-driver-pack-v1", "generative-coding", "runtime-generated-patch", "independent-verification"):
            if value not in requested_features:
                requested_features.append(value)
    task = CodingTask(
        objective=req.objective, workspace_id=req.workspace_id, session_id=req.session_id,
        edits=tuple(CodingEdit(item.path, item.content, item.expected_sha256) for item in req.edits),
        verification_commands=tuple(VerificationCommand(tuple(item.argv), item.timeout_seconds, item.label) for item in req.verification_commands),
        required_capabilities=tuple(requested_capabilities),
        required_runtime_features=tuple(requested_features),
        max_artifacts=req.max_artifacts, max_total_bytes=req.max_total_bytes,
        allow_fallback=req.allow_fallback,
        metadata={**req.metadata, "channel": "http", "user_id": operator.principal},
    )
    execution = await coding_router.execute(task)
    payload = _coding_execution_dict(execution)
    if execution.status in {CodingExecutionStatus.BLOCKED, CodingExecutionStatus.ESCALATED}:
        raise HTTPException(status_code=409, detail=payload)
    return payload


@app.get("/api/approvals/status")
def approval_status():
    return approval_inbox.status_counts()


@app.get("/api/approvals")
def list_approvals(
    status: str = Query(default="pending"),
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    try:
        normalized = None if status == "all" else ApprovalStatus(status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown approval status: {status}") from exc
    return {"approvals": [pending_to_dict(item) for item in approval_inbox.list(normalized)]}


@app.get("/api/approvals/{approval_id}")
def get_approval(
    approval_id: str,
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    try:
        return pending_to_dict(approval_inbox.get(approval_id))
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc


async def _decide_approval(approval_id: str, req: ApprovalDecisionRequest, approved: bool, token: str | None):
    operator = _authenticate_operator(token)
    try:
        outcome = await approval_inbox.decide(
            approval_id,
            approved=approved,
            principal=operator.principal,
            reason=req.reason,
            channel=operator.channel,
            expected_action_hash=req.expected_action_hash,
        )
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except (ApprovalStateError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response = {
        "approval": pending_to_dict(outcome.approval.pending),
        "replayed": outcome.approval.replayed,
    }
    if outcome.expression is not None:
        delivered_to_origin = False
        if outcome.expression.metadata.get("channel") == "telegram":
            await telegram_adapter.express(outcome.expression)
            delivered_to_origin = True
        response["expression"] = {
            "modality": outcome.expression.modality,
            "content": outcome.expression.content,
            "target": outcome.expression.target,
            "metadata": dict(outcome.expression.metadata),
            "delivered_to_origin": delivered_to_origin,
        }
    return response


@app.post("/api/approvals/{approval_id}/approve")
async def approve_action(
    approval_id: str,
    req: ApprovalDecisionRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    return await _decide_approval(approval_id, req, True, x_aether_operator_token)


@app.post("/api/approvals/{approval_id}/reject")
async def reject_action(
    approval_id: str,
    req: ApprovalDecisionRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    return await _decide_approval(approval_id, req, False, x_aether_operator_token)


@app.post("/api/delegate")
async def delegate_task(req: DelegateRequest):
    if req.worker not in {"local-process", "default"}:
        raise HTTPException(status_code=400, detail=f"Runtime adapter is not registered: {req.worker}")
    proposal = ActionProposal(
        target=ActionTarget.RUNTIME,
        operation="echo",
        arguments={"text": req.task},
        required_scopes=(ActionScope.EXECUTE,),
        reason=f"Delegate bounded task through runtime body {req.worker}",
        risk=ActionRisk.LOW,
        reversible=True,
        metadata={"runtime_id": "default", "requested_worker": req.worker, "target_project": req.target_project},
    )
    result = await action_path.execute(proposal)
    if not result.ok:
        raise HTTPException(status_code=403 if result.status in {"approval-required", "denied"} else 502, detail=result.error)
    return {"result": result.output, "action_id": result.action_id, "status": result.status, "metadata": dict(result.metadata)}


@app.get("/api/tasks")
def get_tasks():
    conn = get_db()
    tasks = conn.execute("SELECT * FROM tasks").fetchall()
    conn.close()
    return {"tasks": [dict(task) for task in tasks]}


@app.post("/api/tasks")
def create_task(req: DelegateRequest):
    conn = get_db()
    task_id = str(uuid.uuid4())
    timestamp = datetime.datetime.now().isoformat()
    conn.execute(
        "INSERT INTO tasks (task_id, description, assigned_to, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, req.task, req.worker, "to do", timestamp),
    )
    conn.commit()
    conn.close()
    return {"status": "created", "task_id": task_id}


@app.patch("/api/tasks/{task_id}")
def update_task_status(task_id: str, req: TaskUpdate):
    conn = get_db()
    conn.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (req.status, task_id))
    conn.commit()
    conn.close()
    return {"status": "updated"}


@app.get("/api/team")
def get_team():
    conn = get_db()
    agents = conn.execute("SELECT * FROM agents").fetchall()
    activities = conn.execute("SELECT * FROM agent_activity ORDER BY ts DESC LIMIT 20").fetchall()
    conn.close()
    return {"agents": [dict(agent) for agent in agents], "activities": [dict(item) for item in activities]}


@app.get("/aionui/opportunity-console", response_class=HTMLResponse, include_in_schema=False)
def opportunity_console_page():
    return FileResponse(AIONUI_OPPORTUNITY_CONSOLE_DIR / "index.html")


@app.get("/aionui/opportunity-console/app.js", include_in_schema=False)
def opportunity_console_js():
    return FileResponse(AIONUI_OPPORTUNITY_CONSOLE_DIR / "app.js", media_type="text/javascript")


@app.get("/aionui/opportunity-console/styles.css", include_in_schema=False)
def opportunity_console_css():
    return FileResponse(AIONUI_OPPORTUNITY_CONSOLE_DIR / "styles.css", media_type="text/css")


@app.get("/aionui/opportunity-console/manifest.json", include_in_schema=False)
def opportunity_console_manifest():
    return FileResponse(AIONUI_OPPORTUNITY_CONSOLE_DIR / "manifest.json", media_type="application/json")


@app.get("/api/opportunity-intelligence/console")
def opportunity_intelligence_console(
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    candidates = opportunity_store.candidates(limit=500)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": opportunity_store.status(),
        "sources": [
            {**asdict(item), "kind": item.kind.value, "capabilities": [value.value for value in item.capabilities]}
            for item in opportunity_store.manifests()
        ],
        "source_status": opportunity_store.latest_statuses(),
        "runs": opportunity_store.runs(limit=100),
        "snapshots": [
            {"snapshot_id": item.snapshot_id, "source_id": item.source_id, "canonical_url": item.canonical_url,
             "title": item.title, "retrieved_at": item.retrieved_at, "content_hash": item.content_hash,
             "content_type": item.content_type, "bytes": len(item.content_text.encode("utf-8"))}
            for item in opportunity_store.list_snapshots(limit=200)
        ],
        "claims": [
            {**asdict(item), "stance": item.stance.value, "evidence_strength": item.evidence_strength.value}
            for item in opportunity_store.claims(limit=500)
        ],
        "candidates": [opportunity_candidate_payload(item) for item in candidates],
        "decisions": [asdict(item) | {"decision": item.decision.value} for item in (opportunity_store.decision(candidate.candidate_id) for candidate in candidates) if item],
        "mandates": [experiment_mandate_payload(item) for item in opportunity_store.mandates()],
        "authority": {
            "public_observation": "autonomous",
            "cognitive_synthesis": "autonomous",
            "sandbox_experiments": "budgeted-mandate",
            "bounded_external_actions": "mission-mandate",
            "high_consequence_actions": "explicit-action-approval",
            "direct_knowledge_or_belief_write": "forbidden",
            "claimed_value_is_revenue": False,
        },
        "secret_values_exposed": False,
    }


@app.post("/api/opportunity-intelligence/scout-runs")
async def run_opportunity_scout(
    req: ScoutRunRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        query = ScoutQuery(
            objective=req.objective, queries=tuple(req.queries),
            source_kinds=tuple(SourceKind(item) for item in req.source_kinds),
            maximum_sources=req.maximum_sources, maximum_snapshots=req.maximum_snapshots,
            maximum_bytes=req.maximum_bytes, maximum_duration_seconds=req.maximum_duration_seconds,
            allowed_domains=tuple(req.allowed_domains), blocked_domains=tuple(req.blocked_domains),
            autonomy_level=AutonomyLevel(req.autonomy_level),
            metadata={**req.metadata, "requested_by": operator.principal},
        )
        receipt = await opportunity_scout.run(query)
    except (ValueError, OpportunityBlocked) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(receipt)


@app.get("/api/opportunity-intelligence/candidates")
def list_opportunity_candidates(
    limit: int = Query(default=100, ge=1, le=1000),
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    return {"candidates": [opportunity_candidate_payload(item) for item in opportunity_store.candidates(limit=limit)]}


@app.post("/api/opportunity-intelligence/candidates")
def synthesize_opportunity_candidate(
    req: OpportunityCandidateRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        item = opportunity_intelligence.synthesize_candidate(
            title=req.title, problem_statement=req.problem_statement, beneficiary=req.beneficiary,
            value_proposition=req.value_proposition, revenue_hypothesis=req.revenue_hypothesis,
            category=req.category, claim_ids=req.claim_ids, assumptions=req.assumptions,
            expected_upside_usd=req.expected_upside_usd, probability_success=req.probability_success,
            estimated_cost_usd=req.estimated_cost_usd, estimated_duration_hours=req.estimated_duration_hours,
            risk=req.risk, strategic_alignment=req.strategic_alignment, reversibility=req.reversibility,
            time_to_validation=req.time_to_validation, legal_risk_penalty=req.legal_risk_penalty,
            platform_dependency_penalty=req.platform_dependency_penalty, saturation_penalty=req.saturation_penalty,
            strategy_tags=req.strategy_tags, metadata={**req.metadata, "synthesized_by": operator.principal},
        )
    except (ValueError, OpportunityBlocked, OpportunityNotFound) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return opportunity_candidate_payload(item)


@app.post("/api/opportunity-intelligence/portfolio/score")
def score_opportunity_portfolio(
    req: PortfolioPolicyRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    policy = PortfolioPolicy(**req.model_dump())
    selection = opportunity_intelligence.select_portfolio(opportunity_store.candidates(limit=1000), policy)
    return asdict(selection)


@app.post("/api/opportunity-intelligence/candidates/{candidate_id}/decision")
def decide_opportunity_candidate(
    candidate_id: str, req: PortfolioDecisionRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        item = opportunity_intelligence.decide(
            candidate_id, decision=PortfolioDecisionType(req.decision), principal=operator.principal,
            reason=req.reason, allocated_budget_usd=req.allocated_budget_usd, channel=operator.channel,
        )
    except (ValueError, OpportunityBlocked, OpportunityNotFound, PortfolioDecisionConflict) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(item) | {"decision": item.decision.value}


@app.post("/api/opportunity-intelligence/candidates/{candidate_id}/mandates")
def issue_opportunity_mandate(
    candidate_id: str, req: ExperimentMandateRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        item = opportunity_intelligence.issue_mandate(
            candidate_id, principal=operator.principal, autonomy_level=AutonomyLevel(req.autonomy_level),
            allowed_capabilities=req.allowed_capabilities, forbidden_capabilities=req.forbidden_capabilities,
            maximum_cost_usd=req.maximum_cost_usd, maximum_external_actions=req.maximum_external_actions,
            maximum_duration_seconds=req.maximum_duration_seconds, expires_in_seconds=req.expires_in_seconds,
            reversible_only=req.reversible_only, reason=req.reason,
        )
    except (ValueError, OpportunityBlocked, OpportunityNotFound) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return experiment_mandate_payload(item)


@app.post("/api/opportunity-intelligence/candidates/{candidate_id}/convert-to-mission")
def convert_opportunity_to_mission(
    candidate_id: str,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        brief = opportunity_mission_bridge.convert(candidate_id)
    except (OpportunityBlocked, OpportunityNotFound, MissionBlocked) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    opportunity_event_bus.emit(EventType.OPPORTUNITY_MISSION_CONVERTED.value, actor=operator.principal, payload={
        "candidate_id": candidate_id, "brief_id": brief.brief_id, "brief_hash": brief.brief_hash,
    })
    return opportunity_brief_payload(brief)


@app.get("/aionui/experiment-console", response_class=HTMLResponse, include_in_schema=False)
def experiment_console_page():
    return FileResponse(AIONUI_EXPERIMENT_CONSOLE_DIR / "index.html", media_type="text/html")


@app.get("/aionui/experiment-console/app.js", include_in_schema=False)
def experiment_console_js():
    return FileResponse(AIONUI_EXPERIMENT_CONSOLE_DIR / "app.js", media_type="application/javascript")


@app.get("/aionui/experiment-console/styles.css", include_in_schema=False)
def experiment_console_css():
    return FileResponse(AIONUI_EXPERIMENT_CONSOLE_DIR / "styles.css", media_type="text/css")


@app.get("/aionui/experiment-console/manifest.json", include_in_schema=False)
def experiment_console_manifest():
    return FileResponse(AIONUI_EXPERIMENT_CONSOLE_DIR / "manifest.json", media_type="application/json")


def _safe_source_config(item):
    payload = live_source_configuration_payload(item)
    payload["credential_handle_present"] = bool(payload.pop("credential_handle", None))
    return payload


@app.get("/api/experiments/console")
def experiment_operations_console(x_aether_operator_token: str | None = Header(default=None)):
    _authenticate_operator(x_aether_operator_token)
    return {
        "web": {
            "status": web_intelligence_store.status(),
            "sources": [_safe_source_config(item) for item in web_intelligence_store.configurations()],
            "conformance": [source_conformance_receipt_payload(item) for item in (
                web_intelligence_store.latest_conformance(config.adapter_id) for config in web_intelligence_store.configurations()
            ) if item],
            "freshness": web_intelligence_store.freshness_records(limit=500),
            "discoveries": [source_discovery_candidate_payload(item) for item in web_intelligence_store.discoveries(limit=200)],
        },
        "experiments": {
            "status": experiment_store.status(),
            "plans": [experiment_plan_payload(item) for item in experiment_store.plans(limit=200)],
            "runs": [experiment_run_payload(item) for item in experiment_store.runs(limit=200)],
            "artifacts": [asdict(item) for item in experiment_store.artifacts()],
            "previews": [{"preview_id": item.preview_id, "run_id": item.run_id, "private": item.private, "created_at": item.created_at, "expires_at": item.expires_at, "status": item.status} for item in experiment_store.previews(limit=200)],
            "signals": [demand_signal_payload(item) for item in experiment_store.signals(limit=500)],
            "reviews": [asdict(item) | {"state": item.state.value} for item in experiment_store.reviews(limit=200)],
        },
        "authority": {
            "observation_is_not_execution": True,
            "synthetic_is_not_measured": True,
            "private_preview_is_not_public_deployment": True,
            "external_consequence_requires_review": True,
        },
    }


@app.post("/api/web-intelligence/configurations")
def configure_live_source(req: LiveSourceConfigurationRequest, x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        item = web_intelligence.configure_source(LiveSourceConfiguration(
            adapter_id=req.adapter_id, source_id=req.source_id, endpoint=req.endpoint,
            allowed_domains=tuple(req.allowed_domains), blocked_domains=tuple(req.blocked_domains),
            credential_handle=req.credential_handle, maximum_pages=req.maximum_pages,
            maximum_depth=req.maximum_depth, maximum_bytes=req.maximum_bytes,
            timeout_seconds=req.timeout_seconds, enabled=req.enabled, metadata=req.metadata,
        ), principal=operator.principal)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _safe_source_config(item)


@app.post("/api/web-intelligence/acquire")
async def acquire_live_web_evidence(req: LiveAcquisitionRequest, x_aether_operator_token: str | None = Header(default=None)):
    _authenticate_operator(x_aether_operator_token)
    try:
        result = await live_web_acquisition.acquire(adapter_id=req.adapter_id, url=req.url, title=req.title, objective=req.objective)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    snapshot = result["snapshot"]
    return {
        "snapshot": {
            "snapshot_id": snapshot.snapshot_id, "source_id": snapshot.source_id, "adapter_id": snapshot.adapter_id,
            "canonical_url": snapshot.canonical_url, "title": snapshot.title, "content_type": snapshot.content_type,
            "retrieved_at": snapshot.retrieved_at, "content_hash": snapshot.content_hash, "status_code": snapshot.status_code,
        },
        "claims": [{
            "claim_id": item.claim_id, "statement": item.statement, "stance": item.stance.value,
            "confidence": item.confidence, "source_id": item.source_id, "claim_hash": item.claim_hash,
        } for item in result["claims"]],
        "conformance_state": result["conformance_state"],
        "live_network": result["live_network"],
    }


@app.post("/api/web-intelligence/sources/{adapter_id}/conform")
async def conform_live_source(adapter_id: str, req: SourceConformanceRequest, x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        receipt = await source_conformance_service.conform(adapter_id, principal=operator.principal, ttl_seconds=req.ttl_seconds)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return source_conformance_receipt_payload(receipt)


@app.post("/api/web-intelligence/freshness/run")
def run_evidence_freshness(req: FreshnessRunRequest, x_aether_operator_token: str | None = Header(default=None)):
    _authenticate_operator(x_aether_operator_token)
    try:
        return freshness_scheduler.run(EvidenceFreshnessPolicy(
            fresh_for_seconds=req.fresh_for_seconds, aging_for_seconds=req.aging_for_seconds,
            maximum_stale_fraction=req.maximum_stale_fraction, refresh_batch_size=req.refresh_batch_size,
        ), evaluated_at=req.evaluated_at)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/web-intelligence/discover")
def discover_live_sources(req: SourceDiscoveryRunRequest, x_aether_operator_token: str | None = Header(default=None)):
    _authenticate_operator(x_aether_operator_token)
    items = adaptive_source_discovery.discover(minimum_mentions=req.minimum_mentions, maximum_candidates=req.maximum_candidates)
    return {"candidates": [source_discovery_candidate_payload(item) for item in items]}


@app.post("/api/web-intelligence/discoveries/{candidate_id}/decision")
def decide_discovered_source(candidate_id: str, req: SourceDiscoveryDecisionRequest, x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        item = web_intelligence.decide_source(candidate_id, state=SourceDiscoveryState(req.decision), principal=operator.principal, reason=req.reason)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return source_discovery_candidate_payload(item)


@app.post("/api/experiments/plans")
def create_experiment_plan(req: ReversibleExperimentPlanRequest, x_aether_operator_token: str | None = Header(default=None)):
    _authenticate_operator(x_aether_operator_token)
    try:
        plan = experiment_engine.create_plan(ReversibleExperimentPlan(
            candidate_id=req.candidate_id, mandate_id=req.mandate_id, objective=req.objective,
            hypothesis=req.hypothesis, success_metrics=tuple(req.success_metrics), stop_conditions=tuple(req.stop_conditions),
            steps=tuple(ExperimentStep(
                name=item.name, kind=ExperimentStepKind(item.kind), capability=item.capability,
                payload=item.payload, estimated_cost_usd=item.estimated_cost_usd,
                reversible=item.reversible, external_actions=item.external_actions,
            ) for item in req.steps),
            maximum_cost_usd=req.maximum_cost_usd, maximum_duration_seconds=req.maximum_duration_seconds,
            maximum_artifact_bytes=req.maximum_artifact_bytes, maximum_artifact_files=req.maximum_artifact_files,
            private_preview=req.private_preview,
            planner_id=req.planner_id, metadata=req.metadata,
        ))
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return experiment_plan_payload(plan)


@app.post("/api/experiments/plans/{plan_id}/run")
async def run_reversible_experiment(plan_id: str, x_aether_operator_token: str | None = Header(default=None)):
    _authenticate_operator(x_aether_operator_token)
    try:
        run, token = await experiment_runner.run(plan_id)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    payload = experiment_run_payload(run)
    if token and run.preview_id:
        payload["private_preview"] = {
            "preview_id": run.preview_id,
            "token": token,
            "url": f"/api/experiments/previews/{run.preview_id}/{token}/index.html",
            "token_returned_once": True,
        }
    return payload


@app.get("/api/experiments/previews/{preview_id}/{token}/{relative_path:path}", include_in_schema=False)
def serve_private_preview(preview_id: str, token: str, relative_path: str = "index.html"):
    try:
        target = experiment_runner.resolve_preview_file(preview_id, token, relative_path or "index.html")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(target)


@app.post("/api/experiments/runs/{run_id}/demand-signals")
def record_demand_signal(run_id: str, req: DemandSignalRequest, x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        item = experiment_engine.record_demand_signal(DemandSignal(
            run_id=run_id, kind=DemandSignalKind(req.kind), state=DemandEvidenceState(req.state),
            quantity=req.quantity, unit=req.unit, measured_at=req.measured_at or datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            source=req.source, external_reference=req.external_reference, verifier=req.verifier, metadata=req.metadata,
        ), principal=operator.principal if req.state == "verified" else None)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return demand_signal_payload(item)


@app.post("/api/experiments/runs/{run_id}/external-reviews")
def request_experiment_external_review(run_id: str, req: ExternalReviewRequest, x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        item = experiment_engine.request_external_review(
            run_id=run_id, step_id=req.step_id, action_summary=req.action_summary,
            consequence=req.consequence, requested_by=operator.principal, ttl_seconds=req.ttl_seconds,
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return asdict(item) | {"state": item.state.value}


@app.post("/api/experiments/external-reviews/{review_id}/decision")
def decide_experiment_external_review(review_id: str, req: ExternalReviewDecisionRequest, x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        item = experiment_engine.decide_external_review(review_id, approved=req.approved, principal=operator.principal, reason=req.reason)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return asdict(item) | {"state": item.state.value}


@app.get("/aionui/mission-console", response_class=HTMLResponse, include_in_schema=False)
def mission_console_page():
    return FileResponse(AIONUI_MISSION_CONSOLE_DIR / "index.html")


@app.get("/aionui/mission-console/app.js", include_in_schema=False)
def mission_console_js():
    return FileResponse(AIONUI_MISSION_CONSOLE_DIR / "app.js", media_type="text/javascript")


@app.get("/aionui/mission-console/styles.css", include_in_schema=False)
def mission_console_css():
    return FileResponse(AIONUI_MISSION_CONSOLE_DIR / "styles.css", media_type="text/css")


@app.get("/aionui/mission-console/manifest.json", include_in_schema=False)
def mission_console_manifest():
    return FileResponse(AIONUI_MISSION_CONSOLE_DIR / "manifest.json", media_type="application/json")


@app.get("/api/mission-operations/console")
def mission_operations_console(
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "operator": operator_authenticator.principal,
        "status": mission_store.status(),
        "opportunities": [opportunity_brief_payload(item) for item in mission_store.list_briefs(limit=500)],
        "missions": [mission_store.mission_view(item.mission_id) for item in mission_store.list_plans(limit=500)],
        "authority": {
            "operator_shell_only": True,
            "opportunity_evidence_is_not_permission": True,
            "claimed_value_is_not_revenue": True,
            "mission_plan_approval_does_not_approve_step_actions": True,
            "model_self_approval": "forbidden",
            "automatic_scaling": False,
        },
        "secret_values_exposed": False,
    }


@app.get("/api/opportunities")
def list_opportunities(
    limit: int = Query(default=100, ge=1, le=1000),
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    return {"opportunities": [opportunity_brief_payload(item) for item in mission_store.list_briefs(limit=limit)]}


@app.post("/api/opportunities")
def intake_opportunity(
    req: OpportunityIntakeRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        brief = mission_orchestrator.intake_opportunity(
            title=req.title,
            lane=MissionLane(req.lane),
            problem_statement=req.problem_statement,
            beneficiary=req.beneficiary,
            value_proposition=req.value_proposition,
            probability_success=req.probability_success,
            upside_usd=req.upside_usd,
            estimated_cost_usd=req.estimated_cost_usd,
            estimated_duration_hours=req.estimated_duration_hours,
            revenue_hypothesis=req.revenue_hypothesis,
            assumptions=req.assumptions,
            evidence=tuple(OpportunityEvidence(
                source=item.source,
                statement=item.statement,
                stance=OpportunityEvidenceStance(item.stance),
                observed_at=item.observed_at,
                external_reference=item.external_reference,
                independent_source_id=item.independent_source_id,
                verified=item.verified,
                metadata=item.metadata,
            ) for item in req.evidence),
            risk=MissionRisk(req.risk),
            confidence=req.confidence,
            metadata={**req.metadata, "intake_principal": operator.principal, "intake_channel": operator.channel},
        )
    except (ValueError, MissionBlocked) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return opportunity_brief_payload(brief)


def _mission_execution_dict(item):
    return {
        "mission_id": item.mission_id,
        "status": item.status.value,
        "completed_step_ids": list(item.completed_step_ids),
        "current_step_id": item.current_step_id,
        "approval_id": item.approval_id,
        "blockers": list(item.blockers),
        "metadata": dict(item.metadata),
    }


@app.get("/api/missions")
def list_missions(
    limit: int = Query(default=100, ge=1, le=1000),
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    return {
        "status": mission_store.status(),
        "missions": [mission_store.mission_view(item.mission_id) for item in mission_store.list_plans(limit=limit)],
    }


@app.get("/api/missions/{mission_id}")
def get_mission(
    mission_id: str,
    x_aether_operator_token: str | None = Header(default=None),
):
    _authenticate_operator(x_aether_operator_token)
    try:
        return mission_store.mission_view(mission_id)
    except MissionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/missions/plans")
def create_mission_plan(
    req: MissionPlanRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        steps = tuple(MissionStep(
            step_id=item.step_id or str(uuid.uuid4()),
            title=item.title,
            action=ActionProposal(
                target=ActionTarget(item.target),
                operation=item.operation,
                arguments=item.arguments,
                required_scopes=tuple(ActionScope(scope) for scope in item.required_scopes),
                reason=item.reason,
                risk=ActionRisk(item.risk),
                reversible=item.reversible,
                metadata={**item.metadata, "channel": "http", "requested_by": operator.principal},
            ),
            success_criteria=tuple(item.success_criteria),
            depends_on=tuple(item.depends_on),
            max_attempts=item.max_attempts,
            stop_on_failure=item.stop_on_failure,
            explicit_retry_reason=item.explicit_retry_reason,
            estimated_cost_usd=item.estimated_cost_usd,
            metadata=item.metadata,
        ) for item in req.steps)
        plan = mission_orchestrator.create_plan(
            brief_id=req.brief_id,
            objective=req.objective,
            northstar_alignment=req.northstar_alignment,
            northstar_principle_ids=req.northstar_principle_ids,
            strategy_tags=req.strategy_tags,
            steps=steps,
            budget=MissionBudget(**req.budget.model_dump()),
            stop_conditions=req.stop_conditions,
            metadata={**req.metadata, "plan_principal": operator.principal},
        )
    except (ValueError, MissionBlocked, MissionNotFound) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return mission_store.mission_view(plan.mission_id)


async def _mission_decision(mission_id: str, req: MissionDecisionRequest, approved: bool, token: str | None):
    operator = _authenticate_operator(token)
    try:
        decision = mission_orchestrator.decide(
            mission_id,
            approved=approved,
            principal=operator.principal,
            channel=operator.channel,
            reason=req.reason,
        )
    except MissionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (MissionBlocked, MissionDecisionConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"decision": asdict(decision) | {"decision": decision.decision.value}, "mission": mission_store.mission_view(mission_id)}


@app.post("/api/missions/{mission_id}/approve")
async def approve_mission(mission_id: str, req: MissionDecisionRequest, x_aether_operator_token: str | None = Header(default=None)):
    return await _mission_decision(mission_id, req, True, x_aether_operator_token)


@app.post("/api/missions/{mission_id}/reject")
async def reject_mission(mission_id: str, req: MissionDecisionRequest, x_aether_operator_token: str | None = Header(default=None)):
    return await _mission_decision(mission_id, req, False, x_aether_operator_token)


@app.post("/api/missions/{mission_id}/run")
async def run_mission(mission_id: str, req: MissionRunRequest, x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        result = await mission_orchestrator.run(mission_id, principal=operator.principal, maximum_steps=req.maximum_steps)
    except MissionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissionBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"execution": _mission_execution_dict(result), "mission": mission_store.mission_view(mission_id)}


@app.post("/api/missions/{mission_id}/resume")
async def resume_mission(mission_id: str, req: MissionRunRequest, x_aether_operator_token: str | None = Header(default=None)):
    return await run_mission(mission_id, req, x_aether_operator_token)


@app.post("/api/missions/{mission_id}/pause")
def pause_mission(mission_id: str, req: MissionDecisionRequest, x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        result = mission_orchestrator.pause(mission_id, principal=operator.principal, reason=req.reason)
    except (MissionNotFound, MissionBlocked) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"execution": _mission_execution_dict(result), "mission": mission_store.mission_view(mission_id)}


@app.post("/api/missions/{mission_id}/cancel")
def cancel_mission(mission_id: str, req: MissionDecisionRequest, x_aether_operator_token: str | None = Header(default=None)):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        result = mission_orchestrator.cancel(mission_id, principal=operator.principal, reason=req.reason)
    except (MissionNotFound, MissionBlocked) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"execution": _mission_execution_dict(result), "mission": mission_store.mission_view(mission_id)}


@app.post("/api/missions/{mission_id}/value-evidence")
def record_mission_value(
    mission_id: str,
    req: MissionValueEvidenceRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        item = mission_orchestrator.record_value_evidence(
            mission_id=mission_id,
            kind=MissionValueKind(req.kind),
            description=req.description,
            source=req.source,
            amount_usd=req.amount_usd,
            external_reference=req.external_reference,
            related_evidence_id=req.related_evidence_id,
            verified_by=operator.principal if req.kind == MissionValueKind.VERIFIED.value else None,
            metadata=req.metadata,
        )
    except (ValueError, MissionBlocked, MissionNotFound) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(item) | {"kind": item.kind.value}


@app.post("/api/missions/{mission_id}/outcome")
async def finalize_mission_outcome(
    mission_id: str,
    req: MissionOutcomeRequest,
    x_aether_operator_token: str | None = Header(default=None),
):
    operator = _authenticate_operator(x_aether_operator_token)
    try:
        outcome = await mission_orchestrator.finalize(
            mission_id,
            achieved=req.achieved,
            summary=req.summary,
            lessons=req.lessons,
            principal=operator.principal,
        )
    except (MissionNotFound, MissionBlocked) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(outcome) | {"state": outcome.state.value}


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text("Connected to Aether Gateway live stream")
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Message text was: {data}")


def start_server() -> None:
    host = str(os.environ.get("HOST") or "127.0.0.1").strip()
    try:
        port = int(os.environ.get("PORT") or "8000")
    except ValueError as exc:
        raise RuntimeError("PORT must be an integer") from exc
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
