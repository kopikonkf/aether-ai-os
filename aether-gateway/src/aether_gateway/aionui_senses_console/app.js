import {
  AuthSessionState,
  ExternalSpeechPrivacy,
  TransportMode,
  TurnState,
  createClientStore,
  deriveClientPresentation,
} from './client_state.js?v=senses-v1-slice-9-20260808-1';
import {
  createCapabilityProjectionConsumer,
} from './capability_actions.js?v=senses-v1-slice-9-20260808-1';
import {
  createTurnGenerationCoordinator,
  stopTurnAudio,
} from './turn_generation.js?v=senses-v1-slice-9-20260808-1';
import { createVisionCaptureCoordinator } from './vision_capture.js?v=senses-v1-slice-9-20260808-1';
import {
  CACHE_PREFIX,
  PWA_BUILD_ID,
} from './pwa_cache_policy.js?v=senses-v1-slice-9-20260808-1';
import {
  PwaLifecycleState,
  createInitialPwaRuntime,
  derivePwaPresentation,
  reducePwaRuntime,
} from './pwa_runtime.js?v=senses-v1-slice-9-20260808-1';

const $ = (id) => document.getElementById(id);
const state = {
  room: null,
  localStream: null,
  csrfNonce: '',
  session: null,
  livekit: null,
  deviceKey: null,
  bootstrap: null,
  pairingTimer: null,
  pairingPollInFlight: false,
  heartbeatTimer: null,
  micEnabled: false,
  cameraEnabled: false,
  screenStream: null,
  screenEnabled: false,
  visionTimers: { camera: null, screen: null },
  visionCountdownTimer: null,
  fallbackRecognition: null,
  remoteAudioElements: new Set(),
  remoteAudioTracks: new Set(),
  activeRequestController: null,
  lastUnconfirmedInput: null,
  voices: [],
  voiceProfile: {
    name: '__auto__',
    lang: 'id-ID',
    rate: 1.02,
    pitch: 1.12,
    volume: 1,
  },
  installPrompt: null,
  updateRegistration: null,
  reloadForUpdate: false,
  suspendClosePromise: null,
  capabilityPollTimer: null,
  capabilityProjection: null,
  capabilityAmbiguity: null,
  capabilityCancelAttemptedActions: new Set(),
};
const API = '';
const TURN_STATE_TOPIC = 'aether.senses.turn-state.v1';
const TURN_REQUEST_TIMEOUT_MS = 30000;
const RECONCILIATION_DELAYS_MS = Object.freeze([0, 1000, 3000]);
const CAPABILITY_POLL_INTERVAL_MS = 1500;
const CAPABILITY_STATUS_TIMEOUT_MS = 8000;
const CAPABILITY_CONTROL_TIMEOUT_MS = 10000;
const turnCoordinator = createTurnGenerationCoordinator();
const visionCoordinator = createVisionCaptureCoordinator();
let pwaRuntime = createInitialPwaRuntime({
  online: navigator.onLine,
  visible: document.visibilityState === 'visible',
  controlled: Boolean(navigator.serviceWorker?.controller),
});

function message(role, text) {
  const node = document.createElement('div');
  node.className = `message ${role}`;
  node.textContent = text;
  $('messages').appendChild(node);
  $('messages').scrollTop = $('messages').scrollHeight;
}

function setTransportMessage(text) {
  $('transportStatus').textContent = text;
}

function renderClientState(clientState) {
  const presentation = deriveClientPresentation(clientState);
  const pwa = derivePwaPresentation(pwaRuntime);
  const foreground = pwaRuntime.lifecycle === PwaLifecycleState.FOREGROUND;
  $('systemState').className = `pill ${pwa.aetherAvailable ? presentation.systemClass : 'offline'}`;
  $('systemState').textContent = pwa.aetherAvailable
    ? presentation.systemLabel
    : pwa.label;
  $('pwaRuntimeState').textContent = pwa.label;
  $('pwaRuntimeBanner').classList.toggle('offline', !pwaRuntime.online);
  $('pwaRuntimeBanner').classList.toggle('suspended', pwa.resumeRequired);
  $('resumeSenses').hidden = !pwa.resumeRequired;
  $('authState').textContent = presentation.authLabel;
  $('transportModeState').textContent = presentation.transportLabel;
  $('turnState').textContent = presentation.turnLabel;
  $('consentState').textContent = presentation.consentLabel;
  $('actionState').textContent = presentation.capabilityActionLabel;
  $('externalSpeechState').textContent = presentation.externalSpeechLabel;
  $('pairingState').textContent = presentation.authLabel;

  $('pairButton').disabled = (
    !presentation.canPair
    || clientState.authSession === AuthSessionState.BOOTSTRAP_PENDING
    || !foreground
  );
  $('connectButton').disabled = !presentation.canConnect || !state.deviceKey || !foreground;
  $('disconnectButton').disabled = ![
    AuthSessionState.CONNECTING,
    AuthSessionState.ACTIVE_REALTIME,
    AuthSessionState.ACTIVE_DEGRADED,
    AuthSessionState.RECONNECTING,
    AuthSessionState.SUSPENDED,
  ].includes(clientState.authSession);
  $('fallbackTalk').disabled = !presentation.canSend || !pwa.canSend;
  $('cameraButton').disabled = (
    (!presentation.canUseSensors || !pwa.sensorsAllowed) && !state.cameraEnabled
  );
  $('visionButton').disabled = (
    !presentation.canUseSensors || !pwa.sensorsAllowed || !state.cameraEnabled
  );
  $('screenButton').disabled = (
    (!presentation.canUseSensors || !pwa.sensorsAllowed) && !state.screenEnabled
  );
  $('screenVisionButton').disabled = (
    !presentation.canUseSensors || !pwa.sensorsAllowed || !state.screenEnabled
  );
  $('chatInput').disabled = !presentation.canSend || !pwa.canSend;
  $('chatForm').querySelector('button[type="submit"]').disabled = (
    !presentation.canSend || !pwa.canSend
  );
  $('stopAether').disabled = !presentation.canStopTurn;
  const cancelAttempted = state.capabilityCancelAttemptedActions.has(
    clientState.capabilityAction.actionId,
  );
  $('cancelCapabilityAction').hidden = !presentation.canCancelAction && !cancelAttempted;
  $('cancelCapabilityAction').disabled = !presentation.canCancelAction || cancelAttempted;
  $('retryTurn').hidden = !(presentation.canRetryTurn && state.lastUnconfirmedInput);
  $('retryTurn').disabled = !(presentation.canRetryTurn && state.lastUnconfirmedInput);
  $('previewVoice').disabled = !presentation.canUseBrowserSpeech || !pwa.sensorsAllowed;
  $('privateTextOnly').checked = (
    clientState.externalSpeech.privacy === ExternalSpeechPrivacy.PRIVATE_TEXT_ONLY
  );
}

const clientStore = createClientStore(renderClientState);

function dispatch(type, values = {}) {
  return clientStore.dispatch({ type, ...values });
}

function dispatchPwa(type, values = {}) {
  pwaRuntime = reducePwaRuntime(pwaRuntime, { type, ...values });
  renderClientState(clientStore.getState());
  return pwaRuntime;
}

function markAetherAvailable() {
  dispatchPwa('AETHER_VERIFIED_AVAILABLE');
}

function markAetherUnavailable() {
  if (pwaRuntime.aetherVerified) dispatchPwa('AETHER_UNAVAILABLE');
}

function dispatchForEpoch(type, epoch, values = {}) {
  return clientStore.dispatch({ type, epoch, ...values });
}

function renderCapabilityProjection(projection) {
  const visible = Boolean(projection);
  state.capabilityProjection = projection || null;
  $('capabilityActionPanel').hidden = !visible;
  if (!visible) {
    $('capabilityControlStatus').textContent = (
      'Cancellation is separate from Stop Aether and requires an exact receipt-bound action.'
    );
    return;
  }
  const current = projection.current;
  $('capabilityName').textContent = current.capabilityName;
  $('capabilitySummary').textContent = current.safeSummary || current.capabilityName;
  $('capabilityReceiptState').textContent = current.actionState.toUpperCase().replaceAll('-', ' ');
  $('capabilityReceiptId').textContent = current.authoritativeReceiptId || current.receiptId;
  $('capabilityActionHash').textContent = current.exactActionHash;
  $('capabilityProgress').textContent = current.progress == null
    ? 'receipt only'
    : `${Math.round(current.progress * 100)}%`;
  if (current.reconciliationStatus === 'not-confirmed') {
    $('capabilityControlStatus').textContent = (
      'NOT CONFIRMED — Aether is looking up this action ID only; it will not replay or resubmit it.'
    );
  } else if (current.cancellationStatus === 'not-confirmed') {
    $('capabilityControlStatus').textContent = (
      'Cancel outcome is NOT CONFIRMED. The cancel intent will not be submitted again.'
    );
  } else if (current.cancellationStatus === 'unsupported') {
    $('capabilityControlStatus').textContent = (
      'This capability does not provide an authoritative cancellation acknowledgement.'
    );
  } else if (current.actionState === 'canceled') {
    $('capabilityControlStatus').textContent = 'Cancellation confirmed by the executor receipt.';
  } else if (current.cancelSupported && current.actionState === 'running') {
    $('capabilityControlStatus').textContent = (
      'Cancel is available for this exact action. Stop Aether still affects speech/turn only.'
    );
  } else {
    $('capabilityControlStatus').textContent = (
      'No cancel claim is available for the current receipt.'
    );
  }
  const handoff = projection.approvalHandoff;
  $('approvalHandoff').hidden = !handoff;
  if (handoff) {
    $('approvalExpiry').textContent = handoff.expiresAt;
    $('aionuiApprovalLink').href = handoff.aionuiRoute;
    $('telegramApprovalCommand').textContent = handoff.telegramCommand;
  }
}

