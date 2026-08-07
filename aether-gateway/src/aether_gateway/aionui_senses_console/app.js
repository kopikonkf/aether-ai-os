import {
  AuthSessionState,
  ExternalSpeechPrivacy,
  TransportMode,
  TurnState,
  createClientStore,
  deriveClientPresentation,
} from './client_state.js';

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
  autoVisionTimer: null,
  fallbackRecognition: null,
  voices: [],
  voiceProfile: {
    name: '__auto__',
    lang: 'id-ID',
    rate: 1.02,
    pitch: 1.12,
    volume: 1,
  },
};
const API = '';

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
  $('systemState').className = `pill ${presentation.systemClass}`;
  $('systemState').textContent = presentation.systemLabel;
  $('authState').textContent = presentation.authLabel;
  $('transportModeState').textContent = presentation.transportLabel;
  $('turnState').textContent = presentation.turnLabel;
  $('consentState').textContent = presentation.consentLabel;
  $('actionState').textContent = presentation.capabilityActionLabel;
  $('externalSpeechState').textContent = presentation.externalSpeechLabel;
  $('pairingState').textContent = presentation.authLabel;

  $('pairButton').disabled = (
    clientState.authSession === AuthSessionState.BOOTSTRAP_PENDING
  );
  $('connectButton').disabled = !presentation.canConnect || !state.deviceKey;
  $('disconnectButton').disabled = ![
    AuthSessionState.CONNECTING,
    AuthSessionState.ACTIVE_REALTIME,
    AuthSessionState.ACTIVE_DEGRADED,
    AuthSessionState.RECONNECTING,
    AuthSessionState.SUSPENDED,
  ].includes(clientState.authSession);
  $('fallbackTalk').disabled = !presentation.canSend;
  $('cameraButton').disabled = !presentation.canUseSensors && !state.cameraEnabled;
  $('visionButton').disabled = !presentation.canUseSensors || !state.cameraEnabled;
  $('chatInput').disabled = !presentation.canSend;
  $('chatForm').querySelector('button').disabled = !presentation.canSend;
  $('previewVoice').disabled = !presentation.canUseBrowserSpeech;
  $('privateTextOnly').checked = (
    clientState.externalSpeech.privacy === ExternalSpeechPrivacy.PRIVATE_TEXT_ONLY
  );
}

const clientStore = createClientStore(renderClientState);

function dispatch(type, values = {}) {
  return clientStore.dispatch({ type, ...values });
}

function dispatchForEpoch(type, epoch, values = {}) {
  return clientStore.dispatch({ type, epoch, ...values });
}

function stopAutoVision() {
  clearInterval(state.autoVisionTimer);
  state.autoVisionTimer = null;
  $('autoVision').checked = false;
}

function stopLocalCapture() {
  stopAutoVision();
  state.localStream?.getTracks().forEach((track) => track.stop());
  state.localStream = null;
  state.cameraEnabled = false;
  state.fallbackRecognition?.abort?.();
  state.fallbackRecognition = null;
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
}

function clearSessionRuntime() {
  clearInterval(state.heartbeatTimer);
  state.heartbeatTimer = null;
  stopLocalCapture();
  state.room?.disconnect();
  state.room = null;
  state.csrfNonce = '';
  state.session = null;
  state.livekit = null;
  state.micEnabled = false;
  $('micButton').disabled = true;
  $('micButton').textContent = 'Mute microphone';
  $('orb').classList.remove('active');
  $('voiceState').textContent = 'not started';
  $('cameraState').textContent = 'not started';
  $('cameraButton').textContent = 'Enable camera';
  $('localVideo').srcObject = null;
  $('sessionLabel').textContent = 'no session';
}

