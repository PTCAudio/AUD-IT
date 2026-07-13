"""
AUD-IT Suite — Database Models
SQLite schema and helper functions for inventory and task management.
"""
import uuid
import sqlite3
import os
import json
import re
import difflib
from datetime import datetime

DB_PATH = os.environ.get('DATABASE_PATH', 'audit_suite.db')


def get_db():
    """Get a database connection with row_factory for dict-like access."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _migrate_old_inventory_schema_if_needed(db):
    """The original inventory_items table was a placeholder shape that no
    route ever wrote to (confirmed: nothing in app.py calls get_all_items/
    create_item/etc.) — it doesn't match what the real Inventory tool
    actually stores. Safe to drop and let the real schema below recreate
    it fresh, with zero data-loss risk. Detected by checking for a column
    ('cat'-adjacent 'subcategory') that only exists in the new shape."""
    cols = [r['name'] for r in db.execute("PRAGMA table_info(inventory_items)").fetchall()]
    if cols and 'subcategory' not in cols:
        db.execute('DROP TABLE IF EXISTS inventory_items')
        db.commit()


def init_db():
    """Create all tables if they don't exist."""
    db = get_db()
    _migrate_old_inventory_schema_if_needed(db)
    db.executescript('''
        -- ══════════════════════════════════
        -- SHARED
        -- ══════════════════════════════════
        CREATE TABLE IF NOT EXISTS shows (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            space TEXT NOT NULL DEFAULT 'general',
            archived INTEGER NOT NULL DEFAULT 0,
            load_in TEXT DEFAULT '',
            open_date TEXT DEFAULT '',
            close_date TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- ══════════════════════════════════
        -- INVENTORY
        -- Schema mirrors the real fields the Inventory tool actually uses
        -- (verified against templates/tools/inventory.html's saveItem()),
        -- not the earlier placeholder shape — that version was never
        -- written to by any route, so no migration/data-loss risk here.
        -- The tool itself still runs on localStorage; this table is DB-side
        -- prep for a future cutover, plus soft-delete support.
        -- ══════════════════════════════════
        CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            line INTEGER DEFAULT 0,
            qty INTEGER NOT NULL DEFAULT 0,
            make TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            description TEXT DEFAULT '',
            category TEXT DEFAULT '',
            subcategory TEXT DEFAULT '',
            cost REAL DEFAULT 0,
            serial TEXT DEFAULT '',
            ip TEXT DEFAULT '',
            location TEXT DEFAULT '',
            audit_notes TEXT DEFAULT '',
            units_json TEXT DEFAULT '{}',
            unit_details_json TEXT DEFAULT '{}',
            deleted_at TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Per-show allocation of an inventory item (qty + notes), one row
        -- per item/show pair. show_id references shows.id but isn't
        -- declared as a hard FK since shows can be deleted independently.
        CREATE TABLE IF NOT EXISTS inventory_item_shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
            show_id TEXT NOT NULL,
            qty INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            UNIQUE(item_id, show_id)
        );

        -- Per-space (Stephenson/Hormel/Hardes) allocation of an inventory
        -- item. Spaces are a small fixed set defined client-side (SPACES in
        -- inventory.html), not their own DB table.
        CREATE TABLE IF NOT EXISTS inventory_item_spaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
            space_id TEXT NOT NULL,
            qty INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            UNIQUE(item_id, space_id)
        );

        -- ══════════════════════════════════
        -- TASKS
        -- ══════════════════════════════════
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            space TEXT NOT NULL DEFAULT 'general',
            show_id TEXT DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'none',
            urgency TEXT NOT NULL DEFAULT 'soon',
            due_date TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            done INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- ══════════════════════════════════
        -- JOURNAL
        -- ══════════════════════════════════
        CREATE TABLE IF NOT EXISTS journal_entries (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT 'Matthew',
            hours TEXT DEFAULT '{}',
            total_hours REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- ══════════════════════════════════
        -- HOURS LOG (separate from journal)
        -- ══════════════════════════════════
        CREATE TABLE IF NOT EXISTS hours_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author TEXT NOT NULL,
            date TEXT NOT NULL,
            space TEXT NOT NULL,
            hours REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(author, date, space)
        );

        -- ══════════════════════════════════
        -- TEAM MEMBERS
        -- ══════════════════════════════════
        CREATE TABLE IF NOT EXISTS team_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT NOT NULL DEFAULT '#888078',
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- ══════════════════════════════════
        -- USERS / AUTH
        -- ══════════════════════════════════
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'user',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            last_login_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS invite_tokens (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            invited_by INTEGER,
            expires_at TEXT NOT NULL,
            used_at TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER,
            actor_name TEXT DEFAULT '',
            action TEXT NOT NULL,
            target TEXT DEFAULT '',
            detail TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- ══════════════════════════════════
        -- KNOWLEDGE BASE (hosted copy of AUD-IT Operations/Wiki)
        -- ══════════════════════════════════
        CREATE TABLE IF NOT EXISTS kb_pages (
            slug TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            section TEXT DEFAULT '',
            body_markdown TEXT NOT NULL,
            tags TEXT DEFAULT '[]',
            source_files TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- ══════════════════════════════════
        -- VENUE FACT DB (Home page STAFF/GUEST system data)
        -- ══════════════════════════════════
        CREATE TABLE IF NOT EXISTS venues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(mode, name)
        );

        CREATE TABLE IF NOT EXISTS venue_systems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue_id INTEGER NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            rows_json TEXT NOT NULL DEFAULT '[]',
            warns_json TEXT NOT NULL DEFAULT '[]',
            notes_json TEXT NOT NULL DEFAULT '[]',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- ══════════════════════════════════
        -- DOCUMENTS (Home page Documents section — riders, guides, network
        -- diagrams, budget/incident PDFs). Files live on the Render
        -- persistent disk (see get_docs_storage_dir()), not in the git repo,
        -- so admin upload/delete take effect immediately with no deploy.
        -- ══════════════════════════════════
        CREATE TABLE IF NOT EXISTS doc_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL REFERENCES doc_sections(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            orig_filename TEXT DEFAULT '',
            size_bytes INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            uploaded_by TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
    ''')
    db.commit()

    _seed_venues_if_empty(db)
    _seed_documents_if_empty(db)

    # Migrations
    try:
        db.execute("ALTER TABLE journal_entries ADD COLUMN author TEXT NOT NULL DEFAULT 'Matthew'")
        db.commit()
    except:
        pass

    try:
        db.execute("ALTER TABLE tasks ADD COLUMN created_by INTEGER")
        db.commit()
    except:
        pass

    try:
        db.execute("ALTER TABLE tasks ADD COLUMN created_by_name TEXT DEFAULT ''")
        db.commit()
    except:
        pass

    # Indexes
    db.executescript('''
        CREATE INDEX IF NOT EXISTS idx_tasks_space ON tasks(space);
        CREATE INDEX IF NOT EXISTS idx_tasks_show ON tasks(show_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_done ON tasks(done);
        CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(date);
        CREATE INDEX IF NOT EXISTS idx_journal_author ON journal_entries(author);
        CREATE INDEX IF NOT EXISTS idx_shows_space ON shows(space);
        CREATE INDEX IF NOT EXISTS idx_hours_author ON hours_log(author);
        CREATE INDEX IF NOT EXISTS idx_hours_date ON hours_log(date);
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_invite_email ON invite_tokens(email);
        CREATE INDEX IF NOT EXISTS idx_reset_user ON password_reset_tokens(user_id);
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
        CREATE INDEX IF NOT EXISTS idx_kb_section ON kb_pages(section);
        CREATE INDEX IF NOT EXISTS idx_venues_mode ON venues(mode);
        CREATE INDEX IF NOT EXISTS idx_venue_systems_venue ON venue_systems(venue_id);
        CREATE INDEX IF NOT EXISTS idx_inv_deleted ON inventory_items(deleted_at);
        CREATE INDEX IF NOT EXISTS idx_inv_category ON inventory_items(category);
        CREATE INDEX IF NOT EXISTS idx_inv_item_shows_item ON inventory_item_shows(item_id);
        CREATE INDEX IF NOT EXISTS idx_inv_item_spaces_item ON inventory_item_spaces(item_id);
        CREATE INDEX IF NOT EXISTS idx_doc_sections_sort ON doc_sections(sort_order);
        CREATE INDEX IF NOT EXISTS idx_documents_section ON documents(section_id);
    ''')
    db.commit()
    db.close()


