# Personal Assist — Android-first Persian Voice Inbox

**Version 1 / deployable source** — Dark voice-first UI with four screens based on the selected reference: luminous blue microphone over dusk mountains, recording waveform, transcription review, and task/reminder list. This is a visual recreation, not a pixel-perfect extraction of the source design (the separate original background image wasn't supplied).

## Architecture and honest update model

- **Docker / FastAPI + SQLite**: single-owner private data store, 30-day signed session cookie, persistent tasks, notes, ideas, reminders; optional OpenAI speech transcription + Persian interpretation.
- **HTML + CSS + JavaScript delivered from the server**: users install an Android app only once for UI/backend updates. Reloading the app gets fresh JS/CSS; API/database updates deploy on the server. Cache-Control:no-store and WebView.LOAD_NO_CACHE are configured.
- **Android native WebView shell (Kotlin)**: app starts at your HTTPS domain, directly records with native MediaRecorder for reliable Android support, obtains notification permission, stores and schedules up to 100 reminders via Android AlarmManager, restores scheduled alarms after reboot.
- **Important limitation**: Changing Kotlin/Android permissions, device integrations, app IDs, or security-critical native behavior **requires a newly built, signed APK** (and OS-level install/update). The server cannot silently alter Android native code. Installed apps cannot silently replace themselves outside authorized update mechanisms.
- Scheduled device notifications use `setAndAllowWhileIdle` (inexact); Android Doze, power-saving, notification permission, or manufacturer policies may delay or suppress them. This MVP does **not** guarantee to-the-minute alarms. Server is not responsible for push notifications and cannot fire scheduled alarms remotely while the app is closed.
- **No persistent microphone monitoring**. Recording starts only on tap. Recording audio is sent to your server and on to OpenAI when configured; recording bytes are not saved to disk on the backend. The resulting text/data is stored locally on the server.

## Server prerequisites

Ubuntu 22.04 / 24.04 VPS, Docker Engine, Docker Compose v2, Git, a domain/subdomain pointing to the VPS, and HTTPS reverse proxy (Caddy/Nginx). Do not change or overwrite other Docker Compose projects.

### Deploy with an existing GitHub repository

```bash
sudo mkdir -p /opt/personal-assist
sudo chown "$USER":"$USER" /opt/personal-assist
# Use the URL of the repository you created (if its name differs, substitute it):
git clone https://github.com/aliiitavazoeiii-afk/personal-asis.git /opt/personal-assist
cd /opt/personal-assist
cp .env.example .env
# Create a unique secret:
openssl rand -hex 32
nano .env  # APP_PASSWORD, SESSION_SECRET, OPENAI_API_KEY, DEFAULT_TZ
./scripts/deploy.sh
```

For a source ZIP instead of cloning: upload `Personal-Assist-v1.zip` to the server, create `/opt/personal-assist`, and unzip the archive there; then run `cp .env.example .env`, edit the credentials and run `./scripts/deploy.sh`.

**Caddy example** (`Caddyfile.example`): add the actual DNS name and `reverse_proxy 127.0.0.1:8788`. Enable SSL; do not expose port 8788 publicly. With Nginx, proxy HTTPS requests to `http://127.0.0.1:8788`, forwarding Host/Origin; do not enable cross-origin access. Native media recording loads only HTTPS hosts.

Health: `curl http://127.0.0.1:8788/healthz`. Browse to `https://YOUR_HOST` to log in with `APP_PASSWORD`. Without `OPENAI_API_KEY`, manual entry and deterministic limited Persian date parsing work, but voice transcription is disabled. The API key must **only** be stored in the server `.env`, never inside the APK.

### Redeploy and keep the APK updated

```bash
cd /opt/personal-assist
git pull --ff-only
./scripts/deploy.sh
```

After deploy, open/reopen the installed app and the **server-side UI and behavior will update automatically**, with no APK reinstall. DB persists in Docker volume `personal-assist_assistant-data`. Back up this volume before upgrades. To preserve sessions across restarts, keep `SESSION_SECRET` unchanged.

## Build APK (GitHub Actions — no Android SDK needed on VPS)

1. The source repository is `aliiitavazoeiii-afk/personal-asis` on the `main` branch.
2. Install the APK, then enter your own `https://` server domain in the first-launch Android dialog. You can change it later in the app Settings. No recompile or repository variable is needed for changing server addresses.
3. To keep the **same signing identity** for every future native APK, create a release keystore offline and save it securely:
   ```bash
   keytool -genkeypair -v -keystore personal-assist-release.jks -alias personalassist -keyalg RSA -keysize 3072 -validity 10000
   base64 -w0 personal-assist-release.jks   # copy entire output to GitHub secret ANDROID_KEYSTORE_BASE64
   ```
   Set GitHub Actions Secrets: `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` (`personalassist`) and `ANDROID_KEY_PASSWORD`. Never commit `.jks`. **Back up the signing key** separately; future APK updates require the same certificate.
4. In GitHub **Actions → Build Personal Assist APK → Run workflow** (or push an Android file change). Download artifact `PersonalAssist-APK`, extract, install the `.apk` on Android. Use a signed **release** APK for regular use. Without signing secrets the workflow creates a debug APK for *testing only*; each clean CI runner may use a new debug signature, so in-place Android package upgrades aren't assured.
5. To change native Android code, bump `versionCode` in `android/app/build.gradle.kts`, build another APK, and explicitly install the new APK. This is a separate process from server-driven UI updates.

Android source can also be opened in Android Studio and built with JDK 17, Android SDK 35 and Gradle 8.11.1. The HTTPS server URL is configured at first launch.

## Persian reminders

Saying *فردا ساعت ۱۰ صبح یادم بنداز با تأمین‌کننده تماس بگیرم* → voice transcription → Persian intent parse → **review screen** → tap save → reminder is stored and native alarm scheduled. Any uncertainty, such as *بعداً یادم بنداز* without a specific date/time, is shown as a task with a clarification prompt; it will **not** silently create a random alarm. User can set a date in the review screen and explicitly choose reminder. The server and phone use ISO timestamps with timezone information to avoid off-by-hours errors.

## Privacy, security and first-version constraints

- Single-owner password, signed HTTP-only cookie, same-origin origin check, local bind, HTTPS-only Android shell, no raw audio storage.
- Login rate limiting is in-memory; add an upstream IP rate limiter for internet-facing deployments. No user registration, cloud sync service, calendar connectors, or multi-device alarm syncing.
- Android needs notification permission on Android 13+; battery optimization policies may affect delivery. `POST_NOTIFICATIONS` denial means no notifications even if the data is saved.
- This is a **source project**, not a compiled APK. APK compilation and device installation must be verified via GitHub Actions and on your Android device.

## Developer tests

```bash
python -m pip install -r server/requirements.txt pytest
python -m pytest tests -q
# local test only (COOKIE_SECURE=false), do not expose plaintext HTTP publicly:
APP_PASSWORD=local_password SESSION_SECRET=$(openssl rand -hex 32) COOKIE_SECURE=false DB_PATH=/tmp/personal-assist-dev.sqlite3 uvicorn app:app --app-dir server --port 8000
```

## API overview

`GET /healthz`, `POST /api/login`, `GET /api/me`, `POST /api/logout`, `GET /api/items`, `POST /api/items`, `PATCH /api/items/{id}`, `DELETE /api/items/{id}`, `POST /api/transcribe` multipart audio, `POST /api/parse` JSON. All data APIs require the private session.

### Publish a ZIP installation into a new empty GitHub repository

For an empty repository that you create through GitHub, you can upload the source already on your server:

```bash
cd /opt/personal-assist
git init -b main
git add .
git commit -m 'feat: Personal Assist v1 voice inbox and Android shell'
git remote add origin git@github.com:aliiitavazoeiii-afk/personal-asis.git
git push -u origin main
```

Configure SSH key authentication for the GitHub account first. `.gitignore` excludes the private `.env` and signing key; verify with `git status` before pushing. If you created your repository with a GitHub-generated README, reconcile that history rather than force-pushing.

### Audio limits

The recording UI automatically stops at about **60 seconds** to keep native WebView-to-JavaScript payloads manageable. Longer notes can be entered as text or split into separate recordings. Audio upload size limit is 12 MB.