function expireLocalSession(text) {
  clearSessionRuntime();
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
      capabilities: ['text', 'microphone', 'speaker', 'camera'],
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

function speak(text, { epoch = clientStore.getEpoch(), trackTurn = true } = {}) {
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
    utterance.onstart = () => dispatchForEpoch('RESPONSE_AUDIO_STARTED', epoch);
    utterance.onend = () => dispatchForEpoch('RESPONSE_AUDIO_FINISHED', epoch);
    utterance.onerror = () => dispatchForEpoch('TURN_RESET', epoch);
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
      capabilities: ['text', 'microphone', 'speaker', 'camera'],
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
  const livekit = await import('https://cdn.jsdelivr.net/npm/livekit-client@2.17.2/+esm');
  const room = new livekit.Room({ adaptiveStream: true, dynacast: true });
  room.on(livekit.RoomEvent.TrackSubscribed, (track) => {
    if (track.kind === livekit.Track.Kind.Audio) {
      const element = track.attach();
      element.autoplay = true;
      $('remoteAudio').appendChild(element);
    }
    if (track.kind === livekit.Track.Kind.Video) {
      track.attach($('localVideo'));
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

async function connect() {
  try {
    dispatch('CONNECT_REQUESTED');
    const epoch = clientStore.getEpoch();
    await issueSession(epoch);
    if (state.livekit?.ready) {
      await connectLiveKit(epoch);
      return;
    }
    const mode = verifiedFallbackMode();
    dispatchForEpoch('DEGRADED_VERIFIED', epoch, { mode });
    setTransportMessage(
      `Aether session verified in ${mode.replaceAll('-', ' ')} mode; `
      + 'LiveKit is unavailable.',
    );
  } catch (error) {
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
  if (!deriveClientPresentation(clientStore.getState()).canUseSensors) {
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
    state.localStream?.getTracks().forEach((track) => track.stop());
    state.localStream = null;
    state.cameraEnabled = false;
    $('localVideo').srcObject = null;
    $('cameraState').textContent = 'camera off';
    $('cameraButton').textContent = 'Enable camera';
    $('visionButton').disabled = true;
    stopAutoVision();
    dispatchForEpoch('CONSENT_REVOKED', clientStore.getEpoch(), { source: 'camera' });
  } catch (error) {
    message('system', `Camera failed: ${error.message}`);
  }
}

function captureFrame() {
  const video = $('localVideo');
  if (!video.videoWidth) throw new Error('Camera frame is not ready.');
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

function presentAssistantResponse(response, epoch) {
  message('assistant', response);
  $('transcript').textContent = response;
  if (!state.room && speak(response, { epoch, trackTurn: true })) return;
  dispatchForEpoch('TEXT_RESPONSE_PRESENTED', epoch);
}

async function askVision(silent = false) {
  if (!state.session) throw new Error('Connect a browser session first.');
  const epoch = clientStore.getEpoch();
  dispatchForEpoch('TEXT_COMMIT_STARTED', epoch);
  $('visionBadge').textContent = 'VISION COMMITTING';
  try {
    const result = await jsonFetch(`${API}/api/browser-senses/vision`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(captureFrame()),
    });
    dispatchForEpoch('TURN_ACCEPTED', epoch);
    $('visionBadge').textContent = 'VISION READY';
    if (!silent) message('user', '[camera frame]');
    presentAssistantResponse(result.response, epoch);
  } catch (error) {
    dispatchForEpoch('TURN_REJECTED', epoch);
    $('visionBadge').textContent = 'VISION ERROR';
    message('system', `Vision failed: ${error.message}`);
  }
}

function toggleAutoVision() {
  if (!$('autoVision').checked) {
    stopAutoVision();
    return;
  }
  if (!state.cameraEnabled || !state.session) {
    $('autoVision').checked = false;
    message('system', 'Connect and enable camera before bounded vision.');
    return;
  }
  state.autoVisionTimer = setInterval(
    () => askVision(true).catch((error) => message('system', error.message)),
    15000,
  );
  message(
    'system',
    'Bounded-interval client capture requested. Server consent/lifecycle conformance remains a later slice.',
  );
}

async function sendText(text) {
  if (!state.session) throw new Error('Connect a browser session first.');
  const currentTurn = clientStore.getState().turn;
  if (![TurnState.IDLE, TurnState.LISTENING].includes(currentTurn)) {
    throw new Error('A turn is already active. Wait for its terminal state.');
  }
  const epoch = clientStore.getEpoch();
  dispatchForEpoch('TEXT_COMMIT_STARTED', epoch);
  message('user', text);
  $('transcript').textContent = text;
  try {
    const result = await jsonFetch(`${API}/api/browser-senses/text`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ text }),
    });
    dispatchForEpoch('TURN_ACCEPTED', epoch);
    presentAssistantResponse(result.response, epoch);
  } catch (error) {
    dispatchForEpoch('TURN_REJECTED', epoch);
    throw error;
  }
}

function fallbackSTT() {
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
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    if (clientStore.getState().turn === TurnState.SPEAKING) {
      dispatch('TURN_RESET');
    }
    message(
      'system',
      'Private text-only enabled. Gateway text remains available; speech output is suppressed.',
    );
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
$('connectButton').addEventListener('click', connect);
$('disconnectButton').addEventListener('click', disconnect);
$('micButton').addEventListener('click', toggleMic);
$('fallbackTalk').addEventListener('click', fallbackSTT);
$('cameraButton').addEventListener('click', toggleCamera);
$('visionButton').addEventListener('click', () => {
  askVision(false).catch((error) => message('system', error.message));
});
$('autoVision').addEventListener('change', toggleAutoVision);
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
  state.room?.disconnect();
  stopLocalCapture();
});

renderClientState(clientStore.getState());
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
