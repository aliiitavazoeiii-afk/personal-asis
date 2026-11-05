#!/usr/bin/env bash
# Network-free code-only deployment for existing Personal Assist installation.
# Execute with: bash /root/personal-assist-offline-deploy.sh
set -Eeuo pipefail
cd /opt/personal-assist

test "$(git branch --show-current)" = "feature/pwa-daily-report-v1" || {
  echo "STOP: Unexpected Git branch (expected feature/pwa-daily-report-v1)."
  exit 2
}
test -f .env
test -f compose.yaml
test -f server/app.py
test -f server/static/assets/app.js
grep -Fq "daily-report" server/app.py
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "STOP: tracked files have local changes."
  git status --short
  exit 2
fi
python3 -m py_compile server/app.py
if command -v node >/dev/null 2>&1; then
  node --check server/static/assets/app.js
fi
docker compose config -q

CID="$(docker compose ps -q personal-assist)"
test -n "$CID" || { echo "STOP: Existing service is not running."; exit 3; }
IMAGE_NAME="$(docker inspect --format '{{.Config.Image}}' "$CID")"
test -n "$IMAGE_NAME"
docker image inspect "$IMAGE_NAME" >/dev/null
echo "CURRENT_IMAGE=$IMAGE_NAME"

# Back up the exact image used by the currently running container.
BASE_TAG="personal-assist-safe-base:pwa-$(date +%Y%m%d-%H%M%S)"
docker image tag "$(docker inspect --format '{{.Image}}' "$CID")" "$BASE_TAG"
echo "SAFE_BASE_IMAGE=$BASE_TAG"

rollback() {
  rc=$?
  trap - ERR
  echo "DEPLOY_FAILED exit=$rc; attempting to restore prior image..."
  docker image tag "$BASE_TAG" "$IMAGE_NAME" || true
  docker compose up -d --no-deps --no-build personal-assist || true
  docker compose ps personal-assist || true
  echo "Your SSH session remains open. Saved image: $BASE_TAG"
  exit "$rc"
}
trap rollback ERR

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
cat > "$TMP" <<EOF
FROM $BASE_TAG
USER root
COPY --chown=10001:10001 server/ /app/
USER assistant
EOF

echo "=== OFFLINE BUILD: no PyPI, no new dependencies ==="
docker build --pull=false --network=none -t "$IMAGE_NAME" -f "$TMP" .

echo "=== RECREATE ONLY PERSONAL ASSIST ==="
docker compose up -d --no-deps --no-build personal-assist

echo "=== HEALTH CHECK ==="
curl --retry 12 --retry-delay 2 --retry-connrefused --max-time 5 -fsS http://127.0.0.1:8788/healthz
echo
code="$(curl --max-time 10 -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8788/api/daily-report)"
test "$code" = 401
echo "DAILY_REPORT_PROTECTED=OK"

curl -fsS --max-time 15 https://asis.filmjadiid.ir/ | grep -Fq 'گزارش امروز'
echo "PUBLIC_NEW_UI=OK"

trap - ERR
echo "OFFLINE_DEPLOY_SUCCESS"
docker compose ps personal-assist
echo "ROLLBACK_IMAGE=$BASE_TAG"
