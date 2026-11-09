"""Integration and security checks for MCP bridge, using existing dependencies only."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP_PASSWORD"] = "test-password-only"
os.environ["SESSION_SECRET"] = "test-secret-32-or-more-bytes-for-unit-tests"
os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "assistant.sqlite3")
os.environ["MCP_API_TOKEN"] = "long-test-secret-should-never-be-used-in-production"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from fastapi.testclient import TestClient
from app import app, PASSWORD


def rpc(client, method, params=None, token=None, request_id=1):
    return client.post("/mcp/", headers={
        "Authorization": "Bearer " + (token or os.environ["MCP_API_TOKEN"]),
        "Mcp-Protocol-Version": "2025-06-18",
        "Accept": "application/json, text/event-stream",
    }, json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})


def test_mcp_with_live_rest_db():
    with TestClient(app, base_url="https://asis.filmjadiid.ir") as client:
        assert client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
        assert rpc(client, "ping", token="bad").status_code == 401
        assert client.post("/mcp/", headers={"Host": "attacker.example",
                         "Authorization": "Bearer " + os.environ["MCP_API_TOKEN"]},
                         json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 403
        assert client.post("/mcp/", headers={"Origin": "https://bad.example",
                         "Authorization": "Bearer " + os.environ["MCP_API_TOKEN"]},
                         json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 403
        assert rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "tester", "version": "1.0"}}).json()["result"]["serverInfo"]["name"]
        tools = rpc(client, "tools/list").json()["result"]["tools"]
        assert {x["name"] for x in tools} == {"list_items", "get_item", "create_item", "update_item", "complete_item", "delete_item"}
        created = rpc(client, "tools/call", {"name": "create_item",
                "arguments": {"kind": "task", "title": "MCP bridge test"}}).json()["result"]
        assert created["isError"] is False
        item_id = created["structuredContent"]["id"]
        client.post("/api/login", json={"password": PASSWORD})
        assert any(i["id"] == item_id for i in client.get("/api/items").json()["items"])
        denied = rpc(client, "tools/call", {"name": "delete_item",
                "arguments": {"item_id": item_id}}).json()["result"]
        assert denied["isError"] is True
        done = rpc(client, "tools/call", {"name": "complete_item",
                "arguments": {"item_id": item_id}}).json()["result"]
        assert done["isError"] is False
        assert done["structuredContent"]["status"] == "done"
        assert rpc(client, "tools/call", {"name": "create_item",
                "arguments": {"kind": "reminder", "title": "bad deadline"}}).json()["result"]["isError"] is True
        assert client.get("/mcp/", headers={
            "Authorization": "Bearer " + os.environ["MCP_API_TOKEN"]}).status_code == 405
