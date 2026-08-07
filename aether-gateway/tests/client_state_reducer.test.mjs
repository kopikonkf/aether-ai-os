import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  AuthSessionState,
  CapabilityActionState,
  ConsentMode,
  ExternalSpeechConsent,
  ExternalSpeechPrivacy,
  TransportMode,
  TurnDeliveryState,
  TurnState,
  createInitialClientState,
  deriveClientPresentation,
  reduceClientState,
} from '../src/aether_gateway/aionui_senses_console/client_state.js';

const event = (type, values = {}) => ({ type, ...values });

function pairedState() {
  let state = createInitialClientState();
  state = reduceClientState(state, event('PAIRING_REQUESTED'));
  return reduceClientState(state, event('PAIRING_EXCHANGED'));
}

function activeState(mode = TransportMode.FULL_REALTIME) {
  let state = pairedState();
  state = reduceClientState(state, event('CONNECT_REQUESTED'));
  if (mode === TransportMode.FULL_REALTIME) {
    return reduceClientState(state, event('REALTIME_VERIFIED'));
  }
  return reduceClientState(state, event('DEGRADED_VERIFIED', { mode }));
}

test('initial state exposes six orthogonal axes and no overloaded booleans', () => {
  const state = createInitialClientState();

  assert.equal(state.authSession, AuthSessionState.BOOTSTRAP_REQUIRED);
  assert.equal(state.transportMode, TransportMode.OFFLINE);
  assert.equal(state.turn, TurnState.IDLE);
  assert.equal(state.consent.camera.mode, ConsentMode.OFF);
  assert.equal(state.consent.screen.mode, ConsentMode.OFF);
  assert.equal(state.capabilityAction.state, CapabilityActionState.NONE);
  assert.equal(state.externalSpeech.privacy, ExternalSpeechPrivacy.EXTERNAL_ALLOWED);
  assert.equal(state.externalSpeech.consent, ExternalSpeechConsent.MISSING);
  assert.equal('connected' in state, false);
  assert.equal('thinking' in state, false);
  assert.equal('working' in state, false);
});

test('pairing and session transport transitions match the frozen contract', () => {
  let state = createInitialClientState();
  state = reduceClientState(state, event('PAIRING_REQUESTED'));
  assert.equal(state.authSession, AuthSessionState.BOOTSTRAP_PENDING);
  state = reduceClientState(state, event('PAIRING_EXCHANGED'));
  assert.equal(state.authSession, AuthSessionState.READY);
  state = reduceClientState(state, event('CONNECT_REQUESTED'));
  assert.equal(state.authSession, AuthSessionState.CONNECTING);
  assert.equal(deriveClientPresentation(state).systemLabel, 'CONNECTING');
  state = reduceClientState(state, event('REALTIME_VERIFIED'));
  assert.equal(state.authSession, AuthSessionState.ACTIVE_REALTIME);
  assert.equal(state.transportMode, TransportMode.FULL_REALTIME);
  assert.equal(deriveClientPresentation(state).systemLabel, 'LIVE');
});

test('session issuance cannot be presented as connected before verified transport', () => {
  let state = pairedState();
  state = reduceClientState(state, event('CONNECT_REQUESTED'));
  state = reduceClientState(state, event('SESSION_ISSUED'));

  const presentation = deriveClientPresentation(state);
  assert.equal(state.authSession, AuthSessionState.CONNECTING);
  assert.equal(presentation.systemLabel, 'CONNECTING');
  assert.equal(presentation.canSend, false);
});

test('degraded activation requires an exact non-realtime fallback mode', () => {
  let state = pairedState();
  state = reduceClientState(state, event('CONNECT_REQUESTED'));
  assert.throws(
    () => reduceClientState(state, event('DEGRADED_VERIFIED', { mode: TransportMode.FULL_REALTIME })),
    /degraded session requires a verified fallback mode/,
  );
  state = reduceClientState(state, event('DEGRADED_VERIFIED', { mode: TransportMode.TEXT_ONLY }));
  assert.equal(state.authSession, AuthSessionState.ACTIVE_DEGRADED);
  assert.equal(state.transportMode, TransportMode.TEXT_ONLY);
  assert.equal(deriveClientPresentation(state).systemLabel, 'TEXT ONLY');
});

