"""Conservative Telegram presentation rendering with safe HTML fallback."""
from __future__ import annotations

from dataclasses import dataclass
import html
import re
from typing import Iterable
from urllib.parse import urlparse


_TELEGRAM_MESSAGE_LIMIT = 4096
_SAFE_RENDER_LIMIT = 3800


@dataclass(frozen=True)
class TelegramRenderedMessage:
    """One transport-ready Telegram message and its plain-text fallback."""

    text: str
    plain_text: str
    parse_mode: str | None = "HTML"


class TelegramPresentationAdapter:
    """Render a small, auditable Markdown subset into Telegram-safe HTML.

    The adapter intentionally supports only formatting that can be made safe
    without a full Markdown parser. Unsupported syntax remains visible text.
    """

    capabilities = {
        "approval_buttons": True,
        "basic_formatting": True,
        "headings": True,
        "lists": True,
        "links": True,
        "code_blocks": True,
        "structured_rich_messages": False,
        "streaming": False,
    }

    def __init__(self, *, message_limit: int = _TELEGRAM_MESSAGE_LIMIT) -> None:
        self.message_limit = min(_TELEGRAM_MESSAGE_LIMIT, max(512, int(message_limit)))
        self.render_limit = min(_SAFE_RENDER_LIMIT, self.message_limit - 64)

    def render(self, text: str) -> list[TelegramRenderedMessage]:
        source = str(text or "").strip()
        if not source:
            return []
        messages: list[TelegramRenderedMessage] = []
        for chunk in self._split_source(source):
            rendered = self._render_chunk(chunk)
            if len(rendered) <= self.message_limit:
                messages.append(TelegramRenderedMessage(rendered, chunk))
                continue
            # Defensive fallback: if markup expansion exceeded the transport
            # limit, send bounded plain text rather than risk Telegram rejection.
            for plain in self._split_plain(chunk, self.message_limit):
                messages.append(TelegramRenderedMessage(plain, plain, None))
        return messages

    def capability_snapshot(self) -> dict[str, bool]:
        return dict(self.capabilities)

    def _split_source(self, source: str) -> list[str]:
        blocks = list(self._blocks(source))
        chunks: list[str] = []
        current = ""
        for block in blocks:
            candidates = [block]
            if len(block) > self.render_limit:
                if block.startswith("```") and block.rstrip().endswith("```"):
                    candidates = self._split_fenced_block(block, self.render_limit)
                else:
                    candidates = self._split_plain(block, self.render_limit)
            for candidate in candidates:
                joined = candidate if not current else f"{current}\n\n{candidate}"
                if len(joined) <= self.render_limit:
                    current = joined
                else:
                    if current:
                        chunks.append(current)
                    current = candidate
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _blocks(source: str) -> Iterable[str]:
        lines = source.splitlines()
        paragraph: list[str] = []
        fence: list[str] = []
        in_fence = False
        for line in lines:
            if line.lstrip().startswith("```"):
                if in_fence:
                    fence.append(line)
                    yield "\n".join(fence)
                    fence = []
                    in_fence = False
                else:
                    if paragraph:
                        yield "\n".join(paragraph).strip()
                        paragraph = []
                    fence = [line]
                    in_fence = True
                continue
            if in_fence:
                fence.append(line)
                continue
            if not line.strip():
                if paragraph:
                    yield "\n".join(paragraph).strip()
                    paragraph = []
                continue
            paragraph.append(line)
        if fence:
            # An unclosed fence is treated as plain text, never as trusted HTML.
            yield "\n".join(fence)
        if paragraph:
            yield "\n".join(paragraph).strip()

    @staticmethod
    def _split_plain(text: str, limit: int) -> list[str]:
        result: list[str] = []
        current = ""
        for line in text.splitlines() or [text]:
            parts = [line]
            if len(line) > limit:
                parts = [line[index:index + limit] for index in range(0, len(line), limit)]
            for part in parts:
                candidate = part if not current else f"{current}\n{part}"
                if len(candidate) <= limit:
                    current = candidate
                else:
                    if current:
                        result.append(current)
                    current = part
        if current:
            result.append(current)
        return result

    @staticmethod
    def _split_fenced_block(block: str, limit: int) -> list[str]:
        lines = block.splitlines()
        opening = lines[0] if lines else "```"
        language = opening[3:].strip()
        closing = "```"
        body = lines[1:-1] if len(lines) >= 2 and lines[-1].strip().startswith("```") else lines[1:]
        overhead = len(opening) + len(closing) + 2
        body_limit = max(128, limit - overhead)
        body_chunks = TelegramPresentationAdapter._split_plain("\n".join(body), body_limit)
        if not body_chunks:
            body_chunks = [""]
        prefix = f"```{language}" if language else "```"
        return [f"{prefix}\n{chunk}\n```" for chunk in body_chunks]

    def _render_chunk(self, source: str) -> str:
        placeholders: dict[str, str] = {}

        def hold(value: str) -> str:
            key = f"\x00AETHER{len(placeholders)}\x00"
            placeholders[key] = value
            return key

        def fenced(match: re.Match[str]) -> str:
            language = html.escape((match.group(1) or "").strip())
            body = html.escape(match.group(2).rstrip("\n"), quote=False)
            class_attr = f' class="language-{language}"' if language else ""
            return hold(f"<pre><code{class_attr}>{body}</code></pre>")

        working = re.sub(r"```([^\n`]*)\n(.*?)```", fenced, source, flags=re.DOTALL)

        def inline_code(match: re.Match[str]) -> str:
            return hold(f"<code>{html.escape(match.group(1))}</code>")

        working = re.sub(r"`([^`\n]+)`", inline_code, working)
        working = html.escape(working)

        def link(match: re.Match[str]) -> str:
            label = match.group(1)
            url = html.unescape(match.group(2)).strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                return f"{label} ({html.escape(url)})"
            return f'<a href="{html.escape(url, quote=True)}">{label}</a>'

        working = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+)\)", link, working)
        working = re.sub(r"\*\*([^*\n][^\n]*?)\*\*", r"<b>\1</b>", working)
        working = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", working)
        working = re.sub(r"__([^_\n][^\n]*?)__", r"<u>\1</u>", working)
        working = re.sub(r"~~([^~\n]+)~~", r"<s>\1</s>", working)

        rendered_lines: list[str] = []
        for line in working.splitlines():
            heading = re.match(r"^\s{0,3}#{1,6}\s+(.+)$", line)
            if heading:
                rendered_lines.append(f"<b>{heading.group(1)}</b>")
                continue
            bullet = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
            if bullet:
                indent = "  " * min(4, len(bullet.group(1)) // 2)
                rendered_lines.append(f"{indent}• {bullet.group(2)}")
                continue
            quote = re.match(r"^\s*&gt;\s?(.*)$", line)
            if quote:
                rendered_lines.append(f"<blockquote>{quote.group(1)}</blockquote>")
                continue
            rendered_lines.append(line)
        working = "\n".join(rendered_lines)

        for key, value in placeholders.items():
            working = working.replace(html.escape(key), value).replace(key, value)
        return working
