const values = (definition) => Object.freeze(definition);

export const AuthSessionState = values({
  BOOTSTRAP_REQUIRED: 'bootstrap-required',
  BOOTSTRAP_PENDING: 'bootstrap-pending',
  READY: 'ready',
  CONNECTING: 'connecting',
  ACTIVE_REALTIME: 'active-realtime',
  ACTIVE_DEGRADED: 'active-degraded',
  RECONNECTING: 'reconnecting',
  SUSPENDED: 'suspended',
  CLOSED: 'closed',
});

export const TransportMode = values({
  FULL_REALTIME: 'full-realtime',
  VOICE_FALLBACK: 'voice-fallback',
  TEXT_SPEECH: 'text-speech',
  TEXT_ONLY: 'text-only',
  STATUS_ONLY: 'status-only',
  OFFLINE: 'offline',
});

export const TurnState = values({
  IDLE: 'idle',
  WAKE_ARMED: 'wake-armed',
  LISTENING: 'listening',
  COMMITTING: 'committing',
  THINKING: 'thinking',
  SPEAKING: 'speaking',
  INTERRUPTING: 'interrupting',
  AWAITING_APPROVAL: 'awaiting-approval',
});

export const ConsentMode = values({
  OFF: 'off',
  PREVIEW_LOCAL: 'preview-local',
  ONE_SHOT: 'one-shot',
  BOUNDED: 'bounded',
});

export const CapabilityActionState = values({
  NONE: 'none',
  PROPOSED: 'proposed',
  AWAITING_APPROVAL: 'awaiting-approval',
  QUEUED: 'queued',
  RUNNING: 'running',
  SUCCEEDED: 'succeeded',
  FAILED: 'failed',
  CANCELING: 'canceling',
  CANCELED: 'canceled',
  RECONCILING: 'reconciling',
  REJECTED: 'rejected',
  UNAVAILABLE: 'unavailable',
});

export const ExternalSpeechPrivacy = values({
  EXTERNAL_ALLOWED: 'external-allowed',
  PRIVATE_TEXT_ONLY: 'private-text-only',
});

export const ExternalSpeechConsent = values({
  MISSING: 'missing',
  GRANTED: 'granted',
  REVOKED: 'revoked',
});

const AUTH_TRANSITIONS = new Map([
  [AuthSessionState.BOOTSTRAP_REQUIRED, new Set([
    AuthSessionState.BOOTSTRAP_PENDING,
    AuthSessionState.READY,
  ])],
  [AuthSessionState.BOOTSTRAP_PENDING, new Set([
    AuthSessionState.BOOTSTRAP_REQUIRED,
    AuthSessionState.READY,
  ])],
  [AuthSessionState.READY, new Set([
    AuthSessionState.BOOTSTRAP_REQUIRED,
    AuthSessionState.CONNECTING,
  ])],
  [AuthSessionState.CONNECTING, new Set([
    AuthSessionState.ACTIVE_REALTIME,
    AuthSessionState.ACTIVE_DEGRADED,
    AuthSessionState.CLOSED,
  ])],
  [AuthSessionState.ACTIVE_REALTIME, new Set([
    AuthSessionState.RECONNECTING,
    AuthSessionState.SUSPENDED,
    AuthSessionState.CLOSED,
  ])],
  [AuthSessionState.ACTIVE_DEGRADED, new Set([
    AuthSessionState.CONNECTING,
    AuthSessionState.SUSPENDED,
    AuthSessionState.CLOSED,
  ])],
  [AuthSessionState.RECONNECTING, new Set([
    AuthSessionState.ACTIVE_REALTIME,
    AuthSessionState.ACTIVE_DEGRADED,
    AuthSessionState.SUSPENDED,
    AuthSessionState.CLOSED,
  ])],
  [AuthSessionState.SUSPENDED, new Set([
    AuthSessionState.CONNECTING,
    AuthSessionState.CLOSED,
  ])],
  [AuthSessionState.CLOSED, new Set([
    AuthSessionState.BOOTSTRAP_REQUIRED,
    AuthSessionState.CONNECTING,
    AuthSessionState.READY,
  ])],
]);

