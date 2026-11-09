#!/usr/bin/env bash
# One-time bootstrap. No remote inbound SSH, API keys in chat, or PyPI required.
set -Eeuo pipefail
umask 077
test "$(id -u)" = 0
cd /opt/personal-assist
test "$(git rev-parse HEAD)" = "deec3a53a20c7a60af094f292392fbc75658129d" || { echo "STOP: running app changed"; exit 2; }
test -z "$(git status --porcelain --untracked-files=no)"
test -f .env && test -f compose.yaml
test "$(git remote get-url origin)" = "https://github.com/aliiitavazoeiii-afk/personal-asis.git"

# Configure a high-entropy MCP credential locally; never print it.
cp -p .env ".env.backup.before-mcp-$(date -u +%Y%m%dT%H%M%SZ)"
python3 - <<'PY'
import secrets
from pathlib import Path
p = Path("/opt/personal-assist/.env")
lines = p.read_text().splitlines()
old = [x.split("=", 1)[1].strip() for x in lines if x.startswith("MCP_API_TOKEN=")]
token = old[-1] if old and len(old[-1]) >= 32 else secrets.token_urlsafe(48)
lines = [x for x in lines if not x.startswith(("MCP_API_TOKEN=", "MCP_ALLOWED_HOSTS="))]
lines.extend(["MCP_API_TOKEN=" + token, "MCP_ALLOWED_HOSTS=asis.filmjadiid.ir"])
p.write_text("\n".join(lines) + "\n")
p.chmod(0o600)
PY

install -d -m 700 /var/lib/personal-assist-deploy
git rev-parse HEAD > /var/lib/personal-assist-deploy/applied.sha
# Fetch the pinned source branch via working GitHub Git transport, not raw.githubusercontent.com.
timeout 80 git fetch --no-tags origin refs/heads/assistant-production:refs/remotes/origin/assistant-production
git show refs/remotes/origin/assistant-production:ops/deploy_agent.sh > /usr/local/sbin/personal-assist-deploy
chmod 700 /usr/local/sbin/personal-assist-deploy

cat > /etc/systemd/system/personal-assist-deploy.service <<'UNIT'
[Unit]
Description=Offline-validated Personal Assistant GitHub deployment
Wants=network-online.target
After=network-online.target docker.service

[Service]
Type=oneshot
User=root
ExecStart=/usr/local/sbin/personal-assist-deploy
TimeoutStartSec=1200
UNIT

cat > /etc/systemd/system/personal-assist-deploy.timer <<'UNIT'
[Unit]
Description=Check approved Assistant production updates every five minutes

[Timer]
OnBootSec=2min
OnUnitInactiveSec=5min
RandomizedDelaySec=30s
Persistent=true
Unit=personal-assist-deploy.service

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now personal-assist-deploy.timer
systemctl start personal-assist-deploy.service
systemctl --no-pager -l status personal-assist-deploy.service || true
echo "=== ONE_TIME_BOOTSTRAP_COMPLETE ==="
curl -sS -o /dev/null -w 'LOCAL_HTTP=%{http_code}\n' --max-time 6 http://127.0.0.1:8788/healthz
echo "MCP token is in /opt/personal-assist/.env (do not paste it into chat)."
