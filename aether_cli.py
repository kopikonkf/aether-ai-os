#!/usr/bin/env python3
"""Cross-platform Aether OS developer entrypoint."""
from __future__ import annotations

import argparse
import asyncio
import compileall
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for source in (ROOT / "aether-core" / "src", ROOT / "aether-tools" / "src", ROOT / "aether-gateway" / "src"):
    sys.path.insert(0, str(source))

# The developer/Founder CLI and Gateway must resolve the same runtime state and
# provider credentials. Keep .env optional so offline verification still works
# before Gateway dependencies are installed.
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - reported by founder bring-up doctor
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv(ROOT / "aether-core" / ".env", override=False)


def _set_home(value: str | None) -> Path:
    configured = value or os.environ.get("AETHER_HOME")
    home = Path(configured).expanduser().resolve() if configured else ROOT / "aether-home"
    os.environ["AETHER_HOME"] = str(home)
    home.mkdir(parents=True, exist_ok=True)
    return home


def _json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def command_boot(args: argparse.Namespace) -> int:
    _set_home(args.home)
    from aether.executive.boot import AetherBoot

    _json(AetherBoot().boot())
    return 0


def command_identity(args: argparse.Namespace) -> int:
    from aether.dna.loader import DNALoader

    _json(DNALoader().load_identity())
    return 0


def command_bootstrap_check(args: argparse.Namespace) -> int:
    from aether.bootstrap import validate_bootstrap_policy

    policy_path = ROOT / "aether-core" / "src" / "aether" / "bootstrap" / "bootstrap.yaml"
    result = validate_bootstrap_policy(policy_path)
    _json({"passed": result.passed, "errors": result.errors, "sequence": result.policy.get("sequence")})
    return 0 if result.passed else 1


class _DemoModelProvider:
    provider_id = "provider.demo"

    async def supports(self, capability: str) -> bool:
        return True

    async def invoke(self, request):
        from aether.contracts import ModelResponse

        content = request.messages[-1]["content"]
        return ModelResponse(
            content=f"Aether demo model received: {content}",
            provider_id=self.provider_id,
            model_id="deterministic-v1",
            metadata={"network": False},
        )


async def _run_direct_turn(
    *,
    home: Path,
    text: str,
    source: str,
    session_id: str,
    preferred_model: str | None,
    live: bool,
) -> dict:
    from aether.cognition import AetherCognitiveGateway
    from aether.contracts import Perception
    from aether.events import EventBus
    from aether.senses import SenseEventPath
    from aether_gateway.adapters import DirectTextSenseAdapter
    from aether_gateway.providers import ConfiguredModelProvider

    provider = ConfiguredModelProvider() if live else _DemoModelProvider()
    cognition = AetherCognitiveGateway(provider, system_prompt="You are Aether.")
    path = SenseEventPath(EventBus(home / "events" / "sense-path.jsonl"), cognition)
    adapter = DirectTextSenseAdapter(adapter_id="sense.cli")
    metadata = {"channel": "cli", "session_id": session_id, "response_modality": "text"}
    if preferred_model:
        metadata["preferred_model"] = preferred_model
    trace = await path.handle(
        adapter,
        Perception(modality="text", content=text, source=source, metadata=metadata),
    )
    expression = adapter.expressions[-1]
    return {
        "status": "completed",
        "live_provider": live,
        "response": expression.content,
        "provider_id": expression.metadata.get("provider_id"),
        "model_id": expression.metadata.get("model_id"),
        "trace": trace.__dict__,
    }


