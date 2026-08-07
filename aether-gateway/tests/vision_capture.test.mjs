import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createVisionCaptureCoordinator,
} from '../src/aether_gateway/aionui_senses_console/vision_capture.js';


const lease = (values = {}) => ({
  consent_id: 'vision-consent.1',
  receipt_id: 'vision-consent-event.1',
  source: 'camera',
  mode: 'bounded',
  capture_interval_seconds: 15,
  expires_at: '2026-08-08T00:15:00Z',
  ...values,
});


test('local preview alone cannot create a transmission envelope', () => {
  const coordinator = createVisionCaptureCoordinator({
    now: () => new Date('2026-08-08T00:00:00Z'),
  });
  assert.throws(
    () => coordinator.envelope('camera', { data_base64: 'raw' }, 'visible'),
    /server-authoritative consent lease/,
  );
});


test('bounded envelopes carry the exact lease binding and monotonic sequence', () => {
  let now = new Date('2026-08-08T00:00:00Z');
  const coordinator = createVisionCaptureCoordinator({ now: () => now });
  coordinator.grant(lease());

  const first = coordinator.envelope(
    'camera',
    { data_base64: 'frame-1', content_type: 'image/png', width: 2, height: 3 },
    'visible',
  );
  assert.deepEqual(
    {
      consent_id: first.consent_id,
      source: first.source,
      sequence_number: first.sequence_number,
      captured_at: first.captured_at,
    },
    {
      consent_id: 'vision-consent.1',
      source: 'camera',
      sequence_number: 1,
      captured_at: '2026-08-08T00:00:00.000Z',
    },
  );
  assert.throws(
    () => coordinator.envelope(
      'camera',
      { data_base64: 'too-soon', content_type: 'image/png', width: 2, height: 3 },
      'visible',
    ),
    /15-second interval/,
  );
  now = new Date('2026-08-08T00:00:15Z');
  assert.equal(
    coordinator.envelope(
      'camera',
      { data_base64: 'frame-2', content_type: 'image/png', width: 2, height: 3 },
      'visible',
    ).sequence_number,
    2,
  );
  assert.equal(JSON.stringify(coordinator.snapshot()).includes('frame-2'), false);
});


test('source isolation, expiry, and revocation fail closed', () => {
  let now = new Date('2026-08-08T00:00:00Z');
  const coordinator = createVisionCaptureCoordinator({ now: () => now });
  coordinator.grant(lease());
  assert.throws(
    () => coordinator.envelope('screen', { data_base64: 'raw' }, 'visible'),
    /server-authoritative consent lease/,
  );
  now = new Date('2026-08-08T00:15:00Z');
  assert.throws(
    () => coordinator.envelope('camera', { data_base64: 'raw' }, 'visible'),
    /expired/,
  );
  coordinator.stop('camera');
  assert.equal(coordinator.snapshot().camera, null);
});


test('one-shot lease is consumed locally after exactly one envelope', () => {
  const coordinator = createVisionCaptureCoordinator({
    now: () => new Date('2026-08-08T00:00:00Z'),
  });
  coordinator.grant(lease({ mode: 'one-shot', expires_at: '2026-08-08T00:02:00Z' }));
  assert.equal(
    coordinator.envelope('camera', { data_base64: 'one' }, 'visible').sequence_number,
    1,
  );
  assert.throws(
    () => coordinator.envelope('camera', { data_base64: 'two' }, 'visible'),
    /server-authoritative consent lease/,
  );
});
