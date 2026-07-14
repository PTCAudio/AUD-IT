#!/usr/bin/env python3
"""
Bulk-upload vendor gear manuals into the Manuals library.

Never touches the database directly — only calls the app's authenticated
/api/docs/* endpoints over HTTPS, same pattern as sync_wiki_to_db.py and
import_inventory.py. Creates any missing doc_sections (used here as the
Manuals category groupings) and is safe to re-run: existing documents
(matched by title within a section) are skipped, not duplicated.

The server extracts each PDF's bookmark outline into a page-jump TOC at
upload time (see pdf_utils.extract_pdf_toc) — nothing to do here but supply
the file and a category/device name.

Usage:

    AUDIT_APP_URL=https://www.ptc-audio.com \
    AUDIT_API_KEY=<the API_KEY value from Render env vars> \
    python scripts/import_manuals.py "/path/to/Raw/Manuals"

Expects the manual filenames to match MANIFEST below (case-insensitive,
partial match on stem) — add an entry there for any new manual before
running.
"""

import os
import sys
import pathlib
import requests

APP_URL = os.environ["AUDIT_APP_URL"].rstrip("/")
API_KEY = os.environ["AUDIT_API_KEY"]
HEADERS = {"X-API-Key": API_KEY}

# filename fragment (lowercased, extension-less) -> (category, device, title)
MANIFEST = [
    ("020-001908-06-christie-lit-man-usr-gs-series", "Video & Projection",
     "Christie GS Series", "Christie GS Series Projector — User Manual"),
    ("020-002122-03-christie-lit-man-usr-jazz-series", "Video & Projection",
     "Christie Jazz Series", "Christie Jazz Series Projector — User Manual"),
    ("020-102647-07-christie-lit-guid-set-crimson", "Video & Projection",
     "Christie Crimson", "Christie Crimson — Setup Guide"),
    ("ad4q-user-guide", "RF & Wireless",
     "Shure AD4Q", "AD4Q Digital Quad Receiver — User Guide"),
    ("adx1m-user-guide", "RF & Wireless",
     "Shure ADX1M", "ADX1M Bodypack Transmitter — User Guide"),
    ("arcadia_central_station_user_guide", "Comms",
     "Arcadia Central Station", "Arcadia Central Station — User Guide"),
    ("aud-man-dantecontroller", "Network & Control",
     "Dante Controller", "Dante Controller 4.18.x — Manual"),
    ("me-1 getting started guide", "Consoles & Control Surfaces",
     "Allen & Heath ME-1", "ME-1 Personal Mixer — Getting Started Guide"),
    ("qlab_5_reference_manual", "Show Control",
     "QLab 5", "QLab 5 — Reference Manual"),
    ("rivage pm network primer", "Consoles & Control Surfaces",
     "RIVAGE PM Series", "RIVAGE PM — Network Primer"),
    # No apostrophe in this title on purpose — sanitize() HTML-escapes on
    # upload and Jinja auto-escapes again on render, so an apostrophe here
    # would show up on the page literally as "&#x27;" (pre-existing
    # sanitize()+Jinja interaction, not new; sidestepping it is simpler
    # than touching sanitize() itself).
    ("rivage_pm_series_om", "Consoles & Control Surfaces",
     "RIVAGE PM Series", "RIVAGE PM Series — Owner Manual"),
]


def match_manifest(stem: str):
    stem_l = stem.lower()
    for frag, category, device, title in MANIFEST:
        if frag in stem_l:
            return category, device, title
    return None


def get_or_create_section(name: str, cache: dict) -> int:
    if name in cache:
        return cache[name]
    resp = requests.get(f"{APP_URL}/api/docs/sections", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    for s in resp.json():
        cache[s["name"]] = s["id"]
    if name in cache:
        return cache[name]
    resp = requests.post(f"{APP_URL}/api/docs/sections", headers=HEADERS,
                          json={"name": name}, timeout=30)
    resp.raise_for_status()
    section_id = resp.json()["id"]
    cache[name] = section_id
    return section_id


def existing_titles(section_id: int) -> set:
    resp = requests.get(f"{APP_URL}/api/docs/sections", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    for s in resp.json():
        if s["id"] == section_id:
            return {d["title"] for d in s["documents"]}
    return set()


def main(manuals_dir: str):
    manuals_path = pathlib.Path(manuals_dir)
    pdfs = sorted(manuals_path.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {manuals_dir}", file=sys.stderr)
        sys.exit(1)

    section_cache = {}
    ok, skipped, unmatched, failed = 0, 0, [], []

    for path in pdfs:
        match = match_manifest(path.stem)
        if not match:
            unmatched.append(path.name)
            print(f"  SKIP (no manifest entry) {path.name}")
            continue
        category, device, title = match

        section_id = get_or_create_section(category, section_cache)
        if title in existing_titles(section_id):
            skipped += 1
            print(f"  skip (already uploaded) {title}")
            continue

        with open(path, "rb") as f:
            resp = requests.post(
                f"{APP_URL}/api/docs/upload",
                headers=HEADERS,
                data={"section_id": section_id, "title": title,
                      "is_manual": "1", "device": device},
                files={"file": (path.name, f, "application/pdf")},
                timeout=300,
            )
        if resp.ok:
            body = resp.json()
            ok += 1
            print(f"  ok   {title}  ({body.get('page_count')} pages, "
                  f"{body.get('toc_entries')} TOC entries)")
        else:
            failed.append((path.name, resp.status_code, resp.text[:200]))
            print(f"  FAIL {title}: {resp.status_code}")

    print(f"\nUploaded {ok}, skipped {skipped} already-present, "
          f"{len(unmatched)} unmatched, {len(failed)} failed.")
    if unmatched:
        print("\nNo manifest entry (add one to MANIFEST and re-run):", file=sys.stderr)
        for name in unmatched:
            print(f"  {name}", file=sys.stderr)
    if failed:
        print("\nFailures:", file=sys.stderr)
        for name, status, text in failed:
            print(f"  {name}: {status} {text}", file=sys.stderr)
    if failed or unmatched:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/import_manuals.py <path-to-Manuals-dir>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