const TURN_TRANSITIONS = new Map([
  [TurnState.IDLE, new Set([
    TurnState.WAKE_ARMED,
    TurnState.LISTENING,
    TurnState.COMMITTING,
  ])],
  [TurnState.WAKE_ARMED, new Set([
    TurnState.IDLE,
    TurnState.LISTENING,
  ])],
  [TurnState.LISTENING, new Set([
    TurnState.IDLE,
    TurnState.COMMITTING,
  ])],
  [TurnState.COMMITTING, new Set([
    TurnState.IDLE,
    TurnState.THINKING,
  ])],
  [TurnState.THINKING, new Set([
    TurnState.IDLE,
    TurnState.SPEAKING,
    TurnState.INTERRUPTING,
    TurnState.AWAITING_APPROVAL,
  ])],
  [TurnState.SPEAKING, new Set([
    TurnState.IDLE,
    TurnState.INTERRUPTING,
  ])],
  [TurnState.INTERRUPTING, new Set([
    TurnState.IDLE,
    TurnState.LISTENING,
  ])],
  [TurnState.AWAITING_APPROVAL, new Set([TurnState.IDLE])],
]);

const ACTION_TRANSITIONS = new Map([
  [CapabilityActionState.NONE, new Set([
    CapabilityActionState.PROPOSED,
    CapabilityActionState.UNAVAILABLE,
  ])],
  [CapabilityActionState.PROPOSED, new Set([
    CapabilityActionState.AWAITING_APPROVAL,
    CapabilityActionState.QUEUED,
    CapabilityActionState.REJECTED,
    CapabilityActionState.UNAVAILABLE,
  ])],
  [CapabilityActionState.AWAITING_APPROVAL, new Set([
    CapabilityActionState.QUEUED,
    CapabilityActionState.REJECTED,
  ])],
  [CapabilityActionState.QUEUED, new Set([CapabilityActionState.RUNNING])],
  [CapabilityActionState.RUNNING, new Set([
    CapabilityActionState.SUCCEEDED,
    CapabilityActionState.FAILED,
    CapabilityActionState.CANCELING,
    CapabilityActionState.RECONCILING,
  ])],
  [CapabilityActionState.CANCELING, new Set([CapabilityActionState.CANCELED])],
  [CapabilityActionState.RECONCILING, new Set([
    CapabilityActionState.SUCCEEDED,
    CapabilityActionState.FAILED,
  ])],
]);

const TERMINAL_ACTIONS = new Set([
  CapabilityActionState.SUCCEEDED,
  CapabilityActionState.FAILED,
  CapabilityActionState.CANCELED,
  CapabilityActionState.REJECTED,
  CapabilityActionState.UNAVAILABLE,
]);

const ACTIVE_SESSIONS = new Set([
  AuthSessionState.ACTIVE_REALTIME,
  AuthSessionState.ACTIVE_DEGRADED,
]);

const FALLBACK_MODES = new Set([
  TransportMode.VOICE_FALLBACK,
  TransportMode.TEXT_SPEECH,
  TransportMode.TEXT_ONLY,
  TransportMode.STATUS_ONLY,
]);

const EPOCH_BOUND_EVENTS = new Set([
  'SESSION_ISSUED',
  'REALTIME_VERIFIED',
  'DEGRADED_VERIFIED',
  'TRANSPORT_LOST',
  'LISTENING_STARTED',
  'MICROPHONE_MUTED',
  'TEXT_COMMIT_STARTED',
  'TURN_ACCEPTED',
  'TURN_REJECTED',
  'TEXT_RESPONSE_PRESENTED',
  'RESPONSE_AUDIO_STARTED',
  'RESPONSE_AUDIO_FINISHED',
  'TURN_AWAITING_APPROVAL',
  'APPROVAL_HANDED_OFF',
  'INTERRUPT_REQUESTED',
  'INTERRUPT_ACKNOWLEDGED',
  'TURN_RESET',
  'CONSENT_PREVIEW_STARTED',
  'CONSENT_ONE_SHOT_GRANTED',
  'CONSENT_BOUNDED_GRANTED',
  'CONSENT_REVOKED',
  'CAPABILITY_RECEIPT',
]);

