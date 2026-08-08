export const PWA_BUILD_ID = 'senses-v1-slice-9-20260808-1';
export const CACHE_PREFIX = 'aether-senses-shell-';
export const CACHE_NAME = `${CACHE_PREFIX}${PWA_BUILD_ID}`;
export const SHELL_NAVIGATION_URL = '/senses';

const versioned = (path) => `${path}?v=${PWA_BUILD_ID}`;

export const VERSIONED_STATIC_ASSETS = Object.freeze([
  versioned('/senses/styles.css'),
  versioned('/senses/app.js'),
  versioned('/senses/client_state.js'),
  versioned('/senses/capability_actions.js'),
  versioned('/senses/turn_generation.js'),
  versioned('/senses/vision_capture.js'),
  versioned('/senses/pwa_runtime.js'),
  versioned('/senses/pwa_cache_policy.js'),
  versioned('/senses/icons/aether-senses-192-v1.png'),
  versioned('/senses/icons/aether-senses-512-v1.png'),
  versioned('/senses/icons/aether-senses-maskable-512-v1.png'),
  versioned('/senses/vendor/livekit-client-2.17.2.esm.js'),
]);

export const PRECACHE_ASSETS = Object.freeze([
  SHELL_NAVIGATION_URL,
  ...VERSIONED_STATIC_ASSETS.filter((path) => !path.includes('/vendor/')),
]);

export const CacheDecision = Object.freeze({
  CACHE_FIRST_STATIC: 'cache-first-static',
  NETWORK_FIRST_SHELL: 'network-first-shell',
  NETWORK_ONLY: 'network-only',
});

const STATIC_ASSET_KEYS = new Set(VERSIONED_STATIC_ASSETS);
const MEDIA_DESTINATIONS = new Set(['audio', 'video', 'track']);

function requestKey(url) {
  return `${url.pathname}${url.search}`;
}

export function classifyRequest(request, allowedOrigin) {
  let url;
  try {
    url = new URL(request.url, allowedOrigin);
  } catch {
    return CacheDecision.NETWORK_ONLY;
  }
  if (
    url.origin !== allowedOrigin
    || String(request.method || 'GET').toUpperCase() !== 'GET'
    || MEDIA_DESTINATIONS.has(String(request.destination || '').toLowerCase())
  ) {
    return CacheDecision.NETWORK_ONLY;
  }
  const key = requestKey(url);
  if (
    key === SHELL_NAVIGATION_URL
    && request.mode === 'navigate'
    && request.destination === 'document'
  ) {
    return CacheDecision.NETWORK_FIRST_SHELL;
  }
  if (STATIC_ASSET_KEYS.has(key)) {
    return CacheDecision.CACHE_FIRST_STATIC;
  }
  return CacheDecision.NETWORK_ONLY;
}

export function cacheCleanupPlan(cacheNames, { includeCurrent = false } = {}) {
  return cacheNames.filter((name) => (
    name.startsWith(CACHE_PREFIX) && (includeCurrent || name !== CACHE_NAME)
  ));
}
