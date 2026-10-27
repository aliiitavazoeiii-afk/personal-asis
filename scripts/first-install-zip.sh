#!/usr/bin/env bash
# Run on Ubuntu VPS from the directory containing Personal-Assist-v1.zip.
set -euo pipefail
archive=${1:-Personal-Assist-v1.zip}
command -v unzip >/dev/null || { echo 'Install unzip first: sudo apt-get install unzip'; exit 1; }
sudo mkdir -p /opt/personal-assist
sudo chown "$(id -u):$(id -g)" /opt/personal-assist
unzip -o "$archive" -d /opt/personal-assist
cd /opt/personal-assist
if [ ! -f .env ]; then cp .env.example .env; fi
cat <<'MSG'
Source installed at /opt/personal-assist.
Next:
  1. Run: openssl rand -hex 32
  2. Run: nano /opt/personal-assist/.env
  3. Enter your APP_PASSWORD, SESSION_SECRET and optional OPENAI_API_KEY.
  4. Run: cd /opt/personal-assist && ./scripts/deploy.sh
  5. Configure HTTPS reverse proxy for your chosen domain.
No secrets were generated or published automatically.
MSG
