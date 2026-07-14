"""
PDF table-of-contents extraction for the Manuals library.

Most gear manuals ship with a real bookmark/outline tree baked into the PDF
(Christie, Shure, Yamaha, Audinate, Arcadia all do) — this reads that tree
and resolves each entry to a page number, so the Manuals UI can render a
clickable TOC that jumps straight to the right page via the browser's native
PDF viewer (`/docs/file/<id>#page=N` — no page-rendering infra needed).

Not every manual has one (short docs like the RIVAGE PM Network Primer, or
the ME-1 Getting Started Guide, use no embedded outline at all) — in that
case extract_pdf_toc() returns an empty list and the manual is still viewable,
just without page-jump links from the app.
"""
import pypdf

MAX_ENTRIES = 800   # sanity cap — real manuals we've seen top out around 640
MAX_DEPTH = 4        # deeper than this stops being useful as a jump-to list


def extract_pdf_toc(path):
    """Returns (page_count, toc) where toc is a flat list of
    {"title": str, "page": int (1-indexed), "depth": int}, in document
    order. Never raises — a malformed/unreadable outline just yields []."""
    try:
        reader = pypdf.PdfReader(path)
    except Exception:
        return 0, []

    try:
        page_count = len(reader.pages)
    except Exception:
        page_count = 0

    try:
        outline = reader.outline
    except Exception:
        outline = []

    toc = []

    def walk(items, depth):
        if depth > MAX_DEPTH or len(toc) >= MAX_ENTRIES:
            return
        for item in items:
            if len(toc) >= MAX_ENTRIES:
                return
            if isinstance(item, list):
                walk(item, depth + 1)
                continue
            title = getattr(item, 'title', None)
            if not title:
                continue
            try:
                page_index = reader.get_destination_page_number(item)
            except Exception:
                page_index = None
            if page_index is None:
                continue
            toc.append({
                'title': title.strip(),
                'page': page_index + 1,
                'depth': depth,
            })

    try:
        walk(outline, 0)
    except Exception:
        toc = []

    return page_count, toc
