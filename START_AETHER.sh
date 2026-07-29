#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 scripts/founder_bringup.py start
