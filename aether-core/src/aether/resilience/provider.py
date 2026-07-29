"""Provider-neutral resilience contracts for bounded Aether routing.

The module is intentionally pure and credential-free. It classifies provider
failures, computes bounded retry delays, tracks request/concurrency budgets,
models circuit-breaker state, and produces auditable fallback decisions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping


class ProviderErrorKind(str, Enum):
    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhausted"
    SERVER_TRANSIENT = "server_transient"
    NETWORK_TRANSIENT = "network_transient"
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderErrorSignal:
    status_code: int | None = None
    error_code: str = ""
    message: str = ""
    retry_after_seconds: float | None = None
    exception_name: str = ""


_QUOTA_MARKERS = (
    "insufficient_quota",
    "quota_exceeded",
    "billing_hard_limit",
    "billing limit",
    "credit balance",
    "credits exhausted",
    "spend limit",
    "daily limit",
    "requests per day",
    "rpd limit",
    "billing quota",
)
_NETWORK_MARKERS = ("timeout", "timed out", "connection", "dns", "network", "socket")


def classify_provider_error(signal: ProviderErrorSignal) -> ProviderErrorKind:
    """Classify provider failures without depending on one vendor's schema."""
    status = signal.status_code
    text = " ".join((signal.error_code, signal.message, signal.exception_name)).casefold()

    if status == 429:
        if any(marker in text for marker in _QUOTA_MARKERS):
            return ProviderErrorKind.QUOTA_EXHAUSTED
        return ProviderErrorKind.RATE_LIMIT
    if status in {401, 403}:
        return ProviderErrorKind.AUTHENTICATION
    if status in {400, 409, 413, 415, 422}:
        return ProviderErrorKind.INVALID_REQUEST
    if status in {404, 405, 410, 501}:
        return ProviderErrorKind.UNSUPPORTED
    if status in {408, 425, 500, 502, 503, 504}:
        return ProviderErrorKind.SERVER_TRANSIENT
    if status is None and any(marker in text for marker in _NETWORK_MARKERS):
        return ProviderErrorKind.NETWORK_TRANSIENT
    return ProviderErrorKind.UNKNOWN


def retryable(kind: ProviderErrorKind) -> bool:
    return kind in {
        ProviderErrorKind.RATE_LIMIT,
        ProviderErrorKind.SERVER_TRANSIENT,
        ProviderErrorKind.NETWORK_TRANSIENT,
    }


def fallback_eligible_error(kind: ProviderErrorKind) -> bool:
    return kind in {
        ProviderErrorKind.RATE_LIMIT,
        ProviderErrorKind.QUOTA_EXHAUSTED,
        ProviderErrorKind.SERVER_TRANSIENT,
        ProviderErrorKind.NETWORK_TRANSIENT,
        ProviderErrorKind.AUTHENTICATION,
        ProviderErrorKind.UNSUPPORTED,
    }


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    max_retry_after_seconds: float = 300.0
    jitter_ratio: float = 0.20

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds <= 0 or self.max_delay_seconds <= 0:
            raise ValueError("retry delays must be positive")
        if self.max_retry_after_seconds < self.max_delay_seconds:
            raise ValueError("max_retry_after_seconds must be >= max_delay_seconds")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be within [0, 1]")

    def delay_seconds(
        self,
        attempt: int,
        *,
        retry_after_seconds: float | None = None,
        jitter_key: str = "",
    ) -> float:
        if attempt < 1:
            raise ValueError("attempt is 1-based")
        exponential = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (attempt - 1)))
        digest = hashlib.sha256(f"{jitter_key}:{attempt}".encode("utf-8")).digest()
        fraction = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
        jitter = exponential * self.jitter_ratio * fraction
        delay = exponential + jitter
        if retry_after_seconds is not None:
            delay = max(delay, max(0.0, retry_after_seconds))
        return round(min(delay, self.max_retry_after_seconds), 6)

    def should_retry(self, kind: ProviderErrorKind, *, attempt: int) -> bool:
        return attempt < self.max_attempts and retryable(kind)


class DailyBudgetExceeded(RuntimeError):
    pass


@dataclass
class DailyRequestBudget:
    limit: int
    day_key: str
    consumed: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("daily request limit must be positive")
        if self.consumed < 0:
            raise ValueError("consumed requests cannot be negative")

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.consumed)

    def rollover(self, day_key: str) -> None:
        if day_key != self.day_key:
            self.day_key = day_key
            self.consumed = 0

    def consume(self, *, day_key: str, count: int = 1) -> None:
        if count < 1:
            raise ValueError("count must be positive")
        self.rollover(day_key)
        if count > self.remaining:
            raise DailyBudgetExceeded(
                f"daily request budget exhausted: requested={count}, remaining={self.remaining}"
            )
        self.consumed += count


class ConcurrencyBudgetExceeded(RuntimeError):
    pass


