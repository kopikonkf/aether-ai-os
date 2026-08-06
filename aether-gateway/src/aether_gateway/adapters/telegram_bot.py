"""Telegram communication adapter routed through the canonical SenseEventPath."""
from __future__ import annotations

import asyncio
import io
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any

try:
    from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
except ModuleNotFoundError:  # direct/offline ingestion remains usable without polling dependency
    Update = Any  # type: ignore[misc,assignment]
    Application = CallbackQueryHandler = CommandHandler = MessageHandler = filters = None  # type: ignore[assignment]
    BotCommand = InlineKeyboardButton = InlineKeyboardMarkup = None  # type: ignore[assignment]
    ContextTypes = Any  # type: ignore[misc,assignment]

from aether.contracts.senses import Expression, Perception, SenseAdapter
from aether.senses import SenseEventPath, SensePathResult
from aether_gateway.approvals import (
    ApprovalCoordinator,
    TelegramApprovalCallbackCodec,
    approval_card_text,
    format_pending,
)
from aether_gateway.adapters.telegram_commands import (
    TelegramCommandRegistry,
    default_telegram_command_registry,
)

log = logging.getLogger(__name__)

TextSender = Callable[[int, str], Awaitable[None]]
VoiceSender = Callable[[int, bytes], Awaitable[None]]
VoiceTranscriber = Callable[[bytes, Mapping[str, Any]], Awaitable[str]]
SpeechRenderer = Callable[[str, str], Awaitable[bytes]]
SessionReset = Callable[[str], Awaitable[None]]


def _should_send_followup(*, approved: bool, replayed: bool, has_expression: bool) -> bool:
    """A proactive follow-up is sent only for a fresh approval that produced a
    cognition Expression. Replays must not duplicate the follow-up message."""
    return approved and not replayed and has_expression


