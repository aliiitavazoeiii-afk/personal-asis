#!/usr/bin/env bash
# Pull-only offline code deployment for the single Personal Assistant Docker service.
# Never install new Python dependencies; never change /data or .env.
set -Eeuo pipefail
umask 077
APP=/opt/personal-assist
STATE=/var/lib/personal-assist-deploy
mkdir -p "$STATE"
exec 9>"$STATE/lock"
flock -n 9 || exit 0
cd "$APP"
test -f .env && test -f compose.yaml
test "$(git remote get-url origin)" = "https://github.com/aliiitavazoeiii-afk/personal-asis.git"
test -z "$(git status --porcelain --untracked-files=no)"
CURRENT="$(git rev-parse HEAD)"
test "$(cat "$STATE/applied.sha")" = "$CURRENT" || { echo "STOP: drift detected"; exit 2; }

timeout 80 git fetch --no-tags --quiet origin refs/heads/assistant-production:refs/remotes/origin/assistant-production
TARGET="$(git rev-parse refs/remotes/origin/assistant-production)"
if test "$CURRENT" = "$TARGET"; then echo "UP_TO_DATE=$CURRENT"; exit 0; fi
git merge-base --is-ancestor "$CURRENT" "$TARGET" || { echo "STOP: non-fast-forward"; exit 2; }
if test -f "$STATE/failed.sha" && test "$(cat "$STATE/failed.sha")" = "$TARGET"; then
  echo "SKIP_FAILED_COMMIT=$TARGET"; exit 0
fi
if ! git diff --quiet "$CURRENT" "$TARGET" -- server/requirements.txt Dockerfile compose.yaml; then
  echo "STOP: runtime dependencies or Docker configuration changed; manual review required"; exit 2
fi

CID="$(docker compose ps -q personal-assist)"
test -n "$CID"
OLD_ID="$(docker inspect --format '{{.Image}}' "$CID")"
OLD_TAG="$(docker inspect --format '{{.Config.Image}}' "$CID")"
test -n "$OLD_ID" && test -n "$OLD_TAG"
DATA_SRC="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$CID")"
test -f "$DATA_SRC/assistant.sqlite3" || { echo "STOP: database not found"; exit 2; }
BASE_TAG="personal-assist-safe-base:$(printf '%s' "$CURRENT" | cut -c1-12)"
NEXT_TAG="personal-assist-candidate:$(printf '%s' "$TARGET" | cut -c1-12)"
docker image tag "$OLD_ID" "$BASE_TAG"
WORK="$(mktemp -d)"
CHANGED=no

cleanup() {
  git -C "$APP" worktree remove --force "$WORK/candidate" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
rollback() {
  rc=$?
  trap - ERR
  if test "$CHANGED" = yes; then
    git -C "$APP" checkout --quiet --detach "$CURRENT" || true
    docker image tag "$OLD_ID" "$OLD_TAG" || true
    docker compose up -d --no-deps --no-build --force-recreate personal-assist || true
    printf '%s\n' "$TARGET" > "$STATE/failed.sha"
    echo "ROLLED_BACK_TO=$CURRENT"
  fi
  echo "DEPLOY_FAILED=$TARGET EXIT=$rc" >&2
  exit "$rc"
}
trap cleanup EXIT
trap rollback ERR

git worktree add --quiet --detach "$WORK/candidate" "$TARGET"
python3 -m py_compile "$WORK/candidate/server/app.py" "$WORK/candidate/server/mcp_bridge.py"
if command -v node >/dev/null 2>&1; then node --check "$WORK/candidate/server/static/assets/app.js"; fi
printf 'FROM %s\nUSER root\nCOPY --chown=10001:10001 server/ /app/\nUSER assistant\n' "$BASE_TAG" > "$WORK/Dockerfile"
timeout 600 docker build --pull=false --network=none -q -t "$NEXT_TAG" -f "$WORK/Dockerfile" "$WORK/candidate"
docker run --rm --network=none --entrypoint python -e APP_PASSWORD=deploy-test -e SESSION_SECRET=deploy-test-secret-longer-than-32-chars -e DB_PATH=/tmp/deploy-test.sqlite "$NEXT_TAG" -c 'import app; assert app.app is not None'

# Consistent SQLite online backup prior to any container restart.
BACKUP_DIR=/var/backups/personal-assist
mkdir -p "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/assistant-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
python3 - "$DATA_SRC/assistant.sqlite3" "$BACKUP" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as source:
    with sqlite3.connect(sys.argv[2]) as destination:
        source.backup(destination)
PY
chmod 600 "$BACKUP"
CHANGED=yes
git checkout --quiet --detach "$TARGET"
docker image tag "$NEXT_TAG" "$OLD_TAG"
docker compose up -d --no-deps --no-build --force-recreate personal-assist
# Docker reports "Started" before Uvicorn has finished binding its TCP listener.
# A startup-time TCP reset (curl 56) is transient: retry *all* non-200 results.
READY=no
for ((probe=1; probe<=60; probe++)); do
  if curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:8788/healthz >/dev/null 2>&1; then
    READY=yes
    echo "APP_HEALTH_OK_ON_PROBE=$probe"
    break
  fi
  sleep 2
done
if test "$READY" != yes; then
  echo "STOP: new app did not become healthy within 120 seconds"
  docker compose ps personal-assist || true
  docker compose logs --tail=40 personal-assist || true
  false
fi
# Confirm the newly introduced MCP endpoint has an actual auth boundary;
# when no bearer token is supplied, it must return HTTP 401 (not 404/200).
MCP_DENIED="$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' --max-time 6 -H 'Host: asis.filmjadiid.ir' http://127.0.0.1:8788/mcp/)"
if test "$MCP_DENIED" != 401; then
  echo "STOP: expected token-protected MCP endpoint, got HTTP=$MCP_DENIED"
  false
fi
echo "MCP_AUTH_GATE_OK"
printf '%s\n' "$TARGET" > "$STATE/applied.sha"
rm -f "$STATE/failed.sha"
CHANGED=no
echo "DEPLOY_OK=$TARGET"