@dataclass
class ConcurrencyBudget:
    limit: int
    in_flight: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("concurrency limit must be positive")
        if self.in_flight < 0:
            raise ValueError("in_flight cannot be negative")

    @property
    def available(self) -> int:
        return max(0, self.limit - self.in_flight)

    def acquire(self) -> None:
        if self.in_flight >= self.limit:
            raise ConcurrencyBudgetExceeded(
                f"concurrency budget exhausted: in_flight={self.in_flight}, limit={self.limit}"
            )
        self.in_flight += 1

    def release(self) -> None:
        if self.in_flight <= 0:
            raise RuntimeError("cannot release an empty concurrency budget")
        self.in_flight -= 1


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitBreakerReceipt:
    provider_id: str
    state: CircuitState
    consecutive_failures: int
    opened_at: float | None
    observed_at: float
    cooldown_seconds: float
    reason: str
    receipt_id: str

    @classmethod
    def build(
        cls,
        *,
        provider_id: str,
        state: CircuitState,
        consecutive_failures: int,
        opened_at: float | None,
        observed_at: float,
        cooldown_seconds: float,
        reason: str,
    ) -> "CircuitBreakerReceipt":
        payload = {
            "schema": "aether.provider-circuit-receipt.v1",
            "provider_id": provider_id,
            "state": state.value,
            "consecutive_failures": consecutive_failures,
            "opened_at": opened_at,
            "observed_at": observed_at,
            "cooldown_seconds": cooldown_seconds,
            "reason": reason,
        }
        receipt_id = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return cls(
            provider_id=provider_id,
            state=state,
            consecutive_failures=consecutive_failures,
            opened_at=opened_at,
            observed_at=observed_at,
            cooldown_seconds=cooldown_seconds,
            reason=reason,
            receipt_id=receipt_id,
        )


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_seconds: float = 60.0
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float | None = None
    _half_open_probe_in_flight: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if self.cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")

    def allow_request(self, *, now: float) -> bool:
        if self.state is CircuitState.CLOSED:
            return True
        if self.state is CircuitState.OPEN:
            if self.opened_at is None or now - self.opened_at < self.cooldown_seconds:
                return False
            self.state = CircuitState.HALF_OPEN
            self._half_open_probe_in_flight = False
        if self._half_open_probe_in_flight:
            return False
        self._half_open_probe_in_flight = True
        return True

    def record_success(self) -> None:
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.opened_at = None
        self._half_open_probe_in_flight = False

    def record_failure(self, kind: ProviderErrorKind, *, now: float) -> None:
        self._half_open_probe_in_flight = False
        if kind in {ProviderErrorKind.INVALID_REQUEST, ProviderErrorKind.UNKNOWN}:
            return
        self.consecutive_failures += 1
        if self.state is CircuitState.HALF_OPEN or self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = now

    def receipt(self, *, provider_id: str, observed_at: float, reason: str) -> CircuitBreakerReceipt:
        return CircuitBreakerReceipt.build(
            provider_id=provider_id,
            state=self.state,
            consecutive_failures=self.consecutive_failures,
            opened_at=self.opened_at,
            observed_at=observed_at,
            cooldown_seconds=self.cooldown_seconds,
            reason=reason,
        )


@dataclass(frozen=True)
class ProviderCandidate:
    provider_id: str
    priority: int
    capabilities: frozenset[str]
    healthy: bool = True
    enabled: bool = True
    daily_budget_remaining: int = 1
    concurrency_available: int = 1
    circuit_state: CircuitState = CircuitState.CLOSED
    cooldown_until: float | None = None
    data_policy_tags: frozenset[str] = frozenset()

    def ineligibility_reasons(
        self,
        *,
        required_capabilities: Iterable[str],
        allowed_data_policy_tags: Iterable[str],
        now: float,
    ) -> tuple[str, ...]:
        required = set(required_capabilities)
        allowed = set(allowed_data_policy_tags)
        reasons: list[str] = []
        if not self.enabled:
            reasons.append("disabled")
        if not self.healthy:
            reasons.append("unhealthy")
        missing = sorted(required - set(self.capabilities))
        if missing:
            reasons.append("missing_capabilities:" + ",".join(missing))
        if self.daily_budget_remaining <= 0:
            reasons.append("daily_budget_exhausted")
        if self.concurrency_available <= 0:
            reasons.append("concurrency_exhausted")
        if self.circuit_state is CircuitState.OPEN:
            reasons.append("circuit_open")
        if self.cooldown_until is not None and now < self.cooldown_until:
            reasons.append("cooldown_active")
        disallowed = sorted(set(self.data_policy_tags) - allowed)
        if disallowed:
            reasons.append("data_policy_disallowed:" + ",".join(disallowed))
        return tuple(reasons)


@dataclass(frozen=True)
class FallbackEvaluation:
    provider_id: str
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FallbackDecision:
    selected_provider_id: str | None
    evaluations: tuple[FallbackEvaluation, ...]
    decision_id: str


def select_fallback(
    candidates: Iterable[ProviderCandidate],
    *,
    required_capabilities: Iterable[str],
    allowed_data_policy_tags: Iterable[str],
    now: float,
) -> FallbackDecision:
    evaluations: list[FallbackEvaluation] = []
    selected: str | None = None
    for candidate in sorted(candidates, key=lambda item: (item.priority, item.provider_id)):
        reasons = candidate.ineligibility_reasons(
            required_capabilities=required_capabilities,
            allowed_data_policy_tags=allowed_data_policy_tags,
            now=now,
        )
        eligible = not reasons
        evaluations.append(FallbackEvaluation(candidate.provider_id, eligible, reasons))
        if eligible and selected is None:
            selected = candidate.provider_id

    payload: Mapping[str, object] = {
        "schema": "aether.provider-fallback-decision.v1",
        "selected_provider_id": selected,
        "evaluations": [
            {"provider_id": item.provider_id, "eligible": item.eligible, "reasons": list(item.reasons)}
            for item in evaluations
        ],
    }
    decision_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return FallbackDecision(selected, tuple(evaluations), decision_id)
