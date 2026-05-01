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
from functools import wraps
from flask import (Flask, request, jsonify, render_template,
                   redirect, url_for, session, send_file)
from dotenv import load_dotenv
import models

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me')
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'changeme')


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
@login_required
def api_get_shows():
    return jsonify(models.get_all_shows())


@app.route('/api/shows', methods=['POST'])
@login_required
def api_create_show():
    data = request.get_json()
    models.create_show(data)
    return jsonify({'status': 'created'}), 201


@app.route('/api/shows/<show_id>', methods=['PUT'])
@login_required
def api_update_show(show_id):
    data = request.get_json()
    models.update_show(show_id, data)
    return jsonify({'status': 'updated'})


@app.route('/api/shows/<show_id>', methods=['DELETE'])
@login_required
def api_delete_show(show_id):
    models.delete_show(show_id)
    return jsonify({'status': 'deleted'})


# ══════════════════════════════════
# API — CATEGORIES
# ══════════════════════════════════

@app.route('/api/categories', methods=['GET'])
@login_required
def api_get_categories():
    return jsonify(models.get_all_categories())


@app.route('/api/categories', methods=['POST'])
@login_required
def api_create_category():
    data = request.get_json()
    models.create_category(data)
    return jsonify({'status': 'created'}), 201


@app.route('/api/categories/<cat_id>', methods=['DELETE'])
@login_required
def api_delete_category(cat_id):
    models.delete_category(cat_id)
    return jsonify({'status': 'deleted'})


# ══════════════════════════════════
# API — TASKS
# ══════════════════════════════════

@app.route('/api/tasks', methods=['GET'])
@login_required
def api_get_tasks():
    return jsonify(models.get_all_tasks())


@app.route('/api/tasks', methods=['POST'])
@login_required
def api_create_task():
    data = request.get_json()
    models.create_task(data)
    return jsonify({'status': 'created'}), 201


@app.route('/api/tasks/<task_id>', methods=['PUT'])
@login_required
def api_update_task(task_id):
    data = request.get_json()
    models.update_task(task_id, data)
    return jsonify({'status': 'updated'})


@app.route('/api/tasks/<task_id>', methods=['DELETE'])
@login_required
def api_delete_task(task_id):
    models.delete_task(task_id)
    return jsonify({'status': 'deleted'})


@app.route('/api/tasks/reorder', methods=['POST'])
@login_required
def api_reorder_tasks():
    data = request.get_json()
    models.reorder_tasks(data.get('ids', []))
    return jsonify({'status': 'reordered'})


# ══════════════════════════════════
# API — JOURNAL
# ══════════════════════════════════

@app.route('/api/journal', methods=['GET'])
@login_required
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
@login_required
def api_create_journal():
    data = request.get_json()
    models.create_journal(data)
    return jsonify({'status': 'created'}), 201


@app.route('/api/journal/<entry_id>', methods=['PUT'])
@login_required
def api_update_journal(entry_id):
    data = request.get_json()
    models.update_journal(entry_id, data)
    return jsonify({'status': 'updated'})


@app.route('/api/journal/<entry_id>', methods=['DELETE'])
@login_required
def api_delete_journal(entry_id):
    models.delete_journal(entry_id)
    return jsonify({'status': 'deleted'})


# ══════════════════════════════════
# API — BACKUP / RESTORE
# ══════════════════════════════════

@app.route('/api/backup', methods=['GET'])
@login_required
def api_backup():
    data = models.export_all()
    return jsonify(data)


@app.route('/api/restore/tasks', methods=['POST'])
@login_required
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
