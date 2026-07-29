# ADR-0012 — Durable Cognitive Sessions

**Status:** Accepted in MVP v0.6

## Decision

Aether cognitive sessions use an Aether-owned SQLite store at
`$AETHER_HOME/sessions/cognitive-sessions.sqlite3`. The store is bounded,
portable across Windows/Linux/macOS, and survives process restarts.

## Boundary

Session messages are working context, not beliefs. Clearing a session removes
working context but does not rewrite canonical episodic history. A session
storage failure is reported but must not block core cognition.

## Consequences

- Telegram, HTTP/AionUi, voice, and future senses may resume the same session.
- Conversation state no longer depends on one process lifetime.
- Session storage can be replaced behind `ConversationStore` without changing cognition.