def _seed_venues_if_empty(db):
    """One-time seed of the venues/venue_systems tables from the bundled JSON
    snapshot of the original hardcoded STAFF/GUEST fact data. Only runs when
    the venues table is empty, so it never clobbers edits made later through
    the admin editor — safe to leave in init_db() permanently."""
    existing = db.execute('SELECT COUNT(*) AS c FROM venues').fetchone()['c']
    if existing:
        return

    base = os.path.dirname(os.path.abspath(__file__))
    seed_files = {'staff': 'venues_staff.json', 'guest': 'venues_guest.json'}
    for mode, filename in seed_files.items():
        path = os.path.join(base, 'seed_data', filename)
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for v_order, (venue_name, venue_data) in enumerate(data.items()):
            description = venue_data.get('_d', '')
            cur = db.execute(
                'INSERT INTO venues (mode, name, description, sort_order) VALUES (?,?,?,?)',
                (mode, venue_name, description, v_order)
            )
            venue_id = cur.lastrowid
            s_order = 0
            for sys_name, sys_data in venue_data.items():
                if sys_name == '_d':
                    continue
                db.execute('''INSERT INTO venue_systems
                    (venue_id, name, rows_json, warns_json, notes_json, sort_order)
                    VALUES (?,?,?,?,?,?)''',
                    (venue_id, sys_name,
                     json.dumps(sys_data.get('rows', [])),
                     json.dumps(sys_data.get('warns', [])),
                     json.dumps(sys_data.get('notes', [])),
                     s_order))
                s_order += 1
    db.commit()


def get_docs_storage_dir():
    """Directory where uploaded document PDFs actually live. Placed next to
    the SQLite DB file — on Render that's the persistent disk mount
    (/var/data), so uploads/deletes survive redeploys with no git push
    needed, exactly like the DB itself. Locally (no DATABASE_PATH set) this
    just resolves to a folder next to the repo, which is fine for dev."""
    base = os.path.dirname(os.path.abspath(DB_PATH))
    d = os.path.join(base, 'doc_uploads')
    os.makedirs(d, exist_ok=True)
    return d


# Legacy hardcoded DOCS array from templates/home.html, used only as the
# one-time seed source below — kept here (not re-read from the template) so
# the seed doesn't depend on home.html's JS still matching this shape later.
_LEGACY_DOCS_SEED = [
    ("Riders (external-ready)", [
        ("Stephenson Audio System Rider v1.2", "Riders/Stephenson_Audio_System_Rider_v1.2.pdf"),
        ("Hormel Audio System Rider v1.0", "Riders/Hormel_Audio_System_Rider_v1.0.pdf"),
    ]),
    ("System guides", [
        ("Hormel System Reference Guide v1.3", "System-Guides/Hormel_System_Reference_Guide_v1.3.pdf"),
        ("Hormel Network Signal Flow", "System-Guides/Hormel_Network_Signal_Flow_v1.0.pdf"),
        ("Hormel CL5 MIDI Remote Addendum", "System-Guides/Hormel_CL5_MIDI_Remote_Control_Addendum_v1.0.pdf"),
        ("RIVAGEPM Show-File Teardown", "System-Guides/Inside_the_Show_File_RIVAGEPM_Teardown.pdf"),
    ]),
    ("Network", [
        ("Audio Network Big Picture v1.0", "Network/PTC_Audio_Network_Big_Picture_v1.0.pdf"),
        ("Switch-by-Switch Reference v2.0", "Network/PTC_Audio_Switch_By_Switch_v2.0.pdf"),
        ("Stephenson Designer IP Quick Sheet v1.3", "Network/Stephenson_Designer_IP_QuickSheet_v1.3.pdf"),
        ("Arcadia System Map v1.1", "Network/Arcadia_System_Map_by_Space_v1.1.pdf"),
    ]),
    ("Budget & reports", [
        ("Season Supply Budget Analysis", "Budget/Season_Supply_Budget_Analysis.pdf"),
        ("MS26 Sound Spend Report", "Budget/MS26_Sound_Spend_Report.pdf"),
        ("Band Mic Usage Comparison", "Budget/Band_Mic_Usage_Comparison.pdf"),
    ]),
    ("Incidents", [
        ("PM5 DSP Incident Report v1.1 2026-07-10", "Incidents/PM5_DSP_Incident_Report_v1.1_2026-07-10.pdf"),
    ]),
]