const capabilityConsumer = createCapabilityProjectionConsumer(
  (event) => clientStore.dispatch(event),
  renderCapabilityProjection,
);

function stopCapabilityPolling() {
  clearTimeout(state.capabilityPollTimer);
  state.capabilityPollTimer = null;
}

function capabilityControlId(prefix) {
  return `${prefix}.${crypto.randomUUID()}`;
}

function markCapabilityNetworkAmbiguous(actionId) {
  const current = state.capabilityProjection?.current;
  if (
    !current
    || current.actionId !== actionId
    || current.actionState !== 'running'
    || state.capabilityAmbiguity?.actionId === actionId
  ) return;
  state.capabilityAmbiguity = {
    actionId,
    controlRequestId: capabilityControlId('reconcile'),
    observedReceiptId: current.receiptId,
    exactActionHash: current.exactActionHash,
  };
  message(
    'system',
    'Capability status became network-ambiguous. Aether will look up the same action ID; it will not replay or resubmit execution.',
  );
}

async function recordCapabilityReconciliation(projection, epoch) {
  const ambiguity = state.capabilityAmbiguity;
  if (
    !ambiguity
    || ambiguity.actionId !== projection.actionId
    || projection.current.actionState !== 'running'
  ) return projection;
  // Mark before I/O. Even an ambiguous response never causes this control POST
  // or the underlying action execution to be submitted again automatically.
  state.capabilityAmbiguity = null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), CAPABILITY_CONTROL_TIMEOUT_MS);
  try {
    const raw = await jsonFetch(
      `${API}/api/browser-senses/actions/${encodeURIComponent(projection.actionId)}/reconcile`,
      {
        method: 'POST',
        headers: authHeaders(),
        signal: controller.signal,
        body: JSON.stringify({
          control_request_id: ambiguity.controlRequestId,
          expected_action_hash: ambiguity.exactActionHash,
          observed_receipt_id: ambiguity.observedReceiptId,
        }),
      },
    );
    return capabilityConsumer.consume(raw, { epoch });
  } catch (error) {
    if (error.status !== 401) {
      message(
        'system',
        `Capability reconciliation receipt was not confirmed: ${error.message}. Status lookup continues without resubmission.`,
      );
    }
    return projection;
  } finally {
    clearTimeout(timeout);
  }
}

async function pollCapabilityAction(actionId, epoch) {
  if (!state.session || clientStore.getEpoch() !== epoch) return;
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, CAPABILITY_STATUS_TIMEOUT_MS);
  try {
    const raw = await jsonFetch(
      `${API}/api/browser-senses/actions/${encodeURIComponent(actionId)}/status`,
      { method: 'POST', headers: authHeaders(), signal: controller.signal },
    );
    if (!state.session || clientStore.getEpoch() !== epoch) return;
    let projection = capabilityConsumer.consume(raw, { epoch });
    projection = await recordCapabilityReconciliation(projection, epoch);
    if (projection.terminal) {
      state.capabilityAmbiguity = null;
      stopCapabilityPolling();
      return;
    }
  } catch (error) {
    if (error.status === 401) return;
    if (isAmbiguousNetworkError(error, timedOut)) {
      markCapabilityNetworkAmbiguous(actionId);
    }
    message('system', `Capability receipt refresh failed: ${error.message}`);
  } finally {
    clearTimeout(timeout);
  }
  state.capabilityPollTimer = setTimeout(
    () => pollCapabilityAction(actionId, epoch),
    CAPABILITY_POLL_INTERVAL_MS,
  );
}

function presentCapabilityActions(rawActions, epoch) {
  if (!Array.isArray(rawActions) || !rawActions.length) return;
  if (rawActions.length !== 1) {
    throw new Error('Senses received more than one active capability projection');
  }
  const nextActionId = String(rawActions[0]?.action_id || '');
  const current = clientStore.getState().capabilityAction;
  if (current.actionId && current.actionId !== nextActionId) {
    if (!['succeeded', 'failed', 'canceled', 'rejected', 'unavailable'].includes(current.state)) {
      throw new Error('A prior capability action is still non-terminal');
    }
    dispatchForEpoch('CAPABILITY_CLEARED', epoch);
    capabilityConsumer.reset();
    state.capabilityAmbiguity = null;
  }
  const projection = capabilityConsumer.consume(rawActions[0], { epoch });
  stopCapabilityPolling();
  if (!projection.terminal) {
    state.capabilityPollTimer = setTimeout(
      () => pollCapabilityAction(projection.actionId, epoch),
      CAPABILITY_POLL_INTERVAL_MS,
    );
  }
}

