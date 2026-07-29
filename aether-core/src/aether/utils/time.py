from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    """Return current UTC timestamp in stable ISO-8601 Z format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now_iso() -> str:
    """Backward/forward compatible alias used by Sprint 03 runtime code."""
    return utc_now()