function emptyConsent() {
  return {
    mode: ConsentMode.OFF,
    consentId: null,
    expiresAt: null,
  };
}

function emptyAction() {
  return {
    state: CapabilityActionState.NONE,
    actionId: null,
    exactActionHash: null,
    authoritativeReceiptId: null,
    progress: null,
    safeSummary: null,
    stale: false,
  };
}

export function createInitialClientState() {
  return {
    authSession: AuthSessionState.BOOTSTRAP_REQUIRED,
    transportMode: TransportMode.OFFLINE,
    turn: TurnState.IDLE,
    consent: {
      camera: emptyConsent(),
      screen: emptyConsent(),
    },
    capabilityAction: emptyAction(),
    externalSpeech: {
      privacy: ExternalSpeechPrivacy.EXTERNAL_ALLOWED,
      consent: ExternalSpeechConsent.MISSING,
      consentReceiptId: null,
    },
    epoch: 0,
    lastEvent: 'INITIALIZED',
  };
}

function transitionAuth(state, target, eventType, extra = {}) {
  if (state.authSession === target) {
    return { ...state, ...extra, lastEvent: eventType };
  }
  const allowed = AUTH_TRANSITIONS.get(state.authSession);
  if (!allowed?.has(target)) {
    throw new Error(
      `invalid auth/session transition: ${state.authSession} -> ${target} (${eventType})`,
    );
  }
  return {
    ...state,
    ...extra,
    authSession: target,
    lastEvent: eventType,
  };
}

function transitionTurn(state, target, eventType) {
  if (state.turn === target) {
    return { ...state, lastEvent: eventType };
  }
  const allowed = TURN_TRANSITIONS.get(state.turn);
  if (!allowed?.has(target)) {
    throw new Error(`invalid turn transition: ${state.turn} -> ${target} (${eventType})`);
  }
  return { ...state, turn: target, lastEvent: eventType };
}

function requireActiveSession(state, eventType) {
  if (!ACTIVE_SESSIONS.has(state.authSession)) {
    throw new Error(`${eventType} requires an active verified Senses session`);
  }
}

function stopConsent(state) {
  return {
    camera: emptyConsent(),
    screen: emptyConsent(),
  };
}

function staleAction(action) {
  if (action.state === CapabilityActionState.NONE || TERMINAL_ACTIONS.has(action.state)) {
    return action;
  }
  return { ...action, stale: true };
}

function updateConsent(state, event, mode) {
  requireActiveSession(state, event.type);
  if (!['camera', 'screen'].includes(event.source)) {
    throw new Error('consent source must be camera or screen');
  }
  if (mode !== ConsentMode.OFF && mode !== ConsentMode.PREVIEW_LOCAL) {
    if (!String(event.consentId || '').trim()) {
      throw new Error(`${mode} consent requires a consent ID`);
    }
  }
  if (mode === ConsentMode.BOUNDED && !String(event.expiresAt || '').trim()) {
    throw new Error('bounded consent requires an expiry');
  }
  return {
    ...state,
    consent: {
      ...state.consent,
      [event.source]: mode === ConsentMode.OFF ? emptyConsent() : {
        mode,
        consentId: event.consentId || null,
        expiresAt: event.expiresAt || null,
      },
    },
    lastEvent: event.type,
  };
}

function requireActionHash(value) {
  if (!/^[0-9a-f]{64}$/i.test(String(value || ''))) {
    throw new Error('capability receipt requires an exact-action SHA-256 hash');
  }
}

