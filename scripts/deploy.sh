#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo 'ERROR: cp .env.example .env and set secure values first'; exit 1; }
command -v docker >/dev/null || { echo 'Docker is required'; exit 1; }
docker compose config --quiet
docker compose up -d --build --remove-orphans
docker compose ps
printf '\nLocal health check: http://127.0.0.1:8788/healthz\n'
curl --fail --show-error http://127.0.0.1:8788/healthz
printf '\nDeployment OK; configure HTTPS reverse proxy before Android APK.\n'
