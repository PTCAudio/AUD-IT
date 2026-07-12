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
from flask import (Flask, request, jsonify, render_template,
                   redirect, url_for, session, send_file)
from dotenv import load_dotenv
import models
import auth
import email_utils

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me')
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

login_required = auth.login_required
admin_required = auth.admin_required
require_api_key_or_session = auth.require_api_key_or_session

# Generic message shown regardless of whether an email is registered,
# so /forgot-password can't be used to enumerate accounts.
FORGOT_PASSWORD_GENERIC_MSG = 'If an account exists for that email, a reset link is on its way.'

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = models.get_user_by_email(email)
        if user and user['is_active'] and auth.verify_password(password, user['password_hash']):
            auth.log_in_user(user)
            models.log_action(user['id'], user['name'], 'login')
            return redirect(request.args.get('next') or url_for('tasks'))
        error = 'Invalid email or password'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    user = auth.current_user()
    if user:
        models.log_action(user['id'], user['name'], 'logout')
    session.clear()
    return redirect(url_for('login'))

@app.route('/accept-invite/<token>', methods=['GET', 'POST'])
def accept_invite(token):
    invite = auth.validate_invite(token)
    if not invite:
        return render_template('token_invalid.html', reason='invite')

    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        if len(password) < 8:
            error = 'Password must be at least 8 characters.'
        elif password != confirm:
            error = 'Passwords do not match.'
        else:
            existing = models.get_user_by_email(invite['email'])
            if existing:
                error = 'An account with this email already exists. Try logging in or resetting your password.'
            else:
                user_id = models.create_user(invite['email'], invite['name'],
                                              auth.hash_password(password), invite['role'])
                models.mark_invite_used(token)
                models.log_action(user_id, invite['name'], 'account_created', detail=f"via invite from user {invite['invited_by']}")
                user = models.get_user_by_id(user_id)
                auth.log_in_user(user)
                return redirect(url_for('tasks'))
    return render_template('accept_invite.html', invite=invite, error=error)

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    message = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = models.get_user_by_email(email)
        if user and user['is_active']:
            token = auth.create_password_reset(user['id'])
            email_utils.send_password_reset_email(user['email'], user['name'], token)
            models.log_action(user['id'], user['name'], 'password_reset_requested')
        # Same message whether or not the account exists.
        message = FORGOT_PASSWORD_GENERIC_MSG
    return render_template('forgot_password.html', message=message)

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    reset = auth.validate_reset_token(token)
    if not reset:
        return render_template('token_invalid.html', reason='reset')

    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        if len(password) < 8:
            error = 'Password must be at least 8 characters.'
        elif password != confirm:
            error = 'Passwords do not match.'
        else:
            models.update_user_password(reset['user_id'], auth.hash_password(password))
            models.mark_reset_used(token)
            models.invalidate_user_reset_tokens(reset['user_id'])
            user = models.get_user_by_id(reset['user_id'])
            models.log_action(user['id'], user['name'], 'password_reset_completed')
            auth.log_in_user(user)
            return redirect(url_for('tasks'))
    return render_template('reset_password.html', error=error)

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
    user = auth.current_user()
    return render_template('tasks.html', active='tasks', current_user=user)

@app.route('/admin/users')
@admin_required
def admin_users_page():
    return render_template('admin_users.html', users=models.list_users(),
                            invites=models.get_pending_invites())

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
    user = auth.current_user()
    created_by = user['id'] if user else None
    created_by_name = user['name'] if user else ''
    task_id = models.create_task(data, created_by=created_by, created_by_name=created_by_name)
    return jsonify({'status': 'created', 'id': task_id}), 201

@app.route('/api/tasks/clear-done', methods=['POST'])
@admin_required
def api_clear_done_tasks():
    data = request.get_json(silent=True) or {}
    space = sanitize(data.get('space', ''), 50) or None
    show_id = sanitize(data.get('show', ''), 50) or None
    count = models.clear_done_tasks(space=space, show_id=show_id)
    user = auth.current_user()
    models.log_action(user['id'], user['name'], 'clear_done_tasks', detail=f'{count} tasks, space={space}, show={show_id}')
    return jsonify({'status': 'cleared', 'count': count})

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
# API — USER MANAGEMENT (admin only)
# ══════════════════════════════════

@app.route('/api/users', methods=['GET'])
@admin_required
def api_list_users():
    return jsonify(models.list_users())

@app.route('/api/users/invite', methods=['POST'])
@admin_required
def api_invite_user():
    data = request.get_json() or {}
    email = sanitize(data.get('email', ''), 120)
    name = sanitize(data.get('name', ''), 50)
    role = data.get('role', 'user') if data.get('role') in ('admin', 'user') else 'user'

    if not email or '@' not in email:
        return jsonify({'error': 'Valid email required'}), 400
    if not name:
        return jsonify({'error': 'Name required'}), 400
    if models.get_user_by_email(email):
        return jsonify({'error': 'A user with this email already exists'}), 409

    admin = auth.current_user()
    token = auth.create_invite(email, name, role, admin['id'])
    email_utils.send_invite_email(email, name, token)
    models.log_action(admin['id'], admin['name'], 'invite_sent', target=email, detail=f'role={role}')
    return jsonify({'status': 'invited'}), 201

