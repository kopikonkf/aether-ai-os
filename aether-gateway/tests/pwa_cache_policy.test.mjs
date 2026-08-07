import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CACHE_NAME,
  CACHE_PREFIX,
  CacheDecision,
  SHELL_NAVIGATION_URL,
  VERSIONED_STATIC_ASSETS,
  cacheCleanupPlan,
  classifyRequest,
} from '../src/aether_gateway/aionui_senses_console/pwa_cache_policy.js';


const ORIGIN = 'https://aethers.my.id';


function request(path, values = {}) {
  return {
    url: new URL(path, ORIGIN).href,
    method: 'GET',
    mode: 'same-origin',
    destination: 'script',
    ...values,
  };
}


test('only exact versioned same-origin shell assets are cacheable', () => {
  assert.match(CACHE_NAME, new RegExp(`^${CACHE_PREFIX}`));
  assert.ok(VERSIONED_STATIC_ASSETS.length >= 6);
  for (const path of VERSIONED_STATIC_ASSETS) {
    assert.equal(
      classifyRequest(request(path), ORIGIN),
      CacheDecision.CACHE_FIRST_STATIC,
      path,
    );
  }
  assert.equal(
    classifyRequest(request('/senses/app.js'), ORIGIN),
    CacheDecision.NETWORK_ONLY,
  );
  assert.equal(
    classifyRequest(request(`${VERSIONED_STATIC_ASSETS[0]}&unexpected=1`), ORIGIN),
    CacheDecision.NETWORK_ONLY,
  );
  assert.equal(
    classifyRequest(request('https://cdn.jsdelivr.net/npm/livekit-client/+esm'), ORIGIN),
    CacheDecision.NETWORK_ONLY,
  );
});


test('the canonical shell is network-first with one offline fallback key', () => {
  assert.equal(SHELL_NAVIGATION_URL, '/senses');
  assert.equal(
    classifyRequest(request('/senses', { mode: 'navigate', destination: 'document' }), ORIGIN),
    CacheDecision.NETWORK_FIRST_SHELL,
  );
  assert.equal(
    classifyRequest(request('/senses?token=must-not-cache', {
      mode: 'navigate', destination: 'document',
    }), ORIGIN),
    CacheDecision.NETWORK_ONLY,
  );
});


test('API, auth, status, media, mutation, and unknown requests are network-only', () => {
  for (const path of [
    '/api/browser-senses/status',
    '/api/browser-senses/bootstrap/requests',
    '/api/browser-senses/session/status',
    '/api/browser-senses/text',
    '/api/browser-senses/vision',
    '/aether/api/status',
    '/api/status',
    '/health',
    '/senses/transcript.json',
    '/senses/frame.png',
  ]) {
    assert.equal(classifyRequest(request(path), ORIGIN), CacheDecision.NETWORK_ONLY, path);
  }
  assert.equal(
    classifyRequest(request(VERSIONED_STATIC_ASSETS[0], { method: 'POST' }), ORIGIN),
    CacheDecision.NETWORK_ONLY,
  );
  assert.equal(
    classifyRequest(request(VERSIONED_STATIC_ASSETS[0], { destination: 'audio' }), ORIGIN),
    CacheDecision.NETWORK_ONLY,
  );
});


test('activation and explicit purge delete only Aether Senses managed caches', () => {
  assert.deepEqual(
    cacheCleanupPlan([
      CACHE_NAME,
      `${CACHE_PREFIX}old-build`,
      'other-aether-console-cache',
      'third-party-cache',
    ]),
    [`${CACHE_PREFIX}old-build`],
  );
  assert.deepEqual(
    cacheCleanupPlan([CACHE_NAME, `${CACHE_PREFIX}old-build`], { includeCurrent: true }),
    [CACHE_NAME, `${CACHE_PREFIX}old-build`],
  );
});
