"""
AUD-IT MCP Server
------------------
Exposes the AUD-IT Tasks Flask app (app.py) as a set of MCP tools so
Claude can read and manage shows, tasks, journal entries, team members,
and hours logs over the existing REST API.

This is a thin proxy: every tool call makes an HTTPS request to the
already-deployed AUD-IT app, authenticated with the same X-API-Key
header the app already supports (see require_api_key_or_session in
app.py). No changes to app.py or the database are required.

Environment variables (set these on the Render service running this
server):
  AUDIT_APP_URL   Base URL of the deployed AUD-IT app,
                  e.g. https://audit-suite.onrender.com
  AUDIT_API_KEY   Must match the API_KEY env var set on the AUD-IT app.
  PORT            Provided automatically by Render.

Run locally:
  pip install -r requirements.txt
  AUDIT_APP_URL=https://audit-suite.onrender.com AUDIT_API_KEY=xxx \
    python server.py
"""
import os
import uuid
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

AUDIT_APP_URL = os.environ.get("AUDIT_APP_URL", "").rstrip("/")
AUDIT_API_KEY = os.environ.get("AUDIT_API_KEY", "")

if not AUDIT_APP_URL:
    raise RuntimeError("AUDIT_APP_URL environment variable is required")
if not AUDIT_API_KEY:
    raise RuntimeError("AUDIT_API_KEY environment variable is required")

