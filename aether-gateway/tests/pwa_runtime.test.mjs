import assert from 'node:assert/strict';
import test from 'node:test';

import {
  PwaLifecycleState,
  createInitialPwaRuntime,
  derivePwaPresentation,
  reducePwaRuntime,
} from '../src/aether_gateway/aionui_senses_console/pwa_runtime.js';


const event = (type, values = {}) => ({ type, ...values });


test('cold and warm launch remain explicit and never imply Aether availability', () => {
  const cold = createInitialPwaRuntime({ online: true, visible: true, controlled: false });
  const warm = createInitialPwaRuntime({ online: true, visible: true, controlled: true });

  assert.equal(cold.launchKind, 'cold-uncontrolled');
  assert.equal(warm.launchKind, 'warm-controlled');
  assert.equal(cold.lifecycle, PwaLifecycleState.FOREGROUND);
  assert.equal(derivePwaPresentation(cold).aetherAvailable, false);
  assert.equal(derivePwaPresentation(warm).aetherAvailable, false);
});


test('background suspension is sticky until an explicit foreground resume gesture', () => {
  let state = createInitialPwaRuntime({ online: true, visible: true, controlled: true });
  state = reducePwaRuntime(state, event('AETHER_VERIFIED_AVAILABLE'));
  assert.equal(derivePwaPresentation(state).aetherAvailable, true);

  state = reducePwaRuntime(state, event('PAGE_HIDDEN', { reason: 'page-hidden' }));
  assert.equal(state.lifecycle, PwaLifecycleState.SUSPENDED);
  assert.equal(derivePwaPresentation(state).sensorsAllowed, false);

  state = reducePwaRuntime(state, event('PAGE_VISIBLE'));
  assert.equal(state.lifecycle, PwaLifecycleState.SUSPENDED);
  assert.equal(derivePwaPresentation(state).resumeRequired, true);

  state = reducePwaRuntime(state, event('RESUME_BY_GESTURE'));
  assert.equal(state.lifecycle, PwaLifecycleState.FOREGROUND);
  assert.equal(derivePwaPresentation(state).sensorsAllowed, true);
  assert.equal(derivePwaPresentation(state).aetherAvailable, false);
});


test('offline mode disables cognition and cannot be escaped without network plus gesture', () => {
  let state = createInitialPwaRuntime({ online: true, visible: true, controlled: true });
  state = reducePwaRuntime(state, event('AETHER_VERIFIED_AVAILABLE'));
  state = reducePwaRuntime(state, event('NETWORK_OFFLINE'));

  assert.equal(state.lifecycle, PwaLifecycleState.OFFLINE);
  assert.equal(derivePwaPresentation(state).label, 'OFFLINE — Aether unavailable');
  assert.equal(derivePwaPresentation(state).canSend, false);
  assert.throws(
    () => reducePwaRuntime(state, event('RESUME_BY_GESTURE')),
    /online and visible/,
  );

  state = reducePwaRuntime(state, event('NETWORK_ONLINE'));
  assert.equal(state.lifecycle, PwaLifecycleState.SUSPENDED);
  assert.equal(derivePwaPresentation(state).resumeRequired, true);
  state = reducePwaRuntime(state, event('RESUME_BY_GESTURE'));
  assert.equal(state.lifecycle, PwaLifecycleState.FOREGROUND);
  assert.equal(derivePwaPresentation(state).aetherAvailable, false);
});


test('becoming visible never restarts sensors after a hidden or frozen event', () => {
  for (const suspension of ['PAGE_HIDDEN', 'PAGE_FROZEN']) {
    let state = createInitialPwaRuntime({ online: true, visible: true, controlled: true });
    state = reducePwaRuntime(state, event(suspension));
    state = reducePwaRuntime(state, event('PAGE_VISIBLE'));
    const presentation = derivePwaPresentation(state);
    assert.equal(presentation.sensorsAllowed, false);
    assert.equal(presentation.resumeRequired, true);
  }
});
