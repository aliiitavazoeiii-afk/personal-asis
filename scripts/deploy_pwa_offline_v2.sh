#!/usr/bin/env bash
# Network-free code-only deployment for existing Personal Assist installation.
# Execute with: bash /root/personal-assist-offline-v2.sh
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

echo "=== WAIT UP TO 120s FOR APPLICATION READINESS ==="
READY=0
for attempt in $(seq 1 60); do
  if curl --noproxy '*' --max-time 3 -fsS http://127.0.0.1:8788/healthz >/dev/null 2>&1; then
    READY=1
    echo "HEALTH_OK after check $attempt"
    break
  fi
  if (( attempt % 10 == 0 )); then
    echo "Still starting (check $attempt/60)..."
    docker compose ps personal-assist
  fi
  sleep 2
done
if (( READY != 1 )); then
  echo "NEW_CONTAINER_NOT_READY; recent application logs:"
  docker compose logs --tail=70 personal-assist || true
  false
fi

echo "=== CONFIRM NEW API AND UI ARE RUNNING ==="
code="$(curl --noproxy '*' --max-time 10 -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8788/api/daily-report)"
if [[ "$code" != "401" ]]; then
  echo "Daily report auth check failed: HTTP $code"
  docker compose logs --tail=40 personal-assist || true
  false
fi
echo "DAILY_REPORT_PROTECTED=OK"
if curl --noproxy '*' -fsS --max-time 10 http://127.0.0.1:8788/ | grep -Fq 'گزارش امروز'; then
  echo "LOCAL_NEW_UI=OK"
else
  echo "Local UI marker missing."
  false
fi

# External networking may be slow/blocked on this VPS; never roll back healthy
# application solely because the public domain cannot be reached from the VPS.
if curl -fsS --max-time 12 https://asis.filmjadiid.ir/ | grep -Fq 'گزارش امروز'; then
  echo "PUBLIC_NEW_UI=OK"
else
  echo "PUBLIC_CHECK=WARNING (check from your phone; local deployment is healthy)"
fi

trap - ERR
echo "OFFLINE_DEPLOY_SUCCESS"
docker compose ps personal-assist
echo "ROLLBACK_IMAGE=$BASE_TAG"