class TelegramSenseAdapter(SenseAdapter):
    """Telegram is a sense/communication surface, never a cognitive runtime."""

    def __init__(
        self,
        sense_path: SenseEventPath,
        *,
        behavior_monitor: Any | None = None,
        text_sender: TextSender | None = None,
        voice_sender: VoiceSender | None = None,
        voice_transcriber: VoiceTranscriber | None = None,
        speech_renderer: SpeechRenderer | None = None,
        session_reset: SessionReset | None = None,
        approval_coordinator: ApprovalCoordinator | None = None,
        command_registry: TelegramCommandRegistry | None = None,
        approval_callback_codec: TelegramApprovalCallbackCodec | None = None,
        token: str | None = None,
        enabled: bool | None = None,
        adapter_id: str = "sense.telegram",
    ) -> None:
        self.sense_path = sense_path
        self.behavior_monitor = behavior_monitor
        self._text_sender = text_sender
        self._voice_sender = voice_sender
        self._voice_transcriber = voice_transcriber
        self._speech_renderer = speech_renderer
        self._session_reset = session_reset
        self._approval_coordinator = approval_coordinator
        self._command_registry = command_registry or default_telegram_command_registry()
        callback_secret = (
            os.environ.get("AETHER_TELEGRAM_CALLBACK_SECRET")
            or os.environ.get("AETHER_OPERATOR_TOKEN")
            or os.environ.get("AUTH_SECRET_KEY")
        )
        self._approval_callback_codec = approval_callback_codec
        if self._approval_callback_codec is None and callback_secret:
            try:
                self._approval_callback_codec = TelegramApprovalCallbackCodec(callback_secret)
            except ValueError:
                log.warning("Telegram one-tap approvals disabled: callback secret is too short")
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.enabled = (
            str(os.environ.get("TELEGRAM_ENABLED", "false")).lower() == "true"
            if enabled is None
            else enabled
        )
        self._adapter_id = adapter_id
        self._queue: asyncio.Queue[Perception] = asyncio.Queue()
        self._bot: Any | None = None
        self.model_preferences: dict[int, str] = {}

        allowed = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")
        self.allowed_user_ids = {
            int(part.strip())
            for part in allowed.split(",")
            if part.strip().isdigit()
        }

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @staticmethod
    def session_id(chat_id: int) -> str:
        return f"telegram:{chat_id}"

    def _is_allowed(self, user_id: int) -> bool:
        return not self.allowed_user_ids or user_id in self.allowed_user_ids

    def _is_trusted_operator(self, user_id: int) -> bool:
        # Approval is never enabled in open-access mode. An explicit allowlist is required.
        return bool(self.allowed_user_ids) and user_id in self.allowed_user_ids

    async def perceive(self) -> AsyncIterator[Perception]:
        while True:
            yield await self._queue.get()

    async def ingest_text(
        self,
        text: str,
        *,
        chat_id: int,
        user_id: int,
        message_id: int | None = None,
        language: str | None = None,
        correlation_id: str | None = None,
    ) -> SensePathResult:
        normalized = text.strip()
        if not normalized:
            raise ValueError("Telegram text must not be empty")
        metadata: dict[str, Any] = {
            "channel": "telegram",
            "chat_id": chat_id,
            "user_id": user_id,
            "session_id": self.session_id(chat_id),
            "response_modality": "text",
        }
        if message_id is not None:
            metadata["message_id"] = message_id
        if language:
            metadata["language"] = language
        if chat_id in self.model_preferences:
            metadata["preferred_model"] = self.model_preferences[chat_id]

        perception = Perception(
            modality="telegram.text",
            content=normalized,
            source=self.session_id(chat_id),
            metadata=metadata,
            correlation_id=correlation_id,
        )
        return await self.sense_path.handle(self, perception)

    async def ingest_voice_transcript(
        self,
        transcript: str,
        *,
        chat_id: int,
        user_id: int,
        message_id: int | None = None,
        language: str | None = None,
        correlation_id: str | None = None,
        respond_with_voice: bool = False,
    ) -> SensePathResult:
        normalized = transcript.strip()
        if not normalized:
            raise ValueError("Telegram voice transcript must not be empty")
        metadata: dict[str, Any] = {
            "channel": "telegram",
            "chat_id": chat_id,
            "user_id": user_id,
            "session_id": self.session_id(chat_id),
            "response_modality": "speech" if respond_with_voice else "text",
        }
        if message_id is not None:
            metadata["message_id"] = message_id
        if language:
            metadata["language"] = language
        if chat_id in self.model_preferences:
            metadata["preferred_model"] = self.model_preferences[chat_id]

        perception = Perception(
            modality="telegram.voice.transcript",
            content=normalized,
            source=self.session_id(chat_id),
            metadata=metadata,
            correlation_id=correlation_id,
        )
        return await self.sense_path.handle(self, perception)

    async def express(self, expression: Expression) -> None:
        chat_id_raw = expression.metadata.get("chat_id")
        if chat_id_raw is None and expression.target.startswith("telegram:"):
            chat_id_raw = expression.target.split(":", 1)[1]
        if chat_id_raw is None:
            raise ValueError("Telegram expression is missing chat_id")
        chat_id = int(chat_id_raw)
        text = str(expression.content)

        if expression.metadata.get("pending_approval"):
            await self._send_pending_approval(chat_id, expression)
            return

        if expression.modality in {"speech", "audio.speech"} and self._speech_renderer:
            language = str(expression.metadata.get("language") or "id")
            audio = await self._speech_renderer(text, language)
            await self._send_voice(chat_id, audio)
            return
        await self._send_text(chat_id, text)

    async def _send_text(self, chat_id: int, text: str) -> None:
        if self._text_sender:
            await self._text_sender(chat_id, text)
            return
        if self._bot is None:
            raise RuntimeError("Telegram transport is not initialized")
        await self._bot.send_message(chat_id=chat_id, text=text)

    async def _send_pending_approval(self, chat_id: int, expression: Expression) -> None:
        metadata = dict(expression.metadata.get("pending_approval") or {})
        approval_id = str(metadata.get("approval_id") or "")
        if (
            self._text_sender
            or self._bot is None
            or InlineKeyboardButton is None
            or InlineKeyboardMarkup is None
            or self._approval_callback_codec is None
            or self._approval_coordinator is None
            or not approval_id
        ):
            await self._send_text(chat_id, str(expression.content))
            return
        try:
            pending = self._approval_coordinator.inbox.get(approval_id)
            callback = self._approval_callback_codec
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ Approve once",
                        callback_data=callback.encode("approve", approval_id),
                    ),
                    InlineKeyboardButton(
                        "❌ Reject",
                        callback_data=callback.encode("reject", approval_id),
                    ),
                ],
                [InlineKeyboardButton(
                    "🔍 Details",
                    callback_data=callback.encode("details", approval_id),
                )],
            ])
            await self._bot.send_message(
                chat_id=chat_id,
                text=approval_card_text(pending),
                reply_markup=keyboard,
            )
        except Exception:
            log.exception("Failed to render Telegram approval card; using text fallback")
            await self._send_text(chat_id, str(expression.content))

    async def _send_voice(self, chat_id: int, audio: bytes) -> None:
        if self._voice_sender:
            await self._voice_sender(chat_id, audio)
            return
        if self._bot is None:
            raise RuntimeError("Telegram transport is not initialized")
        await self._bot.send_voice(chat_id=chat_id, voice=io.BytesIO(audio))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update.effective_user.id):
            await update.message.reply_text("Maaf, Anda tidak memiliki akses ke bot ini.")
            return
        await update.message.reply_text("Aether online. Semua pesan masuk melalui Sense Event Path.")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        await update.message.reply_text(self._command_registry.help_text())

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        chat_id = update.effective_chat.id
        if self._session_reset:
            await self._session_reset(self.session_id(chat_id))
        self.model_preferences.pop(chat_id, None)
        await update.message.reply_text("Context sesi Telegram telah dibersihkan.")

    async def model_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        chat_id = update.effective_chat.id
        if context.args:
            route = " ".join(context.args).strip()
            if "/" not in route:
                await update.message.reply_text("Gunakan format provider/model.")
                return
            self.model_preferences[chat_id] = route
            await update.message.reply_text(f"Model preference sesi: {route}")
            return
        current = self.model_preferences.get(chat_id, "default router policy")
        await update.message.reply_text(f"Model preference sesi: {current}")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        events = self.sense_path.event_bus.replay()
        pending_count = 0
        if self._approval_coordinator is not None:
            pending_count = len(self._approval_coordinator.inbox.list())
        await update.message.reply_text(
            f"Aether Sense Path online. Durable events: {len(events)}. "
            f"Pending approvals: {pending_count}. "
            f"Cognition: {self.sense_path.cognition.adapter_id}."
        )

    async def approvals_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not self._is_trusted_operator(user_id):
            await update.message.reply_text(
                "Trusted approval commands require TELEGRAM_ALLOWED_USER_IDS to include your user ID."
            )
            return
        if self._approval_coordinator is None:
            await update.message.reply_text("Approval inbox belum dikonfigurasi.")
            return
        pending = self._approval_coordinator.inbox.list()
        if not pending:
            await update.message.reply_text("Tidak ada pending approval.")
            return
        body = "Pending Aether approvals:\n\n" + "\n\n".join(format_pending(item) for item in pending[:10])
        await update.message.reply_text(body)

    def _pending_for_chat(self, chat_id: int) -> list[Any]:
        if self._approval_coordinator is None:
            return []
        rows = []
        for pending in self._approval_coordinator.inbox.list():
            candidate = pending.proposal.metadata.get("chat_id")
            try:
                if candidate is not None and int(candidate) == int(chat_id):
                    rows.append(pending)
            except (TypeError, ValueError):
                continue
        return rows

    async def _decision_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *, approved: bool) -> None:
        user_id = update.effective_user.id
        if not self._is_trusted_operator(user_id):
            await update.message.reply_text(
                "Trusted approval commands require an explicit Telegram operator allowlist."
            )
            return
        if self._approval_coordinator is None:
            await update.message.reply_text("Approval inbox belum dikonfigurasi.")
            return

        args = list(context.args or [])
        if args:
            approval_id = str(args[0]).strip()
            reason = " ".join(args[1:]).strip()
        else:
            pending = self._pending_for_chat(update.effective_chat.id)
            if not pending:
                await update.message.reply_text("Tidak ada pending approval untuk chat ini.")
                return
            if len(pending) > 1:
                await update.message.reply_text(
                    "Ada lebih dari satu pending approval. Gunakan /approvals lalu pilih "
                    "/approve <approval_id> atau /reject <approval_id>."
                )
                return
            approval_id = pending[0].approval_id
            reason = ""

        if not reason:
            reason = (
                "Founder approved once via trusted Telegram session"
                if approved
                else "Founder rejected once via trusted Telegram session"
            )
        try:
            outcome = await self._approval_coordinator.decide(
                approval_id,
                approved=approved,
                principal=f"telegram:{user_id}",
                reason=reason,
                channel="telegram",
            )
        except Exception as exc:
            await update.message.reply_text(f"Approval gagal: {type(exc).__name__}: {exc}")
            return
        rendered = await self._outcome_text(outcome, approved=approved, approval_id=approval_id)
        if approved and outcome.expression is not None:
            expression_chat_id = outcome.expression.metadata.get("chat_id")
            if expression_chat_id is not None or outcome.expression.target.startswith("telegram:"):
                await self.express(outcome.expression)
                return
        await update.message.reply_text(rendered)

    async def _outcome_text(self, outcome: Any, *, approved: bool, approval_id: str) -> str:
        pending = outcome.approval.pending
        if not approved:
            return f"Rejected {approval_id}. Action {pending.action_id} tidak dijalankan."
        if outcome.approval.replayed:
            return (
                f"Approval {approval_id} sudah consumed. Cached result dikembalikan; "
                "action tidak dijalankan ulang."
            )
        if outcome.expression is not None:
            return str(outcome.expression.content)
        result = outcome.approval.result
        status = result.status if result else pending.status.value
        detail = f"Approval {approval_id} consumed exactly once. Status: {status}."
        if result is not None and not result.ok and result.error:
            detail += f"\nError: {result.error}\nAutomatic retry: disabled."
        return detail

    async def approval_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        user_id = query.from_user.id
        if not self._is_trusted_operator(user_id):
            await query.answer("Trusted Founder access required.", show_alert=True)
            return
        if self._approval_coordinator is None or self._approval_callback_codec is None:
            await query.answer("Approval inbox is unavailable.", show_alert=True)
            return
        try:
            callback = self._approval_callback_codec.decode(query.data or "")
            pending = self._approval_coordinator.inbox.get(callback.approval_id)
        except Exception as exc:
            await query.answer(f"Invalid or expired approval control: {type(exc).__name__}", show_alert=True)
            return

        message = query.message
        callback_chat_id = getattr(getattr(message, "chat", None), "id", None)
        expected_chat_id = pending.proposal.metadata.get("chat_id")
        try:
            chat_matches = callback_chat_id is not None and int(callback_chat_id) == int(expected_chat_id)
        except (TypeError, ValueError):
            chat_matches = False
        if not chat_matches:
            await query.answer("This approval belongs to a different chat.", show_alert=True)
            return

        if callback.decision == "details":
            await query.answer()
            if message is not None:
                await message.reply_text(format_pending(pending))
            return

        approved = callback.decision == "approve"
        await query.answer("Executing…" if approved else "Rejected")
        outcome = None
        try:
            outcome = await self._approval_coordinator.decide(
                callback.approval_id,
                approved=approved,
                principal=f"telegram:{user_id}",
                reason=(
                    "Founder approved once via Telegram inline control"
                    if approved
                    else "Founder rejected once via Telegram inline control"
                ),
                channel="telegram-inline",
            )
        except Exception as exc:
            if query.message is not None:
                await query.edit_message_text(
                    text=f"Approval failed: {type(exc).__name__}: {exc}"
                )
            return
        # Deliver a proactive follow-up expression as a NEW message only for a
        # fresh (non-replayed) approval; collapse the button card to a short
        # final status instead of echoing the raw action output.
        if outcome is not None and _should_send_followup(
            approved=approved,
            replayed=bool(outcome.approval.replayed),
            has_expression=outcome.expression is not None,
        ):
            try:
                await self.express(outcome.expression)
            except Exception:
                pass  # follow-up delivery failure is non-fatal; card still shows status
            if query.message is not None:
                await query.edit_message_text(
                    text="✅ Approved — balasan lanjutan dikirim di atas."
                )
            return
        rendered = await self._outcome_text(
            outcome, approved=approved, approval_id=callback.approval_id
        )
        if query.message is not None:
            await query.edit_message_text(text=rendered)

    async def approve_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._decision_command(update, context, approved=True)

    async def reject_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._decision_command(update, context, approved=False)

    async def yes_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._decision_command(update, context, approved=True)

    async def no_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._decision_command(update, context, approved=False)

    async def handle_text_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        try:
            if self.behavior_monitor:
                self.behavior_monitor.record_api_call()
            await self.ingest_text(
                update.message.text or "",
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                message_id=update.message.message_id,
                language=update.effective_user.language_code,
            )
            if self.behavior_monitor:
                self.behavior_monitor.record_success(iterations=1)
        except Exception as exc:
            log.exception("Telegram text ingestion failed")
            if self.behavior_monitor:
                self.behavior_monitor.record_error()
            await update.message.reply_text(f"Aether gagal memproses pesan: {type(exc).__name__}")

    async def handle_voice_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        if self._voice_transcriber is None:
            await update.message.reply_text("Voice transcription adapter belum dikonfigurasi.")
            return
        try:
            telegram_file = await context.bot.get_file(update.message.voice.file_id)
            payload = bytes(await telegram_file.download_as_bytearray())
            language = update.effective_user.language_code or "id"
            transcript = await self._voice_transcriber(
                payload,
                {
                    "channel": "telegram",
                    "chat_id": update.effective_chat.id,
                    "user_id": update.effective_user.id,
                    "language": language,
                    "mime_type": update.message.voice.mime_type,
                },
            )
            await self.ingest_voice_transcript(
                transcript,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                message_id=update.message.message_id,
                language=language,
            )
        except Exception as exc:
            log.exception("Telegram voice ingestion failed")
            await update.message.reply_text(f"Aether gagal memproses voice: {type(exc).__name__}")

    async def start_polling(self) -> None:
        if Application is None:
            if self.enabled:
                raise RuntimeError("python-telegram-bot is required for Telegram polling")
            return
        if not self.enabled or not self.token:
            log.warning(
                "Telegram disabled: TELEGRAM_ENABLED=%s token=%s",
                os.environ.get("TELEGRAM_ENABLED"),
                "SET" if self.token else "MISSING",
            )
            return

        application = Application.builder().token(self.token).build()
        self._bot = application.bot
        for command_name, handler_name in self._command_registry.bindings():
            handler = getattr(self, handler_name, None)
            if handler is None:
                raise RuntimeError(f"Telegram command /{command_name} is not wired: {handler_name}")
            application.add_handler(CommandHandler(command_name, handler))
        if CallbackQueryHandler is not None:
            application.add_handler(CallbackQueryHandler(self.approval_callback, pattern=r"^a1\|"))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_update))
        application.add_handler(MessageHandler(filters.VOICE, self.handle_voice_update))

        await application.initialize()
        if BotCommand is not None:
            await application.bot.set_my_commands([
                BotCommand(command, description)
                for command, description in self._command_registry.menu_items()
            ])
        await application.start()
        await application.updater.start_polling()
        log.info("Telegram Sense Adapter is polling")
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()


# Transitional import compatibility; all behavior is the new Sense adapter.
TelegramBotAdapter = TelegramSenseAdapter
