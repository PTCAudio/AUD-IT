#!/usr/bin/env python3
"""
Check the AUD-IT Operations/Wiki for link rot and orphaned pages.

Replaces the manual "re-read every page and cross-check" pass that used to
get done by hand each session (see Wiki/changelog.md's "daily ingest" /
"end-of-day health check" entries) with a deterministic script. Catches
exactly the same three things those manual passes were checking for:

  1. Broken links   — [text](some-slug.md) where some-slug.md doesn't exist
  2. Unlisted pages — a .md file on disk that _index.md doesn't link to
  3. Orphan pages    — a .md file that NO other page (including _index.md)
                        links to at all — reachable only by knowing the
                        filename, not by browsing

Exit code is 0 if clean, 1 if anything was found (so this can gate a commit
or CI step later, not just be a manual "run it and read the output" tool).

Usage:
    python3 scripts/check_wiki_links.py "/path/to/AUD-IT Operations/Wiki"
"""

import re
import sys
import pathlib

LINK_RE = re.compile(r'\[[^\]]*\]\(([a-zA-Z0-9_\-]+\.md)(?:#[^)]*)?\)')


def find_links(text: str) -> set:
    """All same-directory .md files linked from this page's markdown."""
    return set(LINK_RE.findall(text))


def main(wiki_dir: str) -> int:
    wiki_path = pathlib.Path(wiki_dir)
    md_files = sorted(wiki_path.glob('*.md'))
    if not md_files:
        print(f'No .md files found in {wiki_dir}', file=sys.stderr)
        return 1

    on_disk = {p.name for p in md_files}
    links_by_page = {}  # filename -> set of .md files it links to
    for path in md_files:
        text = path.read_text(encoding='utf-8')
        links_by_page[path.name] = find_links(text)

    # 1. Broken links: linked target doesn't exist on disk.
    broken = []  # (source_file, target)
    for source, targets in links_by_page.items():
        for target in targets:
            if target not in on_disk:
                broken.append((source, target))

    # 2. Unlisted: on disk, not linked from _index.md, and not _index.md itself.
    index_links = links_by_page.get('_index.md', set())
    unlisted = sorted(
        name for name in on_disk
        if name != '_index.md' and name not in index_links
    )

    # 3. Orphans: on disk, and not linked from ANY page (index or otherwise),
    # and not _index.md itself (the index is the entry point, it doesn't
    # need to be linked from elsewhere to be reachable).
    all_linked_targets = set()
    for targets in links_by_page.values():
        all_linked_targets |= targets
    orphans = sorted(
        name for name in on_disk
        if name != '_index.md' and name not in all_linked_targets
    )

    ok = not (broken or unlisted or orphans)

    print(f'Checked {len(md_files)} pages in {wiki_dir}\n')

    if broken:
        print(f'BROKEN LINKS ({len(broken)}):')
        for source, target in broken:
            print(f'  {source} -> {target} (target does not exist)')
        print()

    if unlisted:
        print(f'UNLISTED IN _index.md ({len(unlisted)}):')
        for name in unlisted:
            print(f'  {name}')
        print()

    if orphans:
        print(f'ORPHANS — no inbound links from anywhere ({len(orphans)}):')
        for name in orphans:
            print(f'  {name}')
        print()

    if ok:
        print(f'Clean: {len(md_files)}/{len(md_files)} pages, 0 broken links, 0 unlisted, 0 orphans.')

    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python3 check_wiki_links.py <path-to-Wiki-dir>', file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
