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
import uuid
import html as html_lib
from flask import (Flask, request, jsonify, render_template,
                   redirect, url_for, session, send_file, Response, send_from_directory,
                   abort)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bleach
import models
import auth
import email_utils
import pdf_utils

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me')
API_KEY = os.environ.get('API_KEY', '')
app.config['MAX_CONTENT_LENGTH'] = 150 * 1024 * 1024  # 150MB — vendor gear manuals (RIVAGE PM OM is ~93MB) run far bigger than the riders/guides this was originally sized for

# Session cookie hardening. SESSION_COOKIE_SECURE defaults on (cookie only
# sent over HTTPS, which is all Render traffic anyway) but can be disabled
# via env var for local `python app.py` testing over plain http://localhost.
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() != 'false'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# CSRF protection for the browser-facing HTML forms (login, invite/reset
# password, etc). /api/* routes are exempted below — they're same-origin
# JSON fetch() calls (see static/tasks.js's api() helper), which the
# browser already blocks cross-site via CORS since there's no
# Access-Control-Allow-Origin header, and they're also reachable via a
# machine X-API-Key credential (the MCP server) that has no session/CSRF
# token to send. A CSRF token would break that path without adding real
# protection on top of what CORS already provides for the JSON routes.
csrf = CSRFProtect(app)

limiter = Limiter(get_remote_address, app=app, default_limits=[])