test('turn machine rejects impossible transitions and returns to idle after text output', () => {
  let state = activeState(TransportMode.TEXT_ONLY);
  assert.throws(
    () => reduceClientState(state, event('RESPONSE_AUDIO_STARTED')),
    /invalid turn transition/,
  );
  state = reduceClientState(state, event('TEXT_COMMIT_STARTED'));
  state = reduceClientState(state, event('TURN_ACCEPTED'));
  assert.equal(state.turn, TurnState.THINKING);
  state = reduceClientState(state, event('TEXT_RESPONSE_PRESENTED'));
  assert.equal(state.turn, TurnState.IDLE);
});

test('external speech privacy survives turn boundaries and blocks every speech output', () => {
  let state = activeState(TransportMode.VOICE_FALLBACK);
  state = reduceClientState(state, event('EXTERNAL_SPEECH_PRIVACY_SET', {
    privacy: ExternalSpeechPrivacy.PRIVATE_TEXT_ONLY,
  }));
  state = reduceClientState(state, event('TEXT_COMMIT_STARTED'));
  state = reduceClientState(state, event('TURN_ACCEPTED'));
  state = reduceClientState(state, event('TEXT_RESPONSE_PRESENTED'));

  assert.equal(state.externalSpeech.privacy, ExternalSpeechPrivacy.PRIVATE_TEXT_ONLY);
  assert.equal(deriveClientPresentation(state).canUseExternalSpeech, false);
  assert.equal(deriveClientPresentation(state).canUseBrowserSpeech, false);
  assert.equal(deriveClientPresentation(state).externalSpeechLabel, 'PRIVATE TEXT-ONLY');
});

test('external provider consent requires an authoritative receipt and remains independent of privacy', () => {
  let state = activeState(TransportMode.TEXT_SPEECH);
  assert.throws(
    () => reduceClientState(state, event('EXTERNAL_SPEECH_CONSENT_RECORDED')),
    /authoritative consent receipt/,
  );
  state = reduceClientState(state, event('EXTERNAL_SPEECH_CONSENT_RECORDED', {
    receiptId: 'consent-receipt-1',
  }));
  assert.equal(state.externalSpeech.consent, ExternalSpeechConsent.GRANTED);
  assert.equal(deriveClientPresentation(state).canUseExternalSpeech, true);
  state = reduceClientState(state, event('EXTERNAL_SPEECH_PRIVACY_SET', {
    privacy: ExternalSpeechPrivacy.PRIVATE_TEXT_ONLY,
  }));
  assert.equal(state.externalSpeech.consent, ExternalSpeechConsent.GRANTED);
  assert.equal(deriveClientPresentation(state).canUseExternalSpeech, false);
});

test('camera and screen consent are independent and suspension revokes both', () => {
  let state = activeState();
  state = reduceClientState(state, event('CONSENT_PREVIEW_STARTED', { source: 'camera' }));
  assert.equal(state.consent.camera.mode, ConsentMode.PREVIEW_LOCAL);
  assert.equal(state.consent.screen.mode, ConsentMode.OFF);
  state = reduceClientState(state, event('CONSENT_BOUNDED_GRANTED', {
    source: 'screen',
    consentId: 'screen-consent-1',
    receiptId: 'screen-consent-receipt-1',
    expiresAt: '2026-08-07T10:15:00Z',
    captureIntervalSeconds: 15,
  }));
  assert.equal(state.consent.screen.mode, ConsentMode.BOUNDED);
  state = reduceClientState(state, event('APP_SUSPENDED'));
  assert.equal(state.authSession, AuthSessionState.SUSPENDED);
  assert.equal(state.consent.camera.mode, ConsentMode.OFF);
  assert.equal(state.consent.screen.mode, ConsentMode.OFF);
  assert.equal(state.turn, TurnState.IDLE);
});