function reduceCapabilityReceipt(state, event) {
  const target = Object.values(CapabilityActionState).includes(event.actionState)
    ? event.actionState
    : null;
  if (!target || target === CapabilityActionState.NONE) {
    throw new Error('capability receipt contains an unknown action state');
  }
  if (!String(event.actionId || '').trim()) {
    throw new Error('capability receipt requires an action ID');
  }
  requireActionHash(event.exactActionHash);
  const current = state.capabilityAction;
  if (current.state !== CapabilityActionState.NONE) {
    if (current.actionId !== event.actionId || current.exactActionHash !== event.exactActionHash) {
      throw new Error('capability receipt does not match the active exact action');
    }
  }
  const allowed = ACTION_TRANSITIONS.get(current.state);
  if (!allowed?.has(target)) {
    throw new Error(`invalid capability action transition: ${current.state} -> ${target}`);
  }
  if (TERMINAL_ACTIONS.has(target) && !String(event.authoritativeReceiptId || '').trim()) {
    throw new Error('terminal capability action requires an authoritative receipt');
  }
  if (event.progress !== undefined && event.progress !== null) {
    if (!Number.isFinite(event.progress) || event.progress < 0 || event.progress > 1) {
      throw new Error('capability progress must be between zero and one');
    }
  }
  return {
    ...state,
    capabilityAction: {
      state: target,
      actionId: event.actionId,
      exactActionHash: event.exactActionHash,
      authoritativeReceiptId: event.authoritativeReceiptId || null,
      progress: event.progress ?? current.progress,
      safeSummary: event.safeSummary || current.safeSummary,
      stale: false,
    },
    lastEvent: event.type,
  };
}