async function cancelCapabilityAction() {
  const projection = state.capabilityProjection;
  const clientState = clientStore.getState();
  const presentation = deriveClientPresentation(clientState);
  if (
    !projection
    || projection.actionId !== clientState.capabilityAction.actionId
    || !presentation.canCancelAction
  ) {
    throw new Error('The current authoritative receipt does not allow cancellation.');
  }
  if (state.capabilityCancelAttemptedActions.has(projection.actionId)) {
    throw new Error('Cancel was already requested once; Aether will not resubmit it.');
  }
  const controlRequestId = capabilityControlId('cancel');
  state.capabilityCancelAttemptedActions.add(projection.actionId);
  renderClientState(clientState);
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, CAPABILITY_CONTROL_TIMEOUT_MS);
  try {
    const raw = await jsonFetch(
      `${API}/api/browser-senses/actions/${encodeURIComponent(projection.actionId)}/cancel`,
      {
        method: 'POST',
        headers: authHeaders(),
        signal: controller.signal,
        body: JSON.stringify({
          control_request_id: controlRequestId,
          expected_action_hash: projection.exactActionHash,
          reason: 'founder-explicit-cancel',
        }),
      },
    );
    const next = capabilityConsumer.consume(raw, { epoch: clientStore.getEpoch() });
    if (next.terminal) stopCapabilityPolling();
    return next;
  } catch (error) {
    if (isAmbiguousNetworkError(error, timedOut)) {
      message(
        'system',
        'Cancel response is NOT CONFIRMED. The exact cancel intent will not be posted again; receipt polling continues.',
      );
      return null;
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function turnEvent(turn, values = {}) {
  return {
    turnId: turn.turnId,
    correlationId: turn.correlationId,
    generation: turn.generation,
    ...values,
  };
}

function turnRequestFields(turn) {
  return {
    turn_id: turn.turnId,
    correlation_id: turn.correlationId,
    generation: turn.generation,
    retry_of_turn_id: turn.retryOfTurnId || null,
  };
}

function normalizedTurnStatus(status) {
  return {
    ...status,
    turnId: status.turn_id,
    correlationId: status.correlation_id,
  };
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function resumeRemoteAudio() {
  if (!state.room || state.remoteAudioElements.size) return;
  for (const track of state.remoteAudioTracks) {
    const element = track.attach();
    element.autoplay = true;
    state.remoteAudioElements.add(element);
    $('remoteAudio').appendChild(element);
  }
}

async function lookupTurnStatus(turn) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    return await jsonFetch(
      `${API}/api/browser-senses/turns/${encodeURIComponent(turn.turnId)}/status`,
      { method: 'POST', headers: authHeaders(), signal: controller.signal },
    );
  } finally {
    clearTimeout(timeout);
  }
}

function stopAutoVision(source) {
  clearInterval(state.visionTimers[source]);
  state.visionTimers[source] = null;
  $(source === 'camera' ? 'autoVision' : 'autoScreenVision').checked = false;
}

function stopAllAutoVision() {
  stopAutoVision('camera');
  stopAutoVision('screen');
  clearInterval(state.visionCountdownTimer);
  state.visionCountdownTimer = null;
}

function stopLocalCapture() {
  stopAllAutoVision();
  visionCoordinator.stop('camera');
  visionCoordinator.stop('screen');
  state.localStream?.getTracks().forEach((track) => track.stop());
  state.localStream = null;
  state.cameraEnabled = false;
  state.screenStream?.getTracks().forEach((track) => track.stop());
  state.screenStream = null;
  state.screenEnabled = false;
  state.fallbackRecognition?.abort?.();
  state.fallbackRecognition = null;
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
  for (const element of state.remoteAudioElements) {
    element.pause?.();
    element.srcObject = null;
    element.remove?.();
  }
  state.remoteAudioElements.clear();
  for (const track of state.remoteAudioTracks) track.detach?.();
  state.remoteAudioTracks.clear();
}

function clearSessionRuntime() {
  clearInterval(state.heartbeatTimer);
  state.heartbeatTimer = null;
  stopCapabilityPolling();
  state.capabilityAmbiguity = null;
  stopLocalCapture();
  state.room?.disconnect();
  state.room = null;
  state.csrfNonce = '';
  state.session = null;
  state.livekit = null;
  state.activeRequestController?.abort();
  state.activeRequestController = null;
  state.lastUnconfirmedInput = null;
  turnCoordinator.reset();
  state.micEnabled = false;
  $('micButton').disabled = true;
  $('micButton').textContent = 'Mute microphone';
  $('orb').classList.remove('active');
  $('voiceState').textContent = 'not started';
  $('cameraState').textContent = 'not started';
  $('cameraButton').textContent = 'Enable camera';
  $('localVideo').srcObject = null;
  $('screenState').textContent = 'not started';
  $('screenButton').textContent = 'Enable screen preview';
  $('screenVideo').srcObject = null;
  $('sessionLabel').textContent = 'no session';
}

async function clearManagedPwaCaches() {
  navigator.serviceWorker?.controller?.postMessage({ type: 'AETHER_CLEAR_CACHES' });
  if (!('caches' in window)) return;
  const names = await caches.keys();
  await Promise.all(
    names
      .filter((name) => name.startsWith(CACHE_PREFIX))
      .map((name) => caches.delete(name)),
  );
}

function closeSessionBestEffort(reason) {
  if (!state.session || !state.csrfNonce || !navigator.onLine) {
    return null;
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1500);
  return fetch(`${API}/api/browser-senses/session/close`, {
    method: 'POST',
    credentials: 'same-origin',
    keepalive: true,
    signal: controller.signal,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify({ reason }),
  }).catch(() => {}).finally(() => clearTimeout(timeout));
}

function expireLocalSession(text) {
  clearSessionRuntime();
  markAetherUnavailable();
  clearManagedPwaCaches().catch(() => {});
  if ([
    AuthSessionState.CONNECTING,
    AuthSessionState.ACTIVE_REALTIME,
    AuthSessionState.ACTIVE_DEGRADED,
    AuthSessionState.RECONNECTING,
    AuthSessionState.SUSPENDED,
  ].includes(clientStore.getState().authSession)) {
    dispatch('SESSION_CLOSED');
  }
  setTransportMessage(text);
  message('system', text);
}

function invalidatePairedDevice(text) {
  clearSessionRuntime();
  markAetherUnavailable();
  clearManagedPwaCaches().catch(() => {});
  state.deviceKey = null;
  removeDeviceKey().catch(() => {});
  dispatch('AUTH_REVOKED');
  setTransportMessage(text);
  pairingView(
    'The device or session credential expired or was revoked. Pair this browser again.',
  );
  message('system', text);
}

async function jsonFetch(url, options = {}) {
  const { authFailure = 'session', ...requestOptions } = options;
  const response = await fetch(url, {
    credentials: 'same-origin',
    ...requestOptions,
    headers: {
      'Content-Type': 'application/json',
      ...(requestOptions.headers || {}),
    },
  });
  let data = {};
  try {
    data = await response.json();
  } catch {
    // Empty error bodies are represented by the HTTP status below.
  }
  if (!response.ok) {
    const error = new Error(
      data.detail?.message
      || data.detail
      || data.error
      || `${response.status} ${response.statusText}`,
    );
    error.status = response.status;
    if (response.status === 401) {
      if (authFailure === 'device') {
        invalidatePairedDevice(
          'Paired-device authentication failed or was revoked. Capture stopped.',
        );
      } else if (authFailure === 'session') {
        expireLocalSession('Senses session expired or was revoked. Capture stopped.');
      }
    }
    throw error;
  }
  return data;
}

function authHeaders() {
  return state.csrfNonce ? { 'X-Aether-CSRF': state.csrfNonce } : {};
}

async function reportTrack(trackSid, kind, source, muted = false) {
  if (!state.session) return;
  try {
    await jsonFetch(`${API}/api/browser-senses/tracks`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        track_sid: trackSid,
        kind,
        source,
        muted,
      }),
    });
  } catch (error) {
    message('system', `Track receipt failed: ${error.message}`);
  }
}

function bytesToB64url(value) {
  return btoa(String.fromCharCode(...new Uint8Array(value)))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replaceAll('=', '');
}

function bytesToHex(value) {
  return Array.from(
    new Uint8Array(value),
    (byte) => byte.toString(16).padStart(2, '0'),
  ).join('');
}

function randomBytes(size) {
  const value = new Uint8Array(size);
  crypto.getRandomValues(value);
  return value;
}

async function signChallenge(challenge) {
  if (!state.deviceKey) {
    throw new Error('This browser has no paired device key. Pair it again.');
  }
  const signature = await crypto.subtle.sign(
    { name: 'ECDSA', hash: 'SHA-256' },
    state.deviceKey,
    new TextEncoder().encode(challenge),
  );
  return bytesToB64url(signature);
}

function openDeviceDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('aether-senses-v1', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('device-keys');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function saveDeviceKey(key) {
  const db = await openDeviceDb();
  await new Promise((resolve, reject) => {
    const transaction = db.transaction('device-keys', 'readwrite');
    transaction.objectStore('device-keys').put(key, 'founder-device-key');
    transaction.oncomplete = resolve;
    transaction.onerror = () => reject(transaction.error);
  });
  db.close();
}

async function loadDeviceKey() {
  try {
    const db = await openDeviceDb();
    const key = await new Promise((resolve, reject) => {
      const transaction = db.transaction('device-keys', 'readonly');
      const request = transaction.objectStore('device-keys').get('founder-device-key');
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => reject(request.error);
    });
    db.close();
    return key;
  } catch {
    return null;
  }
}

async function removeDeviceKey() {
  const db = await openDeviceDb();
  await new Promise((resolve, reject) => {
    const transaction = db.transaction('device-keys', 'readwrite');
    transaction.objectStore('device-keys').delete('founder-device-key');
    transaction.oncomplete = resolve;
    transaction.onerror = () => reject(transaction.error);
  });
  db.close();
}

function pairingView(text) {
  $('pairingHint').textContent = text;
}

async function createDeviceKey() {
  const pair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' },
    false,
    ['sign', 'verify'],
  );
  const publicJwk = await crypto.subtle.exportKey('jwk', pair.publicKey);
  return { privateKey: pair.privateKey, publicJwk };
}

async function requestPairing() {
  if (!window.isSecureContext) {
    throw new Error('Device pairing requires an HTTPS secure context.');
  }
  dispatch('PAIRING_REQUESTED');
  pairingView('Creating an origin-bound pairing request…');
  const generated = await createDeviceKey();
  const verifier = randomBytes(32);
  const verifierHash = bytesToHex(await crypto.subtle.digest('SHA-256', verifier));
  const result = await jsonFetch(`${API}/api/browser-senses/bootstrap/requests`, {
    method: 'POST',
    authFailure: 'none',
    body: JSON.stringify({
      device_label: $('deviceLabel').value.trim() || 'Dee browser',
      client_mode: window.matchMedia('(display-mode: standalone)').matches
        ? 'pwa'
        : 'browser',
      capabilities: ['text', 'microphone', 'speaker', 'camera', 'screen-share'],
      public_key_jwk: generated.publicJwk,
      verifier_hash: verifierHash,
    }),
  });
  state.deviceKey = generated.privateKey;
  state.bootstrap = { ...result, verifier };
  $('pairingCode').hidden = false;
  $('pairingCode').textContent = result.confirmation_code;
  pairingView(
    `Confirm code ${result.confirmation_code} in Dee's trusted approval surface. `
    + 'This request expires in 120 seconds.',
  );
  clearInterval(state.pairingTimer);
  state.pairingTimer = setInterval(
    () => pollPairingOnce().catch((error) => pairingFailed(error.message)),
    1500,
  );
}

async function pollPairingOnce() {
  if (state.pairingPollInFlight) return;
  state.pairingPollInFlight = true;
  try {
    await pollPairing();
  } finally {
    state.pairingPollInFlight = false;
  }
}

function pairingFailed(text) {
  clearInterval(state.pairingTimer);
  state.pairingTimer = null;
  state.pairingPollInFlight = false;
  state.bootstrap = null;
  if (clientStore.getState().authSession === AuthSessionState.BOOTSTRAP_PENDING) {
    state.deviceKey = null;
    dispatch('PAIRING_FAILED');
  }
  $('pairingCode').hidden = true;
  pairingView(text);
}