test('capability success requires the exact authoritative receipt', () => {
  let state = activeState();
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-1',
    actionState: CapabilityActionState.PROPOSED,
    exactActionHash: 'a'.repeat(64),
  }));
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-1',
    actionState: CapabilityActionState.QUEUED,
    exactActionHash: 'a'.repeat(64),
  }));
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-1',
    actionState: CapabilityActionState.RUNNING,
    exactActionHash: 'a'.repeat(64),
  }));
  assert.throws(
    () => reduceClientState(state, event('CAPABILITY_RECEIPT', {
      actionId: 'action-1',
      actionState: CapabilityActionState.SUCCEEDED,
      exactActionHash: 'a'.repeat(64),
      safeSummary: 'The model says it finished.',
    })),
    /authoritative receipt/,
  );
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-1',
    actionState: CapabilityActionState.SUCCEEDED,
    exactActionHash: 'a'.repeat(64),
    authoritativeReceiptId: 'execution-receipt-1',
  }));
  assert.equal(state.capabilityAction.state, CapabilityActionState.SUCCEEDED);
});

test('disconnect preserves running action truth and marks it stale instead of canceling it', () => {
  let state = activeState();
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-2', actionState: CapabilityActionState.PROPOSED,
    exactActionHash: 'b'.repeat(64),
  }));
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-2', actionState: CapabilityActionState.QUEUED,
    exactActionHash: 'b'.repeat(64),
  }));
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-2', actionState: CapabilityActionState.RUNNING,
    exactActionHash: 'b'.repeat(64),
  }));
  state = reduceClientState(state, event('SESSION_CLOSED'));

  assert.equal(state.capabilityAction.state, CapabilityActionState.RUNNING);
  assert.equal(state.capabilityAction.stale, true);
  assert.equal(state.authSession, AuthSessionState.CLOSED);
});

test('capability action and conversational turn remain orthogonal', () => {
  let state = activeState();
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-3', actionState: CapabilityActionState.PROPOSED,
    exactActionHash: 'c'.repeat(64),
  }));
  state = reduceClientState(state, event('TEXT_COMMIT_STARTED'));
  state = reduceClientState(state, event('TURN_ACCEPTED'));

  assert.equal(state.turn, TurnState.THINKING);
  assert.equal(state.capabilityAction.state, CapabilityActionState.PROPOSED);
});

test('transport loss clears sensor consent and marks action status as last known', () => {
  let state = activeState();
  state = reduceClientState(state, event('CONSENT_PREVIEW_STARTED', { source: 'camera' }));
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-reconnect',
    actionState: CapabilityActionState.PROPOSED,
    exactActionHash: 'd'.repeat(64),
  }));
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-reconnect',
    actionState: CapabilityActionState.QUEUED,
    exactActionHash: 'd'.repeat(64),
  }));
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-reconnect',
    actionState: CapabilityActionState.RUNNING,
    exactActionHash: 'd'.repeat(64),
  }));
  state = reduceClientState(state, event('TRANSPORT_LOST'));

  assert.equal(state.authSession, AuthSessionState.RECONNECTING);
  assert.equal(state.transportMode, TransportMode.STATUS_ONLY);
  assert.equal(state.consent.camera.mode, ConsentMode.OFF);
  assert.equal(state.capabilityAction.state, CapabilityActionState.RUNNING);
  assert.equal(state.capabilityAction.stale, true);
  assert.match(deriveClientPresentation(state).capabilityActionLabel, /LAST KNOWN/);

  state = reduceClientState(state, event('DEGRADED_VERIFIED', {
    mode: TransportMode.TEXT_ONLY,
  }));
  assert.equal(state.authSession, AuthSessionState.ACTIVE_DEGRADED);
});

test('reconciling action cannot be resubmitted and needs a receipt to finish', () => {
  let state = activeState();
  for (const actionState of [
    CapabilityActionState.PROPOSED,
    CapabilityActionState.QUEUED,
    CapabilityActionState.RUNNING,
    CapabilityActionState.RECONCILING,
  ]) {
    state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
      actionId: 'action-ambiguous',
      actionState,
      exactActionHash: 'e'.repeat(64),
    }));
  }
  assert.throws(
    () => reduceClientState(state, event('CAPABILITY_RECEIPT', {
      actionId: 'action-ambiguous',
      actionState: CapabilityActionState.QUEUED,
      exactActionHash: 'e'.repeat(64),
    })),
    /invalid capability action transition/,
  );
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-ambiguous',
    actionState: CapabilityActionState.FAILED,
    exactActionHash: 'e'.repeat(64),
    authoritativeReceiptId: 'reconciliation-receipt-1',
  }));
  assert.equal(state.capabilityAction.state, CapabilityActionState.FAILED);
});

