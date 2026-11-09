"""Bearer-protected stateless MCP HTTP endpoint, using existing FastAPI dependencies.

No MCP SDK package is needed on VPS. The same SQLite rows back the PWA REST API.
"""
import datetime as dt
import json
import os
import secrets
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter()
KINDS = ("task", "reminder", "note", "idea")
STATUSES = ("open", "done")
VERSION = "2025-06-18"
DB_PATH = Path(os.getenv("DB_PATH", "/data/assistant.sqlite3"))

SCHEMAS = {
    "list_items": ({"kind": {"type": "string", "enum": ["all", *KINDS], "default": "all"},
                    "status": {"type": "string", "enum": ["all", *STATUSES], "default": "all"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}}, []),
    "get_item": ({"item_id": {"type": "string"}}, ["item_id"]),
    "create_item": ({"kind": {"type": "string", "enum": list(KINDS)},
                     "title": {"type": "string", "minLength": 1, "maxLength": 500},
                     "detail": {"type": "string", "maxLength": 8000, "default": ""},
                     "due_at": {"type": ["string", "null"], "description": "ISO 8601 with timezone offset"}}, ["kind", "title"]),
    "update_item": ({"item_id": {"type": "string"}, "title": {"type": "string"},
                     "detail": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)},
                     "due_at": {"type": "string"}, "clear_due_at": {"type": "boolean"},
                     "status": {"type": "string", "enum": list(STATUSES)}}, ["item_id"]),
    "complete_item": ({"item_id": {"type": "string"}, "done": {"type": "boolean", "default": True}}, ["item_id"]),
    "delete_item": ({"item_id": {"type": "string"}, "confirm": {"type": "boolean", "const": True}}, ["item_id", "confirm"]),
}
DESCRIPTIONS = {
    "list_items": "List saved tasks, reminders, notes and ideas; optionally filter by kind and status.",
    "get_item": "Read one item using its exact ID.",
    "create_item": "Save a task, reminder, note or idea. Reminders require a timezone-aware due_at.",
    "update_item": "Edit one saved item. Set clear_due_at to remove a non-reminder deadline.",
    "complete_item": "Mark a task complete, or reopen it with done=false.",
    "delete_item": "Delete an item permanently, ONLY after explicit user consent and confirm=true.",
}


def _db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _get(con, item_id):
    row = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise ValueError("Item not found")
    return dict(row)


def _due(value):
    if not value:
        return None
    try:
        date = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError()
        return date.astimezone(dt.timezone.utc).isoformat()
    except (TypeError, ValueError, AttributeError):
        raise ValueError("due_at must be ISO 8601 with timezone offset")


