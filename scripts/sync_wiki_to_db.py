#!/usr/bin/env python3
"""
Sync local AUD-IT Operations/Wiki/*.md into the hosted kb_pages table.

Never touches the database directly — only calls the app's authenticated
/api/kb/pages endpoint over HTTPS, same pattern as the MCP connector.

Usage (run from anywhere, e.g. this repo's root):

    AUDIT_APP_URL=https://www.ptc-audio.com \
    AUDIT_API_KEY=<the API_KEY value from Render env vars> \
    python scripts/sync_wiki_to_db.py "/path/to/AUD-IT Operations/Wiki"
"""

import os
import re
import sys
import pathlib
import requests

APP_URL = os.environ["AUDIT_APP_URL"].rstrip("/")
API_KEY = os.environ["AUDIT_API_KEY"]

SECTION_HINTS = {
    "network": "Network",
    "budget": "Budget",
    "manual": "Manuals",
    "inventory": "Inventory",
    "video": "Video",
    "show": "Shows",
}


def slugify(path: pathlib.Path) -> str:
    return path.stem


def guess_section(slug: str) -> str:
    for key, label in SECTION_HINTS.items():
        if key in slug:
            return label
    return "General"


def extract_title(body: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def extract_source_files(body: str) -> list:
    return sorted(set(re.findall(r"`(Raw/[^`]+)`", body)))


def main(wiki_dir: str):
    wiki_path = pathlib.Path(wiki_dir)
    md_files = sorted(wiki_path.glob("*.md"))
    if not md_files:
        print(f"No .md files found in {wiki_dir}", file=sys.stderr)
        sys.exit(1)

    ok, failed = 0, []
    for path in md_files:
        if path.name == "_index.md":
            continue
        body = path.read_text(encoding="utf-8")
        slug = slugify(path)
        title = extract_title(body, fallback=slug.replace("-", " ").title())

        payload = {
            "slug": slug,
            "title": title,
            "section": guess_section(slug),
            "body_markdown": body,
            "source_files": extract_source_files(body),
            "tags": [],
        }

        resp = requests.post(
            f"{APP_URL}/api/kb/pages",
            json=payload,
            headers={"X-API-Key": API_KEY},
            timeout=30,
        )
        if resp.ok:
            ok += 1
            print(f"  ok  {slug}")
        else:
            failed.append((path.name, resp.status_code, resp.text[:200]))
            print(f"  FAIL {slug}: {resp.status_code}")

    total = len(md_files) - (1 if any(p.name == "_index.md" for p in md_files) else 0)
    print(f"\nSynced {ok}/{total} pages.")
    if failed:
        print("Failures:", file=sys.stderr)
        for name, status, text in failed:
            print(f"  {name}: {status} {text}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python sync_wiki_to_db.py <path-to-Wiki-dir>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