test('capability receipts cannot switch exact actions mid-lifecycle', () => {
  let state = activeState();
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-bound',
    actionState: CapabilityActionState.PROPOSED,
    exactActionHash: 'f'.repeat(64),
  }));
  assert.throws(
    () => reduceClientState(state, event('CAPABILITY_RECEIPT', {
      actionId: 'action-other',
      actionState: CapabilityActionState.QUEUED,
      exactActionHash: '0'.repeat(64),
    })),
    /does not match the active exact action/,
  );
});

test('bounded consent fails closed without source, ID, and expiry', () => {
  const state = activeState();
  assert.throws(
    () => reduceClientState(state, event('CONSENT_PREVIEW_STARTED', { source: 'microphone' })),
    /source must be camera or screen/,
  );
  assert.throws(
    () => reduceClientState(state, event('CONSENT_BOUNDED_GRANTED', {
      source: 'camera',
      consentId: 'camera-consent-1',
      receiptId: 'camera-consent-receipt-1',
    })),
    /requires an expiry/,
  );
  assert.throws(
    () => reduceClientState(state, event('CONSENT_ONE_SHOT_GRANTED', {
      source: 'camera',
    })),
    /requires a consent ID/,
  );
});

test('vision frame and revocation receipts must match the authoritative lease', () => {
  let state = activeState();
  state = reduceClientState(state, event('CONSENT_BOUNDED_GRANTED', {
    source: 'camera',
    consentId: 'camera-consent-2',
    receiptId: 'camera-consent-receipt-2',
    expiresAt: '2026-08-07T10:15:00Z',
    captureIntervalSeconds: 15,
  }));
  assert.throws(
    () => reduceClientState(state, event('CONSENT_FRAME_RECEIPTED', {
      source: 'camera', consentId: 'different', receiptId: 'frame-receipt-1',
      sequenceNumber: 1,
    })),
    /does not match active consent/,
  );
  state = reduceClientState(state, event('CONSENT_FRAME_RECEIPTED', {
    source: 'camera', consentId: 'camera-consent-2', receiptId: 'frame-receipt-1',
    sequenceNumber: 1, capturedAt: '2026-08-07T10:00:00Z',
  }));
  assert.equal(state.consent.camera.sequenceNumber, 1);
  assert.throws(
    () => reduceClientState(state, event('CONSENT_REVOKED', { source: 'camera' })),
    /authoritative receipt/,
  );
  state = reduceClientState(state, event('CONSENT_REVOKED', {
    source: 'camera', receiptId: 'camera-revocation-receipt-1',
  }));
  assert.equal(state.consent.camera.mode, ConsentMode.OFF);
});

test('auth revocation stops sensors without resetting the explicit privacy choice', () => {
  let state = activeState();
  state = reduceClientState(state, event('CONSENT_PREVIEW_STARTED', { source: 'camera' }));
  state = reduceClientState(state, event('EXTERNAL_SPEECH_PRIVACY_SET', {
    privacy: ExternalSpeechPrivacy.PRIVATE_TEXT_ONLY,
  }));
  state = reduceClientState(state, event('AUTH_REVOKED'));

  assert.equal(state.authSession, AuthSessionState.BOOTSTRAP_REQUIRED);
  assert.equal(state.transportMode, TransportMode.OFFLINE);
  assert.equal(state.consent.camera.mode, ConsentMode.OFF);
  assert.equal(state.externalSpeech.privacy, ExternalSpeechPrivacy.PRIVATE_TEXT_ONLY);
});

test('late async events from a revoked session epoch are ignored', () => {
  let state = activeState();
  const staleEpoch = state.epoch;
  state = reduceClientState(state, event('AUTH_REVOKED'));
  assert.equal(state.authSession, AuthSessionState.BOOTSTRAP_REQUIRED);
  assert.equal(state.epoch, staleEpoch + 1);

  const afterLateResult = reduceClientState(state, event('TURN_ACCEPTED', { epoch: staleEpoch }));
  assert.equal(afterLateResult, state);
  assert.equal(afterLateResult.turn, TurnState.IDLE);
  const afterLateReset = reduceClientState(
    afterLateResult,
    event('TURN_RESET', { epoch: staleEpoch }),
  );
  assert.equal(afterLateReset, afterLateResult);
});

