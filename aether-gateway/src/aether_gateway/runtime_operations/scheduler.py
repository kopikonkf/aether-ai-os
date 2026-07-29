"""Async interval scheduler for backend-owned runtime fleet operations."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Mapping


class RuntimeFleetScheduler:
    def __init__(self, service, *, poll_interval_seconds: int = 10, enabled: bool = True) -> None:
        self.service = service
        self.poll_interval_seconds = max(1, int(poll_interval_seconds))
        self.enabled = bool(enabled)
        self._running = False
        self._cycles = 0
        self._last_cycle_at: str | None = None
        self._last_error: str | None = None

    async def run_once(self) -> tuple[Mapping[str, Any], ...]:
        self._last_cycle_at = datetime.now(timezone.utc).isoformat()
        try:
            result = await self.service.run_due(principal="aether.fleet-scheduler")
            self._last_error = None
            self._cycles += 1
            return result
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._cycles += 1
            raise

    async def run_forever(self) -> None:
        if not self.enabled:
            return
        self._running = True
        try:
            while True:
                try:
                    await self.run_once()
                except Exception:
                    # Failure is persisted/classified by the service; scheduler stays alive.
                    pass
                await asyncio.sleep(self.poll_interval_seconds)
        finally:
            self._running = False

    def status(self) -> Mapping[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self._running,
            "poll_interval_seconds": self.poll_interval_seconds,
            "cycles": self._cycles,
            "last_cycle_at": self._last_cycle_at,
            "last_error": self._last_error,
        }
