import { CapabilityActionState } from './client_state.js?v=senses-v1-slice-8-20260808-1';

const TERMINAL_STATES = new Set([
  CapabilityActionState.SUCCEEDED,
  CapabilityActionState.FAILED,
  CapabilityActionState.CANCELED,
  CapabilityActionState.REJECTED,
  CapabilityActionState.UNAVAILABLE,
]);

function text(value, label) {
  const normalized = String(value || '').trim();
  if (!normalized) throw new Error(`${label} is required`);
  return normalized;
}

function sha256(value, label) {
  const normalized = text(value, label);
  if (!/^[0-9a-f]{64}$/.test(normalized)) {
    throw new Error(`${label} must be a lowercase SHA-256 hash`);
  }
  return normalized;
}

function normalizeReceipt(raw, actionId, exactActionHash) {
  if (!raw || typeof raw !== 'object' || 'arguments' in raw || 'output' in raw) {
    throw new Error('capability projection contains an unsafe receipt');
  }
  const state = Object.values(CapabilityActionState).includes(raw.state)
    ? raw.state
    : null;
  if (!state || state === CapabilityActionState.NONE) {
    throw new Error('capability receipt contains an unknown action state');
  }
  const receipt = {
    receiptId: text(raw.receipt_id, 'capability receipt ID'),
    actionId: text(raw.action_id, 'capability action ID'),
    sessionId: text(raw.session_id, 'capability session ID'),
    correlationId: text(raw.correlation_id, 'capability correlation ID'),
    capabilityName: text(raw.capability_name, 'capability name'),
    exactActionHash: sha256(raw.exact_action_hash, 'exact action hash'),
    actionState: state,
    observedAt: text(raw.observed_at, 'capability observation time'),
    adapterManifestHash: raw.adapter_manifest_hash == null
      ? null
      : sha256(raw.adapter_manifest_hash, 'adapter manifest hash'),
    approvalRequestId: raw.approval_request_id == null
      ? null
      : text(raw.approval_request_id, 'approval request ID'),
    authoritativeReceiptId: raw.authoritative_receipt_id == null
      ? null
      : text(raw.authoritative_receipt_id, 'authoritative action receipt ID'),
    cancelSupported: raw.cancel_supported === true,
    progress: raw.progress == null ? null : Number(raw.progress),
    safeSummary: raw.safe_summary == null ? null : text(raw.safe_summary, 'safe action summary'),
  };
  if (receipt.actionId !== actionId || receipt.exactActionHash !== exactActionHash) {
    throw new Error('capability receipts do not bind to one exact action');
  }
  if (state !== CapabilityActionState.UNAVAILABLE && !receipt.adapterManifestHash) {
    throw new Error('capability receipt requires a server adapter manifest hash');
  }
  if (state === CapabilityActionState.AWAITING_APPROVAL && !receipt.approvalRequestId) {
    throw new Error('awaiting approval requires a bound approval request ID');
  }
  if (TERMINAL_STATES.has(state) && !receipt.authoritativeReceiptId) {
    throw new Error('terminal capability state requires an authoritative receipt');
  }
  if (
    receipt.progress != null
    && (!Number.isFinite(receipt.progress) || receipt.progress < 0 || receipt.progress > 1)
  ) {
    throw new Error('capability progress must be between zero and one');
  }
  return Object.freeze(receipt);
}

function normalizeHandoff(raw, exactActionHash) {
  if (raw == null) return null;
  if (!raw || typeof raw !== 'object' || raw.decision_in_senses !== false) {
    throw new Error('Senses approval handoff must remain presentation-only');
  }
  const handoffHash = sha256(raw.exact_action_hash, 'handoff exact action hash');
  if (handoffHash !== exactActionHash) {
    throw new Error('approval handoff does not match the exact action');
  }
  const aionuiRoute = text(raw.aionui_route, 'AionUi approval route');
  const telegramCommand = text(raw.telegram_command, 'Telegram approval command');
  if (!aionuiRoute.startsWith('/#/approvals?') || telegramCommand !== '/approvals') {
    throw new Error('approval handoff must target the canonical trusted surfaces');
  }
  return Object.freeze({
    approvalId: text(raw.approval_id, 'handoff approval ID'),
    exactActionHash: handoffHash,
    expiresAt: text(raw.expires_at, 'handoff expiry'),
    decisionInSenses: false,
    aionuiRoute,
    telegramCommand,
  });
}

export function normalizeCapabilityProjection(raw) {
  if (!raw || typeof raw !== 'object' || !Array.isArray(raw.receipts) || !raw.receipts.length) {
    throw new Error('capability projection requires ordered receipts');
  }
  const actionId = text(raw.action_id, 'capability action ID');
  const exactActionHash = sha256(
    raw.receipts[0]?.exact_action_hash,
    'exact action hash',
  );
  const receipts = raw.receipts.map((receipt) => (
    normalizeReceipt(receipt, actionId, exactActionHash)
  ));
  const current = receipts.at(-1);
  if (
    !raw.current
    || raw.current.receipt_id !== current.receiptId
    || raw.current.state !== current.actionState
  ) {
    throw new Error('capability projection current state is not the latest receipt');
  }
  const approvalHandoff = normalizeHandoff(raw.approval_handoff, exactActionHash);
  if (
    current.actionState === CapabilityActionState.AWAITING_APPROVAL
    && (!approvalHandoff || approvalHandoff.approvalId !== current.approvalRequestId)
  ) {
    throw new Error('awaiting approval requires the exact trusted handoff');
  }
  if (
    current.actionState !== CapabilityActionState.AWAITING_APPROVAL
    && approvalHandoff !== null
  ) {
    throw new Error('approval handoff is valid only while awaiting approval');
  }
  return Object.freeze({
    actionId,
    exactActionHash,
    receipts: Object.freeze(receipts),
    current,
    approvalHandoff,
    terminal: TERMINAL_STATES.has(current.actionState),
  });
}

export function createCapabilityProjectionConsumer(dispatch, render) {
  const seenReceiptIds = new Set();
  return Object.freeze({
    consume(raw, values = {}) {
      const projection = normalizeCapabilityProjection(raw);
      const unseen = projection.receipts.filter((receipt) => !seenReceiptIds.has(receipt.receiptId));
      const dispatchable = unseen.length ? unseen : [projection.current];
      for (const receipt of dispatchable) {
        dispatch({ type: 'CAPABILITY_RECEIPT', ...values, ...receipt });
        seenReceiptIds.add(receipt.receiptId);
      }
      render(projection);
      return projection;
    },
    reset() {
      seenReceiptIds.clear();
      render(null);
    },
  });
}