test('turn generations bind async results and expose network reconciliation without replay', () => {
  let state = activeState(TransportMode.TEXT_ONLY);
  const epoch = state.epoch;
  state = reduceClientState(state, event('TURN_GENERATION_STARTED', {
    epoch,
    turnId: 'turn-1',
    correlationId: 'corr-1',
    generation: 0,
  }));
  state = reduceClientState(state, event('TURN_NETWORK_AMBIGUOUS', {
    epoch,
    turnId: 'turn-1',
    correlationId: 'corr-1',
    generation: 0,
  }));

  assert.equal(state.activeTurn.delivery, TurnDeliveryState.RECONCILING);
  assert.equal(deriveClientPresentation(state).turnLabel, 'RECONCILING');
  assert.equal(deriveClientPresentation(state).canSend, false);

  const stale = reduceClientState(state, event('TURN_RESULT_RECEIVED', {
    epoch,
    turnId: 'turn-1',
    correlationId: 'corr-1',
    generation: 1,
    authoritativeReceiptId: 'turn-receipt-1',
  }));
  assert.equal(stale, state);
});

test('worker turn adoption replaces stale UI identity and terminal status is receipt-bound', () => {
  let state = activeState();
  const epoch = state.epoch;
  state = reduceClientState(state, event('TURN_GENERATION_ADOPTED', {
    epoch,
    turnId: 'worker-turn-1',
    correlationId: 'worker-corr-1',
    generation: 0,
  }));
  state = reduceClientState(state, event('TURN_GENERATION_ADOPTED', {
    epoch,
    turnId: 'worker-turn-2',
    correlationId: 'worker-corr-2',
    generation: 0,
  }));
  const stale = reduceClientState(state, event('TURN_RECONCILED', {
    epoch,
    turnId: 'worker-turn-1',
    correlationId: 'worker-corr-1',
    generation: 0,
    status: 'completed',
    authoritativeReceiptId: 'old-receipt',
  }));
  assert.equal(stale, state);

  state = reduceClientState(state, event('TURN_RECONCILED', {
    epoch,
    turnId: 'worker-turn-2',
    correlationId: 'worker-corr-2',
    generation: 1,
    status: 'interrupted',
    authoritativeReceiptId: 'interrupt-receipt',
  }));
  assert.equal(state.activeTurn.generation, 1);
  assert.equal(state.activeTurn.delivery, TurnDeliveryState.INTERRUPTED);
  assert.equal(state.turn, TurnState.IDLE);
});

test('speech interruption advances turn generation but never cancels a capability action', () => {
  let state = activeState();
  const epoch = state.epoch;
  state = reduceClientState(state, event('CAPABILITY_RECEIPT', {
    actionId: 'action-voice-independent',
    actionState: CapabilityActionState.PROPOSED,
    exactActionHash: 'a'.repeat(64),
  }));
  state = reduceClientState(state, event('TURN_GENERATION_STARTED', {
    epoch,
    turnId: 'turn-voice',
    correlationId: 'corr-voice',
    generation: 0,
  }));
  state = reduceClientState(state, event('TURN_ACCEPTED', {
    epoch,
    turnId: 'turn-voice',
    correlationId: 'corr-voice',
    generation: 0,
  }));
  state = reduceClientState(state, event('RESPONSE_AUDIO_STARTED', {
    epoch,
    turnId: 'turn-voice',
    correlationId: 'corr-voice',
    generation: 0,
  }));
  state = reduceClientState(state, event('INTERRUPT_REQUESTED', {
    epoch,
    turnId: 'turn-voice',
    correlationId: 'corr-voice',
    previousGeneration: 0,
    nextGeneration: 1,
  }));

  assert.equal(state.turn, TurnState.INTERRUPTING);
  assert.equal(state.activeTurn.generation, 1);
  assert.equal(state.capabilityAction.state, CapabilityActionState.PROPOSED);

  state = reduceClientState(state, event('INTERRUPT_ACKNOWLEDGED', {
    epoch,
    turnId: 'turn-voice',
    correlationId: 'corr-voice',
    generation: 1,
    authoritativeReceiptId: 'interrupt-receipt-1',
  }));
  assert.equal(state.turn, TurnState.IDLE);
  assert.equal(state.activeTurn.delivery, TurnDeliveryState.INTERRUPTED);
  assert.equal(state.capabilityAction.state, CapabilityActionState.PROPOSED);
});

