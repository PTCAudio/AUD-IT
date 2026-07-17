"""
AUD-IT — Transactional email
Sends via Postmark's HTTP API. If POSTMARK_API_KEY isn't set, emails are
printed to the console instead of sent — lets you build/test locally before
Postmark + DNS (SPF/DKIM/DMARC) are set up.
"""
import os
import requests
import auth

POSTMARK_API_KEY = os.environ.get('POSTMARK_API_KEY', '')
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'noreply@ptc-audio.com')
APP_BASE_URL = os.environ.get('APP_BASE_URL', 'http://localhost:5000')

POSTMARK_URL = 'https://api.postmarkapp.com/email'


def send_email(to_email, subject, html_body, text_body=None):
    if not POSTMARK_API_KEY:
        print('─' * 60)
        print(f'[DEV EMAIL — POSTMARK_API_KEY not set] To: {to_email}')
        print(f'Subject: {subject}')
        print(html_body)
        print('─' * 60)
        return True

    payload = {
        'From': EMAIL_FROM,
        'To': to_email,
        'Subject': subject,
        'HtmlBody': html_body,
        'TextBody': text_body or _strip_html(html_body),
        'MessageStream': 'outbound',
    }
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-Postmark-Server-Token': POSTMARK_API_KEY,
    }
    try:
        resp = requests.post(POSTMARK_URL, json=payload, headers=headers, timeout=10)
    except requests.RequestException as e:
        print(f'[EMAIL ERROR] Postmark request failed for {to_email}: {e}')
        return False
    if not resp.ok:
        print(f'[EMAIL ERROR] Postmark rejected send to {to_email} — status {resp.status_code}: {resp.text}')
    else:
        print(f'[EMAIL SENT] To: {to_email} — Subject: {subject}')
    return resp.ok


def _strip_html(html):
    import re
    return re.sub('<[^<]+?>', '', html)


def send_invite_email(to_email, name, token):
    link = f'{APP_BASE_URL}/accept-invite/{token}'
    subject = 'You\'ve been invited to AUD-IT Tasks'
    html = f'''
    <div style="font-family:Georgia,serif;max-width:480px;margin:0 auto;">
      <h2 style="color:#c8102e;">AUD-IT Tasks</h2>
      <p>Hi {name},</p>
      <p>You've been invited to the Phoenix Theatre Company Audio Department's
      task manager. It's where the department tracks tasks, shows, the daily
      journal/hours log, and the department knowledge base — click below to
      set your password and get started.</p>
      <p><a href="{link}" style="background:#c8102e;color:#fff;padding:12px 20px;
      text-decoration:none;border-radius:4px;display:inline-block;">Accept Invite</a></p>
      <p style="color:#888;font-size:13px;">This link expires in 72 hours.
      If you weren't expecting this, you can ignore this email.</p>
      <p style="color:#888;font-size:13px;">Your password needs to be at least
      {auth.PASSWORD_MIN_LEN} characters, with at least one uppercase letter,
      one lowercase letter, one number, and one special character
      (e.g. ! @ # $ %).</p>
    </div>
    '''
    return send_email(to_email, subject, html)


def send_task_assigned_email(to_email, name, task_text, space='', assigned_by_name=''):
    link = f'{APP_BASE_URL}/home'
    subject = 'New task assigned — AUD-IT'
    assigned_by = f' by {assigned_by_name}' if assigned_by_name else ''
    html = f'''
    <div style="font-family:Georgia,serif;max-width:480px;margin:0 auto;">
      <h2 style="color:#c8102e;">AUD-IT Tasks</h2>
      <p>Hi {name},</p>
      <p>You've been assigned a task{assigned_by}:</p>
      <p style="background:#f5f5f5;border-left:3px solid #c8102e;padding:10px 14px;
      font-size:15px;">{task_text}</p>
      <p><a href="{link}" style="background:#c8102e;color:#fff;padding:12px 20px;
      text-decoration:none;border-radius:4px;display:inline-block;">View in AUD-IT</a></p>
    </div>
    '''
    return send_email(to_email, subject, html)


def send_password_reset_email(to_email, name, token):
    link = f'{APP_BASE_URL}/reset-password/{token}'
    subject = 'Reset your AUD-IT Tasks password'
    html = f'''
    <div style="font-family:Georgia,serif;max-width:480px;margin:0 auto;">
      <h2 style="color:#c8102e;">AUD-IT Tasks</h2>
      <p>Hi {name},</p>
      <p>Someone requested a password reset for your account. Click below to
      choose a new password.</p>
      <p><a href="{link}" style="background:#c8102e;color:#fff;padding:12px 20px;
      text-decoration:none;border-radius:4px;display:inline-block;">Reset Password</a></p>
      <p style="color:#888;font-size:13px;">This link expires in 2 hours.
      If you didn't request this, you can safely ignore this email — your
      password will not be changed.</p>
    </div>
    '''
    return send_email(to_email, subject, html)
