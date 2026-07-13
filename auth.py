"""
AUD-IT — Auth helpers
Password hashing, invite/reset tokens, and route decorators.
"""
import secrets
from functools import wraps
from datetime import datetime, timedelta, timezone

from flask import session, redirect, url_for, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

import models

INVITE_TOKEN_TTL_HOURS = 72
RESET_TOKEN_TTL_HOURS = 2


# ══════════════════════════════════
# PASSWORDS
# ══════════════════════════════════

def hash_password(password):
    """Werkzeug's default (scrypt) — no extra dependency needed."""
    return generate_password_hash(password)


def verify_password(password, password_hash):
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)


# ══════════════════════════════════
# TOKENS (random, DB-backed, revocable)
# ══════════════════════════════════

def _new_token():
    return secrets.token_urlsafe(32)


def _future_iso(hours):
    return (datetime.utcnow() + timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')


def _is_expired(expires_at_str):
    try:
        expires = datetime.strptime(expires_at_str, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return True
    return datetime.utcnow() > expires


def create_invite(email, name, role, invited_by_id):
    token = _new_token()
    models.create_invite_token(token, email, name, role, invited_by_id, _future_iso(INVITE_TOKEN_TTL_HOURS))
    return token


def validate_invite(token):
    """Returns the invite row if valid and unused/unexpired, else None."""
    invite = models.get_invite_token(token)
    if not invite:
        return None
    if invite['used_at']:
        return None
    if _is_expired(invite['expires_at']):
        return None
    return invite


def create_password_reset(user_id):
    token = _new_token()
    models.create_reset_token(token, user_id, _future_iso(RESET_TOKEN_TTL_HOURS))
    return token


def validate_reset_token(token):
    reset = models.get_reset_token(token)
    if not reset:
        return None
    if reset['used_at']:
        return None
    if _is_expired(reset['expires_at']):
        return None
    return reset


# ══════════════════════════════════
# SESSION / DECORATORS
# ══════════════════════════════════

def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return models.get_user_by_id(uid)


def log_in_user(user):
    session.clear()
    session['user_id'] = user['id']
    session['role'] = user['role']
    session['name'] = user['name']
    session.permanent = True
    models.touch_last_login(user['id'])


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        # Check the live DB role, not session['role'] — that's only a
        # snapshot taken at login time (see log_in_user() below), so a role
        # change after login (e.g. promoting someone to admin) wouldn't take
        # effect until they logged out and back in. /home already computes
        # is_admin fresh from the DB on every load, so a stale session here
        # meant admin-only links would show on Home but 403/redirect the
        # moment you clicked them — this keeps the two checks in sync.
        user = models.get_user_by_id(session['user_id'])
        if not user or user.get('role') != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Admin access required'}), 403
            return redirect(url_for('tasks'))
        return f(*args, **kwargs)
    return decorated


def require_api_key_or_session(f):
    """For machine-to-machine API access (e.g. MCP server) OR a logged-in browser session."""
    import os

    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-API-Key')
        api_key = os.environ.get('API_KEY', '')
        if key and api_key and key == api_key:
            return f(*args, **kwargs)
        if session.get('user_id'):
            return f(*args, **kwargs)
        return jsonify({'error': 'Unauthorized'}), 401
    return decorated


def require_api_key_or_admin(f):
    """Same as require_api_key_or_session, but a browser session must be an
    admin — for routes (like inventory writes) where regular logged-in
    users should stay read-only in the UI, while a machine credential
    (e.g. the MCP server) is trusted at admin-equivalent level."""
    import os

    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-API-Key')
        api_key = os.environ.get('API_KEY', '')
        if key and api_key and key == api_key:
            return f(*args, **kwargs)
        # Live DB role check, not session['role'] — see admin_required above
        # for why the cached session snapshot can go stale.
        uid = session.get('user_id')
        user = models.get_user_by_id(uid) if uid else None
        if user and user.get('role') == 'admin':
            return f(*args, **kwargs)
        return jsonify({'error': 'Admin access required'}), 403
    return decorated
