"""
AUD-IT Tasks — Flask Application
Phoenix Theatre Company — Audio Department
Routes:
  /              → redirects to /tasks
  /login         → password gate
  /tasks         → task manager + journal
  /api/...       → REST API endpoints
"""
import os
import json
import html as html_lib
from functools import wraps
from flask import (Flask, request, jsonify, render_template,
                   redirect, url_for, session, send_file)
from dotenv import load_dotenv
import models

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me')
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'changeme')
API_KEY = os.environ.get('API_KEY', '')

MAX_TEXT = 500
MAX_NOTES = 5000
MAX_BODY = 5000

# ══════════════════════════════════
# INPUT VALIDATION
# ══════════════════════════════════

def sanitize(text, max_len=MAX_TEXT):
    """Strip HTML and enforce length limit."""
    if not text:
        return ''
    text = html_lib.escape(str(text).strip())
    return text[:max_len]

def validate_task(data):
    """Sanitize task input fields."""
    return {
        'id': sanitize(data.get('id', ''), 50),
        'text': sanitize(data.get('text', ''), MAX_TEXT),
        'space': sanitize(data.get('space', 'general'), 50),
        'show': sanitize(data.get('show', data.get('show_id', '')), 50),
        'pri': data.get('pri', data.get('priority', 'none')) if data.get('pri', data.get('priority', 'none')) in ('high','med','low','none') else 'none',
        'urg': data.get('urg', data.get('urgency', 'soon')) if data.get('urg', data.get('urgency', 'soon')) in ('now','today','week','soon','date') else 'soon',
        'date': sanitize(data.get('date', data.get('due_date', '')), 10),
        'notes': sanitize(data.get('notes', ''), MAX_NOTES),
        'done': bool(data.get('done')),
        'sort_order': int(data.get('sort_order', 0)) if str(data.get('sort_order', 0)).isdigit() else 0,
    }

def validate_show(data):
    """Sanitize show input fields."""
    return {
        'id': sanitize(data.get('id', ''), 50),
        'name': sanitize(data.get('name', ''), 100),
        'space': sanitize(data.get('space', 'general'), 50),
        'archived': int(bool(data.get('archived', 0))),
        'load_in': sanitize(data.get('load_in', ''), 10),
        'open_date': sanitize(data.get('open_date', ''), 10),
        'close_date': sanitize(data.get('close_date', ''), 10),
    }

def validate_journal(data):
    """Sanitize journal input fields."""
    return {
        'id': sanitize(data.get('id', ''), 50),
        'date': sanitize(data.get('date', ''), 10),
        'body': sanitize(data.get('body', ''), MAX_BODY),
        'author': sanitize(data.get('author', 'Matthew'), 50),
        'hours': data.get('hours', {}),
        'totalHours': float(data.get('totalHours', data.get('total_hours', 0)) or 0),
    }

