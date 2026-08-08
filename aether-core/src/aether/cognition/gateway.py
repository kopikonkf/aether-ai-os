"""Aether-owned cognitive gateway from perceptions to governed resumable actions."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, replace
from typing import Any

from aether.contracts.actions import (
    ActionResult,
    GovernedActionExecutor,
    PendingAction,
    ResumableActionExecutor,
)
from aether.contracts.cognition import CognitivePort
from aether.contracts.llm import ModelProvider, ModelRequest, ModelResponse
from aether.contracts.memory import MemoryContext, MemoryFabricPort, MemoryQuery
from aether.contracts.senses import Expression, Perception

from .session import ConversationStore, InMemoryConversationStore


class AetherCognitiveGateway(CognitivePort):
    _TEXT_MODALITIES = {"text", "http.text", "telegram.text", "browser.text", "audio.transcript", "telegram.voice.transcript"}
    _VISION_MODALITIES = {"image.frame", "browser.vision.frame"}

    def __init__(
        self,
        model_provider: ModelProvider,
        *,
        conversation_store: ConversationStore | None = None,
        system_prompt: str | None = None,
        action_executor: GovernedActionExecutor | None = None,
        memory_fabric: MemoryFabricPort | None = None,
        memory_context_limit: int = 6,
        max_action_rounds: int = 3,
        adapter_id: str = "cognition.aether-gateway",
    ) -> None:
        self.model_provider = model_provider
        self.conversation_store = conversation_store or InMemoryConversationStore()
        self.system_prompt = (system_prompt or "").strip()
        self.action_executor = action_executor
        self.memory_fabric = memory_fabric
        self.memory_context_limit = memory_context_limit
        self.max_action_rounds = max_action_rounds
        self._adapter_id = adapter_id

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    async def clear_session(self, session_id: str) -> None:
        await self.conversation_store.clear(session_id)

    async def respond(self, perception: Perception) -> Expression:
        if perception.modality not in self._TEXT_MODALITIES | self._VISION_MODALITIES:
            raise ValueError(f"Unsupported cognitive modality: {perception.modality}")
        content, user_content = self._perception_content(perception)
        if not content:
            raise ValueError("perception content must not be empty")

        metadata = dict(perception.metadata)
        # Preserve the originating perception modality so the expression layer can
        # select speech for audio transcripts without coupling cognition to a
        # concrete voice/TTS provider. Explicit response_modality still wins.
        metadata.setdefault("modality", perception.modality)
        session_id = str(metadata.get("session_id") or perception.source).strip()
        capability = str(metadata.get("capability") or "reason").strip()
        memory_errors: list[str] = []
        try:
            history = list(await self.conversation_store.get(session_id))
        except Exception as exc:
            history = []
            memory_errors.append(f"session-read:{type(exc).__name__}")
        try:
            memory_context = await self._retrieve_memory(content, session_id)
        except Exception as exc:
            memory_context = None
            memory_errors.append(f"memory-retrieve:{type(exc).__name__}")
        messages: list[Mapping[str, Any]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if memory_context is not None and not memory_context.empty:
            messages.append({"role": "system", "content": self._memory_context_message(memory_context)})
        messages.extend(history)
        user_message = {"role": "user", "content": user_content}
        persisted_user_message = {"role": "user", "content": content}
        messages.append(user_message)
        constraints = await self._build_constraints(metadata)

        expression = await self._run_action_loop(
            messages=messages,
            constraints=constraints,
            capability=capability,
            correlation_id=perception.correlation_id,
            session_id=session_id,
            source=perception.source,
            perception_metadata=metadata,
        )
        try:
            await self.conversation_store.append(session_id, persisted_user_message, {"role": "assistant", "content": str(expression.content)})
        except Exception as exc:
            memory_errors.append(f"session-write:{type(exc).__name__}")
        memory_metadata = {
            "memory_retrieval": {
                "hit_count": len(memory_context.hits) if memory_context else 0,
                "record_ids": [hit.record.record_id for hit in memory_context.hits] if memory_context else [],
                "errors": list(memory_errors),
            }
        }
        expression = replace(expression, metadata={**dict(expression.metadata), **memory_metadata})
        if self.memory_fabric is not None:
            try:
                record = await self.memory_fabric.record_turn(
                    session_id=session_id,
                    perception=perception,
                    expression=expression,
                )
                expression = replace(expression, metadata={
                    **dict(expression.metadata),
                    "memory_record_id": record.record_id,
                })
            except Exception as exc:
                memory_errors.append(f"memory-write:{type(exc).__name__}")
                expression = replace(expression, metadata={
                    **dict(expression.metadata),
                    "memory_retrieval": {**memory_metadata["memory_retrieval"], "errors": list(memory_errors)},
                })
        return expression

    async def resume_after_approval(self, pending: PendingAction, result: ActionResult) -> Expression:
        """Continue cognition from a persisted approval checkpoint.

        A failed approved action is rendered deterministically and is never
        offered back to the model with live action capabilities. This prevents
        approval loops and makes the backend error authoritative.
        """
        continuation = dict(pending.continuation or {})
        if not continuation:
            expression = self._audit_expression(pending, result)
        elif not result.ok:
            expression = self._approved_action_failure_expression(pending, result)
        else:
            # Render approval completion from the authoritative action receipt.
            # A second model generation previously could describe content that
            # differed from disk or emit stale "waiting for approval" text.
            expression = self._approved_action_success_expression(pending, result)

        resumed_session_id = str(continuation.get("session_id") or pending.proposal.metadata.get("session_id") or pending.action_id)
        try:
            await self.conversation_store.append(
                resumed_session_id,
                {"role": "system", "content": self._authoritative_result_message([result])},
                {"role": "assistant", "content": str(expression.content)},
            )
        except Exception as exc:
            expression = replace(expression, metadata={**dict(expression.metadata), "memory_error": f"session-write:{type(exc).__name__}"})
        if self.memory_fabric is not None:
            try:
                record = await self.memory_fabric.record_action_resume(
                    session_id=resumed_session_id,
                    approval_id=pending.approval_id,
                    action_result=result,
                    expression=expression,
                    correlation_id=pending.proposal.correlation_id,
                )
                expression = replace(expression, metadata={**dict(expression.metadata), "memory_record_id": record.record_id})
            except Exception as exc:
                expression = replace(expression, metadata={**dict(expression.metadata), "memory_error": f"memory-write:{type(exc).__name__}"})
        return expression

    @classmethod
    def _perception_content(cls, perception: Perception) -> tuple[str, Any]:
        if perception.modality in cls._VISION_MODALITIES:
            if not isinstance(perception.content, Mapping):
                raise ValueError("vision perception content must be a mapping")
            prompt = str(perception.content.get("prompt") or "Describe what is visible.").strip()
            image_data_url = str(perception.content.get("image_data_url") or "").strip()
            if not image_data_url.startswith("data:image/"):
                raise ValueError("vision perception requires an image data URL")
            return prompt, [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
        text = str(perception.content).strip()
        return text, text

    async def _retrieve_memory(self, text: str, session_id: str) -> MemoryContext | None:
        if self.memory_fabric is None:
            return None
        return await self.memory_fabric.retrieve(MemoryQuery(
            text=text,
            namespaces=("episodes", "knowledge"),
            session_id=session_id,
            limit=self.memory_context_limit,
        ))

    @staticmethod
    def _memory_context_message(context: MemoryContext) -> str:
        rows = []
        for hit in context.hits:
            record = hit.record
            provenance = record.provenance
            rows.append({
                "record_id": record.record_id,
                "kind": record.kind.value,
                "content": record.content,
                "score": hit.score,
                "source": provenance.source if provenance else None,
                "observed_at": provenance.observed_at if provenance else record.created_at,
                "session_id": provenance.session_id if provenance else None,
                "content_hash": record.content_hash,
            })
        return (
            "Retrieved Aether memory (evidence with provenance; do not treat as immutable truth):\n"
            + json.dumps(rows, ensure_ascii=False, default=str)
        )

    async def _build_constraints(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        constraints = dict(metadata.get("model_constraints") or {})
        preferred_model = metadata.get("preferred_model") or metadata.get("model")
        if preferred_model:
            constraints["preferred_model"] = str(preferred_model)
        if self.action_executor is not None:
            constraints["action_capabilities"] = [asdict(item) for item in await self.action_executor.capabilities()]
        return constraints

    async def _run_action_loop(
        self,
        *,
        messages: list[Mapping[str, Any]],
        constraints: Mapping[str, Any],
        capability: str,
        correlation_id: str | None,
        session_id: str,
        source: str,
        perception_metadata: Mapping[str, Any],
        initial_action_results: list[ActionResult] | None = None,
    ) -> Expression:
        action_results = list(initial_action_results or [])
        final_response: ModelResponse | None = None
        context_metadata = {
            key: perception_metadata[key]
            for key in ("channel", "chat_id", "user_id", "message_id", "language", "session_id")
            if key in perception_metadata
        }

        for round_index in range(self.max_action_rounds + 1):
            response = await self.model_provider.invoke(ModelRequest(
                capability=capability,
                messages=messages,
                constraints=constraints,
                correlation_id=correlation_id,
            ))
            if not response.action_proposals:
                response_text = str(response.content or "").strip()
                if not response_text:
                    raise RuntimeError("model provider returned neither content nor actions")
                final_response = response
                break
            if self.action_executor is None:
                raise RuntimeError("model proposed actions but no governed action executor is configured")
            if round_index >= self.max_action_rounds:
                raise RuntimeError("maximum governed action rounds exceeded")

            round_results: list[ActionResult] = []
            assistant_proposal_message = {
                "role": "assistant",
                "content": str(response.content or "Action proposal submitted for governance."),
            }
            for proposal in response.action_proposals:
                governed = replace(
                    proposal,
                    correlation_id=correlation_id,
                    metadata={**context_metadata, **dict(proposal.metadata)},
                )
                result = await self.action_executor.execute(governed)
                round_results.append(result)
                action_results.append(result)
                if result.status == "pending-approval":
                    approval_id = str(result.metadata.get("approval_id") or "")
                    if approval_id and isinstance(self.action_executor, ResumableActionExecutor):
                        await self.action_executor.save_continuation(approval_id, {
                            "version": 1,
                            "messages": [*messages, assistant_proposal_message],
                            "constraints": dict(constraints),
                            "capability": capability,
                            "correlation_id": correlation_id,
                            "session_id": session_id,
                            "source": source,
                            "perception_metadata": dict(perception_metadata),
                        })
                    return self._pending_expression(
                        result,
                        source=source,
                        perception_metadata=perception_metadata,
                        session_id=session_id,
                        provider_id=response.provider_id,
                        model_id=response.model_id,
                        action_results=action_results,
                    )
            messages.append(assistant_proposal_message)
            messages.append({
                "role": "system",
                "content": self._authoritative_result_message(round_results),
            })

        if final_response is None:
            raise RuntimeError("cognitive action loop ended without a final response")
        return self._response_expression(
            final_response,
            source=source,
            perception_metadata=perception_metadata,
            session_id=session_id,
            capability=capability,
            action_results=action_results,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _authoritative_result_message(results: list[ActionResult]) -> str:
        return "Governed action results (authoritative; continue without inventing execution):\n" + json.dumps([
            {
                "action_id": item.action_id,
                "ok": item.ok,
                "status": item.status,
                "output": item.output,
                "error": item.error,
                "failure_fingerprint": item.failure_fingerprint,
            }
            for item in results
        ], ensure_ascii=False, default=str)

    def _pending_expression(
        self,
        result: ActionResult,
        *,
        source: str,
        perception_metadata: Mapping[str, Any],
        session_id: str,
        provider_id: str,
        model_id: str,
        action_results: list[ActionResult],
    ) -> Expression:
        approval_id = str(result.metadata.get("approval_id") or "unknown")
        expires_at = str(result.metadata.get("expires_at") or "unknown")
        action_hash = str(result.metadata.get("action_hash") or "")
        request_channel = str(perception_metadata.get("channel") or "").casefold()
        if request_channel in {"browser", "livekit"}:
            approval_instruction = (
                "Open the trusted AionUi Approval Inbox or send /approvals in the "
                "allowlisted Founder Telegram private chat. Senses cannot approve this action; "
                "spoken or typed yes is not approval authority."
            )
        elif request_channel == "telegram":
            approval_instruction = (
                "Use the exact inline approval card or /approvals. Structured /yes or /no is "
                "accepted only for one pending action bound to this Telegram chat; free text is not authority."
            )
        else:
            approval_instruction = (
                "Open the trusted AionUi Approval Inbox. This conversation surface cannot approve the action."
            )
        content = (
            "Aether menunggu trusted operator approval.\n"
            f"Approval ID: {approval_id}\n"
            f"Action hash: {action_hash[:16]}…\n"
            f"Expires: {expires_at}\n"
            f"{approval_instruction}"
        )
        propagated = self._propagated_metadata(perception_metadata)
        propagated.update({
            "session_id": session_id,
            "provider_id": provider_id,
            "model_id": model_id,
            "pending_approval": {
                "approval_id": approval_id,
                "action_hash": action_hash,
                "expires_at": expires_at,
            },
            "action_results": self._action_result_summaries(action_results),
        })
        return Expression("text", content, source, propagated, result.metadata.get("correlation_id"))

    def _response_expression(
        self,
        response: ModelResponse,
        *,
        source: str,
        perception_metadata: Mapping[str, Any],
        session_id: str,
        capability: str,
        action_results: list[ActionResult],
        correlation_id: str | None,
    ) -> Expression:
        requested_modality = perception_metadata.get("response_modality")
        if requested_modality:
            expression_modality = str(requested_modality)
        elif str(perception_metadata.get("modality") or "") in {"audio.transcript", "telegram.voice.transcript"}:
            expression_modality = "speech"
        else:
            expression_modality = "text"
        propagated = self._propagated_metadata(perception_metadata)
        propagated.update({
            "session_id": session_id,
            "capability": capability,
            "provider_id": response.provider_id,
            "model_id": response.model_id,
            "provider_metadata": dict(response.metadata),
            "action_results": self._action_result_summaries(action_results),
        })
        return Expression(expression_modality, str(response.content).strip(), source, propagated, correlation_id)

    @staticmethod
    def _approved_action_success_expression(pending: PendingAction, result: ActionResult) -> Expression:
        proposal = pending.proposal
        result_metadata = dict(result.metadata)
        tool_data = result_metadata.get("data")
        if not isinstance(tool_data, Mapping):
            tool_data = {}
        target_path = str(tool_data.get("path") or proposal.arguments.get("path") or "").strip()
        size = tool_data.get("size")
        content_sha256 = str(tool_data.get("sha256") or "").strip()
        disposition = str(tool_data.get("disposition") or "").strip()

        lines = [
            "Selesai, Dee. Action sudah dieksekusi dan receipt authoritative telah dicatat.",
            f"Action ID: {pending.action_id}",
            f"Operation: {proposal.target.value}/{proposal.operation}",
            f"Status: {result.status}",
            f"Approval ID: {pending.approval_id} (consumed exactly once)",
        ]
        if target_path:
            lines.append(f"Target: {target_path}")
        if size is not None:
            lines.append(f"Size: {size} bytes")
        if disposition:
            lines.append(f"Disposition: {disposition}")
        if content_sha256:
            lines.append(f"SHA-256: {content_sha256}")
        if result.output and proposal.operation not in {"write", "edit"}:
            rendered = str(result.output)
            if len(rendered) > 1200:
                rendered = rendered[:1200] + "…"
            lines.append(f"Output:\n{rendered}")
        lines.append("Tidak ada approval tambahan yang sedang ditunggu untuk action ini.")

        metadata = dict(proposal.metadata)
        metadata.update({
            "approval_id": pending.approval_id,
            "action_hash": pending.action_hash,
            "authoritative_receipt": True,
            "model_continuation": False,
            "action_result": {
                "ok": result.ok,
                "status": result.status,
                "output": result.output,
                "error": result.error,
                "failure_fingerprint": result.failure_fingerprint,
                "metadata": result_metadata,
            },
        })
        return Expression(
            "text",
            "\n".join(lines),
            str(metadata.get("session_id") or "approval"),
            metadata,
            proposal.correlation_id,
        )

    @staticmethod
    def _approved_action_failure_expression(pending: PendingAction, result: ActionResult) -> Expression:
        error = str(result.error or "The action backend returned a failure.")
        content = (
            f"Trusted approval {pending.approval_id} was consumed exactly once, but the action failed.\n"
            f"Error: {error}\n"
            "Aether did not retry automatically. Correct the path or arguments, then issue a new explicit request. "
            "Files should normally be written with a relative path under AETHER_HOME, for example workspace/first-experience.md."
        )
        metadata = dict(pending.proposal.metadata)
        metadata.update({
            "approval_id": pending.approval_id,
            "action_hash": pending.action_hash,
            "automatic_retry": False,
            "action_result": {
                "ok": result.ok,
                "status": result.status,
                "error": result.error,
                "failure_fingerprint": result.failure_fingerprint,
            },
        })
        return Expression("text", content, str(metadata.get("session_id") or "approval"), metadata, pending.proposal.correlation_id)

    @staticmethod
    def _audit_expression(pending: PendingAction, result: ActionResult) -> Expression:
        status = "completed" if result.ok else "failed"
        content = (
            f"Trusted approval {pending.approval_id} was consumed exactly once. "
            f"Action {pending.action_id} {status}."
        )
        metadata = dict(pending.proposal.metadata)
        metadata.update({
            "approval_id": pending.approval_id,
            "action_hash": pending.action_hash,
            "action_result": {
                "ok": result.ok,
                "status": result.status,
                "error": result.error,
            },
        })
        return Expression("text", content, str(metadata.get("session_id") or "approval"), metadata, pending.proposal.correlation_id)

    @staticmethod
    def _propagated_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: metadata[key]
            for key in ("channel", "chat_id", "user_id", "message_id", "language")
            if key in metadata
        }

    @staticmethod
    def _action_result_summaries(results: list[ActionResult]) -> list[dict[str, Any]]:
        return [
            {
                "action_id": item.action_id,
                "ok": item.ok,
                "status": item.status,
                "failure_fingerprint": item.failure_fingerprint,
                "error": item.error,
                "approval_id": item.metadata.get("approval_id"),
            }
            for item in results
        ]