def _seed_documents_if_empty(db):
    """One-time migration: copies the PDFs that used to be served straight
    out of the git-tracked docs/ folder into the persistent-disk storage dir,
    and seeds doc_sections/documents from the old hardcoded DOCS array in
    home.html. Only runs when doc_sections is empty, so later admin edits
    (renames, uploads, deletes) are never clobbered on restart."""
    existing = db.execute('SELECT COUNT(*) AS c FROM doc_sections').fetchone()['c']
    if existing:
        return

    import shutil
    repo_docs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')
    storage_dir = get_docs_storage_dir()

    for s_order, (section_name, docs) in enumerate(_LEGACY_DOCS_SEED):
        cur = db.execute(
            'INSERT INTO doc_sections (name, sort_order) VALUES (?, ?)',
            (section_name, s_order)
        )
        section_id = cur.lastrowid
        for d_order, (title, rel_path) in enumerate(docs):
            src = os.path.join(repo_docs_dir, rel_path)
            orig_filename = os.path.basename(rel_path)
            ext = os.path.splitext(orig_filename)[1] or '.pdf'
            stored_filename = uuid.uuid4().hex + ext
            size_bytes = 0
            if os.path.isfile(src):
                dst = os.path.join(storage_dir, stored_filename)
                shutil.copyfile(src, dst)
                size_bytes = os.path.getsize(dst)
            else:
                # Source missing (shouldn't happen, but don't fail the whole
                # seed over one missing file) — insert the row anyway with
                # size_bytes=0 so it's at least visible/manageable in admin.
                pass
            db.execute('''INSERT INTO documents
                (section_id, title, filename, orig_filename, size_bytes, sort_order, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (section_id, title, stored_filename, orig_filename, size_bytes, d_order, 'migration'))
    db.commit()


# ══════════════════════════════════
# DOCUMENTS CRUD
# ══════════════════════════════════

def list_documents_grouped():
    """Sections + their (non-empty ordering aside) documents, ordered for
    display — used both by the Home page and the admin editor."""
    db = get_db()
    sections = db.execute(
        'SELECT * FROM doc_sections ORDER BY sort_order, name'
    ).fetchall()
    result = []
    for s in sections:
        docs = db.execute(
            'SELECT * FROM documents WHERE section_id = ? ORDER BY sort_order, title',
            (s['id'],)
        ).fetchall()
        result.append({
            'id': s['id'],
            'name': s['name'],
            'sort_order': s['sort_order'],
            'documents': [dict(d) for d in docs],
        })
    db.close()
    return result

def get_doc_section(section_id):
    db = get_db()
    row = db.execute('SELECT * FROM doc_sections WHERE id = ?', (section_id,)).fetchone()
    db.close()
    return dict(row) if row else None

def create_doc_section(name, sort_order=None):
    db = get_db()
    if sort_order is None:
        max_order = db.execute('SELECT MAX(sort_order) AS m FROM doc_sections').fetchone()['m']
        sort_order = (max_order or 0) + 1
    cur = db.execute(
        'INSERT INTO doc_sections (name, sort_order) VALUES (?, ?)',
        (name, sort_order)
    )
    db.commit()
    section_id = cur.lastrowid
    db.close()
    return section_id

def rename_doc_section(section_id, name):
    db = get_db()
    db.execute('UPDATE doc_sections SET name = ? WHERE id = ?', (name, section_id))
    db.commit()
    db.close()

def reorder_doc_sections(id_order_list):
    db = get_db()
    for order, section_id in enumerate(id_order_list):
        db.execute('UPDATE doc_sections SET sort_order = ? WHERE id = ?', (order, section_id))
    db.commit()
    db.close()

def delete_doc_section(section_id):
    """Returns the stored filenames of any documents in the section, so the
    caller can remove them from disk — the DB rows cascade-delete via the
    FK, but SQLite obviously can't clean up files on disk for us."""
    db = get_db()
    docs = db.execute('SELECT filename FROM documents WHERE section_id = ?', (section_id,)).fetchall()
    filenames = [d['filename'] for d in docs]
    db.execute('DELETE FROM doc_sections WHERE id = ?', (section_id,))
    db.commit()
    db.close()
    return filenames

def get_document(doc_id):
    db = get_db()
    row = db.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone()
    db.close()
    return dict(row) if row else None

def create_document(section_id, title, filename, orig_filename='', size_bytes=0, sort_order=None, uploaded_by=''):
    db = get_db()
    if sort_order is None:
        max_order = db.execute(
            'SELECT MAX(sort_order) AS m FROM documents WHERE section_id = ?', (section_id,)
        ).fetchone()['m']
        sort_order = (max_order or 0) + 1
    cur = db.execute('''INSERT INTO documents
        (section_id, title, filename, orig_filename, size_bytes, sort_order, uploaded_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (section_id, title, filename, orig_filename, size_bytes, sort_order, uploaded_by))
    db.commit()
    doc_id = cur.lastrowid
    db.close()
    return doc_id

def delete_document(doc_id):
    """Returns the stored filename (so the caller can remove it from disk)
    or None if the document didn't exist."""
    db = get_db()
    row = db.execute('SELECT filename FROM documents WHERE id = ?', (doc_id,)).fetchone()
    if not row:
        db.close()
        return None
    filename = row['filename']
    db.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
    db.commit()
    db.close()
    return filename

def reorder_documents(section_id, id_order_list):
    db = get_db()
    for order, doc_id in enumerate(id_order_list):
        db.execute(
            'UPDATE documents SET sort_order = ? WHERE id = ? AND section_id = ?',
            (order, doc_id, section_id)
        )
    db.commit()
    db.close()


# ══════════════════════════════════
# KNOWLEDGE BASE CRUD
# ══════════════════════════════════

def list_kb_pages():
    db = get_db()
    rows = db.execute(
        'SELECT slug, title, section, updated_at FROM kb_pages ORDER BY section, title'
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]

def get_kb_page(slug):
    db = get_db()
    row = db.execute('SELECT * FROM kb_pages WHERE slug = ?', (slug,)).fetchone()
    db.close()
    return dict(row) if row else None

def upsert_kb_page(slug, title, section, body_markdown, tags, source_files):
    db = get_db()
    db.execute('''
        INSERT INTO kb_pages (slug, title, section, body_markdown, tags, source_files, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(slug) DO UPDATE SET
            title = excluded.title,
            section = excluded.section,
            body_markdown = excluded.body_markdown,
            tags = excluded.tags,
            source_files = excluded.source_files,
            updated_at = datetime('now')
    ''', (slug, title, section, body_markdown, json.dumps(tags), json.dumps(source_files)))
    db.commit()
    db.close()

def delete_kb_page(slug):
    db = get_db()
    db.execute('DELETE FROM kb_pages WHERE slug = ?', (slug,))
    db.commit()
    db.close()

_STOPWORDS = {
    'a','an','the','is','are','was','were','do','does','did','how','many','much',
    'what','which','who','whom','where','when','why','in','on','at','of','for',
    'to','and','or','we','i','you','it','this','that','have','has','had','be',
    'can','could','will','would','should','with','about','our'
}

def _find_positions(lower, word):
    positions = []
    start = 0
    while True:
        idx = lower.find(word, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    return positions

def _proximity_window(lower, words, span=250):
    """Find the tightest spot in the body where every search word co-occurs
    within `span` characters of each other, so results favor a passage that's
    actually ABOUT all the query terms together (e.g. 'Hormel' right next to
    'Console: CL5') over a page that just happens to mention each word
    somewhere unrelated. Returns (center_pos, found) — found=False means no
    such co-occurring window exists, only scattered individual mentions."""
    if len(words) == 1:
        positions = _find_positions(lower, words[0])
        return (positions[0], True, positions[:1]) if positions else (0, False, [])

    word_positions = {w: _find_positions(lower, w) for w in words}
    if any(not v for v in word_positions.values()):
        return (0, False, [])

    # Anchor on the rarest word's occurrences — most selective starting point.
    anchor_word = min(word_positions, key=lambda w: len(word_positions[w]))
    best = None
    for anchor in word_positions[anchor_word]:
        window_lo, window_hi = anchor - span, anchor + span
        others_ok = all(
            any(window_lo <= p <= window_hi for p in word_positions[w])
            for w in words if w != anchor_word
        )
        if others_ok:
            # tightest actual spread within this window, for a cleaner snippet center
            nearby = [anchor] + [
                min((p for p in word_positions[w] if window_lo <= p <= window_hi),
                    key=lambda p: abs(p - anchor))
                for w in words if w != anchor_word
            ]
            center = sum(nearby) // len(nearby)
            spread = max(nearby) - min(nearby)
            if best is None or spread < best[1]:
                best = (center, spread, nearby)
    if best is not None:
        return best[0], True, best[2]
    return (word_positions[anchor_word][0], False, [word_positions[anchor_word][0]])

_MD_EMPHASIS_RE = re.compile(r'\*\*(.+?)\*\*|__(.+?)__|`(.+?)`')

def _strip_md_emphasis(text):
    return _MD_EMPHASIS_RE.sub(lambda m: next(g for g in m.groups() if g is not None), text)

def _is_table_row(line):
    s = line.strip()
    return s.startswith('|') and s.endswith('|') and s.count('|') >= 2

def _is_table_separator(line):
    # e.g. "|---|---|---|" — strip('|') only trims the outer edges, so split
    # on '|' first rather than checking the whole string for '-'/':' chars
    # (which would wrongly fail on the internal pipes between columns).
    parts = [p.strip() for p in line.strip().strip('|').split('|')]
    return bool(parts) and all(p != '' and all(c in '-: ' for c in p) for p in parts)

def _table_row_snippet(body, pos):
    """If the matched position falls inside a markdown table, reformat that
    row as 'Header: value, Header: value' instead of dumping raw pipes —
    much more readable than a sliced-up table row/header/separator jumble.
    Returns None if the position isn't inside a table."""
    lines = body.split('\n')
    offsets = []
    running = 0
    for line in lines:
        offsets.append(running)
        running += len(line) + 1
    line_idx = 0
    for i, off in enumerate(offsets):
        if off <= pos:
            line_idx = i
        else:
            break

    if not _is_table_row(lines[line_idx]):
        return None
    if _is_table_separator(lines[line_idx]):
        # landed on the "|---|---|" row itself — nudge to the next data row
        if line_idx + 1 < len(lines) and _is_table_row(lines[line_idx + 1]):
            line_idx += 1
        else:
            return None

    # Walk up to the header row: the first table row at the top of this
    # contiguous block of table lines.
    header_idx = line_idx
    while header_idx > 0 and _is_table_row(lines[header_idx - 1]):
        header_idx -= 1
    if header_idx == line_idx:
        return None  # matched row IS the header, nothing to pair it with

    def cells(line):
        return [c.strip() for c in line.strip().strip('|').split('|')]

    headers = cells(lines[header_idx])
    values = cells(lines[line_idx])
    if len(headers) != len(values):
        return None

    pairs = [f'{h}: {_strip_md_emphasis(v)}' for h, v in zip(headers, values) if v and v != '—']
    return ', '.join(pairs) if pairs else None

def _snippet_for(body, words, width=200):
    """Snippet centered on the tightest co-occurrence of all search words, so
    it shows the actual answer rather than an arbitrary single-word hit.
    Table rows get reformatted into readable 'Header: value' pairs instead
    of raw markdown pipes."""
    lower = body.lower()
    pos, _, nearby = _proximity_window(lower, words)

    # Try each individual matched word's position (not just the arithmetic-
    # mean center) for a table hit — the center can land on a table's header
    # row or fall between a heading and the table below it, even when one of
    # the actual word matches is sitting right inside a data row.
    for candidate in dict.fromkeys([pos] + nearby):  # dedupe, keep order
        table_snippet = _table_row_snippet(body, candidate)
        if table_snippet:
            return table_snippet

    start = max(0, pos - width // 2)
    end = min(len(body), start + width)
    text = body[start:end]
    text = _strip_md_emphasis(text)
    text = ' '.join(text.split())  # collapse markdown line breaks/whitespace
    text = text.lstrip('#-*| ')
    prefix = '…' if start > 0 else ''
    suffix = '…' if end < len(body) else ''
    return f'{prefix}{text}{suffix}'

def search_kb_pages(q, limit=5):
    """Keyword AND-match on title+body, ranked by relevance, with a content
    snippet per result — fine at ~45 pages. Splits the query into significant
    words (dropping common stopwords) and requires every remaining word to
    appear somewhere in the page, so natural questions like 'what console is
    in the hormel' match on 'console'+'hormel' rather than the literal phrase.
    Ranking: title hits count for more than body-only hits, so the page most
    specifically about the topic surfaces first instead of a flat alphabetical
    list. Revisit with FTS5 if the KB grows a lot."""
    db = get_db()
    words = [w.strip('?.,!"\'') for w in q.lower().split()]
    words = [w for w in words if w and w not in _STOPWORDS]
    if not words:
        words = [w.strip('?.,!"\'') for w in q.lower().split() if w.strip('?.,!"\'')]
    if not words:
        db.close()
        return []

    clauses = []
    params = []
    for w in words:
        clauses.append('(title LIKE ? OR body_markdown LIKE ?)')
        like = f'%{w}%'
        params.extend([like, like])
    where = ' AND '.join(clauses)

    rows = db.execute(f'''
        SELECT slug, title, section, body_markdown FROM kb_pages
        WHERE {where}
    ''', params).fetchall()
    db.close()

    scored = []
    for r in rows:
        title_l = r['title'].lower()
        body_l = r['body_markdown'].lower()
        pos, co_occurs, _ = _proximity_window(body_l, words)
        # Proximity dominates: a passage where all terms actually appear
        # together outranks a page that merely mentions each word somewhere
        # unrelated, regardless of how many scattered mentions it racks up.
        score = (100 if co_occurs else 0)
        score += sum(6 for w in words if w in title_l)
        score += sum(body_l.count(w) for w in words)
        scored.append((score, dict(
            slug=r['slug'], title=r['title'], section=r['section'],
            snippet=_snippet_for(r['body_markdown'], words),
        )))
    scored.sort(key=lambda x: (-x[0], x[1]['title']))
    return [item for _, item in scored[:limit]]


# ══════════════════════════════════
# VENUE FACT DB CRUD (Home page STAFF/GUEST data)
# ══════════════════════════════════

def get_venues_nested(mode):
    """Rebuild the exact {venueName: {_d, sysName: {rows,warns,notes}, ...}}
    shape the Home page's client-side JS already expects, so the front-end
    rendering code (sec/venue/card/home) needs zero changes — only the data
    source moves from hardcoded JS to this DB-backed structure."""
    db = get_db()
    venues = db.execute(
        'SELECT id, name, description FROM venues WHERE mode=? ORDER BY sort_order, name',
        (mode,)
    ).fetchall()
    result = {}
    for v in venues:
        systems = db.execute(
            'SELECT name, rows_json, warns_json, notes_json FROM venue_systems '
            'WHERE venue_id=? ORDER BY sort_order, name',
            (v['id'],)
        ).fetchall()
        venue_obj = {'_d': v['description']}
        for s in systems:
            venue_obj[s['name']] = {
                'rows': json.loads(s['rows_json']),
                'warns': json.loads(s['warns_json']),
                'notes': json.loads(s['notes_json']),
            }
        result[v['name']] = venue_obj
    db.close()
    return result


def list_venues(mode=None):
    db = get_db()
    if mode:
        rows = db.execute('SELECT * FROM venues WHERE mode=? ORDER BY sort_order, name', (mode,)).fetchall()
    else:
        rows = db.execute('SELECT * FROM venues ORDER BY mode, sort_order, name').fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_venue(venue_id):
    db = get_db()
    row = db.execute('SELECT * FROM venues WHERE id=?', (venue_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def list_venue_systems(venue_id):
    db = get_db()
    rows = db.execute(
        'SELECT * FROM venue_systems WHERE venue_id=? ORDER BY sort_order, name', (venue_id,)
    ).fetchall()
    db.close()
    out = []
    for r in rows:
        d = dict(r)
        d['rows'] = json.loads(d.pop('rows_json'))
        d['warns'] = json.loads(d.pop('warns_json'))
        d['notes'] = json.loads(d.pop('notes_json'))
        out.append(d)
    return out


def create_venue(mode, name, description='', sort_order=0):
    db = get_db()
    cur = db.execute(
        'INSERT INTO venues (mode, name, description, sort_order) VALUES (?,?,?,?)',
        (mode, name, description, sort_order)
    )
    db.commit()
    venue_id = cur.lastrowid
    db.close()
    return venue_id


def update_venue(venue_id, data):
    db = get_db()
    fields = []
    values = []
    for key in ['name', 'description', 'sort_order']:
        if key in data:
            fields.append(f'{key}=?')
            values.append(data[key])
    if fields:
        fields.append("updated_at=datetime('now')")
        values.append(venue_id)
        db.execute(f'UPDATE venues SET {",".join(fields)} WHERE id=?', values)
        db.commit()
    db.close()


def delete_venue(venue_id):
    db = get_db()
    db.execute('DELETE FROM venue_systems WHERE venue_id=?', (venue_id,))
    db.execute('DELETE FROM venues WHERE id=?', (venue_id,))
    db.commit()
    db.close()


def create_venue_system(venue_id, name, rows=None, warns=None, notes=None, sort_order=0):
    db = get_db()
    cur = db.execute('''INSERT INTO venue_systems
        (venue_id, name, rows_json, warns_json, notes_json, sort_order)
        VALUES (?,?,?,?,?,?)''',
        (venue_id, name, json.dumps(rows or []), json.dumps(warns or []),
         json.dumps(notes or []), sort_order))
    db.commit()
    system_id = cur.lastrowid
    db.close()
    return system_id


def update_venue_system(system_id, data):
    db = get_db()
    fields = []
    values = []
    if 'name' in data:
        fields.append('name=?')
        values.append(data['name'])
    if 'sort_order' in data:
        fields.append('sort_order=?')
        values.append(data['sort_order'])
    for key, col in [('rows', 'rows_json'), ('warns', 'warns_json'), ('notes', 'notes_json')]:
        if key in data:
            fields.append(f'{col}=?')
            values.append(json.dumps(data[key]))
    if fields:
        fields.append("updated_at=datetime('now')")
        values.append(system_id)
        db.execute(f'UPDATE venue_systems SET {",".join(fields)} WHERE id=?', values)
        db.commit()
    db.close()


def delete_venue_system(system_id):
    db = get_db()
    db.execute('DELETE FROM venue_systems WHERE id=?', (system_id,))
    db.commit()
    db.close()


# ══════════════════════════════════
# INVENTORY CRUD
# Field names mirror templates/tools/inventory.html's saveItem() exactly
# (desc/cat/subcat/cost/serial/ip/loc/auditNotes, units/details keyed by
# SK=['available','inuse','broken','repair','retired','unknown'], plus
# separate per-show and per-space allocation tables). This is DB-side prep
# only — the live tool still reads/writes localStorage; nothing here is
# wired to a route yet.
# ══════════════════════════════════

def _row_to_item(row):
    d = dict(row)
    d['units'] = json.loads(d.pop('units_json') or '{}')
    d['unit_details'] = json.loads(d.pop('unit_details_json') or '{}')
    return d


def list_items(include_deleted=False):
    db = get_db()
    if include_deleted:
        rows = db.execute('SELECT * FROM inventory_items ORDER BY line, id').fetchall()
    else:
        rows = db.execute("SELECT * FROM inventory_items WHERE deleted_at='' ORDER BY line, id").fetchall()
    db.close()
    return [_row_to_item(r) for r in rows]


def list_deleted_items():
    """For a future 'Recently Deleted' recovery view."""
    db = get_db()
    rows = db.execute("SELECT * FROM inventory_items WHERE deleted_at!='' ORDER BY deleted_at DESC").fetchall()
    db.close()
    return [_row_to_item(r) for r in rows]


def get_item(item_id, include_deleted=True):
    db = get_db()
    row = db.execute('SELECT * FROM inventory_items WHERE id=?', (item_id,)).fetchone()
    db.close()
    if not row:
        return None
    if not include_deleted and row['deleted_at']:
        return None
    return _row_to_item(row)


def _item_to_tool_shape(item):
    """Convert a DB-shaped item (from _row_to_item) plus its show/space
    allocations into the EXACT field names/shape templates/tools/
    inventory.html's saveItem() constructs (desc/cat/subcat/auditNotes/
    details/showQty/showNotes/spaceQty/spaceNotes as two separate parallel
    objects each) — so the client-side JS needs zero renaming logic and can
    treat API responses exactly like its old localStorage-loaded items."""
    shows = get_item_shows(item['id'])
    spaces = get_item_spaces(item['id'])
    return {
        'id': item['id'],
        'line': item['line'],
        'qty': item['qty'],
        'make': item['make'],
        'model': item['model'],
        'desc': item['description'],
        'cat': item['category'],
        'subcat': item['subcategory'],
        'cost': item['cost'],
        'serial': item['serial'],
        'ip': item['ip'],
        'loc': item['location'],
        'auditNotes': item['audit_notes'],
        'units': item['units'],
        'details': item['unit_details'],
        'showQty': {k: v['qty'] for k, v in shows.items()},
        'showNotes': {k: v['notes'] for k, v in shows.items() if v['notes']},
        'spaceQty': {k: v['qty'] for k, v in spaces.items()},
        'spaceNotes': {k: v['notes'] for k, v in spaces.items() if v['notes']},
    }


def list_items_for_tool(include_deleted=False):
    return [_item_to_tool_shape(i) for i in list_items(include_deleted=include_deleted)]


def get_item_for_tool(item_id):
    item = get_item(item_id)
    return _item_to_tool_shape(item) if item else None


def create_item(data):
    db = get_db()
    cur = db.execute('''INSERT INTO inventory_items
        (line, qty, make, model, description, category, subcategory, cost,
         serial, ip, location, audit_notes, units_json, unit_details_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (data.get('line', 0), data.get('qty', 0), data.get('make', ''), data.get('model', ''),
         data.get('description', data.get('desc', '')), data.get('category', data.get('cat', '')),
         data.get('subcategory', data.get('subcat', '')), data.get('cost', 0) or 0,
         data.get('serial', ''), data.get('ip', ''), data.get('location', data.get('loc', '')),
         data.get('audit_notes', data.get('auditNotes', '')),
         json.dumps(data.get('units', {})), json.dumps(data.get('unit_details', data.get('details', {})))))
    db.commit()
    item_id = cur.lastrowid
    if 'show_allocations' in data:
        set_item_shows(item_id, data['show_allocations'])
    if 'space_allocations' in data:
        set_item_spaces(item_id, data['space_allocations'])
    db.close()
    return item_id


def update_item(item_id, data):
    db = get_db()
    fields = []
    values = []
    field_map = {
        'line': 'line', 'qty': 'qty', 'make': 'make', 'model': 'model',
        'description': 'description', 'desc': 'description',
        'category': 'category', 'cat': 'category',
        'subcategory': 'subcategory', 'subcat': 'subcategory',
        'cost': 'cost', 'serial': 'serial', 'ip': 'ip',
        'location': 'location', 'loc': 'location',
        'audit_notes': 'audit_notes', 'auditNotes': 'audit_notes',
    }
    for js_key, db_key in field_map.items():
        if js_key in data:
            fields.append(f'{db_key}=?')
            values.append(data[js_key])
    if 'units' in data:
        fields.append('units_json=?')
        values.append(json.dumps(data['units']))
    if 'unit_details' in data or 'details' in data:
        fields.append('unit_details_json=?')
        values.append(json.dumps(data.get('unit_details', data.get('details', {}))))
    if fields:
        fields.append("updated_at=datetime('now')")
        values.append(item_id)
        db.execute(f'UPDATE inventory_items SET {",".join(fields)} WHERE id=?', values)
        db.commit()
    db.close()
    if 'show_allocations' in data:
        set_item_shows(item_id, data['show_allocations'])
    if 'space_allocations' in data:
        set_item_spaces(item_id, data['space_allocations'])


def soft_delete_item(item_id):
    """Mark an item deleted without removing it, so it can be restored."""
    db = get_db()
    db.execute("UPDATE inventory_items SET deleted_at=datetime('now') WHERE id=?", (item_id,))
    db.commit()
    db.close()


def restore_item(item_id):
    """Undo a soft-delete."""
    db = get_db()
    db.execute("UPDATE inventory_items SET deleted_at='' WHERE id=?", (item_id,))
    db.commit()
    db.close()


def purge_item(item_id):
    """Permanent hard delete — only for actually clearing out old soft-deleted rows."""
    db = get_db()
    db.execute('DELETE FROM inventory_item_shows WHERE item_id=?', (item_id,))
    db.execute('DELETE FROM inventory_item_spaces WHERE item_id=?', (item_id,))
    db.execute('DELETE FROM inventory_items WHERE id=?', (item_id,))
    db.commit()
    db.close()


def get_item_shows(item_id):
    db = get_db()
    rows = db.execute('SELECT show_id, qty, notes FROM inventory_item_shows WHERE item_id=?', (item_id,)).fetchall()
    db.close()
    return {r['show_id']: {'qty': r['qty'], 'notes': r['notes']} for r in rows}


def set_item_shows(item_id, show_map):
    """Replace all per-show allocations for an item with the given
    {show_id: {'qty':int,'notes':str}} map."""
    db = get_db()
    db.execute('DELETE FROM inventory_item_shows WHERE item_id=?', (item_id,))
    for show_id, v in (show_map or {}).items():
        qty = v.get('qty', 0) if isinstance(v, dict) else v
        notes = v.get('notes', '') if isinstance(v, dict) else ''
        if qty or notes:
            db.execute('INSERT INTO inventory_item_shows (item_id, show_id, qty, notes) VALUES (?,?,?,?)',
                       (item_id, show_id, qty, notes))
    db.commit()
    db.close()


def get_item_spaces(item_id):
    db = get_db()
    rows = db.execute('SELECT space_id, qty, notes FROM inventory_item_spaces WHERE item_id=?', (item_id,)).fetchall()
    db.close()
    return {r['space_id']: {'qty': r['qty'], 'notes': r['notes']} for r in rows}


def set_item_spaces(item_id, space_map):
    """Replace all per-space allocations for an item with the given
    {space_id: {'qty':int,'notes':str}} map."""
    db = get_db()
    db.execute('DELETE FROM inventory_item_spaces WHERE item_id=?', (item_id,))
    for space_id, v in (space_map or {}).items():
        qty = v.get('qty', 0) if isinstance(v, dict) else v
        notes = v.get('notes', '') if isinstance(v, dict) else ''
        if qty or notes:
            db.execute('INSERT INTO inventory_item_spaces (item_id, space_id, qty, notes) VALUES (?,?,?,?)',
                       (item_id, space_id, qty, notes))
    db.commit()
    db.close()


# ══════════════════════════════════
# SHOWS CRUD
# ══════════════════════════════════

def get_all_shows():
    db = get_db()
    rows = db.execute('SELECT * FROM shows ORDER BY name').fetchall()
    db.close()
    return [dict(r) for r in rows]


def create_show(data):
    db = get_db()
    db.execute('INSERT INTO shows (id, name, space, archived, load_in, open_date, close_date) VALUES (?,?,?,?,?,?,?)',
        (data['id'], data['name'], data.get('space', 'general'),
         data.get('archived', 0), data.get('load_in', ''),
         data.get('open_date', ''), data.get('close_date', '')))
    db.commit()
    db.close()


def update_show(show_id, data):
    db = get_db()
    fields = []
    values = []
    for key in ['name', 'space', 'archived', 'load_in', 'open_date', 'close_date']:
        if key in data:
            fields.append(f'{key}=?')
            values.append(data[key])
    if fields:
        values.append(show_id)
        db.execute(f'UPDATE shows SET {",".join(fields)} WHERE id=?', values)
        db.commit()
    db.close()


def delete_show(show_id):
    db = get_db()
    db.execute('DELETE FROM shows WHERE id=?', (show_id,))
    db.commit()
    db.close()


# ══════════════════════════════════
# CATEGORIES CRUD
# ══════════════════════════════════

def get_all_categories():
    db = get_db()
    rows = db.execute('SELECT * FROM categories ORDER BY name').fetchall()
    db.close()
    return [dict(r) for r in rows]


def create_category(data):
    db = get_db()
    db.execute('INSERT INTO categories (id, name) VALUES (?,?)',
        (data['id'], data['name']))
    db.commit()
    db.close()


def delete_category(cat_id):
    db = get_db()
    db.execute('DELETE FROM categories WHERE id=?', (cat_id,))
    db.commit()
    db.close()


# ══════════════════════════════════
# TASKS CRUD
# ══════════════════════════════════

def get_all_tasks():
    db = get_db()
    rows = db.execute('SELECT * FROM tasks ORDER BY sort_order, created_at').fetchall()
    db.close()
    return [dict(r) for r in rows]


def create_task(data, created_by=None, created_by_name=''):
    db = get_db()
    task_id = data.get('id') or str(uuid.uuid4())[:12]
    db.execute('''INSERT INTO tasks (id, text, space, show_id, priority, urgency, due_date, notes, done, sort_order, created_by, created_by_name)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
        (task_id, data.get('text', ''), data.get('space', 'general'),
         data.get('show', ''), data.get('pri', 'none'),
         data.get('urg', 'soon'), data.get('date', ''),
         data.get('notes', ''), 0, data.get('sort_order', 0),
         created_by, created_by_name))
    db.commit()
    db.close()
    return task_id


def clear_done_tasks(space=None, show_id=None):
    """Delete all done tasks, optionally scoped to a space/show. Returns count deleted."""
    db = get_db()
    query = 'SELECT id FROM tasks WHERE done=1'
    params = []
    if space:
        query += ' AND space=?'
        params.append(space)
    if show_id:
        query += ' AND show_id=?'
        params.append(show_id)
    ids = [r['id'] for r in db.execute(query, params).fetchall()]
    if ids:
        db.executemany('DELETE FROM tasks WHERE id=?', [(i,) for i in ids])
        db.commit()
    db.close()
    return len(ids)


def update_task(task_id, data):
    db = get_db()
    fields = []
    values = []
    field_map = {
        'text': 'text', 'space': 'space', 'show': 'show_id',
        'pri': 'priority', 'urg': 'urgency', 'date': 'due_date',
        'notes': 'notes', 'done': 'done', 'sort_order': 'sort_order'
    }
    for js_key, db_key in field_map.items():
        if js_key in data:
            fields.append(f'{db_key}=?')
            values.append(data[js_key])
    if fields:
        fields.append("updated_at=datetime('now')")
        values.append(task_id)
        db.execute(f'UPDATE tasks SET {",".join(fields)} WHERE id=?', values)
        db.commit()
    db.close()


def delete_task(task_id):
    db = get_db()
    db.execute('DELETE FROM tasks WHERE id=?', (task_id,))
    db.commit()
    db.close()


def reorder_tasks(task_ids):
    """Update sort_order based on provided ID list."""
    db = get_db()
    for i, tid in enumerate(task_ids):
        db.execute('UPDATE tasks SET sort_order=? WHERE id=?', (i, tid))
    db.commit()
    db.close()


# ══════════════════════════════════
# JOURNAL CRUD
# ══════════════════════════════════

def get_all_journal():
    db = get_db()
    rows = db.execute('SELECT * FROM journal_entries ORDER BY date DESC').fetchall()
    db.close()
    return [dict(r) for r in rows]


def create_journal(data):
    db = get_db()
    db.execute('''INSERT INTO journal_entries (id, date, body, author, hours, total_hours)
        VALUES (?,?,?,?,?,?)''',
        (data['id'], data['date'], data['body'], data.get('author', 'Matthew'),
         json.dumps(data.get('hours', {})), data.get('totalHours', 0)))
    db.commit()
    db.close()


def update_journal(entry_id, data):
    db = get_db()
    db.execute('''UPDATE journal_entries SET date=?, body=?, author=?, hours=?, total_hours=?,
        updated_at=datetime('now') WHERE id=?''',
        (data['date'], data['body'], data.get('author', 'Matthew'),
         json.dumps(data.get('hours', {})),
         data.get('totalHours', 0), entry_id))
    db.commit()
    db.close()


def delete_journal(entry_id):
    db = get_db()
    db.execute('DELETE FROM journal_entries WHERE id=?', (entry_id,))
    db.commit()
    db.close()


# ══════════════════════════════════
# TEAM MEMBERS CRUD
# ══════════════════════════════════

def get_team():
    db = get_db()
    rows = db.execute('SELECT * FROM team_members ORDER BY archived, name').fetchall()
    db.close()
    return [dict(r) for r in rows]


def create_team_member(name, color='#888078'):
    db = get_db()
    try:
        db.execute('INSERT INTO team_members (name, color) VALUES (?,?)', (name, color))
        db.commit()
    except:
        db.close()
        return False  # Duplicate name
    db.close()
    return True


def update_team_member(member_id, data):
    db = get_db()
    fields = []
    values = []
    for key in ['name', 'color', 'archived']:
        if key in data:
            fields.append(f'{key}=?')
            values.append(data[key])
    if fields:
        values.append(member_id)
        db.execute(f'UPDATE team_members SET {",".join(fields)} WHERE id=?', values)
        db.commit()
    db.close()


def delete_team_member(member_id):
    """Delete a team member and all their journal entries and hours."""
    db = get_db()
    row = db.execute('SELECT name FROM team_members WHERE id=?', (member_id,)).fetchone()
    if row:
        name = row['name']
        db.execute('DELETE FROM journal_entries WHERE author=?', (name,))
        db.execute('DELETE FROM hours_log WHERE author=?', (name,))
        db.execute('DELETE FROM team_members WHERE id=?', (member_id,))
        db.commit()
    db.close()


def archive_team_member(member_id):
    db = get_db()
    db.execute('UPDATE team_members SET archived=1 WHERE id=?', (member_id,))
    db.commit()
    db.close()


def unarchive_team_member(member_id):
    db = get_db()
    db.execute('UPDATE team_members SET archived=0 WHERE id=?', (member_id,))
    db.commit()
    db.close()


# ══════════════════════════════════
# HOURS LOG CRUD
# ══════════════════════════════════

def get_hours(author=None, date_from=None, date_to=None):
    db = get_db()
    query = 'SELECT * FROM hours_log WHERE 1=1'
    params = []
    if author:
        query += ' AND author=?'
        params.append(author)
    if date_from:
        query += ' AND date>=?'
        params.append(date_from)
    if date_to:
        query += ' AND date<=?'
        params.append(date_to)
    query += ' ORDER BY date DESC, space'
    rows = db.execute(query, params).fetchall()
    db.close()
    return [dict(r) for r in rows]


def set_hours(author, date, space, hours):
    """Upsert hours for a specific author/date/space."""
    db = get_db()
    if hours and float(hours) > 0:
        db.execute('''INSERT INTO hours_log (author, date, space, hours)
            VALUES (?,?,?,?)
            ON CONFLICT(author, date, space)
            DO UPDATE SET hours=?, updated_at=datetime('now')''',
            (author, date, space, float(hours), float(hours)))
    else:
        db.execute('DELETE FROM hours_log WHERE author=? AND date=? AND space=?',
            (author, date, space))
    db.commit()
    db.close()


def get_hours_week(author, week_start):
    """Get hours for a full week starting from week_start (Monday)."""
    from datetime import timedelta
    start = datetime.strptime(week_start, '%Y-%m-%d')
    end = start + timedelta(days=6)
    return get_hours(author, week_start, end.strftime('%Y-%m-%d'))


# ══════════════════════════════════
# LAST MODIFIED (for smart polling)
# ══════════════════════════════════

def get_last_modified():
    """Return the most recent updated_at across tasks, journal, and shows."""
    db = get_db()
    row = db.execute('''
        SELECT MAX(ts) as latest FROM (
            SELECT MAX(updated_at) as ts FROM tasks
            UNION ALL
            SELECT MAX(updated_at) as ts FROM journal_entries
            UNION ALL
            SELECT MAX(updated_at) as ts FROM hours_log
            UNION ALL
            SELECT MAX(created_at) as ts FROM shows
        )
    ''').fetchone()
    db.close()
    return row['latest'] if row and row['latest'] else ''


# ══════════════════════════════════
# BULK IMPORT / EXPORT
# ══════════════════════════════════

def export_all():
    """Export all data as a dict for JSON backup."""
    items = list_items(include_deleted=True)
    for item in items:
        item['show_allocations'] = get_item_shows(item['id'])
        item['space_allocations'] = get_item_spaces(item['id'])

    journal = get_all_journal()
    for entry in journal:
        if isinstance(entry.get('hours'), str):
            try:
                entry['hours'] = json.loads(entry['hours'])
            except:
                entry['hours'] = {}

    return {
        'version': 3,
        'type': 'audit_suite_backup',
        'exported': datetime.now().isoformat(),
        'inventory': items,
        'shows': get_all_shows(),
        'categories': get_all_categories(),
        'tasks': get_all_tasks(),
        'journal': journal,
    }


def _merge_qty_notes(qty_map, notes_map):
    """The Inventory tool's own localStorage JSON export stores per-show/
    per-space qty and notes as two SEPARATE parallel objects (showQty:
    {id:number}, showNotes:{id:string}) rather than nested together —
    verified against templates/tools/inventory.html's saveItem(). Merge
    them into the {id:{'qty':...,'notes':...}} shape the rest of this app
    (and this app's own /api/backup export) uses."""
    out = {}
    for k in set((qty_map or {}).keys()) | set((notes_map or {}).keys()):
        out[k] = {'qty': (qty_map or {}).get(k, 0) or 0, 'notes': (notes_map or {}).get(k, '') or ''}
    return out


def import_inventory(data):
    """Import inventory items from a JSON backup (either this app's own
    /api/backup export, or the Inventory tool's legacy localStorage export
    shape — field names and the showQty/showNotes split are matched
    defensively across both)."""
    db = get_db()
    # Clear existing
    db.execute('DELETE FROM inventory_item_shows')
    db.execute('DELETE FROM inventory_item_spaces')
    db.execute('DELETE FROM inventory_items')
    db.execute('DELETE FROM shows')
    db.execute('DELETE FROM categories')
    db.commit()
    db.close()

    # Import items (uses create_item so show/space allocations get inserted
    # into their own tables via the normal helper functions)
    items = data.get('items', data.get('inventory', []))
    for item in items:
        if 'showQty' in item or 'showNotes' in item:
            show_alloc = _merge_qty_notes(item.get('showQty'), item.get('showNotes'))
        else:
            show_alloc = item.get('showAllocations') or item.get('show_allocations') or {}
        if 'spaceQty' in item or 'spaceNotes' in item:
            space_alloc = _merge_qty_notes(item.get('spaceQty'), item.get('spaceNotes'))
        else:
            space_alloc = item.get('spaceAllocations') or item.get('space_allocations') or {}
        create_item({
            'line': item.get('line', 0),
            'qty': item.get('qty', 0),
            'make': item.get('make', ''),
            'model': item.get('model', ''),
            'desc': item.get('desc', item.get('description', '')),
            'cat': item.get('cat', item.get('category', '')),
            'subcat': item.get('subcat', item.get('subcategory', '')),
            'cost': item.get('cost', 0) or 0,
            'serial': item.get('serial', ''),
            'ip': item.get('ip', ''),
            'loc': item.get('loc', item.get('location', '')),
            'auditNotes': item.get('auditNotes', item.get('audit_notes', '')),
            'units': item.get('units', {}),
            'details': item.get('details', item.get('unit_details', {})),
            'show_allocations': show_alloc if isinstance(show_alloc, dict) else {},
            'space_allocations': space_alloc if isinstance(space_alloc, dict) else {},
        })

    db = get_db()
    # Import shows
    shows = data.get('shows', [])
    for show in shows:
        db.execute('INSERT OR IGNORE INTO shows (id, name, space, archived, load_in, open_date, close_date) VALUES (?,?,?,?,?,?,?)',
            (show.get('id', ''), show.get('name', ''),
             show.get('space', 'general'),
             1 if show.get('archived') else 0,
             show.get('loadIn', show.get('load_in', '')),
             show.get('openDate', show.get('open_date', '')),
             show.get('closeDate', show.get('close_date', ''))))

    # Import categories
    cats = data.get('cats', data.get('categories', []))
    for cat in cats:
        if isinstance(cat, str):
            db.execute('INSERT OR IGNORE INTO categories (id, name) VALUES (?,?)', (cat, cat))
        elif isinstance(cat, dict):
            db.execute('INSERT OR IGNORE INTO categories (id, name) VALUES (?,?)',
                (cat.get('id', cat.get('name', '')), cat.get('name', '')))

    db.commit()
    db.close()
    return len(items)


def import_inventory_from_tool_export(payload):
    """One-time migration: load real inventory data from the Inventory
    tool's own localStorage JSON export (the 'JSON backup' button —
    {version, items, shows}) into the database.

    Deliberately NOT the same as import_inventory() above: this does not
    touch the shows/categories tables at all. Those are owned by the Task
    Manager app and already contain the real, live show records — the
    Inventory tool's 'shows' array is a separate local copy with different
    IDs (its own 's1'/'s2'/... scheme) and even a couple of fields (season)
    the shared table doesn't have. Overwriting the shared table with that
    copy would be actively destructive.

    IMPORTANT: show allocations are stored keyed by the Inventory tool's
    OWN local show IDs (its 's1'/'s2'/... scheme from the 'shows' array in
    the export payload) — NOT translated to the Task Manager's real shows
    table IDs. This matters because every bit of client-side UI that reads
    show allocations (the production rows in the edit modal, show filters,
    scopeRows/print reports) looks items up via S.shows, which is loaded
    from the tool's OWN local show list, entirely independent of the
    shared shows table. Translating to the "real" show ID would silently
    break every one of those lookups, even though the data looks fine in
    the database — this was tried once and caused exactly that bug.
    """
    # Idempotent: clear any previously-imported inventory rows so re-running
    # this (e.g. after fixing a show-name mismatch) doesn't duplicate items.
    # Safe — this only touches inventory_items/_shows/_spaces, never shows.
    db = get_db()
    db.execute('DELETE FROM inventory_item_shows')
    db.execute('DELETE FROM inventory_item_spaces')
    db.execute('DELETE FROM inventory_items')
    db.commit()
    db.close()

    items = payload.get('items', [])
    imported = 0

    for item in items:
        # Keep the tool's own local show IDs as-is — see docstring above.
        show_alloc = _merge_qty_notes(item.get('showQty'), item.get('showNotes'))
        space_alloc = _merge_qty_notes(item.get('spaceQty'), item.get('spaceNotes'))

        create_item({
            'line': item.get('line', 0),
            'qty': item.get('qty', 0),
            'make': item.get('make', ''),
            'model': item.get('model', ''),
            'desc': item.get('desc', ''),
            'cat': item.get('cat', ''),
            'subcat': item.get('subcat', ''),
            'cost': _safe_float(item.get('cost')),
            'serial': item.get('serial', ''),
            'ip': item.get('ip', ''),
            'loc': item.get('loc', ''),
            'auditNotes': item.get('auditNotes', ''),
            'units': item.get('units', {}),
            'details': item.get('details', {}),
            'show_allocations': show_alloc,
            'space_allocations': space_alloc,
        })
        imported += 1

    return {'items_imported': imported, 'unmatched_shows': {}}


def _safe_float(v):
    try:
        return float(v) if v not in (None, '') else 0.0
    except (TypeError, ValueError):
        return 0.0


def list_all_shows_raw():
    db = get_db()
    rows = db.execute('SELECT id, name FROM shows').fetchall()
    db.close()
    return [dict(r) for r in rows]


def import_tasks(data):
    """Import tasks from legacy JSON or app backup."""
    db = get_db()
    db.execute('DELETE FROM tasks')
    db.execute('DELETE FROM journal_entries')

    tasks = data.get('tasks', [])
    for i, task in enumerate(tasks):
        db.execute('''INSERT INTO tasks (id, text, space, show_id, priority, urgency, due_date, notes, done, sort_order)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (task.get('id', ''), task.get('text', ''),
             task.get('space', 'general'),
             task.get('show', task.get('show_id', '')),
             task.get('pri', task.get('priority', 'none')),
             task.get('urg', task.get('urgency', 'soon')),
             task.get('date', task.get('due_date', '')),
             task.get('notes', ''),
             1 if task.get('done') else 0,
             task.get('sort_order', i)))

    journal = data.get('journal', [])
    for entry in journal:
        db.execute('''INSERT INTO journal_entries (id, date, body, author, hours, total_hours)
            VALUES (?,?,?,?,?,?)''',
            (entry.get('id', ''), entry.get('date', ''),
             entry.get('body', ''), entry.get('author', 'Matthew'),
             json.dumps(entry.get('hours', {})),
             entry.get('totalHours', entry.get('total_hours', 0))))

    # Also import shows if present
    shows = data.get('shows', [])
    for show in shows:
        db.execute('INSERT OR IGNORE INTO shows (id, name, space, archived) VALUES (?,?,?,?)',
            (show.get('id', ''), show.get('name', ''),
             show.get('space', 'general'),
             1 if show.get('archived') else 0))

    db.commit()
    db.close()
    return len(tasks)


# ══════════════════════════════════
# USERS / AUTH
# ══════════════════════════════════

def get_user_by_email(email):
    db = get_db()
    row = db.execute('SELECT * FROM users WHERE email=? COLLATE NOCASE', (email.strip(),)).fetchone()
    db.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    db = get_db()
    row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def list_users():
    db = get_db()
    rows = db.execute('''SELECT id, email, name, role, is_active, created_at, last_login_at
        FROM users ORDER BY is_active DESC, name''').fetchall()
    db.close()
    return [dict(r) for r in rows]


def create_user(email, name, password_hash, role='user'):
    db = get_db()
    cur = db.execute('INSERT INTO users (email, name, password_hash, role) VALUES (?,?,?,?)',
        (email.lower().strip(), name.strip(), password_hash, role))
    db.commit()
    user_id = cur.lastrowid
    db.close()
    return user_id


def update_user_password(user_id, password_hash):
    db = get_db()
    db.execute('UPDATE users SET password_hash=? WHERE id=?', (password_hash, user_id))
    db.commit()
    db.close()


def set_user_role(user_id, role):
    db = get_db()
    db.execute('UPDATE users SET role=? WHERE id=?', (role, user_id))
    db.commit()
    db.close()


def set_user_active(user_id, active):
    db = get_db()
    db.execute('UPDATE users SET is_active=? WHERE id=?', (1 if active else 0, user_id))
    db.commit()
    db.close()


def touch_last_login(user_id):
    db = get_db()
    db.execute("UPDATE users SET last_login_at=datetime('now') WHERE id=?", (user_id,))
    db.commit()
    db.close()


# ══════════════════════════════════
# INVITE TOKENS
# ══════════════════════════════════

def create_invite_token(token, email, name, role, invited_by, expires_at):
    db = get_db()
    db.execute('''INSERT INTO invite_tokens (token, email, name, role, invited_by, expires_at)
        VALUES (?,?,?,?,?,?)''', (token, email.lower().strip(), name.strip(), role, invited_by, expires_at))
    db.commit()
    db.close()


def get_invite_token(token):
    db = get_db()
    row = db.execute('SELECT * FROM invite_tokens WHERE token=?', (token,)).fetchone()
    db.close()
    return dict(row) if row else None


def mark_invite_used(token):
    db = get_db()
    db.execute("UPDATE invite_tokens SET used_at=datetime('now') WHERE token=?", (token,))
    db.commit()
    db.close()


def delete_invite_token(token):
    """Cancel/remove a pending invite so it no longer shows up or can be accepted."""
    db = get_db()
    db.execute('DELETE FROM invite_tokens WHERE token=?', (token,))
    db.commit()
    db.close()


def get_pending_invites():
    db = get_db()
    rows = db.execute('''SELECT * FROM invite_tokens
        WHERE used_at='' AND expires_at > datetime('now') ORDER BY created_at DESC''').fetchall()
    db.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════
# PASSWORD RESET TOKENS
# ══════════════════════════════════

def create_reset_token(token, user_id, expires_at):
    db = get_db()
    db.execute('INSERT INTO password_reset_tokens (token, user_id, expires_at) VALUES (?,?,?)',
        (token, user_id, expires_at))
    db.commit()
    db.close()


def get_reset_token(token):
    db = get_db()
    row = db.execute('SELECT * FROM password_reset_tokens WHERE token=?', (token,)).fetchone()
    db.close()
    return dict(row) if row else None


def mark_reset_used(token):
    db = get_db()
    db.execute("UPDATE password_reset_tokens SET used_at=datetime('now') WHERE token=?", (token,))
    db.commit()
    db.close()


def invalidate_user_reset_tokens(user_id):
    """Invalidate any outstanding reset tokens for a user (call after a successful reset)."""
    db = get_db()
    db.execute("UPDATE password_reset_tokens SET used_at=datetime('now') WHERE user_id=? AND used_at=''", (user_id,))
    db.commit()
    db.close()


# ══════════════════════════════════
# AUDIT LOG
# ══════════════════════════════════

def log_action(actor_id, actor_name, action, target='', detail=''):
    db = get_db()
    db.execute('INSERT INTO audit_log (actor_id, actor_name, action, target, detail) VALUES (?,?,?,?,?)',
        (actor_id, actor_name, action, target, detail))
    db.commit()
    db.close()


def get_audit_log(limit=200):
    db = get_db()
    rows = db.execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    db.close()
    return [dict(r) for r in rows]
