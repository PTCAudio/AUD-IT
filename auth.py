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


PASSWORD_MIN_LEN = 10
PASSWORD_SPECIAL_CHARS = '!@#$%^&*()_+-=[]{}|;:,.<>?/~`'


def validate_password(password):
    """Traditional complexity policy: minimum length plus at least one
    uppercase letter, one lowercase letter, one digit, and one special
    character. Returns an error string, or None if the password passes."""
    if len(password) < PASSWORD_MIN_LEN:
        return f'Password must be at least {PASSWORD_MIN_LEN} characters.'
    if not any(c.isupper() for c in password):
        return 'Password must include at least one uppercase letter.'
    if not any(c.islower() for c in password):
        return 'Password must include at least one lowercase letter.'
    if not any(c.isdigit() for c in password):
        return 'Password must include at least one number.'
    if not any(c in PASSWORD_SPECIAL_CHARS for c in password):
        return 'Password must include at least one special character (e.g. ! @ # $ %).'
    return None


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


def _valid_api_key(key):
    """Checks an incoming X-API-Key against API_KEY and, if set,
    API_KEY_SECONDARY — supports zero-downtime key rotation.

    Rotation flow: generate a new key, set it as API_KEY_SECONDARY (leave
    the current API_KEY as-is) and redeploy. Both keys work while you
    update every client (e.g. the MCP server's .env) at your own pace.
    Once everything's confirmed on the new key, promote it to API_KEY and
    remove API_KEY_SECONDARY. There's never a window where a stale client
    is locked out mid-rotation."""
    import os
    if not key:
        return False
    api_key = os.environ.get('API_KEY', '')
    secondary_key = os.environ.get('API_KEY_SECONDARY', '')
    if api_key and key == api_key:
        return True
    if secondary_key and key == secondary_key:
        return True
    return False


def require_api_key_or_session(f):
    """For machine-to-machine API access (e.g. MCP server) OR a logged-in browser session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if _valid_api_key(request.headers.get('X-API-Key')):
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
    @wraps(f)
    def decorated(*args, **kwargs):
        if _valid_api_key(request.headers.get('X-API-Key')):
            return f(*args, **kwargs)
        # Live DB role check, not session['role'] — see admin_required above
        # for why the cached session snapshot can go stale.
        uid = session.get('user_id')
        user = models.get_user_by_id(uid) if uid else None
        if user and user.get('role') == 'admin':
            return f(*args, **kwargs)
        return jsonify({'error': 'Admin access required'}), 403
    return decorated
