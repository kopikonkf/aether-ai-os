"""Approval inline delivery decision tests.

Covers the rule that a proactive follow-up Expression is sent as a NEW message
only for a fresh (non-replayed) approval that produced an Expression; replays,
rejections and missing continuations must not produce a duplicate message.
"""

from aether_gateway.adapters.telegram_bot import _should_send_followup


def test_send_success():
    assert _should_send_followup(approved=True, replayed=False, has_expression=True)


def test_replay_does_not_duplicate():
    # Approval already consumed once -> cached result, no new follow-up.
    assert not _should_send_followup(approved=True, replayed=True, has_expression=True)


def test_rejection_sends_no_followup():
    assert not _should_send_followup(approved=False, replayed=False, has_expression=True)


def test_missing_continuation_sends_no_followup():
    # Cognition did not resume -> no Expression -> no follow-up message.
    assert not _should_send_followup(approved=True, replayed=False, has_expression=False)