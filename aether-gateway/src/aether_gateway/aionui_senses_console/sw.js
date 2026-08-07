import {
  CACHE_NAME,
  CacheDecision,
  PRECACHE_ASSETS,
  SHELL_NAVIGATION_URL,
  cacheCleanupPlan,
  classifyRequest,
} from './pwa_cache_policy.js?v=senses-v1-slice-8-20260808-1';

async function fetchStatic(path) {
  const response = await fetch(new Request(path, {
    method: 'GET',
    credentials: 'same-origin',
    cache: 'reload',
  }));
  if (!response.ok || response.type === 'opaque') {
    throw new Error(`PWA shell asset fetch failed: ${path}`);
  }
  return response;
}

async function precacheShell() {
  const cache = await caches.open(CACHE_NAME);
  for (const path of PRECACHE_ASSETS) {
    await cache.put(path, await fetchStatic(path));
  }
}

async function deleteManagedCaches(includeCurrent = false) {
  const names = await caches.keys();
  await Promise.all(
    cacheCleanupPlan(names, { includeCurrent }).map((name) => caches.delete(name)),
  );
}

async function networkFirstShell(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request, { cache: 'no-store' });
    if (response.ok && response.type !== 'opaque') {
      await cache.put(SHELL_NAVIGATION_URL, response.clone());
    }
    return response;
  } catch {
    const fallback = await cache.match(SHELL_NAVIGATION_URL);
    if (fallback) return fallback;
    throw new Error('Aether Senses shell is unavailable offline');
  }
}

async function cacheFirstStatic(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request, { cache: 'no-store' });
  if (response.ok && response.type !== 'opaque') {
    await cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener('install', (event) => {
  event.waitUntil(precacheShell());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    await deleteManagedCaches(false);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const decision = classifyRequest(event.request, self.location.origin);
  if (decision === CacheDecision.NETWORK_FIRST_SHELL) {
    event.respondWith(networkFirstShell(event.request));
  } else if (decision === CacheDecision.CACHE_FIRST_STATIC) {
    event.respondWith(cacheFirstStatic(event.request));
  }
  // NETWORK_ONLY intentionally does not call respondWith. The browser performs
  // an ordinary network request and no Cache Storage write can occur here.
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'AETHER_CLEAR_CACHES') {
    event.waitUntil(deleteManagedCaches(true));
  } else if (event.data?.type === 'AETHER_ACTIVATE_UPDATE') {
    event.waitUntil(self.skipWaiting());
  }
});
