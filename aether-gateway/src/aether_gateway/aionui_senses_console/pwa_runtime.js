export const PwaLifecycleState = Object.freeze({
  FOREGROUND: 'foreground',
  SUSPENDED: 'suspended',
  OFFLINE: 'offline',
});

export function createInitialPwaRuntime({ online, visible, controlled }) {
  const isOnline = Boolean(online);
  const isVisible = Boolean(visible);
  return {
    online: isOnline,
    visible: isVisible,
    controlled: Boolean(controlled),
    launchKind: controlled ? 'warm-controlled' : 'cold-uncontrolled',
    lifecycle: !isOnline
      ? PwaLifecycleState.OFFLINE
      : (isVisible ? PwaLifecycleState.FOREGROUND : PwaLifecycleState.SUSPENDED),
    resumeRequired: !isOnline || !isVisible,
    aetherVerified: false,
    lastEvent: 'INITIALIZED',
    suspensionReason: !isVisible ? 'initially-hidden' : null,
  };
}

export function reducePwaRuntime(state, event) {
  switch (event.type) {
    case 'AETHER_VERIFIED_AVAILABLE':
      if (
        !state.online
        || !state.visible
        || state.lifecycle !== PwaLifecycleState.FOREGROUND
        || state.resumeRequired
      ) {
        throw new Error('Aether availability requires an online foreground runtime');
      }
      return { ...state, aetherVerified: true, lastEvent: event.type };
    case 'AETHER_UNAVAILABLE':
      return { ...state, aetherVerified: false, lastEvent: event.type };
    case 'PAGE_HIDDEN':
    case 'PAGE_FROZEN':
      return {
        ...state,
        visible: false,
        lifecycle: state.online ? PwaLifecycleState.SUSPENDED : PwaLifecycleState.OFFLINE,
        resumeRequired: true,
        aetherVerified: false,
        suspensionReason: String(event.reason || event.type).slice(0, 120),
        lastEvent: event.type,
      };
    case 'PAGE_VISIBLE':
      return {
        ...state,
        visible: true,
        lifecycle: state.online
          ? (state.resumeRequired ? PwaLifecycleState.SUSPENDED : PwaLifecycleState.FOREGROUND)
          : PwaLifecycleState.OFFLINE,
        aetherVerified: false,
        lastEvent: event.type,
      };
    case 'NETWORK_OFFLINE':
      return {
        ...state,
        online: false,
        lifecycle: PwaLifecycleState.OFFLINE,
        resumeRequired: true,
        aetherVerified: false,
        suspensionReason: 'network-offline',
        lastEvent: event.type,
      };
    case 'NETWORK_ONLINE':
      return {
        ...state,
        online: true,
        lifecycle: PwaLifecycleState.SUSPENDED,
        resumeRequired: true,
        aetherVerified: false,
        suspensionReason: 'network-restored',
        lastEvent: event.type,
      };
    case 'RESUME_BY_GESTURE':
      if (!state.online || !state.visible) {
        throw new Error('resume requires an online and visible Senses client');
      }
      return {
        ...state,
        lifecycle: PwaLifecycleState.FOREGROUND,
        resumeRequired: false,
        aetherVerified: false,
        suspensionReason: null,
        lastEvent: event.type,
      };
    case 'SERVICE_WORKER_CONTROLLING':
      return {
        ...state,
        controlled: true,
        launchKind: 'warm-controlled',
        lastEvent: event.type,
      };
    default:
      throw new Error(`unsupported PWA runtime event: ${event.type}`);
  }
}

export function derivePwaPresentation(state) {
  if (!state.online || state.lifecycle === PwaLifecycleState.OFFLINE) {
    return {
      label: 'OFFLINE — Aether unavailable',
      aetherAvailable: false,
      canSend: false,
      sensorsAllowed: false,
      resumeRequired: true,
    };
  }
  if (state.lifecycle === PwaLifecycleState.SUSPENDED || state.resumeRequired) {
    return {
      label: 'SUSPENDED — Resume required',
      aetherAvailable: false,
      canSend: false,
      sensorsAllowed: false,
      resumeRequired: true,
    };
  }
  return {
    label: state.aetherVerified ? 'Aether verified available' : 'Aether not yet verified',
    aetherAvailable: state.aetherVerified,
    canSend: state.aetherVerified,
    sensorsAllowed: true,
    resumeRequired: false,
  };
}
