export const TURN_CONTROL_TOPIC = 'aether.senses.turn-control.v1';

const TURN_CONTROL_FIELDS = Object.freeze([
  'type',
  'turn_id',
  'correlation_id',
  'previous_generation',
  'next_generation',
  'reason',
]);

function defaultIdFactory(kind) {
  if (!globalThis.crypto?.randomUUID) {
    throw new Error('turn IDs require crypto.randomUUID');
  }
  return `${kind}-${globalThis.crypto.randomUUID()}`;
}

function requireText(value, name) {
  const normalized = String(value || '').trim();
  if (!normalized) throw new Error(`${name} is required`);
  return normalized;
}

function snapshot(value) {
  return value ? Object.freeze({ ...value }) : null;
}

function sameTurn(left, right) {
  return Boolean(
    left
    && right
    && left.turnId === (right.turnId ?? right.turn_id)
    && left.correlationId === (right.correlationId ?? right.correlation_id)
  );
}

export function createTurnGenerationCoordinator({ idFactory = defaultIdFactory } = {}) {
  let active = null;
  let lastUnconfirmedTurnId = null;
  let interruption = null;

  function requireMatching(candidate) {
    if (!sameTurn(active, candidate)) {
      throw new Error('turn result does not match the active turn');
    }
  }

  function start({ retryOfTurnId = null } = {}) {
    if (active && !['completed', 'interrupted', 'failed', 'not-confirmed'].includes(active.delivery)) {
      throw new Error('a turn generation is already active');
    }
    active = {
      turnId: requireText(idFactory('turn'), 'turn ID'),
      correlationId: requireText(idFactory('correlation'), 'correlation ID'),
      generation: 0,
      delivery: 'in-flight',
      retryOfTurnId: retryOfTurnId ? requireText(retryOfTurnId, 'retry turn ID') : null,
    };
    interruption = null;
    return snapshot(active);
  }

  function adopt(candidate) {
    const turnId = requireText(candidate?.turnId ?? candidate?.turn_id, 'turn ID');
    const correlationId = requireText(
      candidate?.correlationId ?? candidate?.correlation_id,
      'correlation ID',
    );
    const generation = candidate?.generation;
    if (!Number.isInteger(generation) || generation < 0) {
      throw new Error('turn generation must be a non-negative integer');
    }
    if (sameTurn(active, { turnId, correlationId }) && active.generation === generation) {
      return snapshot(active);
    }
    active = {
      turnId,
      correlationId,
      generation,
      delivery: 'in-flight',
      retryOfTurnId: candidate?.retryOfTurnId ?? candidate?.retry_of_turn_id ?? null,
    };
    interruption = null;
    return snapshot(active);
  }

  return Object.freeze({
    start,
    adopt,
    reset() {
      active = null;
      interruption = null;
      lastUnconfirmedTurnId = null;
    },
    snapshot: () => snapshot(active),
    accepts(candidate) {
      return Boolean(
        sameTurn(active, candidate)
        && active.generation === candidate.generation
      );
    },
    interrupt(reason) {
      if (!active) throw new Error('cannot interrupt without an active turn');
      if (interruption) return interruption;
      const previousGeneration = active.generation;
      active = {
        ...active,
        generation: previousGeneration + 1,
        delivery: 'interrupting',
      };
      interruption = Object.freeze({
        turnId: active.turnId,
        correlationId: active.correlationId,
        reason: requireText(reason, 'interruption reason'),
        previousGeneration,
        nextGeneration: active.generation,
      });
      return interruption;
    },
    acknowledgeInterruption(receiptId) {
      if (!active || !interruption) {
        throw new Error('no interruption is awaiting acknowledgement');
      }
      active = {
        ...active,
        delivery: 'interrupted',
        authoritativeReceiptId: requireText(receiptId, 'interruption receipt ID'),
      };
      return snapshot(active);
    },
    markAmbiguous(candidate) {
      requireMatching(candidate);
      if (active.generation !== candidate.generation) return snapshot(active);
      active = { ...active, delivery: 'reconciling' };
      return snapshot(active);
    },
    reconcile(status) {
      requireMatching(status);
      const state = String(status.state || '').trim();
      if (!['completed', 'interrupted', 'failed', 'not-confirmed', 'accepted'].includes(state)) {
        throw new Error('turn reconciliation returned an unknown state');
      }
      const delivery = state === 'accepted' ? 'reconciling' : state;
      const generation = Number.isInteger(status.generation)
        ? status.generation
        : active.generation;
      if (generation < active.generation) {
        throw new Error('turn reconciliation cannot move generation backwards');
      }
      active = {
        ...active,
        generation,
        delivery,
        authoritativeReceiptId: status.receipt_id || active.authoritativeReceiptId,
      };
      if (delivery === 'not-confirmed') lastUnconfirmedTurnId = active.turnId;
      return snapshot(active);
    },
    startExplicitRetry() {
      if (!active || active.delivery !== 'not-confirmed') {
        throw new Error('explicit retry requires an unconfirmed prior turn');
      }
      const retryOfTurnId = lastUnconfirmedTurnId || active.turnId;
      active = null;
      return start({ retryOfTurnId });
    },
  });
}

function boundedControl(control) {
  const clean = {};
  for (const field of TURN_CONTROL_FIELDS) clean[field] = control?.[field];
  if (clean.type !== 'interrupt') throw new Error('unknown turn control type');
  requireText(clean.turn_id, 'turn control turn ID');
  requireText(clean.correlation_id, 'turn control correlation ID');
  requireText(clean.reason, 'turn control reason');
  if (
    !Number.isInteger(clean.previous_generation)
    || clean.previous_generation < 0
    || clean.next_generation !== clean.previous_generation + 1
  ) {
    throw new Error('turn control must advance generation exactly once');
  }
  return clean;
}

function boundedPublish(promise, timeoutMilliseconds = 500) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('LiveKit turn control timed out')),
      timeoutMilliseconds,
    );
    Promise.resolve(promise).then(
      (value) => {
        clearTimeout(timeout);
        resolve(value);
      },
      (error) => {
        clearTimeout(timeout);
        reject(error);
      },
    );
  });
}

export async function stopTurnAudio({
  speechSynthesis,
  recognition,
  remoteTracks,
  remoteAudioElements,
  room,
  control,
}) {
  try { speechSynthesis?.cancel?.(); } catch { /* continue stopping other surfaces */ }
  try { recognition?.abort?.(); } catch { /* continue stopping other surfaces */ }
  for (const element of remoteAudioElements || []) {
    try { element.pause?.(); } catch { /* continue */ }
    try { element.srcObject = null; } catch { /* continue */ }
    try { element.remove?.(); } catch { /* continue */ }
  }
  remoteAudioElements?.clear?.();
  for (const track of remoteTracks || []) {
    try { track.detach?.(); } catch { /* continue */ }
  }

  let livekitControlSent = false;
  if (room?.localParticipant?.publishData) {
    const payload = new TextEncoder().encode(JSON.stringify(boundedControl(control)));
    try {
      await boundedPublish(room.localParticipant.publishData(payload, {
        reliable: true,
        topic: TURN_CONTROL_TOPIC,
      }));
      livekitControlSent = true;
    } catch {
      // Local silence has already been enforced. Gateway reconciliation records
      // whether provider-side cancellation could be confirmed.
    }
  }
  return Object.freeze({ browserAudioStopped: true, livekitControlSent });
}
