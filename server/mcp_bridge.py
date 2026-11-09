"""Private MCP interface to the existing Personal Assist SQLite task store.

This module deliberately has no arbitrary shell, file-system or SQL execution tool.
All writes use parameterized statements and the same items table as /api/items.
"""
from __future__ import annotations

import datetime as dt
import os
import secrets
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.responses import PlainTextResponse

KINDS = {"task", "reminder", "note", "idea"}
STATUSES = {"open", "done"}
DB_PATH = Path(os.getenv("DB_PATH", "/data/assistant.sqlite3"))

mcp = FastMCP(
    "Ali Personal Assistant",
    instructions=(
        "Manage only this owner's personal tasks, reminders, notes and ideas. "
        "Never claim that a timed reminder sends a phone notification: the PWA "
        "currently does not support closed-app push. Use timezone-aware ISO 8601 "
        "dates. Ask when the deadline is ambiguous. Confirm irreversible deletion."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    host="0.0.0.0",  # The bearer/host gate below enforces access.
)
transport = mcp.streamable_http_app()


def _db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=10000")
    return con


def _time(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone is required")
        return parsed.astimezone(dt.timezone.utc).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("due_at requires ISO 8601 with a timezone offset") from exc


def _get(con, item_id: str) -> dict:
    row = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise ValueError("Item not found")
    return dict(row)


@mcp.tool()
def list_items(kind: str = "all", status: str = "all", limit: int = 100) -> dict:
    """List saved tasks, reminders, notes and ideas with optional kind/status filters."""
    if kind not in KINDS | {"all"} or status not in STATUSES | {"all"}:
        raise ValueError("Invalid filter")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be 1..500")
    clauses, params = [], []
    if kind != "all":
        clauses.append("kind=?")
        params.append(kind)
    if status != "all":
        clauses.append("status=?")
        params.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with _db() as con:
        rows = con.execute(
            "SELECT * FROM items" + where +
            " ORDER BY CASE WHEN due_at IS NULL THEN 1 ELSE 0 END, due_at, created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@mcp.tool()
def get_item(item_id: str) -> dict:
    """Read one item by its exact identifier."""
    with _db() as con:
        return _get(con, item_id)


@mcp.tool()
def create_item(kind: str, title: str, detail: str = "", due_at: str | None = None) -> dict:
    """Save a task, reminder, note or idea. A reminder needs an explicit timezone-aware deadline."""
    if kind not in KINDS:
        raise ValueError("kind must be task, reminder, note or idea")
    if not title.strip() or len(title) > 500 or len(detail) > 8000:
        raise ValueError("Invalid title or detail length")
    due = _time(due_at)
    if kind == "reminder" and not due:
        raise ValueError("A reminder requires an exact due_at")
    item_id = secrets.token_hex(12)
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    with _db() as con:
        con.execute(
            "INSERT INTO items(id,kind,title,detail,due_at,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (item_id, kind, title.strip(), detail, due, "open", stamp, stamp),
        )
        return _get(con, item_id)


@mcp.tool()
def update_item(
    item_id: str,
    title: str | None = None,
    detail: str | None = None,
    kind: str | None = None,
    due_at: str | None = None,
    clear_due_at: bool = False,
    status: str | None = None,
) -> dict:
    """Edit an item; omit unchanged fields. Set clear_due_at=true to remove a deadline."""
    if kind is not None and kind not in KINDS:
        raise ValueError("Invalid kind")
    if status is not None and status not in STATUSES:
        raise ValueError("Invalid status")
    if title is not None and (not title.strip() or len(title) > 500):
        raise ValueError("Invalid title")
    if detail is not None and len(detail) > 8000:
        raise ValueError("Detail too long")
    if clear_due_at and due_at is not None:
        raise ValueError("Cannot set and clear due_at together")
    values = {}
    if title is not None:
        values["title"] = title.strip()
    if detail is not None:
        values["detail"] = detail
    if kind is not None:
        values["kind"] = kind
    if due_at is not None or clear_due_at:
        values["due_at"] = None if clear_due_at else _time(due_at)
    if status is not None:
        values["status"] = status
    if not values:
        raise ValueError("No updates supplied")
    with _db() as con:
        old = _get(con, item_id)
        merged = {**old, **values}
        if merged["kind"] == "reminder" and not merged["due_at"]:
            raise ValueError("A reminder must retain a deadline")
        values["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        columns = ", ".join(f"{field}=?" for field in values)
        con.execute(f"UPDATE items SET {columns} WHERE id=?", (*values.values(), item_id))
        return _get(con, item_id)


@mcp.tool()
def complete_item(item_id: str, done: bool = True) -> dict:
    """Mark a task done or reopen it."""
    return update_item(item_id, status="done" if done else "open")


@mcp.tool()
def delete_item(item_id: str, confirm: bool = False) -> dict:
    """Permanently delete an item only on explicit user instruction; confirm must be true."""
    if not confirm:
        raise ValueError("Deletion requires confirm=true after explicit user approval")
    with _db() as con:
        _get(con, item_id)
        con.execute("DELETE FROM items WHERE id=?", (item_id,))
    return {"deleted": True, "id": item_id}


class ProtectedMCP:
    """ASGI bearer + host gate. Do not allow browser-cookie access to MCP."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        token = os.getenv("MCP_API_TOKEN", "")
        if len(token) < 32:
            await PlainTextResponse("MCP is not configured", status_code=503)(scope, receive, send)
            return
        host = headers.get("host", "").split(":")[0].lower()
        allowed = {x.strip().lower() for x in
                   os.getenv("MCP_ALLOWED_HOSTS", "asis.filmjadiid.ir").split(",") if x.strip()}
        if host not in allowed:
            await PlainTextResponse("Host not allowed", status_code=403)(scope, receive, send)
            return
        origin = headers.get("origin")
        if origin and origin != "https://" + host:
            await PlainTextResponse("Origin not allowed", status_code=403)(scope, receive, send)
            return
        auth = headers.get("authorization", "")
        candidate = auth[7:] if auth.startswith("Bearer ") else ""
        if not secrets.compare_digest(candidate.encode(), token.encode()):
            await PlainTextResponse(
                "Unauthorized", status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        await self.inner(scope, receive, send)