# ══════════════════════════════════
# AUTH
# ══════════════════════════════════

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def require_api_key_or_session(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-API-Key')
        if key and API_KEY and key == API_KEY:
            return f(*args, **kwargs)
        if session.get('authenticated'):
            return f(*args, **kwargs)
        return jsonify({'error': 'Unauthorized'}), 401
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == APP_PASSWORD:
            session['authenticated'] = True
            session.permanent = True
            return redirect(request.args.get('next', url_for('tasks')))
        error = 'Wrong password'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ══════════════════════════════════
# PAGES
# ══════════════════════════════════

@app.route('/')
@login_required
def index():
    return redirect(url_for('tasks'))

@app.route('/tasks')
@login_required
def tasks():
    return render_template('tasks.html', active='tasks')

# ══════════════════════════════════
# API — SHOWS
# ══════════════════════════════════

@app.route('/api/shows', methods=['GET'])
@require_api_key_or_session
def api_get_shows():
    return jsonify(models.get_all_shows())

@app.route('/api/shows', methods=['POST'])
@require_api_key_or_session
def api_create_show():
    data = validate_show(request.get_json())
    if not data['name']:
        return jsonify({'error': 'Show name required'}), 400
    models.create_show(data)
    return jsonify({'status': 'created'}), 201

@app.route('/api/shows/<show_id>', methods=['PUT'])
@require_api_key_or_session
def api_update_show(show_id):
    data = request.get_json()
    models.update_show(show_id, data)
    return jsonify({'status': 'updated'})

@app.route('/api/shows/<show_id>', methods=['DELETE'])
@require_api_key_or_session
def api_delete_show(show_id):
    models.delete_show(show_id)
    return jsonify({'status': 'deleted'})

# ══════════════════════════════════
# API — CATEGORIES
# ══════════════════════════════════

@app.route('/api/categories', methods=['GET'])
@require_api_key_or_session
def api_get_categories():
    return jsonify(models.get_all_categories())

@app.route('/api/categories', methods=['POST'])
@require_api_key_or_session
def api_create_category():
    data = request.get_json()
    models.create_category(data)
    return jsonify({'status': 'created'}), 201

@app.route('/api/categories/<cat_id>', methods=['DELETE'])
@require_api_key_or_session
def api_delete_category(cat_id):
    models.delete_category(cat_id)
    return jsonify({'status': 'deleted'})

# ══════════════════════════════════
# API — TASKS
# ══════════════════════════════════

@app.route('/api/tasks', methods=['GET'])
@require_api_key_or_session
def api_get_tasks():
    return jsonify(models.get_all_tasks())

@app.route('/api/tasks', methods=['POST'])
@require_api_key_or_session
def api_create_task():
    data = validate_task(request.get_json())
    if not data['text']:
        return jsonify({'error': 'Task text required'}), 400
    models.create_task(data)
    return jsonify({'status': 'created'}), 201

@app.route('/api/tasks/<task_id>', methods=['PUT'])
@require_api_key_or_session
def api_update_task(task_id):
    data = request.get_json()
    clean = {}
    if 'text' in data: clean['text'] = sanitize(data['text'], MAX_TEXT)
    if 'space' in data: clean['space'] = sanitize(data['space'], 50)
    if 'show' in data: clean['show'] = sanitize(data['show'], 50)
    if 'pri' in data: clean['pri'] = data['pri'] if data['pri'] in ('high','med','low','none') else 'none'
    if 'urg' in data: clean['urg'] = data['urg'] if data['urg'] in ('now','today','week','soon','date') else 'soon'
    if 'date' in data: clean['date'] = sanitize(data['date'], 10)
    if 'notes' in data: clean['notes'] = sanitize(data['notes'], MAX_NOTES)
    if 'done' in data: clean['done'] = data['done']
    if 'sort_order' in data: clean['sort_order'] = data['sort_order']
    models.update_task(task_id, clean)
    return jsonify({'status': 'updated'})

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
@require_api_key_or_session
def api_delete_task(task_id):
    models.delete_task(task_id)
    return jsonify({'status': 'deleted'})

@app.route('/api/tasks/reorder', methods=['POST'])
@require_api_key_or_session
def api_reorder_tasks():
    data = request.get_json()
    models.reorder_tasks(data.get('ids', []))
    return jsonify({'status': 'reordered'})

# ══════════════════════════════════
# API — JOURNAL
# ══════════════════════════════════

@app.route('/api/journal', methods=['GET'])
@require_api_key_or_session
def api_get_journal():
    entries = models.get_all_journal()
    for e in entries:
        if isinstance(e.get('hours'), str):
            try:
                e['hours'] = json.loads(e['hours'])
            except:
                e['hours'] = {}
    return jsonify(entries)

@app.route('/api/journal', methods=['POST'])
@require_api_key_or_session
def api_create_journal():
    data = validate_journal(request.get_json())
    if not data['body']:
        return jsonify({'error': 'Journal body required'}), 400
    models.create_journal(data)
    return jsonify({'status': 'created'}), 201

@app.route('/api/journal/<entry_id>', methods=['PUT'])
@require_api_key_or_session
def api_update_journal(entry_id):
    data = validate_journal(request.get_json())
    models.update_journal(entry_id, data)
    return jsonify({'status': 'updated'})

@app.route('/api/journal/<entry_id>', methods=['DELETE'])
@require_api_key_or_session
def api_delete_journal(entry_id):
    models.delete_journal(entry_id)
    return jsonify({'status': 'deleted'})

# ══════════════════════════════════
# API — TEAM MEMBERS
# ══════════════════════════════════

@app.route('/api/team', methods=['GET'])
@require_api_key_or_session
def api_get_team():
    return jsonify(models.get_team())

@app.route('/api/team', methods=['POST'])
@require_api_key_or_session
def api_create_team():
    data = request.get_json()
    name = sanitize(data.get('name', ''), 50)
    color = sanitize(data.get('color', '#888078'), 10)
    if not name:
        return jsonify({'error': 'Name required'}), 400
    if models.create_team_member(name, color):
        return jsonify({'status': 'created'}), 201
    return jsonify({'error': 'Name already exists'}), 409

@app.route('/api/team/<int:member_id>', methods=['PUT'])
@require_api_key_or_session
def api_update_team(member_id):
    data = request.get_json()
    clean = {}
    if 'name' in data: clean['name'] = sanitize(data['name'], 50)
    if 'color' in data: clean['color'] = sanitize(data['color'], 10)
    if 'archived' in data: clean['archived'] = int(bool(data['archived']))
    models.update_team_member(member_id, clean)
    return jsonify({'status': 'updated'})

@app.route('/api/team/<int:member_id>/archive', methods=['POST'])
@require_api_key_or_session
def api_archive_team(member_id):
    models.archive_team_member(member_id)
    return jsonify({'status': 'archived'})

@app.route('/api/team/<int:member_id>/unarchive', methods=['POST'])
@require_api_key_or_session
def api_unarchive_team(member_id):
    models.unarchive_team_member(member_id)
    return jsonify({'status': 'unarchived'})

@app.route('/api/team/<int:member_id>', methods=['DELETE'])
@require_api_key_or_session
def api_delete_team(member_id):
    models.delete_team_member(member_id)
    return jsonify({'status': 'deleted'})

# ══════════════════════════════════
# API — HOURS LOG
# ══════════════════════════════════

@app.route('/api/hours', methods=['GET'])
@require_api_key_or_session
def api_get_hours():
    author = request.args.get('author')
    date_from = request.args.get('from')
    date_to = request.args.get('to')
    return jsonify(models.get_hours(author, date_from, date_to))

@app.route('/api/hours', methods=['POST'])
@require_api_key_or_session
def api_set_hours():
    data = request.get_json()
    author = sanitize(data.get('author', ''), 50)
    date = sanitize(data.get('date', ''), 10)
    space = sanitize(data.get('space', ''), 50)
    hours = float(data.get('hours', 0) or 0)
    if not author or not date or not space:
        return jsonify({'error': 'Missing fields'}), 400
    models.set_hours(author, date, space, hours)
    return jsonify({'status': 'saved'})

# ══════════════════════════════════
# API — LAST MODIFIED & BACKUP
# ══════════════════════════════════

@app.route('/api/last-modified', methods=['GET'])
@require_api_key_or_session
def api_last_modified():
    """Return the latest updated_at across all tables for smart polling."""
    ts = models.get_last_modified()
    return jsonify({'ts': ts})

@app.route('/api/backup', methods=['GET'])
@require_api_key_or_session
def api_backup():
    data = models.export_all()
    return jsonify(data)

@app.route('/api/restore/tasks', methods=['POST'])
@require_api_key_or_session
def api_restore_tasks():
    data = request.get_json()
    count = models.import_tasks(data)
    return jsonify({'status': 'restored', 'tasks': count})

# ══════════════════════════════════
# INIT
# ══════════════════════════════════

with app.app_context():
    models.init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
