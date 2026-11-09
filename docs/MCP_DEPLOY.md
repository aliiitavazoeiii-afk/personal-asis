# Ali Assistant MCP — production handoff

The existing FastAPI application exposes an **opt-in** Streamable HTTP MCP endpoint
at `https://asis.filmjadiid.ir/mcp/`. It reuses the existing `/data/assistant.sqlite3`
and the `items` table, so tasks written by MCP appear via `/api/items`.
No OpenAI API key is needed for MCP parsing: ChatGPT interprets the request.

## Safety model

- `MCP_API_TOKEN` is required, at least 32 characters. Without it, all MCP
  HTTP requests return 503. The existing UI and REST API continue working.
- Browser session cookies do **not** authorize MCP.
- Exact Host allowlist: `MCP_ALLOWED_HOSTS=asis.filmjadiid.ir`.
- Browser `Origin` is restricted. The production endpoint requires HTTPS.
- Tool scope: `list_items`, `get_item`, `create_item`, `update_item`,
  `complete_item`, and `delete_item`. No arbitrary code, shell, filesystem,
  network calls, or SQL endpoints are provided.
- `delete_item` rejects requests without `confirm=true`; require explicit
  end-user authorization before asking for irreversible deletion.
- MCP tools do **not** deliver phone push notifications: the existing PWA
  still requires Web Push + a scheduler for reminders when the app is closed.

## Deploy without typing commands on the VPS

1. Review and merge the feature PR to `main` after passing the tests.
2. In GitHub → repo Settings → Secrets and variables → Actions, configure:
   - `ASSISTANT_SSH_HOST` — server address (private secret if needed).
   - `ASSISTANT_SSH_USER` — restricted user with Docker group and read/write
     access to `/opt/personal-assist`.
   - `ASSISTANT_SSH_KEY` — private SSH key authorized on the VPS (not the root
     password; do not paste it into ChatGPT).
   - `ASSISTANT_SSH_KNOWN_HOSTS` — verified SSH known_hosts entry (pin the
     host key obtained through an independent trusted channel; do not blindly
     trust `ssh-keyscan` output).
   - `ASSISTANT_MCP_TOKEN` — separately generated random 32+ character token
     (e.g. 48+ random URL-safe characters). Keep it securely for the
     ChatGPT plugin connection flow.
3. In GitHub Actions, start **Deploy Personal Assistant MCP (manual)** on `main`.
   The workflow SSHes with a pinned host key, backs up `.env`, merges only a
   fast-forward update, rebuilds only `personal-assist`, preserves its Docker
   volume, verifies `/healthz`, and sends an authenticated MCP initialization
   over HTTPS. It does not alter Caddy, other containers, or the database schema.
4. Inspect the deployment run for `MCP_PUBLIC_HANDSHAKE_OK`. If it fails,
   do not create/connect the ChatGPT plugin yet. Check the error and repair it
   without exposing secrets. The remote app may still be running; verify it.

**One-time prerequisite**: an SSH key must already be trusted by the VPS and
its user allowed to run Docker. If this trust does not exist, a human must
authorize a setup path through the VPS/provider console. An API cannot create
its own initial server permissions without an existing trust channel.

## ChatGPT plugin (after deployment verification)

Create a **private plugin** from a valid Agent Plugins package. Its
`mcp.json` will declare the **verified** HTTPS streamable-http endpoint
`https://asis.filmjadiid.ir/mcp/` and an API-key bearer authentication method.
Do not place the bearer token inside `mcp.json` or GitHub. Enter it only
through the connection's secret/credential UI.

Connect the private plugin in this ChatGPT conversation and perform:
1. `list_items` (verify authorization and actual data).
2. `create_item` with an explicitly designated test task.
3. Check that the same task appears in the current Assistant PWA.
4. `complete_item`, then check both ChatGPT and the PWA.
5. Test a missing/incorrect bearer token returns 401.

This code change alone does not mean a plugin is created, deployed, or connected.
Avoid claiming an active connection until the protocol handshake and live item
write/read test succeed.

## Notes

- This integration is purposely separate from the existing UI. Replacing the
  voice-first UI with a plan-only dashboard should happen in a separate reviewed
  step after the MCP write/read connection is proven.
- Daily/task notifications while the PWA is closed need separate implementation.
- Preserve the existing Docker volume `personal-assist_assistant-data`.
