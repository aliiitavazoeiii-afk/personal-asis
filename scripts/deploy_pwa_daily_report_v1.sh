#!/usr/bin/env bash
# Run as: bash /path/to/deploy_pwa_daily_report_v1.sh
# A child Bash process handles errors, so an interactive SSH shell stays open.
set -Eeuo pipefail
trap 'rc=$?; echo "DEPLOY_FAILED at line $LINENO (exit=$rc). SSH is still open."; exit "$rc"' ERR

PROJECT=/opt/personal-assist
BRANCH=feature/pwa-daily-report-v1
cd "$PROJECT"

echo "=== PREFLIGHT: preserve local server configuration ==="
test -f compose.yaml
test -f .env
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "STOP: tracked files have uncommitted changes; no deployment performed."
  git status --short
  exit 2
fi
git status --short
echo "NOTE: untracked compose.override.yaml will be preserved and used by Docker Compose."
docker compose ps personal-assist

echo "=== BACK UP LIVE SQLITE USING SQLITE ONLINE BACKUP ==="
umask 077
BACKUP="/root/personal-assist-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
git rev-parse HEAD > "$BACKUP/predeploy-git-commit"
docker compose exec -T personal-assist python - <<'PY' > "$BACKUP/assistant.sqlite3"
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

path = os.getenv("DB_PATH", "/data/assistant.sqlite3")
source = sqlite3.connect("file:" + path + "?mode=ro", uri=True)
with tempfile.TemporaryDirectory() as directory:
    copy_path = Path(directory) / "assistant-backup.sqlite3"
    target = sqlite3.connect(str(copy_path))
    source.backup(target)
    target.close()
    with copy_path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
source.close()
PY
python3 - "$BACKUP/assistant.sqlite3" <<'PY'
import sqlite3
import sys
con = sqlite3.connect(sys.argv[1])
assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite backup corrupt"
con.close()
PY
echo "DATABASE_BACKUP_OK=$BACKUP/assistant.sqlite3"

echo "=== GET REVIEW BRANCH ==="
git fetch --no-tags origin "$BRANCH"
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git switch "$BRANCH"
  git merge --ff-only FETCH_HEAD
else
  git switch -c "$BRANCH" FETCH_HEAD
fi

echo "=== VERIFY CODE AND COMPOSE ==="
python3 -m py_compile server/app.py
if command -v node >/dev/null 2>&1; then
  node --check server/static/assets/app.js
fi
docker compose config -q

echo "=== BUILD/RECREATE ONLY personal-assist ==="
docker compose up -d --build --no-deps personal-assist

echo "=== VERIFY LOCAL HEALTH AND AUTHENTICATION ==="
curl --retry 10 --retry-delay 2 --retry-connrefused --max-time 5 -fsS http://127.0.0.1:8788/healthz
echo
report_code="$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:8788/api/daily-report)"
test "$report_code" = 401
echo "DAILY_REPORT_ENDPOINT_AUTH=OK (HTTP 401 without login)"

echo "=== VERIFY PUBLIC HOME ==="
curl -fsS --max-time 15 https://asis.filmjadiid.ir/ | grep -Fq 'گزارش امروز'
echo "PUBLIC_NEW_UI=OK"
docker compose ps personal-assist
echo "DEPLOY_SUCCESS"
echo "BACKUP=$BACKUP"