@app.after_request
def _set_security_headers(response):
    """Baseline hardening headers. CSP keeps 'unsafe-inline' for script/style
    because the existing templates rely heavily on inline onclick= handlers
    and inline style= attributes (tasks.html especially) — removing that
    would break the UI outright and isn't worth the risk here. Still blocks
    loading scripts/objects from arbitrary external origins and framing by
    other sites, which is the bulk of the real-world value."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    )
    return response

MAX_TEXT = 500
MAX_NOTES = 5000
MAX_BODY = 5000

# KB pages render markdown -> HTML and display it with |safe (see kb_page()
# below), so the HTML output has to be sanitized first — Python-Markdown
# passes raw HTML straight through untouched, which would otherwise let a
# <script> tag or onclick= handler in a KB page's body execute for anyone
# who views it. bleach strips anything not on this allowlist (tags AND
# attributes) — normal text, quotes, ampersands, etc. are untouched since
# those aren't HTML markup; only actual tags/attributes get filtered.
KB_ALLOWED_TAGS = [
    'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4',
    'strong', 'em', 'b', 'i', 'u', 'del', 'code', 'pre',
    'ul', 'ol', 'li', 'blockquote',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a',
]
KB_ALLOWED_ATTRS = {
    'a': ['href', 'title'],
    'th': ['align'],
    'td': ['align'],
}
KB_ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']

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
        'assignee_id': int(data['assignee_id']) if str(data.get('assignee_id', '')).isdigit() else None,
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
require_api_key_or_admin = auth.require_api_key_or_admin

# Generic message shown regardless of whether an email is registered,
# so /forgot-password can't be used to enumerate accounts.
FORGOT_PASSWORD_GENERIC_MSG = 'If an account exists for that email, a reset link is on its way.'

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
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
@limiter.limit('10 per minute')
def accept_invite(token):
    invite = auth.validate_invite(token)
    if not invite:
        return render_template('token_invalid.html', reason='invite')

    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        pw_error = auth.validate_password(password)
        if pw_error:
            error = pw_error
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
                return redirect(url_for('home_page'))
    return render_template('accept_invite.html', invite=invite, error=error)

@app.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
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
@limiter.limit('10 per minute')
def reset_password(token):
    reset = auth.validate_reset_token(token)
    if not reset:
        return render_template('token_invalid.html', reason='reset')

    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        pw_error = auth.validate_password(password)
        if pw_error:
            error = pw_error
        elif password != confirm:
            error = 'Passwords do not match.'
        else:
            models.update_user_password(reset['user_id'], auth.hash_password(password))
            models.mark_reset_used(token)
            models.invalidate_user_reset_tokens(reset['user_id'])
            user = models.get_user_by_id(reset['user_id'])
            models.log_action(user['id'], user['name'], 'password_reset_completed')
            auth.log_in_user(user)
            return redirect(url_for('home_page'))
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

@app.route('/home')
@login_required
def home_page():
    user = auth.current_user()
    is_admin = bool(user and user.get('role') == 'admin')
    open_tasks = sum(1 for t in models.get_all_tasks() if not t.get('done'))
    return render_template('home.html', is_admin=is_admin,
                            staff_data=models.get_venues_nested('staff'),
                            docs_data=models.list_documents_grouped(),
                            open_tasks=open_tasks)

# ══════════════════════════════════
# DOCUMENTS (riders, system guides, network diagrams, budget/incident PDFs)
# DB-backed (doc_sections/documents in models.py) — files live on the Render
# persistent disk (models.get_docs_storage_dir()), not the git repo, so
# admin upload/delete take effect immediately with no deploy. Served behind
# login, never a public static path.
# ══════════════════════════════════

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')  # legacy git-tracked fallback

@app.route('/docs/file/<int:doc_id>')
@login_required
def docs_file(doc_id):
    doc = models.get_document(doc_id)
    if not doc:
        abort(404)
    storage_dir = models.get_docs_storage_dir()
    full_path = os.path.join(storage_dir, doc['filename'])
    if not os.path.isfile(full_path):
        abort(404)
    download_name = doc['orig_filename'] or (doc['title'] + '.pdf')
    return send_from_directory(storage_dir, doc['filename'], download_name=download_name)

@app.route('/docs/<path:filepath>')
@login_required
def docs_legacy_file(filepath):
    # Kept only for any old bookmarked/shared links to the pre-migration
    # git-tracked paths — new links all go through /docs/file/<id> above.
    full_path = os.path.join(DOCS_DIR, filepath)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(DOCS_DIR, filepath)

ALLOWED_DOC_EXTENSIONS = {'.pdf'}

@app.route('/admin/docs')
@admin_required
def admin_docs_page():
    return render_template('admin_docs.html', active='admin_docs',
                            sections=models.list_documents_grouped())

@app.route('/api/docs/sections', methods=['GET'])
@require_api_key_or_session
def api_list_doc_sections():
    return jsonify(models.list_documents_grouped())

@app.route('/api/docs/sections', methods=['POST'])
@auth.require_api_key_or_admin
def api_create_doc_section():
    data = request.get_json() or {}
    name = sanitize(data.get('name', ''), 80)
    if not name:
        return jsonify({'error': 'Section name required'}), 400
    section_id = models.create_doc_section(name)
    return jsonify({'status': 'created', 'id': section_id}), 201

@app.route('/api/docs/sections/<int:section_id>', methods=['PUT'])
@admin_required
def api_rename_doc_section(section_id):
    data = request.get_json() or {}
    name = sanitize(data.get('name', ''), 80)
    if not name:
        return jsonify({'error': 'Section name required'}), 400
    if not models.get_doc_section(section_id):
        return jsonify({'error': 'Section not found'}), 404
    models.rename_doc_section(section_id, name)
    return jsonify({'status': 'updated'})

@app.route('/api/docs/sections/<int:section_id>', methods=['DELETE'])
@admin_required
def api_delete_doc_section(section_id):
    if not models.get_doc_section(section_id):
        return jsonify({'error': 'Section not found'}), 404
    filenames = models.delete_doc_section(section_id)
    storage_dir = models.get_docs_storage_dir()
    for fn in filenames:
        try:
            os.remove(os.path.join(storage_dir, fn))
        except OSError:
            pass
    return jsonify({'status': 'deleted'})

@app.route('/api/docs/sections/reorder', methods=['POST'])
@admin_required
def api_reorder_doc_sections():
    data = request.get_json() or {}
    order = data.get('order', [])
    if not isinstance(order, list) or not all(isinstance(x, int) for x in order):
        return jsonify({'error': 'order must be a list of section ids'}), 400
    models.reorder_doc_sections(order)
    return jsonify({'status': 'reordered'})

@app.route('/api/docs/upload', methods=['POST'])
@auth.require_api_key_or_admin
def api_upload_doc():
    section_id = request.form.get('section_id', type=int)
    title = sanitize(request.form.get('title', ''), 150)
    file = request.files.get('file')
    # Manuals flag + device name — e.g. is_manual=1, device="Shure AD4Q".
    # Purely additive: existing riders/guides callers that don't send these
    # keep working exactly as before (is_manual defaults to 0).
    is_manual = request.form.get('is_manual', '0') in ('1', 'true', 'True')
    device = sanitize(request.form.get('device', ''), 120)

    if not section_id or not models.get_doc_section(section_id):
        return jsonify({'error': 'Valid section_id required'}), 400
    if not title:
        return jsonify({'error': 'Title required'}), 400
    if not file or not file.filename:
        return jsonify({'error': 'File required'}), 400

    orig_filename = secure_filename(file.filename)
    ext = os.path.splitext(orig_filename)[1].lower()
    if ext not in ALLOWED_DOC_EXTENSIONS:
        return jsonify({'error': 'Only PDF files are allowed'}), 400

    stored_filename = uuid.uuid4().hex + ext
    storage_dir = models.get_docs_storage_dir()
    dest_path = os.path.join(storage_dir, stored_filename)
    file.save(dest_path)
    size_bytes = os.path.getsize(dest_path)

    # Manuals get their bookmark tree extracted at upload time so the
    # Manuals TOC view has page-jump links with zero admin data entry — see
    # pdf_utils.extract_pdf_toc. Not every manual has embedded bookmarks; if
    # not, page_count still gets set and the manual is viewable, just
    # without a jump-list.
    page_count, toc = (0, [])
    if is_manual:
        page_count, toc = pdf_utils.extract_pdf_toc(dest_path)

    user = auth.current_user()
    doc_id = models.create_document(
        section_id, title, stored_filename,
        orig_filename=orig_filename, size_bytes=size_bytes,
        uploaded_by=(user.get('name') if user else 'api'),
        is_manual=is_manual, device=device,
        page_count=page_count, toc_json=json.dumps(toc)
    )
    models.log_action(user['id'] if user else None, user['name'] if user else 'api',
                       'upload_document', target=str(doc_id), detail=title)
    return jsonify({'status': 'uploaded', 'id': doc_id, 'page_count': page_count, 'toc_entries': len(toc)}), 201

@app.route('/api/docs/<int:doc_id>', methods=['DELETE'])
@admin_required
def api_delete_doc(doc_id):
    doc = models.get_document(doc_id)
    filename = models.delete_document(doc_id)
    if filename is None:
        return jsonify({'error': 'Document not found'}), 404
    storage_dir = models.get_docs_storage_dir()
    try:
        os.remove(os.path.join(storage_dir, filename))
    except OSError:
        pass
    user = auth.current_user()
    models.log_action(user['id'] if user else None, user['name'] if user else '',
                       'delete_document', target=str(doc_id), detail=doc['title'] if doc else '')
    return jsonify({'status': 'deleted'})

@app.route('/api/docs/reorder', methods=['POST'])
@admin_required
def api_reorder_docs():
    data = request.get_json() or {}
    section_id = data.get('section_id')
    order = data.get('order', [])
    if not isinstance(section_id, int) or not isinstance(order, list) or not all(isinstance(x, int) for x in order):
        return jsonify({'error': 'section_id (int) and order (list of ids) required'}), 400
    models.reorder_documents(section_id, order)
    return jsonify({'status': 'reordered'})

# ══════════════════════════════════
# STANDALONE TOOLS (ported from local single-file HTML apps)
# Served behind login, not as static assets, so they're not publicly reachable.
# ══════════════════════════════════

TOOL_FILES = {
    'inventory': 'inventory.html',
    'quotebuilder': 'quotebuilder.html',
    'season-calendar': 'season-calendar.html',
    'lens-throw-calculator': 'lens-throw-calculator.html',
    'cl5-patch-generator': 'cl5-patch-generator.html',
}
# Only inventory.html actually needs Jinja (for the IS_ADMIN flag).
TOOLS_NEEDING_JINJA = {'inventory'}

@app.route('/tools/<name>')
@login_required
def tools_page(name):
    filename = TOOL_FILES.get(name)
    if not filename:
        return render_template('token_invalid.html', reason='tool not found'), 404

    if name in TOOLS_NEEDING_JINJA:
        user = auth.current_user()
        is_admin = bool(user and user.get('role') == 'admin')
        return render_template(f'tools/{filename}', is_admin=is_admin)

    # These are static single-file apps with no template variables — serve
    # raw, bypassing Jinja entirely. Minified CSS in files like this often
    # contains a media-query close brace immediately followed by an ID
    # selector, e.g. "}{#layout{...}", which Jinja misreads as an
    # unterminated {# comment #} block and 500s on. Not worth the risk when
    # nothing here actually needs templating.
    path = os.path.join(app.root_path, 'templates', 'tools', filename)
    with open(path, encoding='utf-8') as f:
        return Response(f.read(), mimetype='text/html')

@app.route('/admin/users')
@admin_required
def admin_users_page():
    return render_template('admin_users.html', active='admin_users', users=models.list_users(),
                            invites=models.get_pending_invites())

@app.route('/admin/venues')
@admin_required
def admin_venues_page():
    venues = models.list_venues()
    for v in venues:
        v['systems'] = models.list_venue_systems(v['id'])
    return render_template('admin_venues.html', active='admin_venues', venues=venues)

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
    assignee = models.get_team_member(data.get('assignee_id')) if data.get('assignee_id') else None
    task_id = models.create_task(data, created_by=created_by, created_by_name=created_by_name,
                                  assignee_id=assignee['id'] if assignee else None,
                                  assignee_name=assignee['name'] if assignee else '')
    if assignee and assignee.get('email'):
        email_utils.send_task_assigned_email(assignee['email'], assignee['name'], data['text'],
                                              space=data.get('space', ''), assigned_by_name=created_by_name)
    return jsonify({'status': 'created', 'id': task_id}), 201

@app.route('/api/tasks/cleanup-blank-ids', methods=['POST'])
@auth.require_api_key_or_admin
def api_cleanup_blank_task_ids():
    """One-time data-repair: any task row with a blank/NULL id predates the
    current validate_task() (which already guards create_task against this
    for everything going forward — see models.create_task's `data.get('id')
    or uuid...` fallback). A blank id breaks the /api/tasks/<task_id> routes
    client-side (PUT/DELETE end up hitting /api/tasks/ with nothing after
    the slash -> 404), which is what surfaced this. Backfills a fresh id
    rather than deleting — the task's text/notes/etc. are untouched, it just
    couldn't be addressed by the UI before. Safe to re-run — a second call
    just reports 0 repaired."""
    count = models.repair_blank_task_ids()
    user = auth.current_user()
    models.log_action(user['id'] if user else None, user['name'] if user else 'api',
                       'cleanup_blank_task_ids', detail=f'{count} repaired')
    return jsonify({'status': 'ok', 'repaired': count})

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
    new_assignee = None
    assignee_changed = False
    if 'assignee_id' in data:
        raw = data['assignee_id']
        existing = models.get_task(task_id)
        prev_assignee_id = existing['assignee_id'] if existing else None
        member = models.get_team_member(int(raw)) if str(raw or '').isdigit() else None
        clean['assignee_id'] = member['id'] if member else None
        clean['assignee_name'] = member['name'] if member else ''
        if member and member['id'] != prev_assignee_id:
            new_assignee = member
            assignee_changed = True
    models.update_task(task_id, clean)
    if assignee_changed and new_assignee and new_assignee.get('email'):
        task_text = clean.get('text') or (models.get_task(task_id) or {}).get('text', '')
        user = auth.current_user()
        email_utils.send_task_assigned_email(new_assignee['email'], new_assignee['name'], task_text,
                                              assigned_by_name=user['name'] if user else '')
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
    email = sanitize(data.get('email', ''), 120)
    if not name:
        return jsonify({'error': 'Name required'}), 400
    if models.create_team_member(name, color, email):
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
    if 'email' in data: clean['email'] = sanitize(data['email'], 120)
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

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@admin_required
def api_delete_user(user_id):
    admin = auth.current_user()
    if user_id == admin['id']:
        return jsonify({'error': "You can't delete your own account"}), 400
    target = models.get_user_by_id(user_id)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    if target['is_active']:
        return jsonify({'error': 'Deactivate the account before deleting it'}), 400
    models.delete_user(user_id)
    models.log_action(admin['id'], admin['name'], 'user_deleted', target=target['email'])
    return jsonify({'status': 'deleted'})

@app.route('/api/audit-log', methods=['GET'])
@admin_required
def api_audit_log():
    return jsonify(models.get_audit_log())

# ══════════════════════════════════
# KNOWLEDGE BASE
# ══════════════════════════════════

MAX_KB_BODY = 300000  # generous — some Wiki pages (e.g. TOC-indexed manuals) run long

def validate_kb_page(data):
    # Note: title/section are stored as plain text (NOT html-escaped here) —
    # this endpoint is only reachable via API key (the sync script) or an
    # admin session, not public input, and the KB templates/JS already escape
    # on display (Jinja auto-escapes in kb_index.html/kb_page.html; the Jess
    # search results use textContent). Escaping here too would double-escape
    # (e.g. "Allen & Heath" -> "Allen &amp; Heath" -> literal "&amp;" on screen).
    slug = str(data.get('slug', '')).strip()[:120]
    if not slug or not all(c.isalnum() or c in '-_' for c in slug):
        return None
    return {
        'slug': slug,
        'title': str(data.get('title', slug)).strip()[:200],
        'section': str(data.get('section', '')).strip()[:50],
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
    raw_html = md_lib.markdown(page['body_markdown'], extensions=['tables', 'fenced_code'])
    body_html = bleach.clean(raw_html, tags=KB_ALLOWED_TAGS, attributes=KB_ALLOWED_ATTRS,
                              protocols=KB_ALLOWED_PROTOCOLS, strip=True)
    return render_template('kb_page.html', active='kb', page=page, body_html=body_html)

@app.route('/manuals')
@login_required
def manuals_index():
    return render_template('manuals_index.html', active='kb', sections=models.list_manuals_grouped())

@app.route('/manuals/<int:doc_id>')
@login_required
def manuals_toc(doc_id):
    doc = models.get_manual_toc(doc_id)
    if not doc:
        return render_template('token_invalid.html', reason='manual not found'), 404
    return render_template('manual_toc.html', active='kb', doc=doc)

@app.route('/api/kb/pages', methods=['GET'])
@require_api_key_or_session
def api_kb_list():
    return jsonify(models.list_kb_pages())

@app.route('/api/kb/pages', methods=['POST'])
@require_api_key_or_admin
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

@app.route('/api/kb/pages/<slug>', methods=['GET'])
@require_api_key_or_session
def api_kb_get(slug):
    page = models.get_kb_page(slug)
    if not page:
        return jsonify({'error': 'Page not found'}), 404
    return jsonify(page)

@app.route('/api/kb/pages/<slug>', methods=['DELETE'])
@require_api_key_or_admin
def api_kb_delete(slug):
    if not models.get_kb_page(slug):
        return jsonify({'error': 'Page not found'}), 404
    models.delete_kb_page(slug)
    return jsonify({'status': 'deleted'})

@app.route('/api/kb/search', methods=['GET'])
@require_api_key_or_session
def api_kb_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    return jsonify(models.search_kb_pages(q))

# ══════════════════════════════════
# INVENTORY — one-time migration from the Inventory tool's own localStorage
# JSON export into the database. Admin-only; safe to re-run (idempotent —
# clears and reloads inventory_items/_shows/_spaces only, never touches the
# shared shows table). See models.import_inventory_from_tool_export().
# ══════════════════════════════════

@app.route('/api/inventory/import', methods=['POST'])
@require_api_key_or_session
def api_inventory_import():
    data = request.get_json() or {}
    if not isinstance(data.get('items'), list):
        return jsonify({'error': "Expected the Inventory tool's export shape: {items: [...], shows: [...]}"}), 400
    result = models.import_inventory_from_tool_export(data)
    user = auth.current_user()
    models.log_action(user['id'] if user else None, user['name'] if user else 'api-key',
                       'inventory_imported',
                       detail=f"{result['items_imported']} items, {len(result['unmatched_shows'])} unmatched shows")
    return jsonify(result)

# ══════════════════════════════════
# INVENTORY — items CRUD for the live Inventory tool (templates/tools/
# inventory.html), which now reads/writes the database instead of
# localStorage. Reads are available to any logged-in user (read-only for
# non-admins, same as before); writes are admin-only, enforced server-side
# here (the client-side requireAdmin() check in the tool is UX only, not
# security). Request/response bodies use the tool's own field names
# (desc/cat/subcat/auditNotes/details/showQty/showNotes/spaceQty/
# spaceNotes) via models._item_to_tool_shape, so the JS needs no renaming.
# ══════════════════════════════════

def _item_payload_to_model_data(data, partial=False):
    """Convert a request body in the tool's shape (showQty+showNotes as
    separate parallel objects, etc.) into what models.create_item/
    update_item expect (a combined show_allocations/space_allocations
    dict).

    partial=True (used for PUT/update) only includes keys that were
    actually present in the request body, each carrying the caller's
    exact value through untouched. models.update_item() already only
    writes keys present in the dict it's given — but this function used
    to unconditionally fill in EVERY field with a '' / 0 / {} default
    regardless of whether the caller sent it, which made every field
    "present" and silently blanked out anything the caller omitted on
    partial updates. partial=False (used for POST/create) keeps the old
    default-filling behavior, since a newly created item needs every
    column populated with something.
    """
    defaults = {
        'line': 0, 'qty': 0, 'make': '', 'model': '', 'desc': '', 'cat': '',
        'subcat': '', 'serial': '', 'ip': '', 'loc': '', 'auditNotes': '',
        'units': {}, 'details': {},
    }
    out = {}
    for key, default in defaults.items():
        if partial and key not in data:
            continue
        out[key] = data.get(key, default)
    if not partial or 'cost' in data:
        out['cost'] = models._safe_float(data.get('cost'))
    if 'showQty' in data or 'showNotes' in data:
        out['show_allocations'] = models._merge_qty_notes(data.get('showQty'), data.get('showNotes'))
    if 'spaceQty' in data or 'spaceNotes' in data:
        out['space_allocations'] = models._merge_qty_notes(data.get('spaceQty'), data.get('spaceNotes'))
    return out

@app.route('/api/inventory/items', methods=['GET'])
@require_api_key_or_session
def api_inventory_list_items():
    return jsonify(models.list_items_for_tool())

@app.route('/api/inventory/items', methods=['POST'])
@require_api_key_or_admin
def api_inventory_create_item():
    data = request.get_json() or {}
    if not data.get('make') or not data.get('model') or not data.get('qty'):
        return jsonify({'error': 'Make, Model, and Quantity are required.'}), 400
    item_id = models.create_item(_item_payload_to_model_data(data))
    return jsonify(models.get_item_for_tool(item_id)), 201

@app.route('/api/inventory/items/<int:item_id>', methods=['PUT'])
@require_api_key_or_admin
def api_inventory_update_item(item_id):
    if not models.get_item(item_id):
        return jsonify({'error': 'Item not found'}), 404
    data = request.get_json() or {}
    models.update_item(item_id, _item_payload_to_model_data(data, partial=True))
    return jsonify(models.get_item_for_tool(item_id))

@app.route('/api/inventory/items/<int:item_id>', methods=['DELETE'])
@require_api_key_or_admin
def api_inventory_delete_item(item_id):
    if not models.get_item(item_id):
        return jsonify({'error': 'Item not found'}), 404
    models.soft_delete_item(item_id)
    return jsonify({'status': 'deleted'})

@app.route('/api/inventory/items/deleted', methods=['GET'])
@require_api_key_or_admin
def api_inventory_list_deleted():
    return jsonify([models._item_to_tool_shape(i) for i in models.list_deleted_items()])

@app.route('/api/inventory/items/<int:item_id>/restore', methods=['POST'])
@require_api_key_or_admin
def api_inventory_restore_item(item_id):
    item = models.get_item(item_id)
    if not item:
        return jsonify({'error': 'Item not found'}), 404
    models.restore_item(item_id)
    return jsonify(models.get_item_for_tool(item_id))

@app.route('/api/inventory/items/<int:item_id>/purge', methods=['DELETE'])
@require_api_key_or_admin
def api_inventory_purge_item(item_id):
    if not models.get_item(item_id):
        return jsonify({'error': 'Item not found'}), 404
    models.purge_item(item_id)
    return jsonify({'status': 'purged'})

# ══════════════════════════════════
# INVENTORY — close-show gear archive. Shows in the live Inventory tool
# are still a client-side/localStorage concept (see templates/tools/
# inventory.html), so show_id here is just whatever string id the client
# is using for that show — the server doesn't need its own shows table
# entry to archive against it. "Closing" a show snapshots every item
# currently allocated to it into show_gear_archive (a permanent record)
# and then clears those allocations so the qty reads as available again.
# ══════════════════════════════════

@app.route('/api/inventory/shows/<show_id>/archive-gear', methods=['POST'])
@require_api_key_or_admin
def api_inventory_archive_show_gear(show_id):
    data = request.get_json() or {}
    show_name = str(data.get('show_name', ''))[:200]
    archived = models.archive_show_gear(show_id, show_name)
    user = auth.current_user()
    models.log_action(user['id'] if user else None, user['name'] if user else 'api-key',
                       'show_gear_archived',
                       detail=f"{show_name or show_id}: {len(archived)} item(s), "
                              f"{sum(a['qty'] for a in archived)} unit(s) returned to available")
    return jsonify({'status': 'archived', 'count': len(archived),
                     'total_qty': sum(a['qty'] for a in archived), 'items': archived})

@app.route('/api/inventory/shows/<show_id>/gear-archive', methods=['GET'])
@require_api_key_or_session
def api_inventory_show_gear_archive(show_id):
    return jsonify(models.list_show_gear_archive(show_id))

@app.route('/api/inventory/gear-archive', methods=['GET'])
@require_api_key_or_session
def api_inventory_gear_archive_all():
    return jsonify(models.list_show_gear_archive())

# ══════════════════════════════════
# VENUE FACT DB (Home page STAFF/GUEST editor)
# ══════════════════════════════════

@app.route('/api/venues', methods=['POST'])
@admin_required
def api_create_venue():
    data = request.get_json() or {}
    mode = data.get('mode')
    name = str(data.get('name', '')).strip()[:100]
    if mode not in ('staff', 'guest') or not name:
        return jsonify({'error': 'mode (staff/guest) and name are required'}), 400
    venue_id = models.create_venue(mode, name, str(data.get('description', ''))[:300],
                                    int(data.get('sort_order', 0)))
    return jsonify({'status': 'created', 'id': venue_id}), 201

@app.route('/api/venues/<int:venue_id>', methods=['PUT'])
@admin_required
def api_update_venue(venue_id):
    data = request.get_json() or {}
    update = {}
    if 'name' in data:
        update['name'] = str(data['name']).strip()[:100]
    if 'description' in data:
        update['description'] = str(data['description'])[:300]
    if 'sort_order' in data:
        update['sort_order'] = int(data['sort_order'])
    models.update_venue(venue_id, update)
    return jsonify({'status': 'updated'})

@app.route('/api/venues/<int:venue_id>', methods=['DELETE'])
@admin_required
def api_delete_venue(venue_id):
    models.delete_venue(venue_id)
    return jsonify({'status': 'deleted'})

def _parse_rows_text(text):
    """'Label: Value' per line -> [[label, value], ...]"""
    rows = []
    for line in str(text or '').split('\n'):
        line = line.strip()
        if not line:
            continue
        if ':' in line:
            label, value = line.split(':', 1)
            rows.append([label.strip(), value.strip()])
        else:
            rows.append([line, ''])
    return rows

def _parse_list_text(text):
    """One item per line -> [item, ...]"""
    return [l.strip() for l in str(text or '').split('\n') if l.strip()]

@app.route('/api/venues/<int:venue_id>/systems', methods=['POST'])
@admin_required
def api_create_venue_system(venue_id):
    data = request.get_json() or {}
    name = str(data.get('name', '')).strip()[:100]
    if not name:
        return jsonify({'error': 'name is required'}), 400
    rows = data['rows'] if isinstance(data.get('rows'), list) else _parse_rows_text(data.get('rows_text', ''))
    warns = data['warns'] if isinstance(data.get('warns'), list) else _parse_list_text(data.get('warns_text', ''))
    notes = data['notes'] if isinstance(data.get('notes'), list) else _parse_list_text(data.get('notes_text', ''))
    system_id = models.create_venue_system(venue_id, name, rows, warns, notes,
                                            int(data.get('sort_order', 0)))
    return jsonify({'status': 'created', 'id': system_id}), 201

@app.route('/api/venue-systems/<int:system_id>', methods=['PUT'])
@admin_required
def api_update_venue_system(system_id):
    data = request.get_json() or {}
    update = {}
    if 'name' in data:
        update['name'] = str(data['name']).strip()[:100]
    if 'sort_order' in data:
        update['sort_order'] = int(data['sort_order'])
    if 'rows' in data and isinstance(data['rows'], list):
        update['rows'] = data['rows']
    elif 'rows_text' in data:
        update['rows'] = _parse_rows_text(data['rows_text'])
    if 'warns' in data and isinstance(data['warns'], list):
        update['warns'] = data['warns']
    elif 'warns_text' in data:
        update['warns'] = _parse_list_text(data['warns_text'])
    if 'notes' in data and isinstance(data['notes'], list):
        update['notes'] = data['notes']
    elif 'notes_text' in data:
        update['notes'] = _parse_list_text(data['notes_text'])
    models.update_venue_system(system_id, update)
    return jsonify({'status': 'updated'})

@app.route('/api/venue-systems/<int:system_id>', methods=['DELETE'])
@admin_required
def api_delete_venue_system(system_id):
    models.delete_venue_system(system_id)
    return jsonify({'status': 'deleted'})

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

# Exempt every /api/* route from CSRF token checks — see the comment by
# CSRFProtect(app) above for why. Applied here, after every @app.route has
# registered, rather than one-by-one on ~90 route functions.
for _rule in app.url_map.iter_rules():
    if _rule.rule.startswith('/api/'):
        csrf.exempt(app.view_functions[_rule.endpoint])

with app.app_context():
    models.init_db()
    bootstrap_admin()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