test('unconfirmed turn enables only an explicit linked retry', () => {
  let state = activeState(TransportMode.TEXT_ONLY);
  const epoch = state.epoch;
  state = reduceClientState(state, event('TURN_GENERATION_STARTED', {
    epoch,
    turnId: 'turn-uncertain',
    correlationId: 'corr-uncertain',
    generation: 0,
  }));
  state = reduceClientState(state, event('TURN_NETWORK_AMBIGUOUS', {
    epoch,
    turnId: 'turn-uncertain',
    correlationId: 'corr-uncertain',
    generation: 0,
  }));
  state = reduceClientState(state, event('TURN_NOT_CONFIRMED', {
    epoch,
    turnId: 'turn-uncertain',
    correlationId: 'corr-uncertain',
    generation: 0,
  }));

  const presentation = deriveClientPresentation(state);
  assert.equal(state.activeTurn.delivery, TurnDeliveryState.NOT_CONFIRMED);
  assert.equal(state.turn, TurnState.IDLE);
  assert.equal(presentation.canRetryTurn, true);
  assert.equal(presentation.canSend, false);
});

test('late IndexedDB device-key load cannot replace an in-flight pairing state', () => {
  let state = createInitialClientState();
  state = reduceClientState(state, event('PAIRING_REQUESTED'));
  const afterLateKey = reduceClientState(state, event('DEVICE_CREDENTIAL_LOADED'));

  assert.equal(afterLateKey, state);
  assert.equal(afterLateKey.authSession, AuthSessionState.BOOTSTRAP_PENDING);
});

test('invalid auth transitions fail closed', () => {
  const state = createInitialClientState();
  assert.throws(
    () => reduceClientState(state, event('PAIRING_EXCHANGED')),
    /invalid auth\/session transition/,
  );
  assert.throws(
    () => reduceClientState(state, event('CONNECT_REQUESTED')),
    /invalid auth\/session transition/,
  );
});

test('Senses shell renders all reducer axes and a private text-only control', async () => {
  const html = await readFile(
    new URL('../src/aether_gateway/aionui_senses_console/index.html', import.meta.url),
    'utf8',
  );

  for (const id of [
    'authState',
    'transportModeState',
    'turnState',
    'consentState',
    'actionState',
    'externalSpeechState',
    'privateTextOnly',
    'stopAether',
    'retryTurn',
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
});

test('Senses app is wired only through the reducer presentation boundary', async () => {
  const app = await readFile(
    new URL('../src/aether_gateway/aionui_senses_console/app.js', import.meta.url),
    'utf8',
  );

  assert.match(app, /from '.\/client_state\.js'/);
  assert.match(app, /from '.\/turn_generation\.js'/);
  assert.match(app, /clientStore\.dispatch/);
  assert.match(app, /deriveClientPresentation/);
  assert.match(app, /reconcileAmbiguousTurn/);
  assert.match(app, /interruptActiveTurn/);
  assert.doesNotMatch(app, /function setState\s*\(/);
  assert.doesNotMatch(app, /state\.paired/);
  assert.doesNotMatch(app, /\bconnected\s*:/);
  assert.doesNotMatch(app, /\bthinking\s*:/);
  assert.doesNotMatch(app, /\bworking\s*:/);
});

test('canonical handoff records slice six boundaries and the next slice', async () => {
  const handoff = await readFile(
    new URL('../../LASTSTANDINGPOINT.md', import.meta.url),
    'utf8',
  );

  assert.match(handoff, /Implementation slice 5 is source-present/);
  assert.match(handoff, /Implementation slice 6 is source-present/);
  assert.match(handoff, /merely because slices 1-6 are source-present/);
  assert.match(handoff, /late-result-discarded/);
  assert.match(handoff, /never submitted again automatically/);
  assert.match(handoff, /server-authoritative consent leases/);
  assert.match(handoff, /VisionFrameReceipt` no longer requires/);
  assert.match(handoff, /Bundle browser dependencies/);
  assert.match(handoff, /Conversational interruption remains orthogonal/);
});
