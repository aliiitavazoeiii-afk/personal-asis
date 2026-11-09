"""Protocol-level smoke test for the private MCP bridge.

Existing REST tests remain unchanged; the MCP client writes to the same SQLite DB.
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("APP_PASSWORD", "test-password-very-private")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-local-testing-not-for-production")
os.environ.setdefault("DB_PATH", str(Path(tempfile.mkdtemp()) / "assistant.db"))
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("OPENAI_API_KEY", "")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from fastapi.testclient import TestClient
from app import app


def _rpc(client, method, params=None, request_id=1, token="very-long-test-token-not-for-production-123"):
    return client.post(
        "/mcp/",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Mcp-Protocol-Version": "2025-06-18",
        },
        json={
            "jsonrpc": "2.0", "id": request_id,
            "method": method, "params": params or {},
        },
    )


def test_mcp_requires_separate_bearer_token(monkeypatch):
    monkeypatch.setenv("MCP_API_TOKEN", "very-long-test-token-not-for-production-123")
    with TestClient(app, base_url="https://asis.filmjadiid.ir") as client:
        client.post("/api/login", json={"password": "test-password-very-private"})
        # Cookie auth does not allow access to the agent endpoint.
        r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 401
        r = _rpc(client, "ping", token="this-token-is-not-the-actual-access-token")
        assert r.status_code == 401
    with TestClient(app, base_url="https://evil.example") as client:
        r = _rpc(client, "ping")
        assert r.status_code == 403


def test_mcp_end_to_end_create_update_list(monkeypatch):
    monkeypatch.setenv("MCP_API_TOKEN", "very-long-test-token-not-for-production-123")
    with TestClient(app, base_url="https://asis.filmjadiid.ir") as client:
        hello = _rpc(client, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "assistant-bridge-test", "version": "1.0"},
        })
        assert hello.status_code == 200, hello.text
        assert "result" in hello.json(), hello.text

        catalog = _rpc(client, "tools/list", request_id=2)
        assert catalog.status_code == 200, catalog.text
        names = {t["name"] for t in catalog.json()["result"]["tools"]}
        assert {"list_items", "get_item", "create_item", "update_item",
                "complete_item", "delete_item"} <= names
        assert "execute_shell" not in names

        created = _rpc(client, "tools/call", {
            "name": "create_item",
            "arguments": {
                "kind": "task", "title": "پیگیری جواز کسب",
                "detail": "تست اتصال چت و اپلیکیشن",
            },
        }, request_id=3)
        assert created.status_code == 200, created.text
        assert created.json()["result"].get("isError") is not True, created.text

        client.post("/api/login", json={"password": "test-password-very-private"})
        items = client.get("/api/items").json()["items"]
        matched = [it for it in items if it["title"] == "پیگیری جواز کسب"]
        assert len(matched) == 1
        item_id = matched[0]["id"]

        done = _rpc(client, "tools/call", {
            "name": "complete_item", "arguments": {"item_id": item_id},
        }, request_id=4)
        assert done.status_code == 200, done.text
        assert done.json()["result"].get("isError") is not True, done.text
        assert next(it for it in client.get("/api/items").json()["items"]
                    if it["id"] == item_id)["status"] == "done"

        # An unconfirmed destructive operation must be refused.
        denied = _rpc(client, "tools/call", {
            "name": "delete_item", "arguments": {"item_id": item_id},
        }, request_id=5)
        assert denied.json()["result"].get("isError") is True
        assert any(it["id"] == item_id for it in client.get("/api/items").json()["items"])
