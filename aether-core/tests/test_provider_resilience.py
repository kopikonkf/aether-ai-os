from __future__ import annotations

import pytest

from aether.resilience import (
    CircuitBreaker,
    CircuitState,
    ConcurrencyBudget,
    ConcurrencyBudgetExceeded,
    DailyBudgetExceeded,
    DailyRequestBudget,
    ProviderCandidate,
    ProviderErrorKind,
    ProviderErrorSignal,
    RetryPolicy,
    classify_provider_error,
    select_fallback,
)


def test_429_rate_limit_and_quota_exhaustion_are_distinct() -> None:
    assert classify_provider_error(
        ProviderErrorSignal(status_code=429, error_code="rate_limit_exceeded")
    ) is ProviderErrorKind.RATE_LIMIT
    assert classify_provider_error(
        ProviderErrorSignal(status_code=429, error_code="insufficient_quota")
    ) is ProviderErrorKind.QUOTA_EXHAUSTED
    assert classify_provider_error(
        ProviderErrorSignal(status_code=429, message="billing limit reached")
    ) is ProviderErrorKind.QUOTA_EXHAUSTED


def test_error_taxonomy_distinguishes_transient_and_non_retryable_classes() -> None:
    assert classify_provider_error(
        ProviderErrorSignal(status_code=503)
    ) is ProviderErrorKind.SERVER_TRANSIENT
    assert classify_provider_error(
        ProviderErrorSignal(exception_name="ConnectTimeout")
    ) is ProviderErrorKind.NETWORK_TRANSIENT
    assert classify_provider_error(
        ProviderErrorSignal(status_code=401)
    ) is ProviderErrorKind.AUTHENTICATION
    assert classify_provider_error(
        ProviderErrorSignal(status_code=501)
    ) is ProviderErrorKind.UNSUPPORTED


def test_retry_policy_is_deterministic_bounded_and_honors_retry_after() -> None:
    policy = RetryPolicy(
        base_delay_seconds=1,
        max_delay_seconds=8,
        max_retry_after_seconds=30,
        jitter_ratio=0.25,
    )
    first = policy.delay_seconds(3, jitter_key="google-tts")
    assert first == policy.delay_seconds(3, jitter_key="google-tts")
    assert 4 <= first <= 5
    assert policy.delay_seconds(2, retry_after_seconds=20, jitter_key="x") == 20
    assert policy.delay_seconds(2, retry_after_seconds=100, jitter_key="x") == 30
    assert policy.should_retry(ProviderErrorKind.RATE_LIMIT, attempt=1)
    assert not policy.should_retry(ProviderErrorKind.QUOTA_EXHAUSTED, attempt=1)
    assert not policy.should_retry(ProviderErrorKind.RATE_LIMIT, attempt=4)


def test_daily_request_budget_rolls_over_and_fails_closed() -> None:
    budget = DailyRequestBudget(limit=2, day_key="2026-07-30")
    budget.consume(day_key="2026-07-30")
    budget.consume(day_key="2026-07-30")
    assert budget.remaining == 0
    with pytest.raises(DailyBudgetExceeded):
        budget.consume(day_key="2026-07-30")
    budget.consume(day_key="2026-07-31")
    assert budget.consumed == 1
    assert budget.remaining == 1


def test_concurrency_budget_acquire_release_is_bounded() -> None:
    budget = ConcurrencyBudget(limit=1)
    budget.acquire()
    with pytest.raises(ConcurrencyBudgetExceeded):
        budget.acquire()
    budget.release()
    assert budget.available == 1
    with pytest.raises(RuntimeError):
        budget.release()


def test_circuit_breaker_opens_half_opens_and_recovers() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10)
    assert breaker.allow_request(now=0)
    breaker.record_failure(ProviderErrorKind.SERVER_TRANSIENT, now=1)
    assert breaker.state is CircuitState.CLOSED
    breaker.record_failure(ProviderErrorKind.RATE_LIMIT, now=2)
    assert breaker.state is CircuitState.OPEN
    assert not breaker.allow_request(now=11)
    assert breaker.allow_request(now=12)
    assert breaker.state is CircuitState.HALF_OPEN
    assert not breaker.allow_request(now=12)
    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.consecutive_failures == 0


def test_invalid_request_does_not_poison_provider_health() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=10)
    breaker.record_failure(ProviderErrorKind.INVALID_REQUEST, now=1)
    assert breaker.state is CircuitState.CLOSED
    assert breaker.consecutive_failures == 0