mcp = FastMCP(
    "audit-tasks",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def new_id() -> str:
    """Match the short-id format the AUD-IT frontend generates client-side."""
    return uuid.uuid4().hex[:12]


async def request(method: str, path: str, **kwargs):
    url = f"{AUDIT_APP_URL}{path}"
    headers = {"X-API-Key": AUDIT_API_KEY}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.request(method, url, headers=headers, **kwargs)
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        return {"error": True, "status": resp.status_code, "detail": detail}
    if resp.content:
        return resp.json()
    return {"status": "ok"}


def clean(d: dict) -> dict:
    """Drop keys whose value is None so PATCH-style updates only send what changed."""
    return {k: v for k, v in d.items() if v is not None}


# ══════════════════════════════════
# SHOWS
# ══════════════════════════════════

@mcp.tool()
async def list_shows():
    """List all shows/productions tracked in AUD-IT (id, name, space, dates, archived)."""
    return await request("GET", "/api/shows")


@mcp.tool()
async def create_show(
    name: str,
    space: str = "general",
    load_in: str = "",
    open_date: str = "",
    close_date: str = "",
    archived: bool = False,
):
    """Create a new show/production.

    space: which venue/space it belongs to (e.g. 'stephenson', 'hormel', 'hardes', 'general').
    load_in / open_date / close_date: dates as YYYY-MM-DD strings.
    """
    payload = {
        "id": new_id(),
        "name": name,
        "space": space,
        "load_in": load_in,
        "open_date": open_date,
        "close_date": close_date,
        "archived": archived,
    }
    return await request("POST", "/api/shows", json=payload)


@mcp.tool()
async def update_show(
    show_id: str,
    name: Optional[str] = None,
    space: Optional[str] = None,
    archived: Optional[bool] = None,
    load_in: Optional[str] = None,
    open_date: Optional[str] = None,
    close_date: Optional[str] = None,
):
    """Update fields on an existing show. Only pass the fields you want to change."""
    payload = clean(locals())
    payload.pop("show_id", None)
    return await request("PUT", f"/api/shows/{show_id}", json=payload)


@mcp.tool()
async def delete_show(show_id: str):
    """Delete a show by id."""
    return await request("DELETE", f"/api/shows/{show_id}")


# ══════════════════════════════════
# CATEGORIES (spaces/departments used to tag tasks)
# ══════════════════════════════════

@mcp.tool()
async def list_categories():
    """List task categories/spaces (e.g. Stephenson, Hormel, Hardes, General)."""
    return await request("GET", "/api/categories")


@mcp.tool()
async def create_category(name: str, category_id: Optional[str] = None):
    """Create a new task category/space."""
    payload = {"id": category_id or new_id(), "name": name}
    return await request("POST", "/api/categories", json=payload)


@mcp.tool()
async def delete_category(category_id: str):
    """Delete a task category by id."""
    return await request("DELETE", f"/api/categories/{category_id}")


# ══════════════════════════════════
# TASKS
# ══════════════════════════════════

@mcp.tool()
async def list_tasks():
    """List all tasks (open and done) across every show/space."""
    return await request("GET", "/api/tasks")


@mcp.tool()
async def create_task(
    text: str,
    space: str = "general",
    show: str = "",
    pri: str = "none",
    urg: str = "soon",
    date: str = "",
    notes: str = "",
):
    """Create a new task.

    pri: 'high' | 'med' | 'low' | 'none'
    urg: 'now' | 'today' | 'week' | 'soon' | 'date'
    show: id of a show from list_shows (optional, leave blank for general tasks).
    date: due date as YYYY-MM-DD, only meaningful when urg='date'.
    """
    payload = {
        "id": new_id(),
        "text": text,
        "space": space,
        "show": show,
        "pri": pri,
        "urg": urg,
        "date": date,
        "notes": notes,
    }
    return await request("POST", "/api/tasks", json=payload)


@mcp.tool()
async def update_task(
    task_id: str,
    text: Optional[str] = None,
    space: Optional[str] = None,
    show: Optional[str] = None,
    pri: Optional[str] = None,
    urg: Optional[str] = None,
    date: Optional[str] = None,
    notes: Optional[str] = None,
    done: Optional[bool] = None,
    sort_order: Optional[int] = None,
):
    """Update fields on an existing task, including marking it done/not done."""
    payload = clean(locals())
    payload.pop("task_id", None)
    return await request("PUT", f"/api/tasks/{task_id}", json=payload)


@mcp.tool()
async def delete_task(task_id: str):
    """Delete a task by id."""
    return await request("DELETE", f"/api/tasks/{task_id}")


@mcp.tool()
async def reorder_tasks(task_ids_in_order: list[str]):
    """Set the display sort order of tasks by passing their ids in the desired order."""
    return await request("POST", "/api/tasks/reorder", json={"ids": task_ids_in_order})


# ══════════════════════════════════
# JOURNAL
# ══════════════════════════════════

@mcp.tool()
async def list_journal():
    """List all journal/crew log entries."""
    return await request("GET", "/api/journal")


@mcp.tool()
async def create_journal_entry(
    body: str,
    date: str,
    author: str = "Matthew",
    total_hours: float = 0,
):
    """Add a journal entry for a given date.

    date: YYYY-MM-DD.
    """
    payload = {
        "id": new_id(),
        "date": date,
        "body": body,
        "author": author,
        "hours": {},
        "totalHours": total_hours,
    }
    return await request("POST", "/api/journal", json=payload)


@mcp.tool()
async def update_journal_entry(
    entry_id: str,
    body: Optional[str] = None,
    date: Optional[str] = None,
    author: Optional[str] = None,
    total_hours: Optional[float] = None,
):
    """Update fields on an existing journal entry."""
    payload = clean(locals())
    payload.pop("entry_id", None)
    if "total_hours" in payload:
        payload["totalHours"] = payload.pop("total_hours")
    return await request("PUT", f"/api/journal/{entry_id}", json=payload)


@mcp.tool()
async def delete_journal_entry(entry_id: str):
    """Delete a journal entry by id."""
    return await request("DELETE", f"/api/journal/{entry_id}")


# ══════════════════════════════════
# TEAM
# ══════════════════════════════════

@mcp.tool()
async def list_team():
    """List team/crew members."""
    return await request("GET", "/api/team")


@mcp.tool()
async def create_team_member(name: str, color: str = "#888078"):
    """Add a new team/crew member."""
    return await request("POST", "/api/team", json={"name": name, "color": color})


@mcp.tool()
async def update_team_member(
    member_id: int,
    name: Optional[str] = None,
    color: Optional[str] = None,
    archived: Optional[bool] = None,
):
    """Update a team member's name, color, or archived status."""
    payload = clean(locals())
    payload.pop("member_id", None)
    return await request("PUT", f"/api/team/{member_id}", json=payload)


@mcp.tool()
async def archive_team_member(member_id: int):
    """Archive a team member (soft-remove without deleting their history)."""
    return await request("POST", f"/api/team/{member_id}/archive")


@mcp.tool()
async def unarchive_team_member(member_id: int):
    """Restore a previously archived team member."""
    return await request("POST", f"/api/team/{member_id}/unarchive")


@mcp.tool()
async def delete_team_member(member_id: int):
    """Permanently delete a team member."""
    return await request("DELETE", f"/api/team/{member_id}")


# ══════════════════════════════════
# HOURS
# ══════════════════════════════════

@mcp.tool()
async def get_hours(
    author: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Get logged hours, optionally filtered by author and/or a date range (YYYY-MM-DD)."""
    params = clean({"author": author, "from": date_from, "to": date_to})
    return await request("GET", "/api/hours", params=params)


@mcp.tool()
async def set_hours(author: str, date: str, space: str, hours: float):
    """Log hours worked by a team member on a given date/space."""
    payload = {"author": author, "date": date, "space": space, "hours": hours}
    return await request("POST", "/api/hours", json=payload)


# ══════════════════════════════════
# MISC
# ══════════════════════════════════

@mcp.tool()
async def get_last_modified():
    """Get the timestamp of the most recent change across all tables (for change detection)."""
    return await request("GET", "/api/last-modified")


@mcp.tool()
async def backup_all():
    """Export a full snapshot of shows, categories, tasks, journal, and team data (read-only)."""
    return await request("GET", "/api/backup")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port
    mcp.run(transport="streamable-http")