export function reduceClientState(state, event) {
  if (!state || !event || typeof event.type !== 'string') {
    throw new TypeError('client reducer requires a state and typed event');
  }
  if (
    EPOCH_BOUND_EVENTS.has(event.type)
    && event.epoch !== undefined
    && event.epoch !== state.epoch
  ) {
    return state;
  }

  switch (event.type) {
    case 'PAIRING_REQUESTED':
      return transitionAuth(state, AuthSessionState.BOOTSTRAP_PENDING, event.type);
    case 'PAIRING_EXCHANGED':
      if (state.authSession !== AuthSessionState.BOOTSTRAP_PENDING) {
        throw new Error(
          `invalid auth/session transition: ${state.authSession} -> ${AuthSessionState.READY} (${event.type})`,
        );
      }
      return transitionAuth(state, AuthSessionState.READY, event.type);
    case 'DEVICE_CREDENTIAL_LOADED':
      if (state.authSession !== AuthSessionState.BOOTSTRAP_REQUIRED) {
        return state;
      }
      return transitionAuth(state, AuthSessionState.READY, event.type);
    case 'PAIRING_FAILED':
      return transitionAuth(state, AuthSessionState.BOOTSTRAP_REQUIRED, event.type, {
        epoch: state.epoch + 1,
      });
    case 'CONNECT_REQUESTED':
      return transitionAuth(state, AuthSessionState.CONNECTING, event.type, {
        transportMode: TransportMode.OFFLINE,
        turn: TurnState.IDLE,
        consent: stopConsent(state),
        epoch: state.epoch + 1,
      });
    case 'SESSION_ISSUED':
      if (state.authSession !== AuthSessionState.CONNECTING) {
        throw new Error('session issuance is valid only while connecting');
      }
      return { ...state, lastEvent: event.type };
    case 'REALTIME_VERIFIED':
      return transitionAuth(state, AuthSessionState.ACTIVE_REALTIME, event.type, {
        transportMode: TransportMode.FULL_REALTIME,
      });
    case 'DEGRADED_VERIFIED': {
      if (!FALLBACK_MODES.has(event.mode)) {
        throw new Error('degraded session requires a verified fallback mode');
      }
      return transitionAuth(state, AuthSessionState.ACTIVE_DEGRADED, event.type, {
        transportMode: event.mode,
      });
    }
    case 'TRANSPORT_LOST':
      return transitionAuth(state, AuthSessionState.RECONNECTING, event.type, {
        transportMode: TransportMode.STATUS_ONLY,
        turn: TurnState.IDLE,
        consent: stopConsent(state),
        capabilityAction: staleAction(state.capabilityAction),
      });
    case 'APP_SUSPENDED':
      return transitionAuth(state, AuthSessionState.SUSPENDED, event.type, {
        transportMode: TransportMode.STATUS_ONLY,
        turn: TurnState.IDLE,
        consent: stopConsent(state),
      });
    case 'RESUME_REQUESTED':
      return transitionAuth(state, AuthSessionState.CONNECTING, event.type, {
        transportMode: TransportMode.STATUS_ONLY,
        epoch: state.epoch + 1,
      });
    case 'SESSION_CLOSED':
      return transitionAuth(state, AuthSessionState.CLOSED, event.type, {
        transportMode: TransportMode.OFFLINE,
        turn: TurnState.IDLE,
        consent: stopConsent(state),
        capabilityAction: staleAction(state.capabilityAction),
        epoch: state.epoch + 1,
      });
    case 'AUTH_REVOKED': {
      return {
        ...state,
        authSession: AuthSessionState.BOOTSTRAP_REQUIRED,
        transportMode: TransportMode.OFFLINE,
        turn: TurnState.IDLE,
        consent: stopConsent(state),
        capabilityAction: staleAction(state.capabilityAction),
        epoch: state.epoch + 1,
        lastEvent: event.type,
      };
    }
    case 'LISTENING_STARTED':
      requireActiveSession(state, event.type);
      return transitionTurn(state, TurnState.LISTENING, event.type);
    case 'MICROPHONE_MUTED':
      return transitionTurn(state, TurnState.IDLE, event.type);
    case 'TEXT_COMMIT_STARTED':
      requireActiveSession(state, event.type);
      return transitionTurn(state, TurnState.COMMITTING, event.type);
    case 'TURN_ACCEPTED':
      return transitionTurn(state, TurnState.THINKING, event.type);
    case 'TURN_REJECTED':
    case 'TEXT_RESPONSE_PRESENTED':
      return transitionTurn(state, TurnState.IDLE, event.type);
    case 'RESPONSE_AUDIO_STARTED':
      return transitionTurn(state, TurnState.SPEAKING, event.type);
    case 'RESPONSE_AUDIO_FINISHED':
      return transitionTurn(state, TurnState.IDLE, event.type);
    case 'TURN_AWAITING_APPROVAL':
      return transitionTurn(state, TurnState.AWAITING_APPROVAL, event.type);
    case 'APPROVAL_HANDED_OFF':
      return transitionTurn(state, TurnState.IDLE, event.type);
    case 'INTERRUPT_REQUESTED':
      return transitionTurn(state, TurnState.INTERRUPTING, event.type);
    case 'INTERRUPT_ACKNOWLEDGED':
      return transitionTurn(
        state,
        event.listening ? TurnState.LISTENING : TurnState.IDLE,
        event.type,
      );
    case 'TURN_RESET':
      return { ...state, turn: TurnState.IDLE, lastEvent: event.type };
    case 'CONSENT_PREVIEW_STARTED':
      return updateConsent(state, event, ConsentMode.PREVIEW_LOCAL);
    case 'CONSENT_ONE_SHOT_GRANTED':
      return updateConsent(state, event, ConsentMode.ONE_SHOT);
    case 'CONSENT_BOUNDED_GRANTED':
      return updateConsent(state, event, ConsentMode.BOUNDED);
    case 'CONSENT_REVOKED':
      return updateConsent(state, event, ConsentMode.OFF);
    case 'EXTERNAL_SPEECH_PRIVACY_SET':
      if (!Object.values(ExternalSpeechPrivacy).includes(event.privacy)) {
        throw new Error('unknown external speech privacy state');
      }
      return {
        ...state,
        externalSpeech: { ...state.externalSpeech, privacy: event.privacy },
        lastEvent: event.type,
      };
    case 'EXTERNAL_SPEECH_CONSENT_RECORDED':
      if (!String(event.receiptId || '').trim()) {
        throw new Error('external speech requires an authoritative consent receipt');
      }
      return {
        ...state,
        externalSpeech: {
          ...state.externalSpeech,
          consent: ExternalSpeechConsent.GRANTED,
          consentReceiptId: event.receiptId,
        },
        lastEvent: event.type,
      };
    case 'EXTERNAL_SPEECH_CONSENT_REVOKED':
      if (!String(event.receiptId || '').trim()) {
        throw new Error('external speech consent revocation requires an authoritative receipt');
      }
      return {
        ...state,
        externalSpeech: {
          ...state.externalSpeech,
          consent: ExternalSpeechConsent.REVOKED,
          consentReceiptId: event.receiptId,
        },
        lastEvent: event.type,
      };
    case 'CAPABILITY_RECEIPT':
      return reduceCapabilityReceipt(state, event);
    case 'CAPABILITY_CLEARED':
      if (!TERMINAL_ACTIONS.has(state.capabilityAction.state)) {
        throw new Error('only a terminal capability action may be cleared');
      }
      return { ...state, capabilityAction: emptyAction(), lastEvent: event.type };
    default:
      throw new Error(`unknown client state event: ${event.type}`);
  }
}

