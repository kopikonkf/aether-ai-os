#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f aether-core/.env ]]; then
  python scripts/founder_bringup.py init
fi
if [[ ! -f deploy/.env ]]; then
  cp deploy/.env.example deploy/.env
  echo "Created deploy/.env. Set AETHER_DOMAIN before public deployment." >&2
fi
profiles=()
if grep -Eq '^LIVEKIT_URL=.+$' aether-core/.env && \
   grep -Eq '^LIVEKIT_API_KEY=.+$' aether-core/.env && \
   grep -Eq '^LIVEKIT_API_SECRET=.+$' aether-core/.env; then
  profiles=(--profile livekit)
fi
exec docker compose --env-file deploy/.env -f deploy/docker-compose.yml "${profiles[@]}" up --build