async function pollPairing() {
  if (!state.bootstrap) return;
  const status = await jsonFetch(
    `${API}/api/browser-senses/bootstrap/requests/`
      + `${encodeURIComponent(state.bootstrap.bootstrap_id)}/status`,
    {
      method: 'POST',
      authFailure: 'none',
      headers: { 'X-Aether-Bootstrap-Proof': state.bootstrap.client_proof },
    },
  );
  if (status.state === 'pending') return;
  if (status.state === 'denied' || status.state === 'expired') {
    pairingFailed(`Pairing ${status.state}. Request a new pairing.`);
    return;
  }
  if (status.state === 'exchanged') {
    pairingFailed('This single-use exchange was already consumed. Pair this browser again.');
    return;
  }
  if (status.state !== 'approved') return;

  const challenge = status.exchange_challenge || state.bootstrap.exchange_challenge;
  const exchanged = await jsonFetch(
    `${API}/api/browser-senses/bootstrap/requests/`
      + `${encodeURIComponent(state.bootstrap.bootstrap_id)}/exchange`,
    {
      method: 'POST',
      authFailure: 'none',
      headers: { 'X-Aether-Bootstrap-Proof': state.bootstrap.client_proof },
      body: JSON.stringify({
        verifier: bytesToB64url(state.bootstrap.verifier),
        device_signature: await signChallenge(challenge),
      }),
    },
  );
  try {
    await saveDeviceKey(state.deviceKey);
  } catch {
    message(
      'system',
      'Persistent WebCrypto storage is unavailable. Pairing remains session-only.',
    );
  }
  clearInterval(state.pairingTimer);
  state.pairingTimer = null;
  state.pairingPollInFlight = false;
  state.bootstrap = null;
  $('pairingCode').hidden = true;
  dispatch('PAIRING_EXCHANGED');
  pairingView(
    `Device ${exchanged.device.device_id} is paired. `
    + 'Sensors remain off until Connect senses.',
  );
}

function loadVoiceProfile() {
  // Voice preferences are session-only and are not persisted.
}

function voiceScore(voice) {
  const name = voice.name.toLowerCase();
  const lang = (voice.lang || '').toLowerCase();
  let score = 0;
  if (lang === 'id-id') score += 120;
  else if (lang.startsWith('id')) score += 100;
  if (name.includes('microsoft gadis')) score += 100;
  if (name.includes('aoede')) score += 95;
  if (name.includes('google') && name.includes('bahasa indonesia')) score += 90;
  if (/female|woman|gadis|zira|aria|jenny|natasha|siti|damayanti|catherine|samantha/.test(name)) {
    score += 55;
  }
  if (/male|pria|david|mark|guy/.test(name)) score -= 80;
  if (voice.localService) score += 5;
  return score;
}

function refreshVoiceList() {
  if (!('speechSynthesis' in window)) return;
  state.voices = speechSynthesis
    .getVoices()
    .slice()
    .sort((left, right) => (
      voiceScore(right) - voiceScore(left)
      || left.name.localeCompare(right.name)
    ));
  const select = $('voiceSelect');
  select.innerHTML = '';
  const automatic = document.createElement('option');
  automatic.value = '__auto__';
  automatic.textContent = 'Aether chooses automatically';
  select.appendChild(automatic);
  for (const voice of state.voices) {
    const option = document.createElement('option');
    option.value = voice.name;
    option.textContent = (
      `${voice.name} (${voice.lang})${voice.default ? ' — default' : ''}`
    );
    select.appendChild(option);
  }
  const saved = state.voices.find((voice) => voice.name === state.voiceProfile.name);
  if (state.voiceProfile.name === '__auto__') {
    select.value = '__auto__';
  } else if (saved) {
    state.voiceProfile.lang = saved.lang || 'id-ID';
    select.value = saved.name;
  } else {
    state.voiceProfile.name = '__auto__';
    select.value = '__auto__';
  }
  updateVoiceLabels();
}

function updateVoiceLabels() {
  $('voiceRateValue').textContent = Number(state.voiceProfile.rate).toFixed(2);
  $('voicePitchValue').textContent = Number(state.voiceProfile.pitch).toFixed(2);
}

function saveVoiceProfile() {
  updateVoiceLabels();
}

