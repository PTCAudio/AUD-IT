#!/usr/bin/env python3
"""
One-time migration: load the Inventory tool's own localStorage JSON export
(the "JSON backup" button in the tool — PTC_Audio_Backup_*.json) into the
hosted database.

Never touches the database directly — only calls the app's authenticated
/api/inventory/import endpoint over HTTPS, same pattern as sync_wiki_to_db.py.

This does NOT touch the shows/categories tables — those are owned by the
Task Manager app and already contain the real, live show records. Per-item
show allocations get matched to those real shows by name; any that don't
match exactly are reported back so you can fix a spelling and re-run
(the import is idempotent — safe to run more than once).

Usage:

    AUDIT_APP_URL=https://www.ptc-audio.com \
    AUDIT_API_KEY=<the API_KEY value from Render env vars> \
    python scripts/import_inventory.py "/path/to/PTC_Audio_Backup_2026-07-11.json"
"""

import os
import sys
import json
import requests

APP_URL = os.environ["AUDIT_APP_URL"].rstrip("/")
API_KEY = os.environ["AUDIT_API_KEY"]


def main(backup_path: str):
    with open(backup_path, encoding="utf-8") as f:
        payload = json.load(f)

    items = payload.get("items", [])
    print(f"Loaded {len(items)} items from {backup_path}")

    resp = requests.post(
        f"{APP_URL}/api/inventory/import",
        json=payload,
        headers={"X-API-Key": API_KEY},
        timeout=60,
    )

    if not resp.ok:
        print(f"FAILED: {resp.status_code} {resp.text[:500]}", file=sys.stderr)
        sys.exit(1)

    result = resp.json()
    print(f"\nImported {result['items_imported']} items.")

    unmatched = result.get("unmatched_shows", {})
    if unmatched:
        print(f"\n{len(unmatched)} show name(s) didn't exactly match a real show "
              f"in the shows table — those items were still imported, just not "
              f"linked to a show record:")
        for original, suggestion in unmatched.items():
            hint = f"  (closest real match: \"{suggestion}\")" if suggestion else "  (no close match found)"
            print(f'  - "{original}"{hint}')
        print("\nFix the spelling in either place and re-run this script — it's safe to re-run.")
    else:
        print("All referenced shows matched real show records exactly.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python import_inventory.py <path-to-PTC_Audio_Backup-json>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
