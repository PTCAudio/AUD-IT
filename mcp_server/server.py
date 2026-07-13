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
# INVENTORY
# Field names below (cat/subcat/audit_notes/show_qty/space_qty/etc.) map to
# the Inventory tool's own field names on the wire (desc/cat/subcat/
# auditNotes/showQty/spaceQty/...). show_qty/show_notes/space_qty/
# space_notes are separate {id: value} dicts, matching how the tool itself
# stores them — show/space ids come from list_inventory_items output on
# existing items (they're the Inventory tool's OWN local show ids like
# 's1'/'s2', not the Task Manager shows' ids — the two are different ID
# spaces on purpose, see models.import_inventory_from_tool_export).
# ══════════════════════════════════

@mcp.tool()
async def list_inventory_items():
    """List all active (non-deleted) inventory items — audio/video gear, quantities, locations, and show/space allocations."""
    return await request("GET", "/api/inventory/items")


@mcp.tool()
async def create_inventory_item(
    make: str,
    model: str,
    qty: int,
    line: int = 0,
    desc: str = "",
    cat: str = "",
    subcat: str = "",
    cost: float = 0,
    serial: str = "",
    ip: str = "",
    loc: str = "",
    audit_notes: str = "",
    units: Optional[dict] = None,
    details: Optional[dict] = None,
    show_qty: Optional[dict] = None,
    show_notes: Optional[dict] = None,
    space_qty: Optional[dict] = None,
    space_notes: Optional[dict] = None,
):
    """Create a new inventory item. make, model, and qty are required.

    units: status breakdown, e.g. {"available": 5, "broken": 1} — keys are
    'available'/'inuse'/'broken'/'repair'/'retired'/'unknown'.
    show_qty / space_qty: allocation counts keyed by show/space id (see
    list_inventory_items for existing id examples); show_notes/space_notes
    are matching per-id note text.
    """
    payload = {
        "line": line, "qty": qty, "make": make, "model": model, "desc": desc,
        "cat": cat, "subcat": subcat, "cost": cost, "serial": serial, "ip": ip,
        "loc": loc, "auditNotes": audit_notes,
        "units": units or {}, "details": details or {},
        "showQty": show_qty or {}, "showNotes": show_notes or {},
        "spaceQty": space_qty or {}, "spaceNotes": space_notes or {},
    }
    return await request("POST", "/api/inventory/items", json=payload)


@mcp.tool()
async def update_inventory_item(
    item_id: int,
    make: Optional[str] = None,
    model: Optional[str] = None,
    qty: Optional[int] = None,
    line: Optional[int] = None,
    desc: Optional[str] = None,
    cat: Optional[str] = None,
    subcat: Optional[str] = None,
    cost: Optional[float] = None,
    serial: Optional[str] = None,
    ip: Optional[str] = None,
    loc: Optional[str] = None,
    audit_notes: Optional[str] = None,
    units: Optional[dict] = None,
    details: Optional[dict] = None,
    show_qty: Optional[dict] = None,
    show_notes: Optional[dict] = None,
    space_qty: Optional[dict] = None,
    space_notes: Optional[dict] = None,
):
    """Update fields on an existing inventory item. Only pass the fields you want to change.

    Note: show_qty/space_qty (if passed) REPLACE the item's entire set of
    allocations for that type — pass the full desired map, not just the
    one you're adding/changing.
    """
    payload = clean(locals())
    payload.pop("item_id", None)
    if "audit_notes" in payload: payload["auditNotes"] = payload.pop("audit_notes")
    if "show_qty" in payload: payload["showQty"] = payload.pop("show_qty")
    if "show_notes" in payload: payload["showNotes"] = payload.pop("show_notes")
    if "space_qty" in payload: payload["spaceQty"] = payload.pop("space_qty")
    if "space_notes" in payload: payload["spaceNotes"] = payload.pop("space_notes")
    return await request("PUT", f"/api/inventory/items/{item_id}", json=payload)


@mcp.tool()
async def delete_inventory_item(item_id: int):
    """Delete an inventory item. This is a soft-delete — the item moves to
    Recently Deleted and can be recovered with restore_inventory_item."""
    return await request("DELETE", f"/api/inventory/items/{item_id}")


@mcp.tool()
async def list_deleted_inventory_items():
    """List soft-deleted inventory items that are available to restore."""
    return await request("GET", "/api/inventory/items/deleted")


@mcp.tool()
async def restore_inventory_item(item_id: int):
    """Restore a soft-deleted inventory item back into active inventory."""
    return await request("POST", f"/api/inventory/items/{item_id}/restore")


@mcp.tool()
async def purge_inventory_item(item_id: int):
    """Permanently delete an inventory item — cannot be undone, skips
    Recently Deleted entirely. Use delete_inventory_item for normal,
    recoverable deletion instead unless you specifically need this."""
    return await request("DELETE", f"/api/inventory/items/{item_id}/purge")


# ══════════════════════════════════
# KNOWLEDGE BASE
# ══════════════════════════════════

@mcp.tool()
async def list_kb_pages():
    """List all Knowledge Base pages (slug, title, section, last updated) — no body text, use get_kb_page or search_kb for content."""
    return await request("GET", "/api/kb/pages")


@mcp.tool()
async def get_kb_page(slug: str):
    """Get the full content of one Knowledge Base page by its slug (see list_kb_pages or search_kb for slugs)."""
    return await request("GET", f"/api/kb/pages/{slug}")


@mcp.tool()
async def search_kb(query: str):
    """Search the Knowledge Base by keyword (e.g. a system name, IP, or procedure) and get back matching pages with relevance-ranked snippets."""
    return await request("GET", "/api/kb/search", params={"q": query})


@mcp.tool()
async def upsert_kb_page(
    slug: str,
    title: str,
    body_markdown: str,
    section: str = "",
    tags: Optional[list[str]] = None,
    source_files: Optional[list[str]] = None,
):
    """Create a new Knowledge Base page or overwrite an existing one (matched by slug).

    slug: URL-safe identifier, letters/numbers/hyphens/underscores only (e.g. 'hormel-network-map').
    body_markdown: the page content as Markdown (tables and fenced code blocks are supported).
    """
    payload = {
        "slug": slug,
        "title": title,
        "body_markdown": body_markdown,
        "section": section,
        "tags": tags or [],
        "source_files": source_files or [],
    }
    return await request("POST", "/api/kb/pages", json=payload)


@mcp.tool()
async def delete_kb_page(slug: str):
    """Delete a Knowledge Base page by slug."""
    return await request("DELETE", f"/api/kb/pages/{slug}")


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