def test_circuit_receipt_is_hash_bound_and_stable() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=10)
    breaker.record_failure(ProviderErrorKind.AUTHENTICATION, now=2)
    one = breaker.receipt(
        provider_id="openai-voice",
        observed_at=3,
        reason="auth rejected",
    )
    two = breaker.receipt(
        provider_id="openai-voice",
        observed_at=3,
        reason="auth rejected",
    )
    assert one.receipt_id == two.receipt_id
    assert len(one.receipt_id) == 64
    assert one.state is CircuitState.OPEN


def test_fallback_matrix_prefers_primary_and_skips_ineligible_candidates() -> None:
    candidates = [
        ProviderCandidate(
            provider_id="google-cloud-tts",
            priority=10,
            capabilities=frozenset({"voice.tts", "voice.id-ID"}),
            data_policy_tags=frozenset({"cloud"}),
        ),
        ProviderCandidate(
            provider_id="openai-exact-tts",
            priority=20,
            capabilities=frozenset({"voice.tts", "voice.id-ID"}),
            data_policy_tags=frozenset({"cloud"}),
        ),
        ProviderCandidate(
            provider_id="cartesia",
            priority=30,
            capabilities=frozenset({"voice.tts"}),
            data_policy_tags=frozenset({"cloud"}),
        ),
    ]
    decision = select_fallback(
        candidates,
        required_capabilities={"voice.tts", "voice.id-ID"},
        allowed_data_policy_tags={"cloud"},
        now=0,
    )
    assert decision.selected_provider_id == "google-cloud-tts"
    assert len(decision.decision_id) == 64
    assert decision.evaluations[-1].reasons == (
        "missing_capabilities:voice.id-ID",
    )


def test_fallback_matrix_skips_budget_circuit_cooldown_and_policy_failures() -> None:
    candidates = [
        ProviderCandidate(
            provider_id="google-cloud-tts",
            priority=10,
            capabilities=frozenset({"voice.tts"}),
            daily_budget_remaining=0,
            data_policy_tags=frozenset({"cloud"}),
        ),
        ProviderCandidate(
            provider_id="openai-exact-tts",
            priority=20,
            capabilities=frozenset({"voice.tts"}),
            circuit_state=CircuitState.OPEN,
            data_policy_tags=frozenset({"cloud"}),
        ),
        ProviderCandidate(
            provider_id="cartesia",
            priority=30,
            capabilities=frozenset({"voice.tts"}),
            cooldown_until=50,
            data_policy_tags=frozenset({"cloud"}),
        ),
        ProviderCandidate(
            provider_id="local-tts",
            priority=40,
            capabilities=frozenset({"voice.tts"}),
            data_policy_tags=frozenset({"local"}),
        ),
    ]
    decision = select_fallback(
        candidates,
        required_capabilities={"voice.tts"},
        allowed_data_policy_tags={"cloud"},
        now=10,
    )
    assert decision.selected_provider_id is None
    reasons = {item.provider_id: item.reasons for item in decision.evaluations}
    assert "daily_budget_exhausted" in reasons["google-cloud-tts"]
    assert "circuit_open" in reasons["openai-exact-tts"]
    assert "cooldown_active" in reasons["cartesia"]
    assert reasons["local-tts"] == ("data_policy_disallowed:local",)


def test_voice_fallback_progresses_google_to_openai_to_cartesia() -> None:
    google_exhausted = ProviderCandidate(
        provider_id="google-cloud-tts",
        priority=10,
        capabilities=frozenset({"voice.tts"}),
        daily_budget_remaining=0,
        data_policy_tags=frozenset({"cloud"}),
    )
    openai_ready = ProviderCandidate(
        provider_id="openai-exact-tts",
        priority=20,
        capabilities=frozenset({"voice.tts"}),
        data_policy_tags=frozenset({"cloud"}),
    )
    cartesia_ready = ProviderCandidate(
        provider_id="cartesia",
        priority=30,
        capabilities=frozenset({"voice.tts"}),
        data_policy_tags=frozenset({"cloud"}),
    )

    decision = select_fallback(
        [cartesia_ready, openai_ready, google_exhausted],
        required_capabilities={"voice.tts"},
        allowed_data_policy_tags={"cloud"},
        now=0,
    )
    assert decision.selected_provider_id == "openai-exact-tts"

    openai_open = ProviderCandidate(
        provider_id="openai-exact-tts",
        priority=20,
        capabilities=frozenset({"voice.tts"}),
        circuit_state=CircuitState.OPEN,
        data_policy_tags=frozenset({"cloud"}),
    )
    decision = select_fallback(
        [cartesia_ready, openai_open, google_exhausted],
        required_capabilities={"voice.tts"},
        allowed_data_policy_tags={"cloud"},
        now=0,
    )
    assert decision.selected_provider_id == "cartesia"
