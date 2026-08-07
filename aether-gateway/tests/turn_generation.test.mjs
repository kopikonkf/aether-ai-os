import assert from 'node:assert/strict';
import test from 'node:test';

import {
  TURN_CONTROL_TOPIC,
  createTurnGenerationCoordinator,
  stopTurnAudio,
} from '../src/aether_gateway/aionui_senses_console/turn_generation.js';

function deterministicIds() {
  const values = [
    'turn-00000000-0000-4000-8000-000000000001',
    'corr-00000000-0000-4000-8000-000000000001',
    'turn-00000000-0000-4000-8000-000000000002',
    'corr-00000000-0000-4000-8000-000000000002',
  ];
  return () => values.shift();
}

test('turn coordinator binds one stable turn and correlation ID before dispatch', () => {
  const turns = createTurnGenerationCoordinator({ idFactory: deterministicIds() });
  const first = turns.start();

  assert.equal(first.turnId, 'turn-00000000-0000-4000-8000-000000000001');
  assert.equal(first.correlationId, 'corr-00000000-0000-4000-8000-000000000001');
  assert.equal(first.generation, 0);
  assert.equal(first.retryOfTurnId, null);
  assert.equal(turns.accepts(first), true);
  assert.throws(() => turns.start(), /already active/);
});

test('interruption increments generation once and every old callback becomes stale', () => {
  const turns = createTurnGenerationCoordinator({ idFactory: deterministicIds() });
  const first = turns.start();
  const interrupted = turns.interrupt('explicit_stop');
  const duplicate = turns.interrupt('explicit_stop');

  assert.equal(interrupted.previousGeneration, 0);
  assert.equal(interrupted.nextGeneration, 1);
  assert.equal(duplicate, interrupted);
  assert.equal(turns.accepts(first), false);
  assert.equal(turns.accepts({ ...first, generation: 1 }), true);
});

test('worker turn metadata can be adopted and a newer worker turn invalidates the old one', () => {
  const turns = createTurnGenerationCoordinator({ idFactory: deterministicIds() });
  const first = turns.adopt({
    turn_id: 'worker-turn-1',
    correlation_id: 'worker-corr-1',
    generation: 0,
  });
  const second = turns.adopt({
    turn_id: 'worker-turn-2',
    correlation_id: 'worker-corr-2',
    generation: 0,
  });

  assert.equal(turns.accepts(first), false);
  assert.equal(turns.accepts(second), true);
  assert.equal(second.delivery, 'in-flight');
});

test('ambiguous delivery only reconciles the same ID and explicit retry gets a new linked ID', () => {
  const turns = createTurnGenerationCoordinator({ idFactory: deterministicIds() });
  const first = turns.start();
  turns.markAmbiguous(first);

  assert.equal(turns.snapshot().delivery, 'reconciling');
  assert.throws(
    () => turns.reconcile({ turn_id: 'turn-other', correlation_id: first.correlationId }),
    /does not match the active turn/,
  );
  turns.reconcile({
    turn_id: first.turnId,
    correlation_id: first.correlationId,
    state: 'not-confirmed',
  });
  const retry = turns.startExplicitRetry();

  assert.notEqual(retry.turnId, first.turnId);
  assert.notEqual(retry.correlationId, first.correlationId);
  assert.equal(retry.retryOfTurnId, first.turnId);
});

test('reconciliation may only advance a matching generation', () => {
  const turns = createTurnGenerationCoordinator({ idFactory: deterministicIds() });
  const first = turns.start();
  turns.markAmbiguous(first);
  const interrupted = turns.reconcile({
    turn_id: first.turnId,
    correlation_id: first.correlationId,
    generation: 1,
    state: 'interrupted',
    receipt_id: 'interrupt-receipt-1',
  });

  assert.equal(interrupted.generation, 1);
  assert.equal(interrupted.delivery, 'interrupted');
  assert.throws(
    () => turns.reconcile({ ...first, state: 'completed' }),
    /cannot move generation backwards/,
  );
});

test('audio stop synchronously silences browser and LiveKit playout then sends bounded control', async () => {
  const calls = [];
  const element = {
    pause: () => calls.push('pause'),
    remove: () => calls.push('remove'),
    srcObject: { active: true },
  };
  const track = {
    detach: () => calls.push('detach'),
  };
  const payloads = [];
  const room = {
    localParticipant: {
      publishData: async (payload, options) => {
        payloads.push({ payload: new TextDecoder().decode(payload), options });
      },
    },
  };

  const remoteTracks = new Set([track]);
  const result = await stopTurnAudio({
    speechSynthesis: { cancel: () => calls.push('speech-cancel') },
    recognition: { abort: () => calls.push('recognition-abort') },
    remoteTracks,
    remoteAudioElements: new Set([element]),
    room,
    control: {
      type: 'interrupt',
      turn_id: 'turn-1',
      correlation_id: 'corr-1',
      previous_generation: 0,
      next_generation: 1,
      reason: 'explicit_stop',
      text: 'must never cross the LiveKit control channel',
    },
  });

  assert.deepEqual(calls, [
    'speech-cancel',
    'recognition-abort',
    'pause',
    'remove',
    'detach',
  ]);
  assert.equal(element.srcObject, null);
  assert.equal(payloads.length, 1);
  assert.equal(payloads[0].options.topic, TURN_CONTROL_TOPIC);
  assert.equal(payloads[0].options.reliable, true);
  assert.equal(JSON.parse(payloads[0].payload).turn_id, 'turn-1');
  assert.equal('text' in JSON.parse(payloads[0].payload), false);
  assert.equal(result.livekitControlSent, true);
  assert.equal(remoteTracks.has(track), true);
});

test('audio stop remains local and truthful when no LiveKit room exists', async () => {
  const result = await stopTurnAudio({
    speechSynthesis: { cancel() {} },
    recognition: null,
    remoteTracks: new Set(),
    remoteAudioElements: new Set(),
    room: null,
    control: {
      type: 'interrupt',
      turn_id: 'turn-1',
      correlation_id: 'corr-1',
      previous_generation: 0,
      next_generation: 1,
      reason: 'explicit_stop',
    },
  });

  assert.equal(result.browserAudioStopped, true);
  assert.equal(result.livekitControlSent, false);
});
