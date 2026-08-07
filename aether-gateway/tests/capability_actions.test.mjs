import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createCapabilityProjectionConsumer,
  normalizeCapabilityProjection,
} from '../src/aether_gateway/aionui_senses_console/capability_actions.js';

const hash = 'a'.repeat(64);
const manifestHash = 'b'.repeat(64);

function receipt(state, sequence, values = {}) {
  return {
    receipt_id: `evt.${sequence}`,
    action_id: 'act.1',
    session_id: 'sense-session.1',
    correlation_id: 'corr.1',
    capability_name: 'tool.write',
    exact_action_hash: hash,
    state,
    observed_at: `2026-08-08T00:00:0${sequence}Z`,
    adapter_manifest_hash: manifestHash,
    approval_request_id: null,
    authoritative_receipt_id: null,
    cancel_supported: false,
    progress: null,
    safe_summary: 'tool.write · medium risk',
    metadata: { source: 'action-path-ledger' },
    ...values,
  };
}

function projection(receipts, approvalHandoff = null) {
  return {
    action_id: 'act.1',
    receipts,
    current: receipts.at(-1),
    approval_handoff: approvalHandoff,
  };
}

test('normalizer accepts only an exact receipt-bound trusted handoff', () => {
  const receipts = [
    receipt('proposed', 1),
    receipt('awaiting-approval', 2, { approval_request_id: 'approval.1' }),
  ];
  const normalized = normalizeCapabilityProjection(projection(receipts, {
    approval_id: 'approval.1',
    exact_action_hash: hash,
    expires_at: '2026-08-08T00:15:00Z',
    decision_in_senses: false,
    aionui_route: `/#/approvals?approval_id=approval.1&action_hash=${hash}`,
    telegram_command: '/approvals',
  }));

  assert.equal(normalized.current.actionState, 'awaiting-approval');
  assert.equal(normalized.approvalHandoff.decisionInSenses, false);
  assert.equal(normalized.approvalHandoff.exactActionHash, hash);
});

test('normalizer rejects terminal claims without an authoritative receipt', () => {
  assert.throws(
    () => normalizeCapabilityProjection(projection([
      receipt('proposed', 1),
      receipt('queued', 2),
      receipt('running', 3),
      receipt('succeeded', 4),
    ])),
    /authoritative receipt/,
  );
});

test('normalizer rejects handoff hash substitution and raw action payloads', () => {
  const pending = receipt('awaiting-approval', 2, { approval_request_id: 'approval.1' });
  assert.throws(
    () => normalizeCapabilityProjection(projection([
      receipt('proposed', 1),
      pending,
    ], {
      approval_id: 'approval.1',
      exact_action_hash: 'c'.repeat(64),
      expires_at: '2026-08-08T00:15:00Z',
      decision_in_senses: false,
      aionui_route: '/#/approvals',
      telegram_command: '/approvals',
    })),
    /does not match the exact action/,
  );
  assert.throws(
    () => normalizeCapabilityProjection(projection([
      { ...receipt('proposed', 1), arguments: { secret: true } },
    ])),
    /unsafe receipt/,
  );
});

test('consumer dispatches new receipts in order and refreshes current receipt safely', () => {
  const events = [];
  const rendered = [];
  const consumer = createCapabilityProjectionConsumer(
    (event) => events.push(event),
    (value) => rendered.push(value),
  );
  const proposed = projection([receipt('proposed', 1)]);
  consumer.consume(proposed, { epoch: 4 });
  consumer.consume(proposed, { epoch: 4 });

  assert.deepEqual(events.map((event) => event.actionState), ['proposed', 'proposed']);
  assert.equal(events[0].epoch, 4);
  assert.equal(rendered.at(-1).current.receiptId, 'evt.1');
});