function extractSpeechText(text) {
  return String(text || '')
    .replace(
      /\[(?:TOOL|WRITE)[^\]]*\][\s\S]*?\[\/(?:TOOL|WRITE)\]/gi,
      '',
    )
    .replace(/<[^>]+>/g, ' ')
    .replace(/\[(?:VOICE|\/VOICE)\]/gi, '')
    .replace(/[`*_#>]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function chooseAutomaticVoice(spoken) {
  if (!state.voices.length) return null;
  const feminine = state.voices.filter((voice) => voiceScore(voice) > 20);
  const pool = feminine.length ? feminine : state.voices;
  const normalized = String(spoken || '').toLowerCase();
  let offset = 0;
  if (/selamat|berhasil|great|keren|yay|haha|wkwk/.test(normalized)) offset = 1;
  else if (/tenang|refleksi|maaf|khawatir|pelan/.test(normalized)) offset = 2;
  else if (/bisnis|revenue|strategi|keputusan|risiko/.test(normalized)) offset = 3;
  return pool[Math.min(offset, pool.length - 1)] || pool[0];
}

function finishPresentedTurn(turn, status, epoch) {
  if (!turnCoordinator.accepts(turn)) return;
  const reconciled = turnCoordinator.reconcile(normalizedTurnStatus(status));
  dispatchForEpoch('TURN_RESULT_RECEIVED', epoch, turnEvent(reconciled, {
    authoritativeReceiptId: status.terminal_receipt_id || status.receipt_id,
  }));
}

function speak(
  text,
  {
    epoch = clientStore.getEpoch(),
    trackTurn = true,
    turn = null,
    status = null,
  } = {},
) {
  const presentation = deriveClientPresentation(clientStore.getState());
  if (!presentation.canUseBrowserSpeech || !('speechSynthesis' in window)) {
    return false;
  }
  const spoken = extractSpeechText(text);
  if (!spoken) return false;
  const utterance = new SpeechSynthesisUtterance(spoken);
  const selected = state.voiceProfile.name === '__auto__'
    ? chooseAutomaticVoice(spoken)
    : (
      state.voices.find((voice) => voice.name === state.voiceProfile.name)
      || state.voices[0]
    );
  if (selected) {
    utterance.voice = selected;
    utterance.lang = selected.lang || state.voiceProfile.lang;
  } else {
    utterance.lang = state.voiceProfile.lang || 'id-ID';
  }
  utterance.rate = Number(state.voiceProfile.rate) || 1.02;
  utterance.pitch = Number(state.voiceProfile.pitch) || 1.12;
  utterance.volume = Number(state.voiceProfile.volume) || 1;
  if (trackTurn) {
    utterance.onstart = () => {
      if (!turn || turnCoordinator.accepts(turn)) {
        dispatchForEpoch('RESPONSE_AUDIO_STARTED', epoch, turn ? turnEvent(turn) : {});
      }
    };
    utterance.onend = () => {
      if (turn && status) finishPresentedTurn(turn, status, epoch);
      else dispatchForEpoch('RESPONSE_AUDIO_FINISHED', epoch);
    };
    utterance.onerror = () => {
      if (turn && status) finishPresentedTurn(turn, status, epoch);
      else dispatchForEpoch('TURN_RESET', epoch);
    };
  }
  speechSynthesis.cancel();
  speechSynthesis.speak(utterance);
  return true;
}

function previewVoice() {
  if (!speak(
    '[VOICE]Halo, Dee. Aku Aether. Suara ini akan menjadi suara browser senses-ku.[/VOICE]',
    { trackTurn: false },
  )) {
    message('system', 'Voice preview is unavailable while Private text-only is active.');
  }
}

function startSessionHeartbeat() {
  clearInterval(state.heartbeatTimer);
  state.heartbeatTimer = setInterval(() => {
    if (!state.session) return;
    jsonFetch(`${API}/api/browser-senses/session/status`, {
      method: 'POST',
      headers: authHeaders(),
    }).catch(() => {});
  }, 15000);
}

async function issueSession(epoch) {
  if (!state.deviceKey) {
    throw new Error('Pair this device before opening a Senses session.');
  }
  const challenge = await jsonFetch(`${API}/api/browser-senses/session/challenges`, {
    method: 'POST',
    authFailure: 'device',
  });
  const result = await jsonFetch(`${API}/api/browser-senses/session`, {
    method: 'POST',
    authFailure: 'device',
    body: JSON.stringify({
      display_name: $('displayName').value.trim() || 'Founder',
      capabilities: ['text', 'microphone', 'speaker', 'camera', 'screen-share'],
      ttl_seconds: 3600,
      challenge_id: challenge.challenge_id,
      device_signature: await signChallenge(challenge.challenge),
    }),
  });
  state.csrfNonce = result.csrf_nonce;
  state.session = result.session;
  state.livekit = result.livekit;
  dispatchForEpoch('SESSION_ISSUED', epoch);
  startSessionHeartbeat();
  $('sessionLabel').textContent = result.session.session_id;
  message(
    'system',
    `Session ${result.session.session_id} issued through the paired-device boundary. `
    + `LiveKit ${result.livekit.ready ? 'ready' : 'unavailable'}.`,
  );
  return result;
}

async function connectLiveKit(epoch) {
  if (!state.livekit?.ready) {
    throw new Error(state.livekit?.error || 'LiveKit transport is not ready.');
  }
  const livekit = await import(
    `./vendor/livekit-client-2.17.2.esm.js?v=${PWA_BUILD_ID}`
  );
  const room = new livekit.Room({ adaptiveStream: true, dynacast: true });
  room.on(livekit.RoomEvent.TrackSubscribed, (track) => {
    if (track.kind === livekit.Track.Kind.Audio) {
      const element = track.attach();
      element.autoplay = true;
      $('remoteAudio').appendChild(element);
      state.remoteAudioTracks.add(track);
      state.remoteAudioElements.add(element);
    }
    if (track.kind === livekit.Track.Kind.Video) {
      track.attach($('localVideo'));
    }
  });
  room.on(livekit.RoomEvent.TrackUnsubscribed, (track) => {
    if (track.kind !== livekit.Track.Kind.Audio) return;
    state.remoteAudioTracks.delete(track);
    for (const element of track.detach() || []) {
      state.remoteAudioElements.delete(element);
      element.remove?.();
    }
  });
  room.on(livekit.RoomEvent.DataReceived, (payload, participant, _kind, topic) => {
    if (topic !== TURN_STATE_TOPIC || payload.byteLength > 2048 || !participant) return;
    try {
      const event = JSON.parse(new TextDecoder().decode(payload));
      if (
        event.type !== 'turn-state'
        || !['accepted', 'response-ready', 'completed', 'interrupted', 'failed'].includes(event.state)
        || !String(event.turn_id || '').trim()
        || !String(event.correlation_id || '').trim()
        || !Number.isInteger(event.generation)
      ) return;
      const epoch = clientStore.getEpoch();
      const turn = {
        turnId: event.turn_id,
        correlationId: event.correlation_id,
        generation: event.generation,
        retryOfTurnId: event.retry_of_turn_id || null,
      };
      if (event.state === 'accepted') {
        turnCoordinator.adopt(turn);
        dispatchForEpoch('TURN_GENERATION_ADOPTED', epoch, turnEvent(turn, {
          retryOfTurnId: turn.retryOfTurnId,
        }));
      } else if (event.state === 'response-ready' && turnCoordinator.accepts(turn)) {
        resumeRemoteAudio();
        dispatchForEpoch('TURN_ACCEPTED', epoch, turnEvent(turn));
      } else if (['completed', 'interrupted', 'failed'].includes(event.state)) {
        const status = normalizedTurnStatus(event);
        turnCoordinator.reconcile(status);
        if (event.state === 'interrupted') {
          stopTurnAudio({
            speechSynthesis: window.speechSynthesis,
            recognition: state.fallbackRecognition,
            remoteTracks: state.remoteAudioTracks,
            remoteAudioElements: state.remoteAudioElements,
            room: null,
            control: null,
          }).catch(() => {});
        }
        dispatchForEpoch('TURN_RECONCILED', epoch, turnEvent(
          turnCoordinator.snapshot(),
          {
            status: event.state,
            authoritativeReceiptId: event.receipt_id || null,
          },
        ));
      }
    } catch {
      // Turn-state packets are bounded metadata. Malformed packets are ignored.
    }
  });
  room.on(livekit.RoomEvent.TranscriptionReceived, (segments) => {
    const finalTranscript = segments
      .filter((segment) => segment.final)
      .map((segment) => segment.text)
      .join(' ');
    if (finalTranscript) {
      $('transcript').textContent = finalTranscript;
      message('user', finalTranscript);
    }
  });
  room.on(livekit.RoomEvent.Disconnected, () => {
    if (clientStore.getEpoch() !== epoch) return;
    if (clientStore.getState().authSession === AuthSessionState.ACTIVE_REALTIME) {
      dispatchForEpoch('TRANSPORT_LOST', epoch);
      markAetherUnavailable();
      setTransportMessage(
        'LiveKit disconnected. No uncertain turn will be replayed automatically.',
      );
    }
  });
  await room.connect(state.livekit.server_url, state.livekit.participant_token);
  state.room = room;
  await room.localParticipant.setMicrophoneEnabled(true);
  state.micEnabled = true;
  await reportTrack('browser-microphone', 'audio', 'microphone', false);
  await jsonFetch(`${API}/api/browser-senses/session/active`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ transport: 'livekit' }),
  });
  dispatchForEpoch('REALTIME_VERIFIED', epoch);
  markAetherAvailable();
  dispatchForEpoch('LISTENING_STARTED', epoch);
  $('micButton').disabled = false;
  $('voiceState').textContent = 'LiveKit voice active';
  $('orb').classList.add('active');
  setTransportMessage(
    'LiveKit microphone/speaker verified. Aether Gateway owns cognition.',
  );
}

function verifiedFallbackMode() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Recognition) return TransportMode.VOICE_FALLBACK;
  if ('speechSynthesis' in window) return TransportMode.TEXT_SPEECH;
  return TransportMode.TEXT_ONLY;
}

async function verifyIssuedTransport(epoch) {
  if (state.livekit?.ready) {
    await connectLiveKit(epoch);
    return;
  }
  const mode = verifiedFallbackMode();
  dispatchForEpoch('DEGRADED_VERIFIED', epoch, { mode });
  markAetherAvailable();
  setTransportMessage(
    `Aether session verified in ${mode.replaceAll('-', ' ')} mode; `
    + 'LiveKit is unavailable.',
  );
}

async function connect() {
  try {
    if (!derivePwaPresentation(pwaRuntime).sensorsAllowed) {
      throw new Error('Resume the visible online PWA before connecting Senses.');
    }
    dispatch('CONNECT_REQUESTED');
    const epoch = clientStore.getEpoch();
    await issueSession(epoch);
    await verifyIssuedTransport(epoch);
  } catch (error) {
    markAetherUnavailable();
    message('system', `Connect failed: ${error.message}`);
    setTransportMessage(error.message);
    if (
      error.status !== 401
      && clientStore.getState().authSession === AuthSessionState.CONNECTING
    ) {
      dispatch('SESSION_CLOSED');
    }
  }
}

async function ensureCamera() {
  if (state.cameraEnabled) return;
  if (
    !deriveClientPresentation(clientStore.getState()).canUseSensors
    || !derivePwaPresentation(pwaRuntime).sensorsAllowed
  ) {
    throw new Error('Connect a verified browser session before enabling camera preview.');
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    video: {
      facingMode: 'user',
      width: { ideal: 1280 },
      height: { ideal: 720 },
    },
    audio: false,
  });
  state.localStream = stream;
  $('localVideo').srcObject = stream;
  state.cameraEnabled = true;
  dispatchForEpoch('CONSENT_PREVIEW_STARTED', clientStore.getEpoch(), {
    source: 'camera',
  });
  $('cameraState').textContent = 'local preview';
  $('cameraButton').textContent = 'Disable camera';
  $('visionButton').disabled = !state.session;
  message(
    'system',
    'Camera preview is local. Continuous camera video is not published as v1 cognition.',
  );
}

async function toggleCamera() {
  try {
    if (!state.cameraEnabled) {
      await ensureCamera();
      return;
    }
    await stopVisionSource('camera', 'camera-stop');
  } catch (error) {
    message('system', `Camera failed: ${error.message}`);
  }
}

async function ensureScreen() {
  if (state.screenEnabled) return;
  if (
    !deriveClientPresentation(clientStore.getState()).canUseSensors
    || !derivePwaPresentation(pwaRuntime).sensorsAllowed
  ) {
    throw new Error('Connect a verified browser session before enabling screen preview.');
  }
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: { frameRate: { ideal: 5, max: 5 } },
    audio: false,
  });
  state.screenStream = stream;
  state.screenEnabled = true;
  $('screenVideo').srcObject = stream;
  dispatchForEpoch('CONSENT_PREVIEW_STARTED', clientStore.getEpoch(), {
    source: 'screen',
  });
  $('screenState').textContent = 'local preview';
  $('screenButton').textContent = 'Disable screen preview';
  $('screenVisionButton').disabled = !state.session;
  stream.getVideoTracks()[0]?.addEventListener('ended', () => {
    stopVisionSource('screen', 'browser-permission-ended').catch((error) => {
      message('system', `Screen stop could not be confirmed: ${error.message}`);
    });
  }, { once: true });
  message(
    'system',
    'Screen preview is local. Continuous screen video is never published as v1 cognition.',
  );
}

async function toggleScreen() {
  try {
    if (!state.screenEnabled) {
      await ensureScreen();
      return;
    }
    await stopVisionSource('screen', 'screen-stop');
  } catch (error) {
    message('system', `Screen capture failed: ${error.message}`);
  }
}

async function stopVisionLease(source, reason) {
  stopAutoVision(source);
  const lease = visionCoordinator.stop(source);
  if (!lease) {
    dispatchForEpoch('CONSENT_LOCAL_STOPPED', clientStore.getEpoch(), { source });
    return null;
  }
  dispatchForEpoch('CONSENT_LOCAL_STOPPED', clientStore.getEpoch(), { source });
  if (!state.session || !state.csrfNonce) return null;
  const revoked = await jsonFetch(
    `${API}/api/browser-senses/vision/consents/${encodeURIComponent(lease.consentId)}/revoke`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ reason }),
    },
  );
  if ([
    AuthSessionState.ACTIVE_REALTIME,
    AuthSessionState.ACTIVE_DEGRADED,
  ].includes(clientStore.getState().authSession)) {
    dispatchForEpoch('CONSENT_REVOKED', clientStore.getEpoch(), {
      source,
      receiptId: revoked.receipt_id,
    });
  }
  return revoked;
}

async function stopVisionSource(source, reason) {
  const revocation = stopVisionLease(source, reason);
  const streamKey = source === 'camera' ? 'localStream' : 'screenStream';
  const enabledKey = source === 'camera' ? 'cameraEnabled' : 'screenEnabled';
  const video = $(source === 'camera' ? 'localVideo' : 'screenVideo');
  const stateNode = $(source === 'camera' ? 'cameraState' : 'screenState');
  const button = $(source === 'camera' ? 'cameraButton' : 'screenButton');
  const askButton = $(source === 'camera' ? 'visionButton' : 'screenVisionButton');
  state[streamKey]?.getTracks().forEach((track) => track.stop());
  state[streamKey] = null;
  state[enabledKey] = false;
  video.srcObject = null;
  stateNode.textContent = `${source} off`;
  button.textContent = source === 'camera' ? 'Enable camera' : 'Enable screen preview';
  askButton.disabled = true;
  await revocation;
}

function captureFrame(source) {
  const video = $(source === 'camera' ? 'localVideo' : 'screenVideo');
  if (!video.videoWidth) throw new Error(`${source} frame is not ready.`);
  const canvas = $('frameCanvas');
  const maxWidth = 960;
  const scale = Math.min(1, maxWidth / video.videoWidth);
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext('2d').drawImage(
    video,
    0,
    0,
    canvas.width,
    canvas.height,
  );
  const dataUrl = canvas.toDataURL('image/jpeg', 0.72);
  return {
    data_base64: dataUrl.split(',')[1],
    content_type: 'image/jpeg',
    width: canvas.width,
    height: canvas.height,
    prompt: $('visionPrompt').value.trim(),
  };
}

async function grantVisionLease(source, mode) {
  const consent = await jsonFetch(`${API}/api/browser-senses/vision/consents`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ source, mode }),
  });
  visionCoordinator.grant(consent);
  dispatchForEpoch(
    mode === 'bounded' ? 'CONSENT_BOUNDED_GRANTED' : 'CONSENT_ONE_SHOT_GRANTED',
    clientStore.getEpoch(),
    {
      source,
      consentId: consent.consent_id,
      receiptId: consent.receipt_id,
      expiresAt: consent.expires_at,
      captureIntervalSeconds: consent.capture_interval_seconds,
    },
  );
  return consent;
}

function presentAssistantResponse(response, epoch, turn, status) {
  if (!turnCoordinator.accepts(turn)) return false;
  message('assistant', response);
  $('transcript').textContent = response;
  if (!state.room && speak(response, {
    epoch,
    trackTurn: true,
    turn,
    status,
  })) return true;
  finishPresentedTurn(turn, status, epoch);
  return true;
}

function terminalReceiptId(status) {
  return status?.terminal_receipt_id || status?.receipt_id || null;
}

function dispatchReconciledStatus(status, epoch) {
  const normalized = normalizedTurnStatus(status);
  const reconciled = turnCoordinator.reconcile(normalized);
  dispatchForEpoch('TURN_RECONCILED', epoch, turnEvent(reconciled, {
    status: status.state,
    authoritativeReceiptId: terminalReceiptId(status),
  }));
  if (status.state !== 'accepted') state.lastUnconfirmedInput = null;
  return reconciled;
}

async function reconcileAmbiguousTurn(turn, epoch) {
  let lastStatus = null;
  for (const delay of RECONCILIATION_DELAYS_MS) {
    if (delay) await sleep(delay);
    if (!turnCoordinator.accepts(turn)) return;
    try {
      lastStatus = await lookupTurnStatus(turn);
    } catch (error) {
      if (error.status !== 404) continue;
      lastStatus = null;
    }
    if (!lastStatus) continue;
    if (lastStatus.state === 'accepted') continue;
    dispatchReconciledStatus(lastStatus, epoch);
    if (lastStatus.state === 'completed') {
      message(
        'system',
        'Turn completed at Aether, but the response body was lost in transit. It was not replayed.',
      );
    } else if (lastStatus.state === 'failed') {
      message('system', 'Aether confirmed that the ambiguous turn failed.');
    }
    return;
  }
  if (!turnCoordinator.accepts(turn)) return;
  const unconfirmed = turnCoordinator.reconcile({
    ...turn,
    state: 'not-confirmed',
  });
  dispatchForEpoch('TURN_NOT_CONFIRMED', epoch, turnEvent(unconfirmed));
  message(
    'system',
    'Turn outcome is not confirmed. Aether did not replay it; Retry creates a new linked turn.',
  );
}

function isAmbiguousNetworkError(error, timedOut) {
  return timedOut || error?.name === 'AbortError' || error instanceof TypeError;
}

async function executeBrowserTurn({ endpoint, payload, turn, epoch, inputForRetry }) {
  const controller = new AbortController();
  state.activeRequestController = controller;
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, TURN_REQUEST_TIMEOUT_MS);
  try {
    const result = await jsonFetch(`${API}${endpoint}`, {
      method: 'POST',
      headers: authHeaders(),
      signal: controller.signal,
      body: JSON.stringify({ ...payload, ...turnRequestFields(turn) }),
    });
    if (!turnCoordinator.accepts(turn)) return null;
    if (result.replayed) {
      dispatchReconciledStatus(result.turn_status, epoch);
      return null;
    }
    const status = result.turn_status;
    if (
      status?.turn_id !== turn.turnId
      || status?.correlation_id !== turn.correlationId
      || status?.generation !== turn.generation
      || status?.state !== 'completed'
      || !terminalReceiptId(status)
    ) {
      throw new Error('Aether returned an unbound turn result');
    }
    dispatchForEpoch('TURN_ACCEPTED', epoch, turnEvent(turn));
    presentCapabilityActions(result.capability_actions, epoch);
    state.lastUnconfirmedInput = null;
    presentAssistantResponse(result.response, epoch, turn, status);
    return result;
  } catch (error) {
    if (!turnCoordinator.accepts(turn)) return null;
    if (isAmbiguousNetworkError(error, timedOut)) {
      turnCoordinator.markAmbiguous(turn);
      state.lastUnconfirmedInput = inputForRetry;
      dispatchForEpoch('TURN_NETWORK_AMBIGUOUS', epoch, turnEvent(turn));
      await reconcileAmbiguousTurn(turn, epoch);
      return null;
    }
    turnCoordinator.reconcile({ ...turn, state: 'failed' });
    dispatchForEpoch('TURN_REJECTED', epoch, turnEvent(turn));
    throw error;
  } finally {
    clearTimeout(timeout);
    if (state.activeRequestController === controller) {
      state.activeRequestController = null;
    }
  }
}

async function beginBrowserTurn({ retry = false } = {}) {
  const active = turnCoordinator.snapshot();
  if (
    active
    && !['completed', 'interrupted', 'failed', 'not-confirmed'].includes(active.delivery)
  ) {
    await interruptActiveTurn('competing_input');
  }
  return retry ? turnCoordinator.startExplicitRetry() : turnCoordinator.start();
}

async function askVision(source = 'camera', silent = false) {
  if (!state.session) throw new Error('Connect a browser session first.');
  if (!derivePwaPresentation(pwaRuntime).canSend) {
    throw new Error('Aether is offline or Senses requires an explicit resume.');
  }
  const enabled = source === 'camera' ? state.cameraEnabled : state.screenEnabled;
  if (!enabled) throw new Error(`Enable ${source} local preview before transmission.`);
  let lease = visionCoordinator.snapshot()[source];
  if (!lease) {
    await grantVisionLease(source, 'one-shot');
    lease = visionCoordinator.snapshot()[source];
  }
  const epoch = clientStore.getEpoch();
  const turn = await beginBrowserTurn();
  dispatchForEpoch('TURN_GENERATION_STARTED', epoch, turnEvent(turn, {
    retryOfTurnId: turn.retryOfTurnId,
  }));
  const badge = $(source === 'camera' ? 'visionBadge' : 'screenVisionBadge');
  badge.textContent = `${source.toUpperCase()} COMMITTING`;
  try {
    if (!silent) message('user', `[${source} keyframe]`);
    const payload = visionCoordinator.envelope(
      source,
      captureFrame(source),
      $('visionPrompt').value.trim(),
    );
    const result = await executeBrowserTurn({
      endpoint: '/api/browser-senses/vision',
      payload,
      turn,
      epoch,
      inputForRetry: null,
    });
    if (result?.frame) {
      dispatchForEpoch('CONSENT_FRAME_RECEIPTED', epoch, {
        source,
        consentId: result.frame.consent_id,
        receiptId: result.frame.receipt_id,
        sequenceNumber: result.frame.sequence_number,
        capturedAt: result.frame.captured_at,
      });
    }
    badge.textContent = result ? `${source.toUpperCase()} READY` : `${source.toUpperCase()} UNCONFIRMED`;
  } catch (error) {
    badge.textContent = `${source.toUpperCase()} ERROR`;
    message('system', `Vision failed: ${error.message}`);
    if (/consent lease is expired/i.test(error.message)) {
      await stopVisionLease(source, 'lease-expired').catch(() => null);
    }
  }
}

function renderVisionCountdowns() {
  const now = Date.now();
  for (const source of ['camera', 'screen']) {
    const lease = visionCoordinator.snapshot()[source];
    if (!lease || lease.mode !== 'bounded') continue;
    const remaining = Math.max(0, Math.ceil((lease.expiresAt - now) / 1000));
    $(source === 'camera' ? 'cameraState' : 'screenState').textContent = (
      `VISION ACTIVE · ${remaining}s`
    );
    if (remaining === 0) {
      stopVisionLease(source, 'lease-expired').catch((error) => {
        message('system', `Vision expiry stop failed: ${error.message}`);
      });
    }
  }
}

async function toggleAutoVision(source = 'camera') {
  const checkbox = $(source === 'camera' ? 'autoVision' : 'autoScreenVision');
  if (!checkbox.checked) {
    await stopVisionLease(source, 'bounded-stop');
    return;
  }
  const enabled = source === 'camera' ? state.cameraEnabled : state.screenEnabled;
  if (!enabled || !state.session) {
    checkbox.checked = false;
    message('system', `Connect and enable ${source} preview before bounded vision.`);
    return;
  }
  await grantVisionLease(source, 'bounded');
  state.visionTimers[source] = setInterval(
    () => askVision(source, true).catch((error) => message('system', error.message)),
    15000,
  );
  if (!state.visionCountdownTimer) {
    state.visionCountdownTimer = setInterval(renderVisionCountdowns, 1000);
  }
  renderVisionCountdowns();
  message(
    'system',
    `${source} bounded vision is active for 15 minutes at one keyframe every 15 seconds.`,
  );
}

async function sendText(text, { retry = false } = {}) {
  if (!state.session) throw new Error('Connect a browser session first.');
  if (!derivePwaPresentation(pwaRuntime).canSend) {
    throw new Error('Aether is offline or Senses requires an explicit resume.');
  }
  const epoch = clientStore.getEpoch();
  const turn = await beginBrowserTurn({ retry });
  dispatchForEpoch('TURN_GENERATION_STARTED', epoch, turnEvent(turn, {
    retryOfTurnId: turn.retryOfTurnId,
  }));
  message('user', text);
  $('transcript').textContent = text;
  return executeBrowserTurn({
    endpoint: '/api/browser-senses/text',
    payload: { text },
    turn,
    epoch,
    inputForRetry: { kind: 'text', text },
  });
}

function fallbackSTT() {
  if (!derivePwaPresentation(pwaRuntime).canSend) {
    message('system', 'Resume the online Senses session before browser speech input.');
    return;
  }
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    message('system', 'Browser SpeechRecognition is unavailable. Use text input.');
    return;
  }
  const epoch = clientStore.getEpoch();
  if (clientStore.getState().turn === TurnState.IDLE) {
    dispatchForEpoch('LISTENING_STARTED', epoch);
  }
  const recognition = new Recognition();
  recognition.lang = navigator.language || 'id-ID';
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.onresult = (event) => {
    let text = '';
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      text += event.results[index][0].transcript;
    }
    $('transcript').textContent = text;
    if (event.results[event.results.length - 1].isFinal) {
      sendText(text.trim()).catch((error) => message('system', error.message));
    }
  };
  recognition.onerror = (event) => {
    dispatchForEpoch('TURN_RESET', epoch);
    message('system', `Browser STT error: ${event.error}`);
  };
  recognition.start();
  state.fallbackRecognition = recognition;
}

async function interruptActiveTurn(reason = 'explicit_stop') {
  const active = turnCoordinator.snapshot();
  if (
    !active
    || ['completed', 'interrupted', 'failed', 'not-confirmed'].includes(active.delivery)
  ) return null;
  const epoch = clientStore.getEpoch();
  const interruption = turnCoordinator.interrupt(reason);
  dispatchForEpoch('INTERRUPT_REQUESTED', epoch, {
    turnId: interruption.turnId,
    correlationId: interruption.correlationId,
    previousGeneration: interruption.previousGeneration,
    nextGeneration: interruption.nextGeneration,
  });
  state.activeRequestController?.abort();
  const audio = await stopTurnAudio({
    speechSynthesis: window.speechSynthesis,
    recognition: state.fallbackRecognition,
    remoteTracks: state.remoteAudioTracks,
    remoteAudioElements: state.remoteAudioElements,
    room: state.room,
    control: {
      type: 'interrupt',
      turn_id: interruption.turnId,
      correlation_id: interruption.correlationId,
      previous_generation: interruption.previousGeneration,
      next_generation: interruption.nextGeneration,
      reason,
    },
  });
  state.fallbackRecognition = null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  let receipt;
  try {
    receipt = await jsonFetch(
      `${API}/api/browser-senses/turns/${encodeURIComponent(interruption.turnId)}/interrupt`,
      {
        method: 'POST',
        headers: authHeaders(),
        signal: controller.signal,
        body: JSON.stringify({
          correlation_id: interruption.correlationId,
          previous_generation: interruption.previousGeneration,
          next_generation: interruption.nextGeneration,
          reason,
          delivered_audio_ms: null,
          livekit_control_sent: audio.livekitControlSent,
          browser_audio_stopped: audio.browserAudioStopped,
        }),
      },
    );
  } catch (error) {
    const status = await lookupTurnStatus(interruption).catch(() => null);
    if (
      status?.state !== 'interrupted'
      || status.turn_id !== interruption.turnId
      || status.correlation_id !== interruption.correlationId
      || status.generation !== interruption.nextGeneration
      || !status.receipt_id
    ) throw error;
    receipt = status;
  } finally {
    clearTimeout(timeout);
  }
  const acknowledged = turnCoordinator.acknowledgeInterruption(receipt.receipt_id);
  dispatchForEpoch('INTERRUPT_ACKNOWLEDGED', epoch, turnEvent(acknowledged, {
    authoritativeReceiptId: receipt.receipt_id,
    listening: state.micEnabled,
  }));
  return receipt;
}

async function retryUnconfirmedTurn() {
  const input = state.lastUnconfirmedInput;
  if (!input || input.kind !== 'text') return;
  state.lastUnconfirmedInput = null;
  await sendText(input.text, { retry: true });
}

async function toggleMic() {
  if (!state.room) return;
  const epoch = clientStore.getEpoch();
  state.micEnabled = !state.micEnabled;
  await state.room.localParticipant.setMicrophoneEnabled(state.micEnabled);
  await reportTrack('browser-microphone', 'audio', 'microphone', !state.micEnabled);
  $('micButton').textContent = state.micEnabled
    ? 'Mute microphone'
    : 'Unmute microphone';
  $('voiceState').textContent = state.micEnabled
    ? 'LiveKit voice active'
    : 'microphone muted';
  dispatchForEpoch(
    state.micEnabled ? 'LISTENING_STARTED' : 'MICROPHONE_MUTED',
    epoch,
  );
}

async function disconnect() {
  const epoch = clientStore.getEpoch();
  try {
    await interruptActiveTurn('disconnect');
  } catch (error) {
    message('system', `Turn interruption could not be confirmed: ${error.message}`);
  }
  clearInterval(state.heartbeatTimer);
  state.heartbeatTimer = null;
  stopLocalCapture();
  if (state.room) await state.room.disconnect();
  if (state.session) {
    try {
      await jsonFetch(`${API}/api/browser-senses/session/close`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ reason: 'browser-disconnect' }),
      });
    } catch {
      // jsonFetch already closes or invalidates the applicable auth boundary.
    }
  }
  clearSessionRuntime();
  if (
    clientStore.getEpoch() === epoch
    && clientStore.getState().authSession !== AuthSessionState.BOOTSTRAP_REQUIRED
  ) {
    dispatch('SESSION_CLOSED');
  }
  setTransportMessage('Disconnected. Device pairing remains available.');
}

function setPrivateTextOnly(enabled) {
  dispatch('EXTERNAL_SPEECH_PRIVACY_SET', {
    privacy: enabled
      ? ExternalSpeechPrivacy.PRIVATE_TEXT_ONLY
      : ExternalSpeechPrivacy.EXTERNAL_ALLOWED,
  });
  if (enabled) {
    interruptActiveTurn('explicit_stop').catch((error) => {
      if ('speechSynthesis' in window) speechSynthesis.cancel();
      message('system', `Speech stopped locally; receipt is unconfirmed: ${error.message}`);
    });
    message(
      'system',
      'Private text-only enabled. Gateway text remains available; speech output is suppressed.',
    );
  }
}

function showPwaUpdate(registration) {
  state.updateRegistration = registration;
  $('activatePwaUpdate').hidden = false;
  setTransportMessage('A versioned Senses shell update is ready. Apply it when no turn is active.');
}

async function registerPwaShell() {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
  const registration = await navigator.serviceWorker.register(
    `/senses/sw.js?v=${PWA_BUILD_ID}`,
    { scope: '/senses', type: 'module', updateViaCache: 'none' },
  );
  if (registration.waiting && navigator.serviceWorker.controller) {
    showPwaUpdate(registration);
  }
  registration.addEventListener('updatefound', () => {
    const installing = registration.installing;
    if (!installing) return;
    installing.addEventListener('statechange', () => {
      if (installing.state === 'installed' && navigator.serviceWorker.controller) {
        showPwaUpdate(registration);
      }
    });
  });
}

async function activatePwaUpdate() {
  const registration = state.updateRegistration;
  if (!registration?.waiting) return;
  await suspendSenses('PAGE_FROZEN', 'pwa-update');
  state.reloadForUpdate = true;
  $('activatePwaUpdate').disabled = true;
  registration.waiting.postMessage({ type: 'AETHER_ACTIVATE_UPDATE' });
}

async function promptPwaInstall() {
  if (!state.installPrompt) return;
  const prompt = state.installPrompt;
  state.installPrompt = null;
  $('installPwa').hidden = true;
  await prompt.prompt();
  await prompt.userChoice;
}

async function resumeSenses() {
  try {
    dispatchPwa('RESUME_BY_GESTURE');
    await state.suspendClosePromise;
    state.suspendClosePromise = null;
    const auth = clientStore.getState().authSession;
    if (auth !== AuthSessionState.SUSPENDED) {
      setTransportMessage('Foreground restored. Sensors remain off until explicitly enabled.');
      message('system', 'Senses resumed. No microphone, camera, or screen source restarted.');
      return;
    }
    dispatch('RESUME_REQUESTED');
    const epoch = clientStore.getEpoch();
    await issueSession(epoch);
    await verifyIssuedTransport(epoch);
    message('system', 'Senses resumed with a newly verified session. Sensors remain off.');
  } catch (error) {
    markAetherUnavailable();
    setTransportMessage(`Resume failed: ${error.message}`);
    message('system', `Resume failed: ${error.message}`);
    if (clientStore.getState().authSession === AuthSessionState.CONNECTING) {
      dispatch('SESSION_CLOSED');
    }
  }
}

loadVoiceProfile();
$('voiceRate').value = state.voiceProfile.rate;
$('voicePitch').value = state.voiceProfile.pitch;
refreshVoiceList();
if ('speechSynthesis' in window) {
  speechSynthesis.addEventListener?.('voiceschanged', refreshVoiceList);
  speechSynthesis.onvoiceschanged = refreshVoiceList;
}
$('voiceSelect').addEventListener('change', (event) => {
  const selected = state.voices.find((voice) => voice.name === event.target.value);
  state.voiceProfile.name = event.target.value;
  if (selected) state.voiceProfile.lang = selected.lang;
  saveVoiceProfile();
});
$('voiceRate').addEventListener('input', (event) => {
  state.voiceProfile.rate = Number(event.target.value);
  saveVoiceProfile();
});
$('voicePitch').addEventListener('input', (event) => {
  state.voiceProfile.pitch = Number(event.target.value);
  saveVoiceProfile();
});
$('privateTextOnly').addEventListener('change', (event) => {
  setPrivateTextOnly(event.target.checked);
});
$('previewVoice').addEventListener('click', previewVoice);
$('pairButton').addEventListener('click', () => {
  requestPairing().catch((error) => pairingFailed(error.message));
});
$('resumeSenses').addEventListener('click', resumeSenses);
$('installPwa').addEventListener('click', promptPwaInstall);
$('activatePwaUpdate').addEventListener('click', activatePwaUpdate);
$('connectButton').addEventListener('click', connect);
$('disconnectButton').addEventListener('click', disconnect);
$('stopAether').addEventListener('click', () => {
  interruptActiveTurn('explicit_stop').catch((error) => {
    message('system', `Stop could not be confirmed: ${error.message}`);
  });
});
$('retryTurn').addEventListener('click', () => {
  retryUnconfirmedTurn().catch((error) => message('system', error.message));
});
$('cancelCapabilityAction').addEventListener('click', () => {
  cancelCapabilityAction().catch((error) => message('system', error.message));
});
$('micButton').addEventListener('click', toggleMic);
$('fallbackTalk').addEventListener('click', fallbackSTT);
$('cameraButton').addEventListener('click', toggleCamera);
$('visionButton').addEventListener('click', () => {
  askVision('camera', false).catch((error) => message('system', error.message));
});
$('autoVision').addEventListener('change', () => {
  toggleAutoVision('camera').catch((error) => message('system', error.message));
});
$('screenButton').addEventListener('click', toggleScreen);
$('screenVisionButton').addEventListener('click', () => {
  askVision('screen', false).catch((error) => message('system', error.message));
});
$('autoScreenVision').addEventListener('change', () => {
  toggleAutoVision('screen').catch((error) => message('system', error.message));
});
$('chatForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = $('chatInput').value.trim();
  if (!text) return;
  $('chatInput').value = '';
  try {
    await sendText(text);
  } catch (error) {
    message('system', error.message);
  }
});
window.addEventListener('beforeunload', () => {
  state.activeRequestController?.abort();
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  for (const element of state.remoteAudioElements) element.pause?.();
  state.room?.disconnect();
  stopLocalCapture();
});
async function stopBackgroundSensors(reason) {
  const stops = [];
  if (state.cameraEnabled) stops.push(stopVisionSource('camera', reason));
  if (state.screenEnabled) stops.push(stopVisionSource('screen', reason));
  await Promise.allSettled(stops);
}

async function suspendSenses(runtimeEvent, reason) {
  dispatchPwa(runtimeEvent, { reason });
  const auth = clientStore.getState().authSession;
  const epoch = clientStore.getEpoch();
  state.activeRequestController?.abort();
  state.fallbackRecognition?.abort?.();
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  state.room?.localParticipant?.setMicrophoneEnabled(false).catch(() => {});
  state.room?.disconnect();
  state.micEnabled = false;
  const stoppingSensors = stopBackgroundSensors(reason);
  const closePromise = closeSessionBestEffort(reason);
  if (closePromise) state.suspendClosePromise = closePromise;
  if ([
    AuthSessionState.ACTIVE_REALTIME,
    AuthSessionState.ACTIVE_DEGRADED,
    AuthSessionState.RECONNECTING,
  ].includes(auth)) {
    dispatchForEpoch('APP_SUSPENDED', epoch);
  } else if (auth === AuthSessionState.CONNECTING) {
    dispatch('SESSION_CLOSED');
  }
  clearSessionRuntime();
  setTransportMessage(`${derivePwaPresentation(pwaRuntime).label}. Sensors stopped.`);
  await stoppingSensors;
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') {
    suspendSenses('PAGE_HIDDEN', 'browser-backgrounded').catch(() => null);
  } else if (!pwaRuntime.visible) {
    dispatchPwa('PAGE_VISIBLE');
  }
});
window.addEventListener('pagehide', () => {
  suspendSenses('PAGE_HIDDEN', 'page-hidden').catch(() => null);
});
document.addEventListener('freeze', () => {
  suspendSenses('PAGE_FROZEN', 'page-frozen').catch(() => null);
});
window.addEventListener('offline', () => {
  suspendSenses('NETWORK_OFFLINE', 'network-offline').catch(() => null);
});
window.addEventListener('online', () => {
  if (!pwaRuntime.online) dispatchPwa('NETWORK_ONLINE');
});
window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  state.installPrompt = event;
  $('installPwa').hidden = false;
});
window.addEventListener('appinstalled', () => {
  state.installPrompt = null;
  $('installPwa').hidden = true;
});
navigator.serviceWorker?.addEventListener('controllerchange', () => {
  if (state.reloadForUpdate) {
    window.location.reload();
    return;
  }
  if (!pwaRuntime.controlled) dispatchPwa('SERVICE_WORKER_CONTROLLING');
});
window.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape' || $('stopAether').disabled) return;
  interruptActiveTurn('explicit_stop').catch((error) => {
    message('system', `Stop could not be confirmed: ${error.message}`);
  });
});

renderClientState(clientStore.getState());
registerPwaShell().catch((error) => {
  message('system', `PWA shell registration failed: ${error.message}`);
});
loadDeviceKey().then((key) => {
  if (
    !key
    || clientStore.getState().authSession !== AuthSessionState.BOOTSTRAP_REQUIRED
    || state.bootstrap
  ) {
    return;
  }
  state.deviceKey = key;
  dispatch('DEVICE_CREDENTIAL_LOADED');
  pairingView(
    'A non-exportable device key is stored in this browser. '
    + 'Connect will verify its HttpOnly device credential.',
  );
});
if (!window.isSecureContext) {
  message(
    'system',
    'This page is not a secure context. Pairing, microphone, and camera require HTTPS.',
  );
  pairingView('Open Senses through its canonical HTTPS origin.');
  $('pairButton').disabled = true;
}
