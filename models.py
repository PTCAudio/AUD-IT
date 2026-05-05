"""
AUD-IT Suite — Database Models
SQLite schema and helper functions for inventory and task management.
"""

import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.environ.get('DATABASE_PATH', 'audit_suite.db')


def get_db():
    """Get a database connection with row_factory for dict-like access."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    """Create all tables if they don't exist."""
    db = get_db()
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
        -- ══════════════════════════════════
        CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qty INTEGER NOT NULL DEFAULT 1,
            make TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            description TEXT DEFAULT '',
            category TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Available',
            location TEXT DEFAULT '',
            unit_cost REAL DEFAULT 0,
            notes TEXT DEFAULT '',
            image TEXT DEFAULT '',
            service_url TEXT DEFAULT '',
            show_allocations TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
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
    ''')
    db.commit()

    # Migrations
    try:
        db.execute("ALTER TABLE journal_entries ADD COLUMN author TEXT NOT NULL DEFAULT 'Matthew'")
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
    ''')
    db.commit()
    db.close()


# ══════════════════════════════════
# INVENTORY CRUD
# ══════════════════════════════════

def get_all_items():
    db = get_db()
    rows = db.execute('SELECT * FROM inventory_items ORDER BY id').fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_item(item_id):
    db = get_db()
    row = db.execute('SELECT * FROM inventory_items WHERE id=?', (item_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def create_item(data):
    db = get_db()
    db.execute('''INSERT INTO inventory_items
        (qty, make, model, description, category, status, location, unit_cost, notes, image, service_url, show_allocations)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
        (data.get('qty', 1), data.get('make', ''), data.get('model', ''),
         data.get('description', ''), data.get('category', ''),
         data.get('status', 'Available'), data.get('location', ''),
         data.get('unit_cost', 0), data.get('notes', ''),
         data.get('image', ''), data.get('service_url', ''),
         json.dumps(data.get('show_allocations', {}))))
    db.commit()
    item_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.close()
    return item_id


def update_item(item_id, data):
    db = get_db()
    fields = []
    values = []
    for key in ['qty', 'make', 'model', 'description', 'category', 'status',
                'location', 'unit_cost', 'notes', 'image', 'service_url']:
        if key in data:
            fields.append(f'{key}=?')
            values.append(data[key])
    if 'show_allocations' in data:
        fields.append('show_allocations=?')
        values.append(json.dumps(data['show_allocations']))
    if fields:
        fields.append("updated_at=datetime('now')")
        values.append(item_id)
        db.execute(f'UPDATE inventory_items SET {",".join(fields)} WHERE id=?', values)
        db.commit()
    db.close()


def delete_item(item_id):
    db = get_db()
    db.execute('DELETE FROM inventory_items WHERE id=?', (item_id,))
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


def create_task(data):
    db = get_db()
    db.execute('''INSERT INTO tasks (id, text, space, show_id, priority, urgency, due_date, notes, done, sort_order)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (data['id'], data['text'], data.get('space', 'general'),
         data.get('show', ''), data.get('pri', 'none'),
         data.get('urg', 'soon'), data.get('date', ''),
         data.get('notes', ''), 0, data.get('sort_order', 0)))
    db.commit()
    db.close()


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
    items = get_all_items()
    # Parse show_allocations back to dict
    for item in items:
        if isinstance(item.get('show_allocations'), str):
            try:
                item['show_allocations'] = json.loads(item['show_allocations'])
            except:
                item['show_allocations'] = {}

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


def import_inventory(data):
    """Import inventory items from legacy JSON backup."""
    db = get_db()
    # Clear existing
    db.execute('DELETE FROM inventory_items')
    db.execute('DELETE FROM shows')
    db.execute('DELETE FROM categories')

    # Import items
    items = data.get('items', [])
    for item in items:
        alloc = item.get('showAllocations', item.get('show_allocations', {}))
        db.execute('''INSERT INTO inventory_items
            (qty, make, model, description, category, status, location, unit_cost, notes, image, service_url, show_allocations)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (item.get('qty', 1), item.get('make', ''), item.get('model', ''),
             item.get('desc', item.get('description', '')),
             item.get('cat', item.get('category', '')),
             item.get('status', 'Available'),
             item.get('loc', item.get('location', '')),
             item.get('cost', item.get('unit_cost', 0)),
             item.get('notes', ''),
             item.get('img', item.get('image', '')),
             item.get('svc', item.get('service_url', '')),
             json.dumps(alloc if isinstance(alloc, dict) else {})))

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