function label(value) {
  return value.toUpperCase().replaceAll('-', ' ');
}

export function deriveClientPresentation(state) {
  const authLabels = {
    [AuthSessionState.BOOTSTRAP_REQUIRED]: 'PAIRING REQUIRED',
    [AuthSessionState.BOOTSTRAP_PENDING]: 'PAIRING PENDING',
    [AuthSessionState.READY]: 'READY',
    [AuthSessionState.CONNECTING]: 'CONNECTING',
    [AuthSessionState.ACTIVE_REALTIME]: 'LIVE',
    [AuthSessionState.ACTIVE_DEGRADED]: label(state.transportMode),
    [AuthSessionState.RECONNECTING]: 'RECONNECTING',
    [AuthSessionState.SUSPENDED]: 'SUSPENDED',
    [AuthSessionState.CLOSED]: 'CLOSED',
  };
  const active = ACTIVE_SESSIONS.has(state.authSession);
  const privateTextOnly = (
    state.externalSpeech.privacy === ExternalSpeechPrivacy.PRIVATE_TEXT_ONLY
  );
  let externalSpeechLabel = 'EXTERNAL CONSENT REQUIRED';
  if (privateTextOnly) {
    externalSpeechLabel = 'PRIVATE TEXT-ONLY';
  } else if (state.externalSpeech.consent === ExternalSpeechConsent.GRANTED) {
    externalSpeechLabel = 'EXTERNAL SPEECH ALLOWED';
  } else if (state.externalSpeech.consent === ExternalSpeechConsent.REVOKED) {
    externalSpeechLabel = 'EXTERNAL CONSENT REVOKED';
  }
  return {
    systemLabel: authLabels[state.authSession],
    systemClass: active ? 'online' : 'offline',
    authLabel: label(state.authSession),
    transportLabel: label(state.transportMode),
    turnLabel: label(state.turn),
    consentLabel: `CAMERA ${label(state.consent.camera.mode)} · SCREEN ${label(state.consent.screen.mode)}`,
    capabilityActionLabel: (
      `${label(state.capabilityAction.state)}${state.capabilityAction.stale ? ' · LAST KNOWN' : ''}`
    ),
    externalSpeechLabel,
    canConnect: [
      AuthSessionState.READY,
      AuthSessionState.CLOSED,
    ].includes(state.authSession),
    canSend: (
      active
      && state.transportMode !== TransportMode.STATUS_ONLY
      && [TurnState.IDLE, TurnState.LISTENING].includes(state.turn)
    ),
    canUseExternalSpeech: (
      !privateTextOnly
      && state.externalSpeech.consent === ExternalSpeechConsent.GRANTED
    ),
    canUseBrowserSpeech: !privateTextOnly && active,
    canUseSensors: active,
  };
}

export function createClientStore(onChange = () => {}, initialState = createInitialClientState()) {
  let current = initialState;
  return Object.freeze({
    getState: () => current,
    getEpoch: () => current.epoch,
    dispatch(event) {
      const next = reduceClientState(current, event);
      if (next !== current) {
        current = next;
        onChange(current, event);
      }
      return current;
    },
  });
}