def _call(name, a):
    if name == "list_items":
        kind, status, limit = a.get("kind", "all"), a.get("status", "all"), a.get("limit", 100)
        if kind not in (*KINDS, "all") or status not in (*STATUSES, "all") or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("Invalid list filters")
        parts, values = [], []
        if kind != "all":
            parts.append("kind=?")
            values.append(kind)
        if status != "all":
            parts.append("status=?")
            values.append(status)
        where = " WHERE " + " AND ".join(parts) if parts else ""
        with _db() as con:
            rows = con.execute("SELECT * FROM items" + where +
                               " ORDER BY CASE WHEN due_at IS NULL THEN 1 ELSE 0 END, due_at, created_at DESC LIMIT ?",
                               (*values, limit)).fetchall()
        return {"items": [dict(r) for r in rows]}
    if name == "create_item":
        kind, title, detail = a.get("kind"), a.get("title"), a.get("detail", "")
        if kind not in KINDS or not isinstance(title, str) or not 1 <= len(title.strip()) <= 500 or not isinstance(detail, str) or len(detail) > 8000:
            raise ValueError("Invalid item kind/title/detail")
        due = _due(a.get("due_at"))
        if kind == "reminder" and not due:
            raise ValueError("A reminder requires an exact due_at")
        item_id = secrets.token_hex(12)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with _db() as con:
            con.execute("INSERT INTO items(id,kind,title,detail,due_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (item_id, kind, title.strip(), detail, due, "open", now, now))
            return _get(con, item_id)
    item_id = a.get("item_id")
    if not isinstance(item_id, str) or not item_id or len(item_id) > 128:
        raise ValueError("item_id is required")
    with _db() as con:
        old = _get(con, item_id)
        if name == "get_item":
            return old
        if name == "delete_item":
            if a.get("confirm") is not True:
                raise ValueError("Explicit confirmation required for deletion")
            con.execute("DELETE FROM items WHERE id=?", (item_id,))
            return {"deleted": True, "id": item_id}
        if name == "complete_item":
            if type(a.get("done", True)) is not bool:
                raise ValueError("done must be boolean")
            values = {"status": "done" if a.get("done", True) else "open"}
        elif name == "update_item":
            values = {}
            for k in ("kind", "title", "detail", "status"):
                if k in a:
                    values[k] = a[k]
            if "due_at" in a and a.get("clear_due_at"):
                raise ValueError("Cannot set and clear due_at together")
            if "due_at" in a or a.get("clear_due_at"):
                values["due_at"] = None if a.get("clear_due_at") else _due(a["due_at"])
        else:
            raise ValueError("Unknown tool")
        merged = {**old, **values}
        if merged["kind"] not in KINDS or merged["status"] not in STATUSES:
            raise ValueError("Invalid kind/status")
        if not isinstance(merged["title"], str) or not 1 <= len(merged["title"].strip()) <= 500:
            raise ValueError("Invalid title")
        if not isinstance(merged["detail"], str) or len(merged["detail"]) > 8000:
            raise ValueError("Invalid detail")
        if merged["kind"] == "reminder" and not merged["due_at"]:
            raise ValueError("Reminder requires due_at")
        if not values:
            raise ValueError("No changes given")
        values["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        assignments = ", ".join(k + "=?" for k in values)
        con.execute("UPDATE items SET " + assignments + " WHERE id=?", (*values.values(), item_id))
        return _get(con, item_id)


def _guard(request):
    token = os.getenv("MCP_API_TOKEN", "")
    if len(token) < 32:
        return Response("MCP not configured", status_code=503)
    host = request.headers.get("host", "").split(":")[0].lower()
    hosts = {h.strip().lower() for h in os.getenv("MCP_ALLOWED_HOSTS", "asis.filmjadiid.ir").split(",")}
    if host not in hosts:
        return Response("Host not allowed", status_code=403)
    origin = request.headers.get("origin")
    if origin and origin != "https://" + host:
        return Response("Origin not allowed", status_code=403)
    auth = request.headers.get("authorization", "")
    candidate = auth[7:] if auth.startswith("Bearer ") else ""
    if not secrets.compare_digest(candidate.encode(), token.encode()):
        return Response("Unauthorized", status_code=401,
                        headers={"WWW-Authenticate": "Bearer"})
    return None


def _result(request_id, data):
    return {"jsonrpc": "2.0", "id": request_id, "result": data}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


@router.post("/mcp/")
async def mcp_post(request: Request):
    denied = _guard(request)
    if denied is not None:
        return denied
    raw = await request.body()
    if len(raw) > 65536:
        return Response("Request too large", status_code=413)
    try:
        msg = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return JSONResponse(_error(None, -32600, "Invalid request"), status_code=400)
    if "id" not in msg:
        return Response(status_code=202)
    request_id, method, params = msg["id"], msg.get("method"), msg.get("params", {})
    if not isinstance(params, dict):
        return JSONResponse(_error(request_id, -32602, "Invalid params"))
    if method == "initialize":
        result = {"protocolVersion": VERSION, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "Ali Personal Assistant", "version": "1.0.0"},
                  "instructions": "Manage the owner's tasks, notes, ideas and reminders. Never claim the PWA sends closed-app push notifications. Confirm deletion."}
        return JSONResponse(_result(request_id, result))
    if method == "ping":
        return JSONResponse(_result(request_id, {}))
    if method == "tools/list":
        tools = [{"name": name, "description": DESCRIPTIONS[name],
                  "inputSchema": {"type": "object", "properties": props,
                                  "required": required, "additionalProperties": False}}
                 for name, (props, required) in SCHEMAS.items()]
        return JSONResponse(_result(request_id, {"tools": tools}))
    if method == "tools/call":
        name, arguments = params.get("name"), params.get("arguments", {})
        if name not in SCHEMAS:
            return JSONResponse(_error(request_id, -32602, "Unknown tool"))
        if not isinstance(arguments, dict) or set(arguments) - set(SCHEMAS[name][0]):
            return JSONResponse(_error(request_id, -32602, "Invalid tool arguments"))
        try:
            payload = _call(name, arguments)
            result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                      "structuredContent": payload, "isError": False}
        except (TypeError, ValueError, sqlite3.Error) as exc:
            result = {"content": [{"type": "text", "text": str(exc) if isinstance(exc, ValueError) else "Database error"}],
                      "isError": True}
        return JSONResponse(_result(request_id, result))
    return JSONResponse(_error(request_id, -32601, "Method not found"))


@router.get("/mcp/")
async def mcp_get(request: Request):
    denied = _guard(request)
    return denied if denied is not None else Response(status_code=405)
