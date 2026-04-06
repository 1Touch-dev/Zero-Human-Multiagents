#!/usr/bin/env bash
set -euo pipefail

# Run this orchestrator instance alongside an existing Paperclip deployment.
# Defaults avoid clashing with a production instance already using :3000.
PORT="${PORT:-3101}"
HOST="${HOST:-0.0.0.0}"

echo "Starting Multiagents orchestrator in side-by-side mode..."
echo "Host: ${HOST}"
echo "Port: ${PORT}"
echo "Local URL: http://127.0.0.1:${PORT}"
echo "Remote URL (same server): http://<SERVER_IP>:${PORT}"
echo

export HOST
export PORT
export PAPERCLIP_OPEN_ON_LISTEN=false

# local_trusted only allows loopback host binding. For external access on
# a different port, run in authenticated mode.
export PAPERCLIP_DEPLOYMENT_MODE="${PAPERCLIP_DEPLOYMENT_MODE:-authenticated}"
if [[ -z "${BETTER_AUTH_SECRET:-}" ]]; then
  if command -v openssl >/dev/null 2>&1; then
    export BETTER_AUTH_SECRET="$(openssl rand -hex 32)"
  else
    export BETTER_AUTH_SECRET="$(date +%s)-paperclip-side-by-side-secret"
  fi
  echo "Generated temporary BETTER_AUTH_SECRET for this session."
fi

pnpm dev -- --authenticated-private
