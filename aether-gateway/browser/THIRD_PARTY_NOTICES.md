# Aether Senses browser dependency notices

The generated `livekit-client-2.17.2.esm.js` bundle is built from the exact npm
dependencies locked in this directory. It is committed so the Windows release
does not require Node.js or public-CDN access at runtime.

- `livekit-client` 2.17.2 — Apache-2.0; <https://github.com/livekit/client-sdk-js>
- `esbuild` 0.28.1 — MIT; build-time only; <https://github.com/evanw/esbuild>

The generated bundle retains applicable legal comments. `npm ci` integrity
verification plus the CI rebuild/diff check is the provenance boundary.