@app.route('/api/users/invite/<token>', methods=['DELETE'])
@admin_required
def api_cancel_invite(token):
    invite = models.get_invite_token(token)
    if not invite:
        return jsonify({'error': 'Invite not found'}), 404
    models.delete_invite_token(token)
    admin = auth.current_user()
    models.log_action(admin['id'], admin['name'], 'invite_cancelled', target=invite['email'])
    return jsonify({'status': 'cancelled'})

@app.route('/api/users/<int:user_id>/role', methods=['PUT'])
@admin_required
def api_set_user_role(user_id):
    data = request.get_json() or {}
    role = data.get('role')
    if role not in ('admin', 'user'):
        return jsonify({'error': 'Role must be admin or user'}), 400
    admin = auth.current_user()
    if user_id == admin['id'] and role != 'admin':
        return jsonify({'error': "You can't remove your own admin access"}), 400
    models.set_user_role(user_id, role)
    models.log_action(admin['id'], admin['name'], 'role_changed', target=str(user_id), detail=role)
    return jsonify({'status': 'updated'})

@app.route('/api/users/<int:user_id>/active', methods=['PUT'])
@admin_required
def api_set_user_active(user_id):
    data = request.get_json() or {}
    active = bool(data.get('active', True))
    admin = auth.current_user()
    if user_id == admin['id'] and not active:
        return jsonify({'error': "You can't deactivate your own account"}), 400
    models.set_user_active(user_id, active)
    models.log_action(admin['id'], admin['name'], 'active' if active else 'deactivated', target=str(user_id))
    return jsonify({'status': 'updated'})

@app.route('/api/audit-log', methods=['GET'])
@admin_required
def api_audit_log():
    return jsonify(models.get_audit_log())

# ══════════════════════════════════
# KNOWLEDGE BASE
# ══════════════════════════════════

MAX_KB_BODY = 300000  # generous — some Wiki pages (e.g. TOC-indexed manuals) run long

def validate_kb_page(data):
    slug = str(data.get('slug', '')).strip()[:120]
    if not slug or not all(c.isalnum() or c in '-_' for c in slug):
        return None
    return {
        'slug': slug,
        'title': sanitize(data.get('title', slug), 200),
        'section': sanitize(data.get('section', ''), 50),
        'body_markdown': str(data.get('body_markdown', ''))[:MAX_KB_BODY],
        'tags': data.get('tags', []) if isinstance(data.get('tags', []), list) else [],
        'source_files': data.get('source_files', []) if isinstance(data.get('source_files', []), list) else [],
    }

@app.route('/kb')
@login_required
def kb_index():
    return render_template('kb_index.html', active='kb', pages=models.list_kb_pages())

@app.route('/kb/<slug>')
@login_required
def kb_page(slug):
    page = models.get_kb_page(slug)
    if not page:
        return render_template('token_invalid.html', reason='kb page not found'), 404
    import markdown as md_lib
    body_html = md_lib.markdown(page['body_markdown'], extensions=['tables', 'fenced_code'])
    return render_template('kb_page.html', active='kb', page=page, body_html=body_html)

@app.route('/api/kb/pages', methods=['POST'])
@require_api_key_or_session
def api_kb_upsert():
    data = request.get_json() or {}
    page = validate_kb_page(data)
    if not page:
        return jsonify({'error': 'Invalid or missing slug'}), 400
    models.upsert_kb_page(
        page['slug'], page['title'], page['section'],
        page['body_markdown'], page['tags'], page['source_files']
    )
    return jsonify({'status': 'ok', 'slug': page['slug']})

@app.route('/api/kb/search', methods=['GET'])
@require_api_key_or_session
def api_kb_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    return jsonify(models.search_kb_pages(q))

# ══════════════════════════════════
# INIT
# ══════════════════════════════════

def bootstrap_admin():
    """One-time: if no users exist yet, create the first admin from env vars.
    Set BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_NAME / BOOTSTRAP_ADMIN_PASSWORD,
    deploy once, then you can remove them — this only fires when users table is empty."""
    if models.list_users():
        return
    email = os.environ.get('BOOTSTRAP_ADMIN_EMAIL', '')
    name = os.environ.get('BOOTSTRAP_ADMIN_NAME', 'Admin')
    password = os.environ.get('BOOTSTRAP_ADMIN_PASSWORD', '')
    if email and password:
        models.create_user(email, name, auth.hash_password(password), role='admin')
        print(f'[bootstrap] Created first admin account: {email}')

with app.app_context():
    models.init_db()
    bootstrap_admin()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