def command_chat(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    try:
        result = asyncio.run(
            _run_direct_turn(
                home=home,
                text=args.text,
                source=args.session,
                session_id=args.session,
                preferred_model=args.model,
                live=True,
            )
        )
    except Exception as exc:
        _json({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
        return 1
    _json(result)
    return 0


def command_cognitive_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    result = asyncio.run(
        _run_direct_turn(
            home=home,
            text=args.text,
            source=args.session,
            session_id=args.session,
            preferred_model=None,
            live=False,
        )
    )
    _json(result)
    return 0


def command_sense_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether.cognition import AetherCognitiveGateway
    from aether.events import EventBus
    from aether.senses import SenseEventPath
    from aether_gateway.adapters.voice_bridge import VoiceBridgeAdapter

    spoken: list[str] = []

    async def speech_sink(text: str) -> None:
        spoken.append(text)

    async def scenario() -> dict:
        journal = home / "events" / "sense-path.jsonl"
        voice = VoiceBridgeAdapter(speech_sink)
        cognition = AetherCognitiveGateway(_DemoModelProvider())
        path = SenseEventPath(EventBus(journal), cognition)
        consumer = asyncio.create_task(path.run(voice, limit=1))
        await voice.ingest_transcript(
            args.text,
            source=args.source,
            metadata={"language": args.language, "session_id": args.source},
        )
        results = await consumer
        return {
            "status": "completed",
            "journal": str(journal),
            "spoken": spoken,
            "trace": [result.__dict__ for result in results],
            "events": [event.to_dict() for event in path.event_bus.replay()[-5:]],
        }

    _json(asyncio.run(scenario()))
    return 0


def _build_demo_browser_sense_service(home: Path):
    from aether.cognition import AetherCognitiveGateway
    from aether.events import EventBus
    from aether.senses import SenseEventPath
    from aether_gateway.browser_senses.service import BrowserSenseService, BrowserSessionTokenCodec

    event_bus = EventBus(home / "events" / "browser-senses.jsonl")
    cognition = AetherCognitiveGateway(_DemoModelProvider(), system_prompt="You are Aether.")
    sense_path = SenseEventPath(event_bus, cognition)
    return BrowserSenseService(
        home / "senses",
        sense_path,
        event_bus=event_bus,
        token_codec=BrowserSessionTokenCodec("aether-demo-browser-sense-secret-32-bytes-minimum"),
    )


def command_browser_sense_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether.contracts import BrowserSenseCapability

    async def scenario() -> dict:
        service = _build_demo_browser_sense_service(home)
        issued = service.issue_session(
            principal="founder",
            display_name="Founder",
            capabilities=(
                BrowserSenseCapability.TEXT,
                BrowserSenseCapability.MICROPHONE,
                BrowserSenseCapability.SPEAKER,
                BrowserSenseCapability.CAMERA,
            ),
            ttl_seconds=900,
            metadata={"network": False, "demo": True},
        )
        token = issued["browser_session_token"]
        service.mark_active(token, metadata={"transport": "offline-demo"})
        turn = await service.handle_text(token, args.text)
        service.close(token, reason="demo-complete")
        return {
            "status": "completed",
            "browser_session_token_exposed_in_output": False,
            "livekit_ready": bool(issued["livekit"].get("ready")),
            "response": turn["response"],
            "session": service.status(),
        }

    _json(asyncio.run(scenario()))
    return 0


def command_senses_status(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    service = _build_demo_browser_sense_service(home)
    from aether_gateway.browser_senses.worker import LiveKitWorkerConfig

    _json({
        "release": "0.19.2",
        "browser_senses": service.status(),
        "livekit_worker": LiveKitWorkerConfig.from_env().readiness(),
        "browser_url": args.gateway.rstrip("/") + "/senses",
    })
    return 0


def command_telegram_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether.cognition import AetherCognitiveGateway
    from aether.events import EventBus
    from aether.senses import SenseEventPath
    from aether_gateway.adapters.telegram_bot import TelegramSenseAdapter

    sent: list[dict[str, object]] = []

    async def sender(chat_id: int, text: str) -> None:
        sent.append({"chat_id": chat_id, "text": text})

    async def scenario() -> dict:
        cognition = AetherCognitiveGateway(_DemoModelProvider())
        path = SenseEventPath(EventBus(home / "events" / "sense-path.jsonl"), cognition)
        telegram = TelegramSenseAdapter(path, text_sender=sender, enabled=False)
        trace = await telegram.ingest_text(
            args.text,
            chat_id=args.chat_id,
            user_id=args.user_id,
            language=args.language,
        )
        return {
            "status": "completed",
            "sent": sent,
            "trace": trace.__dict__,
            "events": [event.to_dict() for event in path.event_bus.replay()[-5:]],
        }

    _json(asyncio.run(scenario()))
    return 0



class _DemoActionModelProvider:
    provider_id = "provider.demo-action"

    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def supports(self, capability: str) -> bool:
        return True

    async def invoke(self, request):
        from aether.contracts import (
            ActionProposal, ActionRisk, ActionScope, ActionTarget, ModelResponse,
        )

        if any("Governed action results" in str(message.get("content", "")) for message in request.messages):
            return ModelResponse(
                content="Aether completed the governed action and received verified body output.",
                provider_id=self.provider_id,
                model_id="deterministic-action-v1",
            )
        if self.mode == "tool":
            proposal = ActionProposal(
                target=ActionTarget.TOOL,
                operation="read",
                arguments={"path": "evidence.txt"},
                required_scopes=(ActionScope.READ,),
                reason="Read bounded evidence before answering.",
                risk=ActionRisk.LOW,
                reversible=True,
                correlation_id=request.correlation_id,
            )
        else:
            proposal = ActionProposal(
                target=ActionTarget.RUNTIME,
                operation="echo",
                arguments={"text": "Aether runtime body online"},
                required_scopes=(ActionScope.EXECUTE,),
                reason="Verify bounded runtime body delegation.",
                risk=ActionRisk.LOW,
                reversible=True,
                correlation_id=request.correlation_id,
                metadata={"runtime_id": "default"},
            )
        return ModelResponse(
            content="I need one governed action before answering.",
            provider_id=self.provider_id,
            model_id="deterministic-action-v1",
            action_proposals=(proposal,),
        )


def command_action_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "evidence.txt").write_text("Aether governed tool path online.\n", encoding="utf-8")

    from aether.actions import FailureFingerprintStore, GovernedActionPath
    from aether.cognition import AetherCognitiveGateway
    from aether.contracts import Perception
    from aether.events import EventBus
    from aether.governance import ActionGovernor
    from aether.senses import SenseEventPath
    from aether_gateway.actions import RegistryToolExecutor
    from aether_gateway.adapters import DirectTextSenseAdapter, LocalProcessRuntimeAdapter
    from aether_tools import ToolRegistry
    from aether_tools.primitives import ReadTool

    async def scenario() -> dict:
        registry = ToolRegistry()
        registry.register(ReadTool([workspace]))
        action_bus = EventBus(home / "events" / "action-path.jsonl")
        action_path = GovernedActionPath(
            action_bus,
            ActionGovernor(),
            FailureFingerprintStore(home / "evolution" / "action-failures.jsonl"),
            tool_executor=RegistryToolExecutor(registry),
            runtimes={"default": LocalProcessRuntimeAdapter(cwd=workspace)},
        )
        cognition = AetherCognitiveGateway(_DemoActionModelProvider(args.mode), action_executor=action_path)
        sense_path = SenseEventPath(EventBus(home / "events" / "sense-path.jsonl"), cognition)
        adapter = DirectTextSenseAdapter(adapter_id="sense.action-demo")
        trace = await sense_path.handle(adapter, Perception(
            modality="text",
            content=f"Verify the governed {args.mode} path.",
            source="cli:action-demo",
            metadata={"session_id": "cli:action-demo", "response_modality": "text"},
        ))
        expression = adapter.expressions[-1]
        return {
            "status": "completed",
            "mode": args.mode,
            "response": expression.content,
            "action_results": expression.metadata.get("action_results"),
            "sense_trace": trace.__dict__,
            "action_events": [event.to_dict() for event in action_bus.replay()],
        }

    _json(asyncio.run(scenario()))
    return 0


class _DemoApprovalModelProvider:
    provider_id = "provider.demo-approval"

    async def supports(self, capability: str) -> bool:
        return True

    async def invoke(self, request):
        from aether.contracts import (
            ActionProposal, ActionRisk, ActionScope, ActionTarget, ModelResponse,
        )

        if any("Governed action results" in str(message.get("content", "")) for message in request.messages):
            return ModelResponse(
                content="Aether resumed after trusted approval and verified the written artifact.",
                provider_id=self.provider_id,
                model_id="deterministic-approval-v1",
            )
        return ModelResponse(
            content="A governed write is required.",
            provider_id=self.provider_id,
            model_id="deterministic-approval-v1",
            action_proposals=(ActionProposal(
                target=ActionTarget.TOOL,
                operation="write",
                arguments={"path": "approved-artifact.txt", "_body": "Aether trusted approval path online.\n"},
                required_scopes=(ActionScope.WRITE,),
                reason="Create one bounded approval-demo artifact",
                risk=ActionRisk.MEDIUM,
                reversible=False,
                correlation_id=request.correlation_id,
            ),),
        )


def command_approval_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    from aether.actions import (
        FailureFingerprintStore, GovernedActionPath, PendingActionStore, TrustedApprovalInbox,
    )
    from aether.cognition import AetherCognitiveGateway
    from aether.contracts import Perception
    from aether.events import EventBus
    from aether.governance import ActionGovernor
    from aether.senses import SenseEventPath
    from aether_gateway.actions import RegistryToolExecutor
    from aether_gateway.adapters import DirectTextSenseAdapter
    from aether_gateway.approvals import ApprovalCoordinator
    from aether_tools import ToolRegistry
    from aether_tools.primitives import WriteTool

    async def scenario() -> dict:
        registry = ToolRegistry()
        registry.register(WriteTool([workspace]))
        action_bus = EventBus(home / "events" / "approval-demo-actions.jsonl")
        pending_store = PendingActionStore(home / "governance" / "approval-demo.sqlite3", default_ttl_seconds=300)
        action_path = GovernedActionPath(
            action_bus,
            ActionGovernor(),
            FailureFingerprintStore(home / "evolution" / "approval-demo-failures.jsonl"),
            tool_executor=RegistryToolExecutor(registry),
            pending_store=pending_store,
            approval_ttl_seconds=300,
        )
        cognition = AetherCognitiveGateway(_DemoApprovalModelProvider(), action_executor=action_path)
        sense_path = SenseEventPath(EventBus(home / "events" / "approval-demo-sense.jsonl"), cognition)
        adapter = DirectTextSenseAdapter(adapter_id="sense.approval-demo")
        await sense_path.handle(adapter, Perception(
            modality="http.text",
            content="Create the governed approval demo artifact.",
            source="http:approval-demo",
            metadata={"channel": "http", "session_id": "http:approval-demo", "response_modality": "text"},
        ))
        pending_expression = adapter.expressions[-1]
        approval_id = pending_expression.metadata["pending_approval"]["approval_id"]
        inbox = TrustedApprovalInbox(pending_store, action_path, action_bus)
        coordinator = ApprovalCoordinator(inbox, cognition)
        approved = await coordinator.decide(
            approval_id,
            approved=True,
            principal="founder",
            reason="Exact bounded file write reviewed",
            channel="cli",
        )
        replay = await coordinator.decide(
            approval_id,
            approved=True,
            principal="founder",
            reason="Simulated duplicate client request",
            channel="cli",
        )
        artifact = workspace / "approved-artifact.txt"
        return {
            "status": "completed",
            "approval_id": approval_id,
            "pending_message": pending_expression.content,
            "final_expression": approved.expression.content if approved.expression else None,
            "approval_status": approved.approval.pending.status.value,
            "replay_blocked": replay.approval.replayed,
            "artifact_exists": artifact.exists(),
            "artifact_content": artifact.read_text(encoding="utf-8") if artifact.exists() else None,
            "immutable_records": pending_store.approval_records(approval_id),
            "events": [event.to_dict() for event in action_bus.replay()],
        }

    _json(asyncio.run(scenario()))
    return 0



class _DemoMemoryModelProvider:
    provider_id = "provider.demo-memory"

    async def supports(self, capability: str) -> bool:
        return True

    async def invoke(self, request):
        from aether.contracts import ModelResponse
        context = "\n".join(str(message.get("content", "")) for message in request.messages)
        if "Aurora" in context and "Retrieved Aether memory" in context:
            answer = "Aether recalls that the project codename is Aurora, with provenance preserved."
        else:
            answer = "Acknowledged. The project codename is Aurora."
        return ModelResponse(answer, self.provider_id, "deterministic-memory-v1")


def _memory_stack(home: Path):
    from aether.cognition import SQLiteConversationStore
    from aether.events import EventBus
    from aether.memory import (
        AetherMemoryFabric, ObsidianMemoryProjector, SQLiteCanonicalMemoryStore, SQLiteLexicalMemoryProvider,
    )
    canonical = SQLiteCanonicalMemoryStore(home / "memory" / "canonical-episodes.sqlite3")
    retrieval = SQLiteLexicalMemoryProvider(home / "memory" / "retrieval-index.sqlite3", canonical)
    fabric = AetherMemoryFabric(
        canonical, retrieval,
        event_bus=EventBus(home / "events" / "memory-fabric.jsonl"),
        obsidian=ObsidianMemoryProjector(home / "obsidian" / "vault"),
    )
    sessions = SQLiteConversationStore(home / "sessions" / "cognitive-sessions.sqlite3", max_messages=48)
    return sessions, fabric


def command_memory_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether.cognition import AetherCognitiveGateway
    from aether.contracts import Perception

    async def scenario():
        sessions, fabric = _memory_stack(home)
        first_gateway = AetherCognitiveGateway(_DemoMemoryModelProvider(), conversation_store=sessions, memory_fabric=fabric)
        first = await first_gateway.respond(Perception(
            "http.text", "The project codename is Aurora.", "http:memory-demo",
            metadata={"session_id": "http:memory-demo", "channel": "http"},
        ))
        # Construct fresh objects to prove process-independent durability.
        restarted_sessions, restarted_fabric = _memory_stack(home)
        second_gateway = AetherCognitiveGateway(_DemoMemoryModelProvider(), conversation_store=restarted_sessions, memory_fabric=restarted_fabric)
        second = await second_gateway.respond(Perception(
            "http.text", "What is the project codename?", "http:memory-demo-2",
            metadata={"session_id": "http:memory-demo-2", "channel": "http"},
        ))
        rebuilt = await restarted_fabric.rebuild_index()
        projection = await restarted_fabric.project_session("http:memory-demo")
        return {
            "status": "completed",
            "first_response": first.content,
            "recalled_response": second.content,
            "memory_retrieval": second.metadata.get("memory_retrieval"),
            "reindexed_records": rebuilt,
            "obsidian_projection": projection,
            "stats": await restarted_fabric.stats(),
            "durable_session": list(await restarted_sessions.get("http:memory-demo")),
        }

    _json(asyncio.run(scenario()))
    return 0


def command_memory_rebuild(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    async def scenario():
        _sessions, fabric = _memory_stack(home)
        return {"status": "rebuilt", "records": await fabric.rebuild_index(), "stats": await fabric.stats()}
    _json(asyncio.run(scenario()))
    return 0


def command_memory_project(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    async def scenario():
        _sessions, fabric = _memory_stack(home)
        return {"status": "projected", "session_id": args.session, "path": await fabric.project_session(args.session)}
    _json(asyncio.run(scenario()))
    return 0



def _knowledge_stack(home: Path):
    from aether.events import EventBus
    from aether.knowledge import MemoryCurator, ObsidianKnowledgeProjector, SQLiteKnowledgeProposalStore
    _sessions, fabric = _memory_stack(home)
    proposals = SQLiteKnowledgeProposalStore(home / "memory" / "knowledge-proposals.sqlite3")
    curator = MemoryCurator(
        fabric.canonical,
        proposals,
        fabric,
        event_bus=EventBus(home / "events" / "knowledge-curator.jsonl"),
        projector=ObsidianKnowledgeProjector(home / "obsidian" / "vault"),
    )
    return fabric, proposals, curator


def command_knowledge_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether.contracts import MemoryKind, MemoryProvenance, MemoryQuery, MemoryRecord

    async def evidence(fabric, key, text, source, claim=None, claim_key=None, polarity=1):
        metadata = {}
        if claim:
            metadata["knowledge_candidate"] = {
                "claim": claim, "claim_key": claim_key or claim, "polarity": polarity,
            }
        return await fabric.remember(MemoryRecord(
            key=key, value=text, namespace="episodes", kind=MemoryKind.OBSERVATION,
            content=text, metadata=metadata,
            provenance=MemoryProvenance(source, "2026-07-28T00:00:00Z"),
        ))

    async def scenario():
        fabric, proposals, curator = _knowledge_stack(home)
        claim = "Aether runtime adapters remain replaceable without changing Core."
        await evidence(fabric, "curator-e1", "Runtime adapter A was replaced without Core changes.", "verification:a", claim, "architecture.runtime-adapters")
        await evidence(fabric, "curator-e2", "Runtime adapter B was replaced without Core changes.", "verification:b", claim, "architecture.runtime-adapters")
        created = await curator.curate_explicit_candidates()
        proposal = created[0]
        review = curator.review(proposal.proposal_id)
        promoted = await curator.decide(
            proposal.proposal_id, approved=True, principal="founder", channel="cli",
            reason="Two independent adapter replacement verifications passed.", confidence=0.80,
        )
        knowledge = await fabric.retrieve(MemoryQuery(
            "runtime adapters replaceable", namespaces=("knowledge",), limit=5,
        ))
        # A non-identical repetition remains visible as a duplicate and is blocked.
        c = await evidence(fabric, "curator-e3", "Runtime adapter C was replaceable.", "verification:c")
        d = await evidence(fabric, "curator-e4", "Runtime adapter D was replaceable.", "verification:d")
        duplicate = await curator.propose(
            claim=claim, claim_key="architecture.runtime-adapters", polarity=1,
            evidence_record_ids=[c.record_id, d.record_id],
        )
        # Opposite polarity remains visible as an unresolved contradiction.
        opposing = await curator.propose(
            claim="Aether runtime adapters must be hard-coded into Core.",
            claim_key="architecture.runtime-adapters", polarity=-1,
            evidence_record_ids=[c.record_id, d.record_id],
        )
        return {
            "status": "completed",
            "proposal_id": proposal.proposal_id,
            "initial_blockers": list(review.blockers),
            "promotion_status": promoted.proposal.status.value,
            "decision_id": promoted.decision.decision_id if promoted.decision else None,
            "knowledge_record_id": promoted.proposal.knowledge_record_id,
            "retrieval_hits": [hit.record.record_id for hit in knowledge.hits],
            "duplicate": {
                "proposal_id": duplicate.proposal_id,
                "duplicate_of": duplicate.duplicate_of,
                "blockers": list(curator.review(duplicate.proposal_id).blockers),
            },
            "contradiction": {
                "proposal_id": opposing.proposal_id,
                "contradiction_ids": list(opposing.contradiction_ids),
                "blockers": list(curator.review(opposing.proposal_id).blockers),
            },
            "proposal_counts": {
                "proposed": len(proposals.list(__import__("aether.contracts", fromlist=["KnowledgeProposalStatus"]).KnowledgeProposalStatus.PROPOSED)),
                "promoted": len(proposals.list(__import__("aether.contracts", fromlist=["KnowledgeProposalStatus"]).KnowledgeProposalStatus.PROMOTED)),
            },
        }

    _json(asyncio.run(scenario()))
    return 0


def command_knowledge_curate(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    async def scenario():
        _fabric, _proposals, curator = _knowledge_stack(home)
        items = await curator.curate_explicit_candidates(limit=args.limit)
        return {
            "status": "completed",
            "proposal_count": len(items),
            "proposals": [
                {
                    "proposal_id": item.proposal_id,
                    "claim": item.claim,
                    "duplicate_of": item.duplicate_of,
                    "contradiction_ids": list(item.contradiction_ids),
                    "blockers": list(curator.review(item.proposal_id).blockers),
                }
                for item in items
            ],
        }
    _json(asyncio.run(scenario()))
    return 0


def _evolution_stack(home: Path, workspace: Path):
    from aether.events import EventBus
    from aether.evolution import InternalEvolutionEngine, SQLiteEvolutionStore
    from aether_gateway.evolution import LocalArtifactPromoter, LocalEvolutionSandbox

    store = SQLiteEvolutionStore(home / "evolution" / "internal-evolution.sqlite3")
    engine = InternalEvolutionEngine(
        store,
        event_bus=EventBus(home / "events" / "internal-evolution.jsonl"),
    )
    sandbox = LocalEvolutionSandbox(workspace, home / "evolution" / "sandboxes")
    promoter = LocalArtifactPromoter(workspace, home / "evolution" / "backups")
    return store, engine, sandbox, promoter


def command_evolution_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = home / "evolution-demo" / "workspace"
    if workspace.parent.exists():
        shutil.rmtree(workspace.parent)
    (workspace / "tests").mkdir(parents=True)
    (workspace / "heldout").mkdir()
    (workspace / "calculator.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8",
    )
    (workspace / "tests" / "test_add.py").write_text(
        "import unittest\nfrom calculator import add\n"
        "class AddTest(unittest.TestCase):\n"
        "    def test_positive(self): self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    (workspace / "heldout" / "test_edge.py").write_text(
        "import unittest\nfrom calculator import add\n"
        "class EdgeTest(unittest.TestCase):\n"
        "    def test_zero(self): self.assertEqual(add(0, 1), 1)\n",
        encoding="utf-8",
    )

    from aether.contracts import EvolutionCheckKind, EvolutionCommand, EvolutionTargetType
    from aether.evolution import capability_gap

    async def scenario():
        store, engine, sandbox, promoter = _evolution_stack(home, workspace)
        trigger = engine.register_trigger(capability_gap(
            summary="Calculator addition returns subtraction.",
            target="calculator.py",
            evidence_ids=("verification.demo.failure",),
            metadata={"source": "cli-demo"},
        ))
        candidate = engine.propose_candidate(
            trigger_id=trigger.trigger_id,
            target_type=EvolutionTargetType.CODE,
            target_path="calculator.py",
            baseline_content=(workspace / "calculator.py").read_text(encoding="utf-8"),
            candidate_content="def add(a, b):\n    return a + b\n",
            rationale="Correct the bounded arithmetic defect.",
            generator_id="generator.deterministic-demo",
            deterministic_checks=(EvolutionCommand(
                ("{python}", "-m", "unittest", "discover", "-s", "tests"),
                EvolutionCheckKind.DETERMINISTIC,
                "unit-tests",
            ),),
            heldout_checks=(EvolutionCommand(
                ("{python}", "-m", "unittest", "discover", "-s", "heldout"),
                EvolutionCheckKind.HELDOUT,
                "heldout-tests",
            ),),
        )
        evaluation = await engine.evaluate(candidate.candidate_id, sandbox)
        promoted = await engine.decide(
            candidate.candidate_id,
            approved=True,
            principal="founder",
            channel="cli",
            reason="Deterministic and held-out checks prove measurable improvement with zero regressions.",
            promoter=promoter,
        )
        lineage = store.get_lineage(promoted.lineage_id)
        return {
            "status": promoted.status.value,
            "trigger_id": trigger.trigger_id,
            "fingerprint": trigger.fingerprint,
            "prior_learning_ids": list(trigger.prior_learning_ids),
            "candidate_id": candidate.candidate_id,
            "target_path": candidate.target_path,
            "diff": candidate.diff,
            "evaluation": {
                "evaluation_id": evaluation.evaluation_id,
                "baseline_score": evaluation.baseline_score,
                "candidate_score": evaluation.candidate_score,
                "improvement": evaluation.improvement,
                "regression_count": evaluation.regression_count,
                "passed": evaluation.passed,
            },
            "lineage": {
                "lineage_id": lineage.lineage_id,
                "parent_hash": lineage.parent_hash,
                "promoted_hash": lineage.promoted_hash,
                "backup_path": lineage.backup_path,
            },
            "promoted_content": (workspace / "calculator.py").read_text(encoding="utf-8"),
            "engine_status": engine.status(),
        }

    _json(asyncio.run(scenario()))
    return 0


def command_evolution_status(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    store, engine, _sandbox, _promoter = _evolution_stack(home, workspace)
    _json({
        **engine.status(),
        "workspace": str(workspace),
        "recent_triggers": [
            {
                "trigger_id": item.trigger_id,
                "fingerprint": item.fingerprint,
                "summary": item.summary,
                "prior_learning_ids": list(item.prior_learning_ids),
            }
            for item in store.list_triggers(limit=20)
        ],
    })
    return 0



def _skill_stack(home: Path, workspace: Path):
    from aether.events import EventBus
    from aether.skills import SkillFactory, SQLiteSkillStore
    from aether_gateway.skills import LocalRuntimeSkillInstaller, LocalSkillBenchmarkSandbox

    store = SQLiteSkillStore(home / "skills" / "skill-factory.sqlite3")
    factory = SkillFactory(store, event_bus=EventBus(home / "events" / "skill-factory.jsonl"))
    sandbox = LocalSkillBenchmarkSandbox(workspace, home / "skills" / "sandboxes")
    installer = LocalRuntimeSkillInstaller(home / "skills" / "registry")
    return store, factory, sandbox, installer


def command_skill_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = home / "skill-demo" / "workspace"
    if workspace.parent.exists():
        shutil.rmtree(workspace.parent)
    (workspace / "tests").mkdir(parents=True)
    (workspace / "heldout").mkdir()
    test_body = (
        "import json\nfrom pathlib import Path\n"
        "def test_manifest():\n"
        "    path = Path('.aether/skills/math-helper.json')\n"
        "    assert path.exists()\n"
        "    data = json.loads(path.read_text())\n"
        "    assert 'Add two integers' in data['instructions']\n"
    )
    (workspace / "tests" / "test_skill.py").write_text(test_body, encoding="utf-8")
    (workspace / "heldout" / "test_skill_heldout.py").write_text(
        test_body.replace("test_manifest", "test_manifest_heldout"), encoding="utf-8"
    )

    from aether.contracts import (
        EvolutionCheckKind, EvolutionCommand, SkillLifecycleAction, SkillManifest,
        SkillUsageContract, SkillUsageEvent,
    )

    async def scenario():
        store, factory, sandbox, installer = _skill_stack(home, workspace)
        candidate = factory.propose_repeated_workflow(
            manifest=SkillManifest(
                name="math-helper",
                version="1.0.0",
                summary="Deterministic integer addition workflow.",
                instructions="Add two integers and return the exact result.",
                usage=SkillUsageContract(
                    capabilities=("reason",),
                    input_schema={"a": "integer", "b": "integer"},
                    output_schema={"result": "integer"},
                ),
                tags=("math", "deterministic"),
            ),
            workflow_fingerprint="workflow:add-integers",
            evidence_ids=("demo-success-1", "demo-success-2", "demo-success-3"),
            observed_count=3,
            successful_count=3,
            source_workflow="manual-addition",
            generator_id="generator.deterministic-demo",
            deterministic_checks=(EvolutionCommand(
                ("{python}", "-m", "pytest", "-q", "tests/test_skill.py"),
                EvolutionCheckKind.DETERMINISTIC,
                "unit",
            ),),
            heldout_checks=(EvolutionCommand(
                ("{python}", "-m", "pytest", "-q", "heldout/test_skill_heldout.py"),
                EvolutionCheckKind.HELDOUT,
                "heldout",
            ),),
            rationale="Package a repeated successful workflow as a bounded Aether-owned skill.",
        )
        benchmark = await factory.benchmark(candidate.candidate_id, sandbox)
        activated = await factory.decide(
            candidate.candidate_id,
            approved=True,
            principal="founder",
            channel="cli",
            reason="Deterministic and held-out benchmarks prove reusable behavior with zero regressions.",
            installer=installer,
        )
        skill_id = activated.skill_id
        factory.record_usage(SkillUsageEvent(
            skill_id=skill_id,
            runtime_id="runtime.demo",
            success=True,
            duration_seconds=0.05,
            session_id="cli:skill-demo",
        ))
        review = factory.review(skill_id)
        archived = await factory.lifecycle(
            skill_id,
            action=SkillLifecycleAction.ARCHIVE,
            principal="founder",
            channel="cli",
            reason="Archive the demo skill explicitly while retaining its artifact and immutable lineage.",
            installer=installer,
        )
        return {
            "status": "completed",
            "candidate_id": candidate.candidate_id,
            "artifact_hash": candidate.artifact_hash,
            "benchmark": {
                "baseline_score": benchmark.baseline_score,
                "candidate_score": benchmark.candidate_score,
                "improvement": benchmark.improvement,
                "regressions": benchmark.regression_count,
                "passed": benchmark.passed,
            },
            "skill_id": skill_id,
            "install_path": archived.install_receipt.install_path,
            "artifact_retained": Path(archived.install_receipt.install_path).exists(),
            "review": {
                "current_status": review.current_status.value,
                "recommended_status": review.recommended_status.value,
                "usage_count": review.usage_count,
                "success_rate": review.success_rate,
            },
            "final_lifecycle": archived.lifecycle_status.value,
            "factory_status": factory.status(),
        }

    _json(asyncio.run(scenario()))
    return 0


def command_skill_status(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    store, factory, _sandbox, installer = _skill_stack(home, workspace)
    _json({
        **factory.status(),
        "workspace": str(workspace),
        "installer": installer.adapter_id,
        "recent_skills": [
            {
                "skill_id": item.skill_id,
                "name": item.manifest.name,
                "version": item.manifest.version,
                "lifecycle_status": item.lifecycle_status.value,
                "artifact_hash": item.artifact_hash,
                "usage_count": len(store.usages(item.skill_id)),
            }
            for item in store.list_records(limit=20)
        ],
    })
    return 0



def command_capability_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = home / "capability-demo" / "workspace"
    if workspace.parent.exists():
        shutil.rmtree(workspace.parent)
    (workspace / "tests").mkdir(parents=True)
    (workspace / "heldout").mkdir()
    test_body = (
        "import json\nfrom pathlib import Path\n"
        "def test_manifest():\n"
        "    path = Path('.aether/skills/greeting-skill.json')\n"
        "    assert path.exists()\n"
        "    data = json.loads(path.read_text())\n"
        "    assert data['metadata']['execution']['kind'] == 'template-v1'\n"
    )
    (workspace / "tests" / "test_skill.py").write_text(test_body, encoding="utf-8")
    (workspace / "heldout" / "test_skill_heldout.py").write_text(
        test_body.replace("test_manifest", "test_manifest_heldout"), encoding="utf-8"
    )

    from aether.actions import FailureFingerprintStore, GovernedActionPath
    from aether.capabilities import CapabilityRouter
    from aether.contracts import (
        CapabilityRequirement, EvolutionCheckKind, EvolutionCommand, SkillManifest, SkillUsageContract,
    )
    from aether.events import EventBus
    from aether.governance import ActionGovernor
    from aether_gateway.skills import LocalProjectedSkillRuntimeAdapter

    async def scenario():
        store, factory, sandbox, installer = _skill_stack(home, workspace)
        candidate = factory.propose_capability_gap(
            manifest=SkillManifest(
                name="greeting-skill",
                version="1.0.0",
                summary="Render a deterministic greeting.",
                instructions="Render a bounded greeting from structured input.",
                usage=SkillUsageContract(
                    capabilities=("greet",),
                    input_schema={
                        "type": "object",
                        "required": ["name"],
                        "properties": {"name": {"type": "string"}},
                    },
                    output_schema={
                        "type": "object",
                        "required": ["text"],
                        "properties": {"text": {"type": "string"}},
                    },
                    runtime_requirements=("aether.template-v1",),
                ),
                tags=("demo", "deterministic"),
                metadata={"execution": {"kind": "template-v1", "template": "Hello, {name}!"}},
            ),
            gap_fingerprint="gap:greeting",
            evidence_ids=("demo-gap-1",),
            generator_id="generator.deterministic-demo",
            deterministic_checks=(EvolutionCommand(
                ("{python}", "-m", "pytest", "-q", "tests/test_skill.py"),
                EvolutionCheckKind.DETERMINISTIC,
                "unit",
            ),),
            heldout_checks=(EvolutionCommand(
                ("{python}", "-m", "pytest", "-q", "heldout/test_skill_heldout.py"),
                EvolutionCheckKind.HELDOUT,
                "heldout",
            ),),
            rationale="Close a measured greeting capability gap with a bounded template skill.",
        )
        benchmark = await factory.benchmark(candidate.candidate_id, sandbox)
        activated = await factory.decide(
            candidate.candidate_id,
            approved=True,
            principal="founder",
            channel="cli",
            reason="Deterministic and held-out benchmarks prove safe runtime-neutral execution.",
            installer=installer,
        )
        runtime = LocalProjectedSkillRuntimeAdapter(
            store,
            factory,
            home / "skills" / "runtime-projections" / "local-template",
            event_bus=EventBus(home / "events" / "runtime-skill-projection.jsonl"),
        )
        action_bus = EventBus(home / "events" / "action-path.jsonl")
        action_path = GovernedActionPath(
            action_bus,
            ActionGovernor(),
            FailureFingerprintStore(home / "evolution" / "action-failures.jsonl"),
            runtimes={runtime.routing_key: runtime},
            hidden_runtime_ids={runtime.routing_key},
        )
        route_bus = EventBus(home / "events" / "capability-router.jsonl")
        router = CapabilityRouter(store, action_path, [runtime.profile], event_bus=route_bus)
        result = await router.execute(CapabilityRequirement(
            capability="greet",
            arguments={"name": args.name},
            required_runtime_features=("aether.template-v1",),
            reason="Run the activated greeting capability through governed skill execution.",
            session_id="cli:capability-demo",
        ))
        usage = store.usages(activated.skill_id)
        return {
            "status": result.status.value,
            "ok": result.ok,
            "output": result.output,
            "candidate_id": candidate.candidate_id,
            "skill_id": activated.skill_id,
            "benchmark": {
                "baseline_score": benchmark.baseline_score,
                "candidate_score": benchmark.candidate_score,
                "improvement": benchmark.improvement,
                "regressions": benchmark.regression_count,
            },
            "selected_skill_id": result.selected_skill_id,
            "attempts": list(result.attempts),
            "usage_count": len(usage),
            "projection_path": result.action_result.metadata.get("projection_path") if result.action_result else None,
            "route_events": [event.to_dict() for event in route_bus.replay()],
        }

    _json(asyncio.run(scenario()))
    return 0

def command_runtime_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = home / "workspace" / "runtime-demo"
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / "calc.py"
    source.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (workspace / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    import hashlib
    expected = hashlib.sha256(source.read_bytes()).hexdigest()

    from aether.actions import FailureFingerprintStore, GovernedActionPath, PendingActionStore, TrustedApprovalInbox
    from aether.contracts import CodingEdit, CodingTask, VerificationCommand
    from aether.events import EventBus
    from aether.governance import ActionGovernor
    from aether.runtimes import CodingRuntimeRouter
    from aether_gateway.runtime_sdk import (
        CodingRuntimeDispatchAdapter, LocalStructuredCodingRuntimeAdapter, RuntimeAdapterRegistry,
        RuntimeTelemetryStore, SQLiteWorkspaceBindingStore,
    )

    async def scenario() -> dict:
        runtime_bus = EventBus(home / "events" / "coding-runtime.jsonl")
        bindings = SQLiteWorkspaceBindingStore(home / "runtime" / "workspace-bindings.sqlite3", [workspace])
        binding = bindings.bind(workspace, "cli:runtime-demo", workspace_id="runtime-demo")
        telemetry = RuntimeTelemetryStore(home / "runtime" / "runtime-telemetry.sqlite3")
        runtime = LocalStructuredCodingRuntimeAdapter(home / "runtime" / "local-structured", telemetry, allowed_workspace_roots=[workspace], event_bus=runtime_bus)
        registry = RuntimeAdapterRegistry(event_bus=runtime_bus)
        registry.register(runtime, runtime.descriptor)
        dispatcher = CodingRuntimeDispatchAdapter(registry, event_bus=runtime_bus)
        action_bus = EventBus(home / "events" / "action-path.jsonl")
        pending = PendingActionStore(home / "governance" / "pending-actions.sqlite3")
        action_path = GovernedActionPath(
            action_bus, ActionGovernor(),
            FailureFingerprintStore(home / "evolution" / "action-failures.jsonl"),
            runtimes={dispatcher.routing_key: dispatcher}, pending_store=pending,
            hidden_runtime_ids={dispatcher.routing_key},
        )
        router = CodingRuntimeRouter(registry, bindings, action_path, event_bus=runtime_bus, dispatch_routing_key=dispatcher.routing_key)
        task = CodingTask(
            objective="Correct the bounded addition implementation and verify it.",
            workspace_id=binding.workspace_id,
            session_id=binding.session_id,
            edits=(CodingEdit("calc.py", "def add(a, b):\n    return a + b\n", expected),),
            verification_commands=(VerificationCommand((sys.executable, "-m", "pytest", "-q", "test_calc.py"), label="heldout"),),
            required_runtime_features=("structured-edits", "verification-receipts"),
        )
        requested = await router.execute(task)
        if requested.action_result is None or requested.action_result.status != "pending-approval":
            raise RuntimeError("coding task did not enter trusted approval inbox")
        approval_id = str(requested.action_result.metadata["approval_id"])
        inbox = TrustedApprovalInbox(pending, action_path, action_bus)
        approved = await inbox.decide_and_resume(
            approval_id, approved=True, principal="founder",
            reason="Reviewed exact workspace, artifact hash, and bounded verification command.",
            channel="cli",
        )
        result = approved.result
        return {
            "status": "completed" if result and result.ok else "failed",
            "workspace_binding": binding.__dict__,
            "approval_id": approval_id,
            "approval_status": approved.pending.status.value,
            "runtime_result": result.output if result else None,
            "source": source.read_text(encoding="utf-8"),
            "telemetry": telemetry.status(),
            "runtime_events": [event.to_dict() for event in runtime_bus.replay()],
        }

    _json(asyncio.run(scenario()))
    return 0



def command_external_runtime_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = home / "workspace" / "external-runtime-demo"
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / "calc.py"
    source.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (workspace / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    import hashlib
    expected = hashlib.sha256(source.read_bytes()).hexdigest()

    from aether.actions import FailureFingerprintStore, GovernedActionPath, PendingActionStore, TrustedApprovalInbox
    from aether.contracts import CodingEdit, CodingTask, VerificationCommand
    from aether.events import EventBus
    from aether.governance import ActionGovernor
    from aether.runtimes import CodingRuntimeRouter
    from aether_gateway.runtime_sdk import (
        CodingRuntimeDispatchAdapter, ExternalStreamingCodingRuntimeAdapter,
        RuntimeAdapterRegistry, RuntimeTelemetryStore, SQLiteWorkspaceBindingStore,
    )

    async def scenario() -> dict:
        runtime_bus = EventBus(home / "events" / "external-coding-runtime.jsonl")
        bindings = SQLiteWorkspaceBindingStore(home / "runtime" / "workspace-bindings.sqlite3", [workspace])
        binding = bindings.bind(workspace, "cli:external-runtime-demo", workspace_id="external-runtime-demo")
        telemetry = RuntimeTelemetryStore(home / "runtime" / "runtime-telemetry.sqlite3")
        runtime = ExternalStreamingCodingRuntimeAdapter(
            (sys.executable, "-m", "aether_gateway.runtime_sdk.reference_external_runtime"),
            home / "runtime" / "external-jsonl-reference",
            telemetry,
            allowed_workspace_roots=[workspace],
            event_bus=runtime_bus,
        )
        registry = RuntimeAdapterRegistry(event_bus=runtime_bus)
        registry.register(runtime, runtime.descriptor)
        dispatcher = CodingRuntimeDispatchAdapter(registry, event_bus=runtime_bus)
        action_bus = EventBus(home / "events" / "action-path.jsonl")
        pending = PendingActionStore(home / "governance" / "pending-actions.sqlite3")
        action_path = GovernedActionPath(
            action_bus, ActionGovernor(),
            FailureFingerprintStore(home / "evolution" / "action-failures.jsonl"),
            runtimes={dispatcher.routing_key: dispatcher}, pending_store=pending,
            hidden_runtime_ids={dispatcher.routing_key},
        )
        router = CodingRuntimeRouter(registry, bindings, action_path, event_bus=runtime_bus, dispatch_routing_key=dispatcher.routing_key)
        task = CodingTask(
            objective="Ask an external coding body to generate and verify the addition patch.",
            workspace_id=binding.workspace_id,
            session_id=binding.session_id,
            edits=(CodingEdit("calc.py", "def add(a, b):\n    return a + b\n", expected),),
            verification_commands=(VerificationCommand((sys.executable, "-m", "pytest", "-q", "test_calc.py"), label="heldout"),),
            required_runtime_features=("external-cli", "jsonl-stream-v1", "runtime-generated-patch", "independent-verification"),
        )
        requested = await router.execute(task)
        if requested.action_result is None or requested.action_result.status != "pending-approval":
            raise RuntimeError("external coding task did not enter trusted approval inbox")
        approval_id = str(requested.action_result.metadata["approval_id"])
        inbox = TrustedApprovalInbox(pending, action_path, action_bus)
        approved = await inbox.decide_and_resume(
            approval_id, approved=True, principal="founder",
            reason="Reviewed external runtime candidate, workspace binding, expected hash, and independent verification command.",
            channel="cli",
        )
        result = approved.result
        transcript = home / "runtime" / "external-jsonl-reference" / "runs" / task.task_id / "stream.jsonl"
        return {
            "status": "completed" if result and result.ok else "failed",
            "workspace_binding": binding.__dict__,
            "approval_id": approval_id,
            "approval_status": approved.pending.status.value,
            "runtime_result": result.output if result else None,
            "source": source.read_text(encoding="utf-8"),
            "telemetry": telemetry.status(),
            "stream_transcript": str(transcript),
            "stream_transcript_exists": transcript.exists(),
            "runtime_events": [event.to_dict() for event in runtime_bus.replay()],
        }

    _json(asyncio.run(scenario()))
    return 0


def command_driver_status(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether_gateway.runtime_drivers import RuntimeDriverPack
    from aether_gateway.runtime_sdk import RuntimeTelemetryStore
    workspace = home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    pack = RuntimeDriverPack(
        home / "runtime" / "driver-pack",
        RuntimeTelemetryStore(home / "runtime" / "runtime-telemetry.sqlite3"),
        allowed_workspace_roots=[workspace],
    )
    _json(pack.as_dict())
    return 0


def command_codex_live_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = home / "workspace" / "codex-live-demo"
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / "calc.py"
    source.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (workspace / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8",
    )

    from aether.actions import FailureFingerprintStore, GovernedActionPath, PendingActionStore, TrustedApprovalInbox
    from aether.contracts import CodingTask, RuntimeDriverAvailability, VerificationCommand
    from aether.events import EventBus
    from aether.governance import ActionGovernor
    from aether.runtimes import CodingRuntimeRouter
    from aether_gateway.runtime_drivers import RuntimeDriverPack
    from aether_gateway.runtime_sdk import (
        CodingRuntimeDispatchAdapter, RuntimeAdapterRegistry, RuntimeTelemetryStore, SQLiteWorkspaceBindingStore,
    )

    async def scenario() -> tuple[dict, int]:
        runtime_bus = EventBus(home / "events" / "codex-driver.jsonl")
        telemetry = RuntimeTelemetryStore(home / "runtime" / "runtime-telemetry.sqlite3")
        pack = RuntimeDriverPack(home / "runtime" / "driver-pack", telemetry,
                                 allowed_workspace_roots=[workspace], event_bus=runtime_bus)
        statuses = {item.manifest.driver_id: item for item in pack.status()}
        codex_status = statuses["openai-codex-cli"]
        if codex_status.availability != RuntimeDriverAvailability.AVAILABLE:
            return ({
                "status": "unavailable",
                "driver": codex_status.manifest.driver_id,
                "availability": codex_status.availability.value,
                "reason": codex_status.reason,
                "executable": codex_status.executable,
                "instruction": "Install/authenticate Codex CLI or configure AETHER_CODEX_BIN and AETHER_CODEX_HOME/OPENAI_API_KEY.",
            }, 2)
        try:
            receipt = await pack.conform("openai-codex-cli", principal="founder", ttl_hours=24)
        except Exception as exc:
            return ({"status": "conformance-failed", "driver": "openai-codex-cli", "error": f"{type(exc).__name__}: {exc}"}, 2)
        bindings = SQLiteWorkspaceBindingStore(home / "runtime" / "workspace-bindings.sqlite3", [workspace])
        binding = bindings.bind(workspace, "cli:codex-live-demo", workspace_id="codex-live-demo")
        registry = RuntimeAdapterRegistry(event_bus=runtime_bus)
        adapters = pack.build_live_adapters()
        for adapter in adapters:
            registry.register(adapter, adapter.descriptor)
        dispatcher = CodingRuntimeDispatchAdapter(registry, event_bus=runtime_bus)
        action_bus = EventBus(home / "events" / "action-path.jsonl")
        pending = PendingActionStore(home / "governance" / "pending-actions.sqlite3")
        action_path = GovernedActionPath(
            action_bus, ActionGovernor(), FailureFingerprintStore(home / "evolution" / "action-failures.jsonl"),
            runtimes={dispatcher.routing_key: dispatcher}, pending_store=pending,
            hidden_runtime_ids={dispatcher.routing_key},
        )
        router = CodingRuntimeRouter(registry, bindings, action_path, event_bus=runtime_bus,
                                     dispatch_routing_key=dispatcher.routing_key)
        task = CodingTask(
            objective="Fix calc.py so the held-out addition test passes. Generate the smallest correct patch.",
            workspace_id=binding.workspace_id,
            session_id=binding.session_id,
            edits=(),
            verification_commands=(VerificationCommand((sys.executable, "-m", "pytest", "-q", "test_calc.py"), label="heldout"),),
            required_capabilities=("coding.patch-generation", "coding.verify", "coding.artifact-return"),
            required_runtime_features=("vendor-driver-pack-v1", "generative-coding", "runtime-generated-patch", "independent-verification"),
            allow_fallback=False,
        )
        requested = await router.execute(task)
        if requested.action_result is None or requested.action_result.status != "pending-approval":
            return ({"status": "failed", "reason": "task did not enter trusted approval inbox", "execution": str(requested)}, 1)
        approval_id = str(requested.action_result.metadata["approval_id"])
        inbox = TrustedApprovalInbox(pending, action_path, action_bus)
        approved = await inbox.decide_and_resume(
            approval_id, approved=True, principal="founder",
            reason="Reviewed Codex driver, staging-only workspace, bounded patch limits, and independent verification.",
            channel="cli",
        )
        result = approved.result
        return ({
            "status": "completed" if result and result.ok else "failed",
            "driver": codex_status.manifest.driver_id,
            "runtime_version": result.metadata.get("external_runtime_version") if result else None,
            "approval_id": approval_id,
            "approval_status": approved.pending.status.value,
            "runtime_result": result.output if result else None,
            "source": source.read_text(encoding="utf-8"),
            "telemetry": telemetry.status(),
            "runtime_events": [event.to_dict() for event in runtime_bus.replay()],
        }, 0 if result and result.ok else 1)

    payload, code = asyncio.run(scenario())
    _json(payload)
    return code

def command_opencode_live_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = home / "workspace" / "opencode-live-demo"
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / "calc.py"
    source.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (workspace / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8",
    )

    from aether.actions import FailureFingerprintStore, GovernedActionPath, PendingActionStore, TrustedApprovalInbox
    from aether.contracts import CodingTask, RuntimeDriverAvailability, VerificationCommand
    from aether.events import EventBus
    from aether.governance import ActionGovernor
    from aether.runtimes import CodingRuntimeRouter
    from aether_gateway.runtime_drivers import RuntimeDriverPack
    from aether_gateway.runtime_sdk import (
        CodingRuntimeDispatchAdapter, RuntimeAdapterRegistry, RuntimeTelemetryStore, SQLiteWorkspaceBindingStore,
    )

    async def scenario() -> tuple[dict, int]:
        runtime_bus = EventBus(home / "events" / "opencode-driver.jsonl")
        telemetry = RuntimeTelemetryStore(home / "runtime" / "runtime-telemetry.sqlite3")
        pack = RuntimeDriverPack(home / "runtime" / "driver-pack", telemetry,
                                 allowed_workspace_roots=[workspace], event_bus=runtime_bus)
        statuses = {item.manifest.driver_id: item for item in pack.status()}
        opencode_status = statuses["opencode-cli"]
        if opencode_status.availability != RuntimeDriverAvailability.AVAILABLE:
            return ({
                "status": "unavailable",
                "driver": opencode_status.manifest.driver_id,
                "availability": opencode_status.availability.value,
                "reason": opencode_status.reason,
                "executable": opencode_status.executable,
                "instruction": "Install/authenticate OpenCode CLI or configure AETHER_OPENCODE_BIN and AETHER_OPENCODE_API_KEY_FILE.",
            }, 2)
        try:
            receipt = await pack.conform("opencode-cli", principal="founder", ttl_hours=24)
        except Exception as exc:
            return ({"status": "conformance-failed", "driver": "opencode-cli", "error": f"{type(exc).__name__}: {exc}"}, 2)
        bindings = SQLiteWorkspaceBindingStore(home / "runtime" / "workspace-bindings.sqlite3", [workspace])
        binding = bindings.bind(workspace, "cli:opencode-live-demo", workspace_id="opencode-live-demo")
        registry = RuntimeAdapterRegistry(event_bus=runtime_bus)
        adapters = pack.build_live_adapters()
        for adapter in adapters:
            registry.register(adapter, adapter.descriptor)
        dispatcher = CodingRuntimeDispatchAdapter(registry, event_bus=runtime_bus)
        action_bus = EventBus(home / "events" / "action-path.jsonl")
        pending = PendingActionStore(home / "governance" / "pending-actions.sqlite3")
        action_path = GovernedActionPath(
            action_bus, ActionGovernor(), FailureFingerprintStore(home / "evolution" / "action-failures.jsonl"),
            runtimes={dispatcher.routing_key: dispatcher}, pending_store=pending,
            hidden_runtime_ids={dispatcher.routing_key},
        )
        router = CodingRuntimeRouter(registry, bindings, action_path, event_bus=runtime_bus,
                                     dispatch_routing_key=dispatcher.routing_key)
        task = CodingTask(
            objective="Fix calc.py so the held-out addition test passes. Generate the smallest correct patch.",
            workspace_id=binding.workspace_id,
            session_id=binding.session_id,
            edits=(),
            verification_commands=(VerificationCommand((sys.executable, "-m", "pytest", "-q", "test_calc.py"), label="heldout"),),
            required_capabilities=("coding.patch-generation", "coding.verify", "coding.artifact-return"),
            required_runtime_features=("vendor-driver-pack-v1", "generative-coding", "runtime-generated-patch", "independent-verification"),
            allow_fallback=False,
        )
        requested = await router.execute(task)
        if requested.action_result is None or requested.action_result.status != "pending-approval":
            return ({"status": "failed", "reason": "task did not enter trusted approval inbox", "execution": str(requested)}, 1)
        approval_id = str(requested.action_result.metadata["approval_id"])
        inbox = TrustedApprovalInbox(pending, action_path, action_bus)
        approved = await inbox.decide_and_resume(
            approval_id, approved=True, principal="founder",
            reason="Reviewed OpenCode driver, staging-only workspace, bounded patch limits, and independent verification.",
            channel="cli",
        )
        result = approved.result
        return ({
            "status": "completed" if result and result.ok else "failed",
            "driver": opencode_status.manifest.driver_id,
            "runtime_version": result.metadata.get("external_runtime_version") if result else None,
            "approval_id": approval_id,
            "approval_status": approved.pending.status.value,
            "runtime_result": result.output if result else None,
            "source": source.read_text(encoding="utf-8"),
            "telemetry": telemetry.status(),
            "runtime_events": [event.to_dict() for event in runtime_bus.replay()],
        }, 0 if result and result.ok else 1)

    payload, code = asyncio.run(scenario())
    _json(payload)
    return code



def _command_live_driver(args: argparse.Namespace, *, driver_id: str, slug: str, instruction: str) -> int:
    home = _set_home(args.home)
    workspace = home / "workspace" / f"{slug}-live-demo"
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / "calc.py"
    source.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (workspace / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8",
    )
    from aether.actions import FailureFingerprintStore, GovernedActionPath, PendingActionStore, TrustedApprovalInbox
    from aether.contracts import CodingTask, RuntimeDriverAvailability, VerificationCommand
    from aether.events import EventBus
    from aether.governance import ActionGovernor
    from aether.runtimes import CodingRuntimeRouter
    from aether_gateway.runtime_drivers import RuntimeDriverPack
    from aether_gateway.runtime_sdk import CodingRuntimeDispatchAdapter, RuntimeAdapterRegistry, RuntimeTelemetryStore, SQLiteWorkspaceBindingStore

    async def scenario() -> tuple[dict, int]:
        runtime_bus = EventBus(home / "events" / f"{slug}-driver.jsonl")
        telemetry = RuntimeTelemetryStore(home / "runtime" / "runtime-telemetry.sqlite3")
        pack = RuntimeDriverPack(home / "runtime" / "driver-pack", telemetry, allowed_workspace_roots=[workspace], event_bus=runtime_bus)
        status = {item.manifest.driver_id: item for item in pack.status()}[driver_id]
        if status.availability != RuntimeDriverAvailability.AVAILABLE:
            return ({
                "status": "unavailable", "driver": driver_id, "availability": status.availability.value,
                "reason": status.reason, "executable": status.executable, "instruction": instruction,
            }, 2)
        try:
            receipt = await pack.conform(driver_id, principal="founder", ttl_hours=24)
        except Exception as exc:
            return ({"status": "conformance-failed", "driver": driver_id, "error": f"{type(exc).__name__}: {exc}"}, 2)
        bindings = SQLiteWorkspaceBindingStore(home / "runtime" / "workspace-bindings.sqlite3", [workspace])
        binding = bindings.bind(workspace, f"cli:{slug}-live-demo", workspace_id=f"{slug}-live-demo")
        registry = RuntimeAdapterRegistry(event_bus=runtime_bus)
        for adapter in pack.build_live_adapters():
            registry.register(adapter, adapter.descriptor)
        dispatcher = CodingRuntimeDispatchAdapter(registry, event_bus=runtime_bus)
        action_bus = EventBus(home / "events" / "action-path.jsonl")
        pending = PendingActionStore(home / "governance" / "pending-actions.sqlite3")
        action_path = GovernedActionPath(
            action_bus, ActionGovernor(), FailureFingerprintStore(home / "evolution" / "action-failures.jsonl"),
            runtimes={dispatcher.routing_key: dispatcher}, pending_store=pending, hidden_runtime_ids={dispatcher.routing_key},
        )
        router = CodingRuntimeRouter(registry, bindings, action_path, event_bus=runtime_bus, dispatch_routing_key=dispatcher.routing_key)
        task = CodingTask(
            objective="Fix calc.py so the held-out addition test passes. Generate the smallest correct patch.",
            workspace_id=binding.workspace_id, session_id=binding.session_id, edits=(),
            verification_commands=(VerificationCommand((sys.executable, "-m", "pytest", "-q", "test_calc.py"), label="heldout"),),
            required_capabilities=("coding.patch-generation", "coding.verify", "coding.artifact-return"),
            required_runtime_features=("vendor-driver-pack-v3", "generative-coding", "runtime-generated-patch", "independent-verification"),
            allow_fallback=False,
        )
        requested = await router.execute(task)
        if requested.action_result is None or requested.action_result.status != "pending-approval":
            return ({"status": "failed", "reason": "task did not enter trusted approval inbox", "execution": str(requested)}, 1)
        approval_id = str(requested.action_result.metadata["approval_id"])
        inbox = TrustedApprovalInbox(pending, action_path, action_bus)
        approved = await inbox.decide_and_resume(
            approval_id, approved=True, principal="founder",
            reason=f"Reviewed exact {driver_id} task, conformance receipt, staging boundary, and held-out verification.",
            channel="cli",
        )
        result = approved.result
        return ({
            "status": "completed" if result and result.ok else "failed", "driver": driver_id,
            "receipt_id": receipt.receipt_id, "approval_id": approval_id, "approval_status": approved.pending.status.value,
            "runtime_result": result.output if result else None, "source": source.read_text(encoding="utf-8"),
            "operations_console": pack.operations_console(), "runtime_events": [event.to_dict() for event in runtime_bus.replay()],
        }, 0 if result and result.ok else 1)

    payload, code = asyncio.run(scenario())
    _json(payload)
    return code


def command_gemini_live_demo(args: argparse.Namespace) -> int:
    return _command_live_driver(
        args, driver_id="google-gemini-cli", slug="gemini",
        instruction="Install Gemini CLI and configure AETHER_GEMINI_API_KEY_FILE or AETHER_GEMINI_CREDENTIALS_FILE.",
    )


def command_claude_live_demo(args: argparse.Namespace) -> int:
    return _command_live_driver(
        args, driver_id="anthropic-claude-code", slug="claude",
        instruction="Install/authenticate Claude Code or configure AETHER_CLAUDE_API_KEY_FILE/AETHER_CLAUDE_CONFIG_DIR.",
    )


def _build_runtime_fleet(home: Path):
    from aether_gateway.runtime_drivers import RuntimeDriverPack
    from aether_gateway.runtime_operations import (
        FleetOperationsStore,
        RuntimeFleetOperationsService,
        RuntimeFleetScheduler,
    )
    from aether_gateway.runtime_sdk import RuntimeTelemetryStore

    workspace = home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    telemetry = RuntimeTelemetryStore(home / "runtime" / "runtime-telemetry.sqlite3")
    pack = RuntimeDriverPack(
        home / "runtime" / "driver-pack",
        telemetry,
        allowed_workspace_roots=[workspace],
    )
    store = FleetOperationsStore(home / "runtime" / "fleet-operations.sqlite3")
    service = RuntimeFleetOperationsService(pack, telemetry, store)
    scheduler = RuntimeFleetScheduler(service, enabled=False)
    return pack, service, scheduler


def command_runtime_operations(args: argparse.Namespace) -> int:
    """Backward-compatible alias for the full v0.16 fleet snapshot."""
    home = _set_home(args.home)
    _pack, service, scheduler = _build_runtime_fleet(home)
    manual_run = None
    if getattr(args, "renew_due", False):
        from aether.contracts import FleetJobKind
        manual_run = asyncio.run(service.run_job(FleetJobKind.RECEIPT_RENEWAL, principal="founder"))
    _json({**service.snapshot(), "scheduler": scheduler.status(), "manual_run": manual_run})
    return 0


def command_fleet_operations(args: argparse.Namespace) -> int:
    return command_runtime_operations(args)


def command_fleet_run(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether.contracts import FleetJobKind
    _pack, service, scheduler = _build_runtime_fleet(home)
    try:
        kind = FleetJobKind(args.job)
        run = asyncio.run(service.run_job(kind, principal="founder"))
    except Exception as exc:
        _json({"status": "failed", "job": args.job, "error": f"{type(exc).__name__}: {exc}"})
        return 2
    _json({"status": "completed", "run": run, **service.snapshot(), "scheduler": scheduler.status()})
    return 0


def command_aionui_console(args: argparse.Namespace) -> int:
    gateway = (args.gateway or "http://127.0.0.1:8000").rstrip("/")
    _json({
        "status": "ready",
        "embedded_console": f"{gateway}/aionui/runtime-console",
        "fleet_api": f"{gateway}/api/runtime-fleet/console",
        "integration_pack": str(ROOT / "aionui-integration"),
        "installer": str(ROOT / "aionui-integration" / "scripts" / "install_aionui_integration.py"),
        "authority": "operator-shell-only",
        "scheduler_owner": "aether-gateway",
    })
    return 0


def command_driver_conformance(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether_gateway.runtime_drivers import RuntimeDriverPack
    from aether_gateway.runtime_sdk import RuntimeTelemetryStore
    workspace = home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    pack = RuntimeDriverPack(
        home / "runtime" / "driver-pack",
        RuntimeTelemetryStore(home / "runtime" / "runtime-telemetry.sqlite3"),
        allowed_workspace_roots=[workspace],
    )
    try:
        receipt = asyncio.run(pack.conform(args.driver, principal="founder", ttl_hours=args.ttl_hours))
    except Exception as exc:
        _json({"status": "failed", "driver": args.driver, "error": f"{type(exc).__name__}: {exc}"})
        return 2
    _json({"status": "passed", "receipt": pack._receipt_dict(receipt)})
    return 0


def command_mission_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    workspace = home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    from aether.actions import FailureFingerprintStore, GovernedActionPath, PendingActionStore, TrustedApprovalInbox
    from aether.contracts import (
        ActionProposal, ActionRisk, ActionScope, ActionTarget, MissionBudget, MissionLane,
        MissionRisk, MissionStep, MissionValueKind, OpportunityEvidence,
    )
    from aether.events import EventBus
    from aether.governance import ActionGovernor
    from aether.missions import MissionOrchestrator, SQLiteMissionStore
    from aether_gateway.actions import RegistryToolExecutor
    from aether_gateway.missions import GovernedMissionActionAdapter
    from aether_tools import ToolRegistry
    from aether_tools.primitives import WriteTool

    async def scenario() -> dict:
        action_bus = EventBus(home / "events" / "mission-demo-actions.jsonl")
        pending = PendingActionStore(home / "governance" / "mission-demo-approvals.sqlite3")
        registry = ToolRegistry()
        registry.register(WriteTool([workspace]))
        action_path = GovernedActionPath(
            action_bus,
            ActionGovernor(),
            FailureFingerprintStore(home / "evolution" / "mission-demo-failures.jsonl"),
            tool_executor=RegistryToolExecutor(registry),
            pending_store=pending,
        )
        inbox = TrustedApprovalInbox(pending, action_path, action_bus)
        store = SQLiteMissionStore(home / "missions" / "mission-orchestrator.sqlite3")
        orchestrator = MissionOrchestrator(
            store,
            GovernedMissionActionAdapter(action_path, pending),
            event_bus=EventBus(home / "events" / "mission-orchestrator.jsonl"),
            maximum_steps_per_run=3,
        )
        brief = orchestrator.intake_opportunity(
            title="Deterministic external-value artifact experiment",
            lane=MissionLane.EXTERNAL_VALUE,
            problem_statement="A bounded artifact is required to prove the mission approval and resumption path.",
            beneficiary="Aether operator",
            value_proposition="Produce one verified artifact without bypassing governance.",
            probability_success=0.8,
            upside_usd=25.0,
            estimated_cost_usd=2.0,
            estimated_duration_hours=0.1,
            revenue_hypothesis="Demo-only receipt evidence is recorded separately from actual revenue.",
            assumptions=("This is a deterministic demonstration, not a real commercial claim.",),
            evidence=(
                OpportunityEvidence(source="demo-source-a", independent_source_id="a", statement="The artifact is absent and needed.", external_reference="demo://a"),
                OpportunityEvidence(source="demo-source-b", independent_source_id="b", statement="The governed write path must be exercised.", external_reference="demo://b"),
            ),
            risk=MissionRisk.LOW,
            confidence=0.9,
            metadata={"demo_only": True},
        )
        plan = orchestrator.create_plan(
            brief_id=brief.brief_id,
            objective="Create one bounded external-value demo artifact through trusted action approval.",
            northstar_alignment="Truthful evidence-first execution with no automatic scaling or revenue claim.",
            northstar_principle_ids=("SP1", "SP5", "SP6"),
            strategy_tags=("business_experimentation",),
            steps=(MissionStep(
                step_id="create-demo-artifact",
                title="Create governed mission artifact",
                action=ActionProposal(
                    target=ActionTarget.TOOL,
                    operation="write",
                    arguments={"path": "mission-demo.txt", "_body": "Aether external CEE mission path online.\n"},
                    required_scopes=(ActionScope.WRITE,),
                    reason="Create one bounded demo artifact after trusted approval.",
                    risk=ActionRisk.MEDIUM,
                    reversible=False,
                ),
                success_criteria=("mission-demo.txt exists with the approved content.",),
                estimated_cost_usd=1.0,
            ),),
            budget=MissionBudget(max_cost_usd=2.0, max_duration_seconds=300, max_step_attempts=2),
            stop_conditions=("Stop on write failure.", "Stop when budget is exhausted."),
            metadata={"demo_only": True},
        )
        orchestrator.decide(plan.mission_id, approved=True, principal="founder", channel="cli", reason="Reviewed deterministic evidence and bounded budget.")
        first = await orchestrator.run(plan.mission_id, principal="founder")
        approval_id = first.approval_id
        if not approval_id:
            raise RuntimeError("mission demo expected a pending approval")
        approval = await inbox.decide_and_resume(
            approval_id,
            approved=True,
            principal="founder",
            reason="Approve exact bounded artifact write.",
            channel="cli",
        )
        resumed = await orchestrator.run(plan.mission_id, principal="founder")
        claimed = orchestrator.record_value_evidence(
            mission_id=plan.mission_id,
            kind=MissionValueKind.CLAIMED,
            description="Estimated demonstration value only.",
            source="mission-demo",
            amount_usd=25.0,
            metadata={"demo_only": True},
        )
        realized = orchestrator.record_value_evidence(
            mission_id=plan.mission_id,
            kind=MissionValueKind.REALIZED,
            description="Synthetic demo receipt; not real revenue.",
            source="mission-demo-receipt",
            amount_usd=0.0,
            external_reference="demo-receipt://zero-value",
            metadata={"demo_only": True, "real_revenue": False},
        )
        verified = orchestrator.record_value_evidence(
            mission_id=plan.mission_id,
            kind=MissionValueKind.VERIFIED,
            description="Founder verified that the synthetic receipt carries zero real revenue.",
            source="founder-review",
            amount_usd=0.0,
            external_reference="demo-receipt://zero-value",
            related_evidence_id=realized.evidence_id,
            verified_by="founder",
            metadata={"demo_only": True, "real_revenue": False},
        )
        outcome = await orchestrator.finalize(
            plan.mission_id,
            achieved=True,
            summary="The governed mission completed; no real revenue is claimed by this demo.",
            lessons=("Mission approval and action approval are separate authorities.", "Claimed value must not be reported as realized revenue."),
            principal="founder",
        )
        return {
            "status": resumed.status.value,
            "mission_id": plan.mission_id,
            "brief_id": brief.brief_id,
            "approval_id": approval_id,
            "approval_consumed": approval.pending.status.value,
            "artifact": str(workspace / "mission-demo.txt"),
            "artifact_exists": (workspace / "mission-demo.txt").exists(),
            "claimed_value_usd": outcome.claimed_value_usd,
            "realized_revenue_usd": outcome.realized_revenue_usd,
            "verified_revenue_usd": outcome.verified_revenue_usd,
            "value_evidence_ids": [claimed.evidence_id, realized.evidence_id, verified.evidence_id],
            "mission": store.mission_view(plan.mission_id),
        }

    _json(asyncio.run(scenario()))
    return 0


def command_mission_status(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether.missions import SQLiteMissionStore
    store = SQLiteMissionStore(home / "missions" / "mission-orchestrator.sqlite3")
    _json({
        "status": store.status(),
        "opportunities": [item.brief_id for item in store.list_briefs(limit=args.limit)],
        "missions": [store.mission_view(item.mission_id) for item in store.list_plans(limit=args.limit)],
    })
    return 0

def command_opportunity_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether.contracts import (
        AutonomyLevel, PortfolioDecisionType, ScoutQuery, SourceAdapterManifest,
        SourceCapability, SourceKind,
    )
    from aether.events import EventBus
    from aether.missions import MissionOrchestrator, SQLiteMissionStore
    from aether.opportunities import OpportunityIntelligenceEngine, SQLiteOpportunityStore
    from aether_gateway.opportunities import (
        AutonomousOpportunityScout, OpportunityMissionBridge, SourceCapabilityMesh, StaticCatalogAdapter,
    )

    class NoopMissionExecutor:
        async def execute(self, proposal):
            raise RuntimeError("opportunity demo converts to a mission brief but does not execute mission actions")
        async def approval_result(self, approval_id):
            return None

    async def scenario() -> dict:
        store = SQLiteOpportunityStore(home / "opportunities" / "opportunity-intelligence.sqlite3")
        engine = OpportunityIntelligenceEngine(store, event_bus=EventBus(home / "events" / "opportunity-intelligence.jsonl"))
        mesh = SourceCapabilityMesh()
        documents = {
            "ecosystem": (
                ("https://evidence.example/ecosystem", "Ecosystem signal", "Independent small operators report recurring workflow automation demand and measurable delays caused by manual coordination."),
            ),
            "market": (
                ("https://evidence.example/market", "Market signal", "A separate market source reports recurring demand for bounded automation proofs that reduce repetitive operational work."),
            ),
        }
        for suffix, docs in documents.items():
            adapter = StaticCatalogAdapter(SourceAdapterManifest(
                source_id=f"source.demo.{suffix}", adapter_id=f"source.adapter.demo.{suffix}", name=f"Demo {suffix}",
                kind=SourceKind.CATALOG, capabilities=(SourceCapability.SEARCH, SourceCapability.FETCH, SourceCapability.CATALOG),
                forbidden_capabilities=("credential-export", "external-write"),
            ), docs)
            mesh.register(adapter)
            engine.register_source(adapter.manifest)
        scout = AutonomousOpportunityScout(mesh, engine, event_bus=EventBus(home / "events" / "opportunity-scout.jsonl"))
        receipt = await scout.run(ScoutQuery(
            objective="bounded workflow automation opportunity", queries=("automation demand",),
            source_kinds=(SourceKind.CATALOG,), maximum_sources=2, maximum_snapshots=4,
            autonomy_level=AutonomyLevel.OBSERVE,
        ))
        candidate = engine.synthesize_candidate(
            title="Bounded workflow automation proof",
            problem_statement="Small operators repeat a costly coordination workflow.", beneficiary="Small service operators",
            value_proposition="Build a private reversible proof and measure time savings.",
            revenue_hypothesis="A customer pays only after independently verified operational savings.",
            category="operations-automation", claim_ids=receipt.claim_ids,
            assumptions=("A synthetic workflow can represent the operational bottleneck.",),
            expected_upside_usd=1000.0, probability_success=0.6, estimated_cost_usd=50.0,
            estimated_duration_hours=8.0, risk="low", strategic_alignment=0.95,
            reversibility=0.95, time_to_validation=0.85, legal_risk_penalty=0.05,
            platform_dependency_penalty=0.05, saturation_penalty=0.1,
            strategy_tags=("business-experimentation", "human-value"),
        )
        decision = engine.decide(
            candidate.candidate_id, decision=PortfolioDecisionType.SELECT, principal="founder",
            reason="Two independent sources support a reversible and budget-bounded validation experiment.",
            allocated_budget_usd=50.0, channel="cli",
        )
        mandate = engine.issue_mandate(
            candidate.candidate_id, principal="founder", autonomy_level=AutonomyLevel.SANDBOX_EXPERIMENT,
            allowed_capabilities=("prototype.build", "prototype.verify"), maximum_cost_usd=40.0,
            maximum_external_actions=0, maximum_duration_seconds=3600,
            reason="Build and verify one private reversible prototype before any external consequence.",
        )
        mission_store = SQLiteMissionStore(home / "missions" / "mission-orchestrator.sqlite3")
        bridge = OpportunityMissionBridge(engine, MissionOrchestrator(mission_store, NoopMissionExecutor()))
        brief = bridge.convert(candidate.candidate_id)
        return {
            "status": "completed", "scout_run": receipt.__dict__,
            "candidate": {"candidate_id": candidate.candidate_id, "status": candidate.status.value,
                          "utility_score": candidate.score.utility_score, "expected_net_value_usd": candidate.score.expected_net_value_usd,
                          "independent_sources": len(candidate.supporting_source_ids)},
            "portfolio_decision": {"decision_id": decision.decision_id, "decision": decision.decision.value,
                                   "allocated_budget_usd": decision.allocated_budget_usd},
            "mandate": {"mandate_id": mandate.mandate_id, "autonomy_level": mandate.autonomy_level.value,
                        "maximum_cost_usd": mandate.maximum_cost_usd, "maximum_external_actions": mandate.maximum_external_actions,
                        "forbidden_capabilities": list(mandate.forbidden_capabilities)},
            "mission_brief": {"brief_id": brief.brief_id, "blockers": list(brief.blockers),
                              "independent_support_count": brief.independent_support_count},
            "store": store.status(),
            "real_revenue_claimed": False,
        }
    _json(asyncio.run(scenario()))
    return 0


def command_opportunity_status(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether.contracts import opportunity_candidate_payload, experiment_mandate_payload
    from aether.opportunities import SQLiteOpportunityStore
    store = SQLiteOpportunityStore(home / "opportunities" / "opportunity-intelligence.sqlite3")
    candidates = store.candidates(limit=args.limit)
    _json({
        "status": store.status(),
        "sources": [item.adapter_id for item in store.manifests()],
        "source_status": store.latest_statuses(),
        "runs": store.runs(limit=args.limit),
        "candidates": [opportunity_candidate_payload(item) for item in candidates],
        "decisions": [str(item.decision.value) for item in (store.decision(candidate.candidate_id) for candidate in candidates) if item],
        "mandates": [experiment_mandate_payload(item) for item in store.mandates()],
    })
    return 0



def command_experiment_demo(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether.contracts import (
        AutonomyLevel, DemandEvidenceState, DemandSignal, DemandSignalKind,
        ExperimentStep, ExperimentStepKind, PortfolioDecisionType, ReversibleExperimentPlan,
        ScoutQuery, SourceAdapterManifest, SourceCapability, SourceKind,
    )
    from aether.events import EventBus
    from aether.experiments import ReversibleExperimentEngine, SQLiteExperimentStore
    from aether.opportunities import OpportunityIntelligenceEngine, SQLiteOpportunityStore
    from aether_gateway.experiments import ReversibleExperimentRunner
    from aether_gateway.opportunities import AutonomousOpportunityScout, SourceCapabilityMesh, StaticCatalogAdapter

    async def scenario() -> dict:
        opportunity_store = SQLiteOpportunityStore(home / "opportunities" / "opportunity-intelligence.sqlite3")
        opportunity_engine = OpportunityIntelligenceEngine(
            opportunity_store, event_bus=EventBus(home / "events" / "opportunity-intelligence.jsonl")
        )
        mesh = SourceCapabilityMesh()
        fixtures = {
            "operators": (("https://evidence.example/operators", "Operator demand", "Independent operators report recurring workflow friction and interest in a private automation proof."),),
            "market": (("https://evidence.example/market", "Market demand", "A separate market source reports demand for reversible workflow prototypes before production purchase."),),
        }
        for suffix, documents in fixtures.items():
            adapter = StaticCatalogAdapter(SourceAdapterManifest(
                source_id=f"source.demo.{suffix}", adapter_id=f"source.adapter.demo.{suffix}", name=f"Demo {suffix}",
                kind=SourceKind.CATALOG,
                capabilities=(SourceCapability.SEARCH, SourceCapability.FETCH, SourceCapability.CATALOG),
                forbidden_capabilities=("credential-export", "external-write"),
            ), documents)
            mesh.register(adapter)
            opportunity_engine.register_source(adapter.manifest)
        receipt = await AutonomousOpportunityScout(mesh, opportunity_engine).run(ScoutQuery(
            objective="private workflow prototype demand", queries=("workflow prototype",),
            source_kinds=(SourceKind.CATALOG,), maximum_sources=2, maximum_snapshots=4,
            autonomy_level=AutonomyLevel.OBSERVE,
        ))
        candidate = opportunity_engine.synthesize_candidate(
            title="Private workflow validation prototype",
            problem_statement="Small operators repeat a costly coordination workflow.",
            beneficiary="Small service operators",
            value_proposition="A private reversible prototype tests clarity and workflow fit.",
            revenue_hypothesis="Measured interest may support a paid implementation after validation.",
            category="operations-automation", claim_ids=receipt.claim_ids,
            assumptions=("The private prototype represents the core workflow problem.",),
            expected_upside_usd=500.0, probability_success=0.6, estimated_cost_usd=20.0,
            estimated_duration_hours=2.0, risk="low", strategic_alignment=0.9,
            reversibility=0.95, time_to_validation=0.9, legal_risk_penalty=0.05,
            platform_dependency_penalty=0.05, saturation_penalty=0.1,
            strategy_tags=("reversible-experiment", "human-value"),
        )
        opportunity_engine.decide(
            candidate.candidate_id, decision=PortfolioDecisionType.SELECT, principal="founder",
            reason="Two independent sources support a private reversible validation experiment.",
            allocated_budget_usd=20.0, channel="cli",
        )
        mandate = opportunity_engine.issue_mandate(
            candidate.candidate_id, principal="founder", autonomy_level=AutonomyLevel.SANDBOX_EXPERIMENT,
            allowed_capabilities=("prototype.build", "prototype.verify", "preview.private", "demand.measure"),
            maximum_cost_usd=15.0, maximum_external_actions=0, maximum_duration_seconds=3600,
            reason="Build, validate, and privately preview one reversible prototype without external consequences.",
        )
        experiment_store = SQLiteExperimentStore(home / "experiments" / "reversible-experiments.sqlite3")
        experiment_engine = ReversibleExperimentEngine(experiment_store, opportunity_store)
        plan = experiment_engine.create_plan(ReversibleExperimentPlan(
            candidate_id=candidate.candidate_id, mandate_id=mandate.mandate_id,
            objective="Build a private demand-validation landing page.",
            hypothesis="A concise workflow value proposition is understandable to the target operator.",
            success_metrics=("prototype passes deterministic validation", "private measurement surface is ready"),
            stop_conditions=("validation fails", "budget is exhausted", "external action is requested"),
            maximum_cost_usd=5.0, maximum_duration_seconds=300,
            steps=(
                ExperimentStep(
                    name="Build prototype", kind=ExperimentStepKind.WRITE_ARTIFACT,
                    capability="prototype.build", estimated_cost_usd=1.0,
                    payload={"files": {
                        "index.html": "<!doctype html><html><head><title>Aether Workflow Proof</title></head><body><main><h1>Reduce repetitive coordination</h1><p>Private validation prototype.</p><button id='cta'>Request validation</button><script src='app.js'></script></main></body></html>",
                        "app.js": "document.getElementById('cta').addEventListener('click',()=>console.log('synthetic-demo-only'));",
                    }},
                ),
                ExperimentStep(
                    name="Validate prototype", kind=ExperimentStepKind.VERIFY_ARTIFACT,
                    capability="prototype.verify", estimated_cost_usd=1.0,
                    payload={"required_files": ["index.html", "app.js"], "contains": {"index.html": ["Aether Workflow Proof", "Request validation"]}},
                ),
                ExperimentStep(
                    name="Create private preview", kind=ExperimentStepKind.PRIVATE_PREVIEW,
                    capability="preview.private", payload={"index_file": "index.html", "ttl_seconds": 3600},
                ),
                ExperimentStep(
                    name="Prepare measurement", kind=ExperimentStepKind.MEASURE_DEMAND,
                    capability="demand.measure", payload={},
                ),
            ),
            metadata={"demo_only": True, "real_market_demand": False},
        ))
        runner = ReversibleExperimentRunner(home / "experiments", experiment_engine)
        run, token = await runner.run(plan.plan_id)
        synthetic = experiment_engine.record_demand_signal(DemandSignal(
            run_id=run.run_id, kind=DemandSignalKind.SYNTHETIC, state=DemandEvidenceState.SYNTHETIC,
            quantity=12, unit="simulated-events", measured_at=run.completed_at, source="deterministic-demo",
            external_reference=None, metadata={"demo_only": True, "real_demand": False},
        ))
        return {
            "status": run.status.value,
            "candidate_id": candidate.candidate_id,
            "mandate_id": mandate.mandate_id,
            "plan_id": plan.plan_id,
            "run_id": run.run_id,
            "workspace": run.workspace_path,
            "artifact_count": len(run.artifact_ids),
            "cost_usd": run.cost_usd,
            "private_preview": {
                "preview_id": run.preview_id,
                "token": token,
                "local_path": str(runner.resolve_preview_file(run.preview_id, token)) if run.preview_id and token else None,
                "publicly_deployed": False,
            },
            "synthetic_signal": {"signal_id": synthetic.signal_id, "quantity": synthetic.quantity, "state": synthetic.state.value},
            "measured_demand": 0,
            "verified_demand": 0,
            "real_revenue_claimed": False,
            "store": experiment_store.status(),
        }

    _json(asyncio.run(scenario()))
    return 0


def command_experiment_status(args: argparse.Namespace) -> int:
    home = _set_home(args.home)
    from aether.contracts import demand_signal_payload, experiment_plan_payload, experiment_run_payload
    from aether.experiments import SQLiteExperimentStore
    from aether.web_intelligence import SQLiteWebIntelligenceStore
    web = SQLiteWebIntelligenceStore(home / "web-intelligence" / "live-web-intelligence.sqlite3")
    experiments = SQLiteExperimentStore(home / "experiments" / "reversible-experiments.sqlite3")
    _json({
        "web": {
            "status": web.status(),
            "sources": [item.adapter_id for item in web.configurations()],
            "freshness": web.freshness_records(limit=args.limit),
            "discoveries": [item.candidate_id for item in web.discoveries(limit=args.limit)],
        },
        "experiments": {
            "status": experiments.status(),
            "plans": [experiment_plan_payload(item) for item in experiments.plans(limit=args.limit)],
            "runs": [experiment_run_payload(item) for item in experiments.runs(limit=args.limit)],
            "signals": [demand_signal_payload(item) for item in experiments.signals(limit=args.limit)],
        },
    })
    return 0


def command_verify(args: argparse.Namespace) -> int:
    home = _set_home(args.home or tempfile.mkdtemp(prefix="aether-verify-"))
    from aether.bootstrap import validate_bootstrap_policy
    from aether.actions import PendingActionStore
    from aether.contracts import (
        AETHER_CODING_STREAM_PROTOCOL, ActionProposal, ActionTarget, CapabilityRequirement, CapabilityRouteStatus, CodingTask, EventType, FleetJobKind, RuntimeDriverImplementation, RuntimeDriverManifest,
        EvolutionTargetType, KnowledgeProposalStatus, MemoryQuery, RuntimeCommand,
        SkillLifecycleStatus, SkillTriggerType, MissionLane, MissionStatus,
        AutonomyLevel, OpportunityStatus, PortfolioPolicy, SourceKind,
        FreshnessState, ExperimentStatus, ExperimentStepKind, BrowserSenseCapability, BrowserSenseSessionState,
    )
    from aether.dna.loader import DNALoader

    bootstrap = validate_bootstrap_policy(
        ROOT / "aether-core" / "src" / "aether" / "bootstrap" / "bootstrap.yaml"
    )
    checks = {
        "dna_integrity": DNALoader().verify_integrity(),
        "bootstrap_policy": bootstrap.passed,
        "contracts_import": RuntimeCommand(command="health").command == "health",
        "event_contract": str(EventType.ACTION_COMPLETED) == "action.completed",
        "action_contract": ActionProposal(target=ActionTarget.TOOL, operation="read", reason="verify").operation == "read",
        "action_policy": (ROOT / "aether-core" / "src" / "aether" / "governance" / "action_policy.yaml").exists(),
        "approval_store": PendingActionStore(home / "governance" / "verify-approvals.sqlite3").path.exists(),
        "approval_api_module": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "approvals" / "coordinator.py").exists(),
        "memory_policy": (ROOT / "aether-core" / "src" / "aether" / "memory" / "memory_fabric.yaml").exists(),
        "memory_contract": MemoryQuery("verify").text == "verify",
        "knowledge_policy": (ROOT / "aether-core" / "src" / "aether" / "knowledge" / "knowledge_promotion.yaml").exists(),
        "knowledge_contract": KnowledgeProposalStatus.PROPOSED.value == "proposed",
        "evolution_policy": (ROOT / "aether-core" / "src" / "aether" / "evolution" / "internal_evolution.yaml").exists(),
        "evolution_contract": EvolutionTargetType.CODE.value == "code",
        "evolution_store": __import__("aether.evolution", fromlist=["SQLiteEvolutionStore"]).SQLiteEvolutionStore(home / "evolution" / "verify.sqlite3").path.exists(),
        "evolution_sandbox_adapter": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "evolution" / "local.py").exists(),
        "skill_policy": (ROOT / "aether-core" / "src" / "aether" / "skills" / "skill_factory.yaml").exists(),
        "skill_contract": SkillTriggerType.REPEATED_SUCCESS.value == "repeated-success" and SkillLifecycleStatus.ARCHIVED.value == "archived",
        "skill_store": __import__("aether.skills", fromlist=["SQLiteSkillStore"]).SQLiteSkillStore(home / "skills" / "verify.sqlite3").path.exists(),
        "skill_sandbox_adapter": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "skills" / "local.py").exists(),
        "capability_router_policy": (ROOT / "aether-core" / "src" / "aether" / "capabilities" / "capability_router.yaml").exists(),
        "capability_contract": CapabilityRequirement("verify").capability == "verify" and CapabilityRouteStatus.COMPLETED.value == "completed",
        "capability_router_core": (ROOT / "aether-core" / "src" / "aether" / "capabilities" / "router.py").exists(),
        "runtime_skill_projection_adapter": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "skills" / "runtime.py").exists(),
        "runtime_adapter_sdk_policy": (ROOT / "aether-core" / "src" / "aether" / "runtimes" / "runtime_adapter_sdk.yaml").exists(),
        "coding_runtime_contract": CodingTask("verify", "workspace", "session").objective == "verify",
        "runtime_adapter_registry": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_sdk" / "registry.py").exists(),
        "first_coding_runtime_body": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_sdk" / "local_coding.py").exists(),
        "external_runtime_protocol_policy": (ROOT / "aether-core" / "src" / "aether" / "runtimes" / "external_runtime_protocol.yaml").exists(),
        "external_runtime_protocol_contract": AETHER_CODING_STREAM_PROTOCOL == "aether.coding-jsonl.v1",
        "external_runtime_adapter": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_sdk" / "external_stream.py").exists(),
        "reference_external_runtime": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_sdk" / "reference_external_runtime.py").exists(),
        "runtime_driver_pack_policy": (ROOT / "aether-core" / "src" / "aether" / "runtimes" / "runtime_driver_pack.yaml").exists(),
        "runtime_driver_contract": RuntimeDriverManifest(
            "verify-driver", "Verify", "Aether", RuntimeDriverImplementation.PLANNED,
            AETHER_CODING_STREAM_PROTOCOL, "runtime://verify", "runtime.verify", (), (), (), (), (), ("linux",),
        ).driver_id == "verify-driver",
        "codex_live_driver": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_drivers" / "codex_cli.py").exists(),
        "opencode_live_driver": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_drivers" / "opencode_cli.py").exists(),
        "gemini_live_driver": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_drivers" / "gemini_cli.py").exists(),
        "claude_live_driver": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_drivers" / "claude_code.py").exists(),
        "runtime_operations_console": "runtime-operations/console" in (ROOT / "aether-gateway" / "src" / "aether_gateway" / "api" / "server.py").read_text(encoding="utf-8"),
        "fleet_operations_policy": (ROOT / "aether-core" / "src" / "aether" / "runtimes" / "runtime_fleet_operations.yaml").exists(),
        "fleet_operations_contract": FleetJobKind.HEALTH_PROBE.value == "health-probe",
        "fleet_operations_store": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_operations" / "store.py").exists(),
        "fleet_operations_service": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_operations" / "service.py").exists(),
        "fleet_operations_scheduler": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_operations" / "scheduler.py").exists(),
        "native_console_assets": all((ROOT / "aether-gateway" / "src" / "aether_gateway" / "aionui_runtime_console" / name).exists() for name in ("index.html", "app.js", "styles.css", "manifest.json")),
        "aionui_integration_pack": (ROOT / "aionui-integration" / "packages" / "desktop" / "src" / "renderer" / "pages" / "runtime-operations" / "index.tsx").exists(),
        "fleet_api_routes": "/api/runtime-fleet/console" in (ROOT / "aether-gateway" / "src" / "aether_gateway" / "api" / "server.py").read_text(encoding="utf-8"),
        "mission_policy": (ROOT / "aether-core" / "src" / "aether" / "missions" / "mission_orchestrator.yaml").exists(),
        "mission_contract": MissionLane.EXTERNAL_VALUE.value == "external-value" and MissionStatus.WAITING_APPROVAL.value == "waiting-approval",
        "mission_store": __import__("aether.missions", fromlist=["SQLiteMissionStore"]).SQLiteMissionStore(home / "missions" / "verify.sqlite3").path.exists(),
        "mission_gateway_adapter": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "missions" / "execution.py").exists(),
        "mission_console_assets": all((ROOT / "aether-gateway" / "src" / "aether_gateway" / "aionui_mission_console" / name).exists() for name in ("index.html", "app.js", "styles.css", "manifest.json")),
        "native_mission_console": all((ROOT / "aionui-integration" / path).exists() for path in (
            "packages/desktop/src/renderer/pages/mission-operations/index.tsx",
            "packages/desktop/src/process/services/aetherMission/AetherMissionService.ts",
            "packages/desktop/src/process/bridge/aetherMissionBridge.ts",
        )),
        "mission_api_routes": "/api/mission-operations/console" in (ROOT / "aether-gateway" / "src" / "aether_gateway" / "api" / "server.py").read_text(encoding="utf-8"),
        "opportunity_policy": (ROOT / "aether-core" / "src" / "aether" / "opportunities" / "opportunity_intelligence.yaml").exists(),
        "opportunity_contract": AutonomyLevel.OBSERVE.value == "observe" and OpportunityStatus.PORTFOLIO_READY.value == "portfolio-ready" and SourceKind.CATALOG.value == "catalog",
        "opportunity_store": __import__("aether.opportunities", fromlist=["SQLiteOpportunityStore"]).SQLiteOpportunityStore(home / "opportunities" / "verify.sqlite3").path.exists(),
        "portfolio_policy": PortfolioPolicy().minimum_independent_sources == 2,
        "opportunity_gateway": all((ROOT / "aether-gateway" / "src" / "aether_gateway" / "opportunities" / name).exists() for name in ("adapters.py", "scout.py", "mission_bridge.py")),
        "crawl4ai_restricted_adapter": "Crawl4AIRestrictedAdapter" in (ROOT / "aether-gateway" / "src" / "aether_gateway" / "opportunities" / "adapters.py").read_text(encoding="utf-8"),
        "opportunity_console_assets": all((ROOT / "aether-gateway" / "src" / "aether_gateway" / "aionui_opportunity_console" / name).exists() for name in ("index.html", "app.js", "styles.css", "manifest.json")),
        "native_opportunity_console": all((ROOT / "aionui-integration" / path).exists() for path in (
            "packages/desktop/src/renderer/pages/opportunity-intelligence/index.tsx",
            "packages/desktop/src/process/services/aetherOpportunity/AetherOpportunityService.ts",
            "packages/desktop/src/process/bridge/aetherOpportunityBridge.ts",
        )),
        "opportunity_api_routes": "/api/opportunity-intelligence/console" in (ROOT / "aether-gateway" / "src" / "aether_gateway" / "api" / "server.py").read_text(encoding="utf-8"),
        "live_web_policy": (ROOT / "aether-core" / "src" / "aether" / "web_intelligence" / "live_web_intelligence.yaml").exists(),
        "live_web_contract": FreshnessState.STALE.value == "stale",
        "live_web_store": __import__("aether.web_intelligence", fromlist=["SQLiteWebIntelligenceStore"]).SQLiteWebIntelligenceStore(home / "web-intelligence" / "verify.sqlite3").path.exists(),
        "source_conformance_service": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "web_intelligence" / "live.py").exists(),
        "reversible_experiment_policy": (ROOT / "aether-core" / "src" / "aether" / "experiments" / "reversible_experiments.yaml").exists(),
        "reversible_experiment_contract": ExperimentStatus.PREVIEW_READY.value == "preview-ready" and ExperimentStepKind.PRIVATE_PREVIEW.value == "private-preview",
        "experiment_store": __import__("aether.experiments", fromlist=["SQLiteExperimentStore"]).SQLiteExperimentStore(home / "experiments" / "verify.sqlite3").path.exists(),
        "experiment_runner": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "experiments" / "runner.py").exists(),
        "experiment_console_assets": all((ROOT / "aether-gateway" / "src" / "aether_gateway" / "aionui_experiment_console" / name).exists() for name in ("index.html", "app.js", "styles.css", "manifest.json")),
        "native_experiment_console": all((ROOT / "aionui-integration" / path).exists() for path in (
            "packages/desktop/src/renderer/pages/live-web-experiments/index.tsx",
            "packages/desktop/src/process/services/aetherExperiment/AetherExperimentService.ts",
            "packages/desktop/src/process/bridge/aetherExperimentBridge.ts",
        )),
        "experiment_api_routes": "/api/experiments/console" in (ROOT / "aether-gateway" / "src" / "aether_gateway" / "api" / "server.py").read_text(encoding="utf-8"),
        "browser_senses_policy": (ROOT / "aether-core" / "src" / "aether" / "browser_senses" / "browser_senses.yaml").exists(),
        "browser_senses_contract": BrowserSenseCapability.CAMERA.value == "camera" and BrowserSenseSessionState.ACTIVE.value == "active",
        "browser_senses_store": (ROOT / "aether-core" / "src" / "aether" / "browser_senses" / "store.py").exists(),
        "browser_senses_gateway": all((ROOT / "aether-gateway" / "src" / "aether_gateway" / "browser_senses" / name).exists() for name in ("service.py", "worker.py")),
        "browser_senses_console": all((ROOT / "aether-gateway" / "src" / "aether_gateway" / "aionui_senses_console" / name).exists() for name in ("index.html", "app.js", "styles.css", "manifest.json")),
        "browser_senses_api": "/api/browser-senses/session" in (ROOT / "aether-gateway" / "src" / "aether_gateway" / "api" / "server.py").read_text(encoding="utf-8"),
        "native_unified_senses": (ROOT / "aionui-integration" / "packages" / "desktop" / "src" / "renderer" / "pages" / "unified-senses" / "index.tsx").exists(),
        "sidecar_supervisor": (ROOT / "scripts" / "aether_sidecar.py").exists(),
        "one_domain_caddy": (ROOT / "deploy" / "caddy" / "Caddyfile").exists(),
        "docker_compose_deployment": (ROOT / "deploy" / "docker-compose.yml").exists(),
        "systemd_deployment": all((ROOT / "deploy" / "systemd" / name).exists() for name in ("aether-gateway.service", "aether-sense-worker.service", "aionui-web.service")),
        "runtime_conformance_ledger": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_drivers" / "conformance.py").exists(),
        "runtime_driver_pack": (ROOT / "aether-gateway" / "src" / "aether_gateway" / "runtime_drivers" / "pack.py").exists(),
        "direct_skill_execution_hidden": "direct_skill_execution_exposed_to_models: false" in (ROOT / "aether-core" / "src" / "aether" / "capabilities" / "capability_router.yaml").read_text(encoding="utf-8"),
        "legacy_direct_promotion_disabled": "Direct KnowledgeLifecycle promotion is disabled" in (ROOT / "aether-core" / "src" / "aether" / "knowledge" / "lifecycle.py").read_text(encoding="utf-8"),
        "legacy_runtime_manager_removed": not (ROOT / "aether-core" / "src" / "aether" / "router" / "runtime.py").exists(),
        "provider_config_outside_core": not (ROOT / "aether-core" / "configs" / "llm_providers.yaml").exists(),
        "legacy_resource_router_removed": not (ROOT / "aether-core" / "src" / "aether" / "router" / "resource.py").exists(),
        "python_compile": all(
            compileall.compile_dir(str(path), quiet=1)
            for path in (ROOT / "aether-core" / "src", ROOT / "aether-tools" / "src", ROOT / "aether-gateway" / "src")
        ),
        "aether_home": str(home),
    }
    failed = [name for name, result in checks.items() if result is False]

    if args.tests:
        output_path = home / "test-suites" / "summary.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_release_tests.py"), "--output", str(output_path)],
            cwd=str(ROOT), check=False,
        )
        suite_summary = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else {"ok": False}
        checks["test_suites"] = suite_summary
        checks["tests"] = completed.returncode == 0 and bool(suite_summary.get("ok"))
        if not checks["tests"]:
            failed.append("tests")

    _json(checks)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aether", description="Aether OS v0.19.2 founder bring-up CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, handler in (
        ("boot", command_boot),
        ("identity", command_identity),
        ("bootstrap-check", command_bootstrap_check),
        ("verify", command_verify),
    ):
        command = sub.add_parser(name)
        command.add_argument("--home", help="Override AETHER_HOME")
        if name == "verify":
            command.add_argument("--tests", action="store_true", help="Run pytest suites")
        command.set_defaults(handler=handler)

    cognitive_demo = sub.add_parser("cognitive-demo", help="Verify the provider-neutral cognitive gateway offline")
    cognitive_demo.add_argument("--home")
    cognitive_demo.add_argument("--text", required=True)
    cognitive_demo.add_argument("--session", default="cli:demo")
    cognitive_demo.set_defaults(handler=command_cognitive_demo)

    chat = sub.add_parser("chat", help="Send one live turn through the configured model provider")
    chat.add_argument("--home")
    chat.add_argument("--text", required=True)
    chat.add_argument("--session", default="cli:live")
    chat.add_argument("--model", help="Optional provider/model route")
    chat.set_defaults(handler=command_chat)

    sense_demo = sub.add_parser("sense-demo", help="Run one voice transcript through cognition and expression")
    sense_demo.add_argument("--home")
    sense_demo.add_argument("--text", required=True)
    sense_demo.add_argument("--source", default="cli-microphone")
    sense_demo.add_argument("--language", default="id")
    sense_demo.set_defaults(handler=command_sense_demo)

    browser_sense_demo = sub.add_parser("browser-sense-demo", help="Issue a bounded browser session and run one offline text turn")
    browser_sense_demo.add_argument("--home")
    browser_sense_demo.add_argument("--text", default="Aether browser senses first pulse")
    browser_sense_demo.set_defaults(handler=command_browser_sense_demo)

    senses_status = sub.add_parser("senses-status", help="Inspect browser media and LiveKit worker readiness")
    senses_status.add_argument("--home")
    senses_status.add_argument("--gateway", default="http://127.0.0.1:8000")
    senses_status.set_defaults(handler=command_senses_status)

    telegram_demo = sub.add_parser("telegram-demo", help="Run Telegram text through the canonical sense path offline")
    telegram_demo.add_argument("--home")
    telegram_demo.add_argument("--text", required=True)
    telegram_demo.add_argument("--chat-id", type=int, default=1001)
    telegram_demo.add_argument("--user-id", type=int, default=1001)
    telegram_demo.add_argument("--language", default="id")
    telegram_demo.set_defaults(handler=command_telegram_demo)

    action_demo = sub.add_parser("action-demo", help="Run a governed tool or runtime action through cognition")
    action_demo.add_argument("--home")
    action_demo.add_argument("--mode", choices=["tool", "runtime"], default="tool")
    action_demo.set_defaults(handler=command_action_demo)

    approval_demo = sub.add_parser("approval-demo", help="Run a pending approval through trusted exact-once resumption")
    approval_demo.add_argument("--home")
    approval_demo.set_defaults(handler=command_approval_demo)

    memory_demo = sub.add_parser("memory-demo", help="Verify durable sessions, retrieval, rebuild, and Obsidian projection")
    memory_demo.add_argument("--home")
    memory_demo.set_defaults(handler=command_memory_demo)

    memory_rebuild = sub.add_parser("memory-rebuild", help="Rebuild the retrieval projection from canonical memory")
    memory_rebuild.add_argument("--home")
    memory_rebuild.set_defaults(handler=command_memory_rebuild)

    memory_project = sub.add_parser("memory-project", help="Project one session into the Obsidian vault")
    memory_project.add_argument("--home")
    memory_project.add_argument("--session", required=True)
    memory_project.set_defaults(handler=command_memory_project)

    knowledge_demo = sub.add_parser("knowledge-demo", help="Verify evidence-backed curation, governance, and promotion")
    knowledge_demo.add_argument("--home")
    knowledge_demo.set_defaults(handler=command_knowledge_demo)

    knowledge_curate = sub.add_parser("knowledge-curate", help="Create proposals from explicitly marked canonical candidates")
    knowledge_curate.add_argument("--home")
    knowledge_curate.add_argument("--limit", type=int, default=500)
    knowledge_curate.set_defaults(handler=command_knowledge_curate)

    evolution_demo = sub.add_parser("evolution-demo", help="Run one governed internal evolution iteration end-to-end")
    evolution_demo.add_argument("--home")
    evolution_demo.set_defaults(handler=command_evolution_demo)

    evolution_status = sub.add_parser("evolution-status", help="Inspect durable internal evolution triggers and lineage")
    evolution_status.add_argument("--home")
    evolution_status.add_argument("--workspace", help="Configured evolution workspace")
    evolution_status.set_defaults(handler=command_evolution_status)

    skill_demo = sub.add_parser("skill-demo", help="Run one governed skill lifecycle end-to-end")
    skill_demo.add_argument("--home")
    skill_demo.set_defaults(handler=command_skill_demo)

    skill_status = sub.add_parser("skill-status", help="Inspect skill candidates, registry, telemetry, and lifecycle")
    skill_status.add_argument("--home")
    skill_status.add_argument("--workspace", help="Configured skill benchmark workspace")
    skill_status.set_defaults(handler=command_skill_status)

    runtime_demo = sub.add_parser("runtime-demo", help="Run the first governed coding runtime body end-to-end")
    runtime_demo.add_argument("--home")
    runtime_demo.set_defaults(handler=command_runtime_demo)

    external_runtime_demo = sub.add_parser("external-runtime-demo", help="Run the governed external JSONL coding runtime end-to-end")
    external_runtime_demo.add_argument("--home")
    external_runtime_demo.set_defaults(handler=command_external_runtime_demo)

    driver_status = sub.add_parser("driver-status", help="Inspect the runtime driver pack and installed CLI availability")
    driver_status.add_argument("--home")
    driver_status.set_defaults(handler=command_driver_status)

    codex_live_demo = sub.add_parser("codex-live-demo", help="Run a live governed Codex CLI task when Codex is installed and authenticated")
    codex_live_demo.add_argument("--home")
    codex_live_demo.set_defaults(handler=command_codex_live_demo)

    opencode_live_demo = sub.add_parser("opencode-live-demo", help="Run a live governed OpenCode task when the CLI and key file are configured")
    opencode_live_demo.add_argument("--home")
    opencode_live_demo.set_defaults(handler=command_opencode_live_demo)

    gemini_live_demo = sub.add_parser("gemini-live-demo", help="Run a live governed Gemini CLI task when the CLI and credential file are configured")
    gemini_live_demo.add_argument("--home")
    gemini_live_demo.set_defaults(handler=command_gemini_live_demo)

    claude_live_demo = sub.add_parser("claude-live-demo", help="Run a live governed Claude Code task when the CLI and authentication are configured")
    claude_live_demo.add_argument("--home")
    claude_live_demo.set_defaults(handler=command_claude_live_demo)

    runtime_operations = sub.add_parser("runtime-operations", help="Inspect driver health, conformance, quota, and reliability evidence")
    runtime_operations.add_argument("--home")
    runtime_operations.add_argument("--renew-due", action="store_true")
    runtime_operations.add_argument("--ttl-hours", type=int, default=24)
    runtime_operations.set_defaults(handler=command_runtime_operations)

    fleet_operations = sub.add_parser("fleet-operations", help="Inspect scheduled fleet jobs, budgets, incidents, and driver readiness")
    fleet_operations.add_argument("--home")
    fleet_operations.add_argument("--renew-due", action="store_true")
    fleet_operations.add_argument("--ttl-hours", type=int, default=24)
    fleet_operations.set_defaults(handler=command_fleet_operations)

    fleet_run = sub.add_parser("fleet-run", help="Run one backend-owned fleet operation immediately")
    fleet_run.add_argument("--home")
    fleet_run.add_argument("--job", required=True, choices=["health-probe", "receipt-renewal", "budget-evaluation", "incident-sweep"])
    fleet_run.set_defaults(handler=command_fleet_run)

    aionui_console = sub.add_parser("aionui-console", help="Print the embedded console URL and native AionUi integration paths")
    aionui_console.add_argument("--gateway", default="http://127.0.0.1:8000")
    aionui_console.set_defaults(handler=command_aionui_console)

    driver_conformance = sub.add_parser("driver-conformance", help="Issue a versioned conformance receipt for an installed runtime driver")
    driver_conformance.add_argument("--home")
    driver_conformance.add_argument("--driver", required=True)
    driver_conformance.add_argument("--ttl-hours", type=int, default=24)
    driver_conformance.set_defaults(handler=command_driver_conformance)

    mission_demo = sub.add_parser("mission-demo", help="Run one Northstar-bounded mission through plan approval, action approval, and outcome evidence")
    mission_demo.add_argument("--home")
    mission_demo.set_defaults(handler=command_mission_demo)

    mission_status = sub.add_parser("mission-status", help="Inspect opportunity briefs, mission state, attempts, and value evidence")
    mission_status.add_argument("--home")
    mission_status.add_argument("--limit", type=int, default=100)
    mission_status.set_defaults(handler=command_mission_status)

    opportunity_demo = sub.add_parser("opportunity-demo", help="Run autonomous source discovery, portfolio selection, bounded mandate, and mission conversion")
    opportunity_demo.add_argument("--home")
    opportunity_demo.set_defaults(handler=command_opportunity_demo)

    opportunity_status = sub.add_parser("opportunity-status", help="Inspect source mesh, scout runs, candidates, decisions, and mandates")
    opportunity_status.add_argument("--home")
    opportunity_status.add_argument("--limit", type=int, default=100)
    opportunity_status.set_defaults(handler=command_opportunity_status)

    experiment_demo = sub.add_parser("experiment-demo", help="Build, verify, and privately preview one mandate-bound reversible experiment")
    experiment_demo.add_argument("--home")
    experiment_demo.set_defaults(handler=command_experiment_demo)

    experiment_status = sub.add_parser("experiment-status", help="Inspect live source evidence and reversible experiment ledgers")
    experiment_status.add_argument("--home")
    experiment_status.add_argument("--limit", type=int, default=100)
    experiment_status.set_defaults(handler=command_experiment_status)

    capability_demo = sub.add_parser("capability-demo", help="Route and execute one active Aether skill end-to-end")
    capability_demo.add_argument("--home")
    capability_demo.add_argument("--name", default="Aether")
    capability_demo.set_defaults(handler=command_capability_demo)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
