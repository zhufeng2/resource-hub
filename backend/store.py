"""SQLite persistence. All quota and token transitions use short write transactions."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8))


def day_key(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, SHANGHAI).date().isoformat()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + value


def password_valid(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored)


def pkce(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


class Store:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Covers SQLite journal/WAL files as well as the main database in this service process.
        if os.name == 'posix':
            os.umask(0o077)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL, daily_limit INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS clients (
                    id TEXT PRIMARY KEY, redirects TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY, params TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS codes (
                    hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, client_id TEXT NOT NULL,
                    redirect TEXT NOT NULL, challenge TEXT NOT NULL, resource TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tokens (
                    hash TEXT PRIMARY KEY, kind TEXT NOT NULL, user_id INTEGER NOT NULL,
                    client_id TEXT NOT NULL, resource TEXT NOT NULL, family TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS limits (
                    key TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS searches (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, request_id TEXT NOT NULL,
                    query TEXT NOT NULL, day TEXT NOT NULL, status TEXT NOT NULL,
                    created REAL NOT NULL, result TEXT, UNIQUE(user_id, request_id));
                CREATE INDEX IF NOT EXISTS searches_user_day ON searches(user_id, day, status);
                CREATE TABLE IF NOT EXISTS web_sessions (
                    hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS preferences (
                    user_id INTEGER PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bindings (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, provider TEXT NOT NULL,
                    label TEXT NOT NULL, upstream_hash TEXT NOT NULL, created REAL NOT NULL);
            ''')
            columns = {r['name'] for r in db.execute('PRAGMA table_info(users)')}
            if 'is_admin' not in columns:
                db.execute('ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0')

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def user(self, user_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM users WHERE id=? AND enabled=1', (user_id,)).fetchone()
            return dict(row) if row else None

    def add_user(self, username, password, limit, is_admin=False):
        if not username or len(username) > 64 or not 12 <= len(password) <= 256 or not 0 <= limit <= 10000:
            raise ValueError('用户名需为 1–64 字符；密码需为 12–256 字符；额度需为 0–10000')
        encoded = password_hash(password)
        with self.connection(True) as db:
            db.execute('INSERT INTO users(username,password,daily_limit,is_admin) VALUES(?,?,?,?)',
                       (username, encoded, limit, int(is_admin)))

    def change_user(self, username, *, enabled=None, password=None, limit=None, is_admin=None):
        with self.connection(True) as db:
            row = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
            if not row:
                raise ValueError('账号不存在')
            if enabled is not None:
                db.execute('UPDATE users SET enabled=? WHERE id=?', (int(enabled), row['id']))
            if is_admin is not None:
                db.execute('UPDATE users SET is_admin=? WHERE id=?', (int(is_admin), row['id']))
            if password is not None:
                if not 12 <= len(password) <= 256:
                    raise ValueError('密码需为 12–256 字符')
                db.execute('UPDATE users SET password=? WHERE id=?', (password_hash(password), row['id']))
            if limit is not None:
                if not 0 <= limit <= 10000:
                    raise ValueError('额度需为 0–10000')
                db.execute('UPDATE users SET daily_limit=? WHERE id=?', (limit, row['id']))
            if password is not None or enabled is False:
                for table in ('tokens', 'codes', 'web_sessions'):
                    db.execute(f'DELETE FROM {table} WHERE user_id=?', (row['id'],))

    def users(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT id,username,enabled,daily_limit,is_admin FROM users ORDER BY id')]

    def web_session(self, user_id):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connection(True) as db:
            db.execute('INSERT INTO web_sessions VALUES(?,?,?,?)',
                       (digest(token), user_id, csrf, time.time() + 7 * 86400))
        return token, csrf

    def web_user(self, token):
        with self.connection() as db:
            row = db.execute('''SELECT u.*,s.csrf FROM web_sessions s JOIN users u ON u.id=s.user_id
                WHERE s.hash=? AND s.expires>? AND u.enabled=1''', (digest(token), time.time())).fetchone()
            return dict(row) if row else None

    def web_logout(self, token):
        with self.connection(True) as db:
            db.execute('DELETE FROM web_sessions WHERE hash=?', (digest(token),))

    def preferences(self, user_id, value=None):
        defaults = {'cloud_types': ['quark'], 'channels': [], 'plugins': [], 'src': 'all',
                    'page_size': 20, 'view': 'list', 'sort': 'relevance', 'theme': 'light',
                    'auto_check': False, 'hide_invalid': False, 'include_words': '',
                    'exclude_words': '', 'match_mode': 'any'}
        with self.connection(value is not None) as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO preferences VALUES(?,?)', (user_id, json.dumps(value)))
            row = db.execute('SELECT value FROM preferences WHERE user_id=?', (user_id,)).fetchone()
        return {**defaults, **(json.loads(row['value']) if row else {})}

    def recent(self, user_id):
        items, seen = [], set()
        with self.connection() as db:
            rows = db.execute("""SELECT id,query,created FROM searches WHERE user_id=?
                AND status='done' AND created>? AND result IS NOT NULL ORDER BY created DESC,id DESC""",
                (user_id, time.time() - 86400))
            for row in rows:
                try:
                    value = json.loads(row['query'])
                    query = value.get('query', '') if isinstance(value, dict) else row['query']
                except (ValueError, TypeError):
                    query = row['query']
                key = ' '.join(unicodedata.normalize('NFKC', query).split()).casefold()
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append({'id': row['id'], 'query': query, 'created': row['created']})
                if len(items) == 12:
                    break
        return items

    def bindings(self, user_id):
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM bindings WHERE user_id=? ORDER BY created', (user_id,))]

    def binding(self, user_id, binding_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM bindings WHERE user_id=? AND id=?', (user_id, binding_id)).fetchone()
            return dict(row) if row else None

    def add_binding(self, user_id, provider, label, upstream_hash):
        binding_id = secrets.token_urlsafe(18)
        with self.connection(True) as db:
            count = db.execute('SELECT COUNT(*) FROM bindings WHERE user_id=?', (user_id,)).fetchone()[0]
            if count >= 15:
                raise ValueError('最多添加 15 个搜索源账号')
            db.execute('INSERT INTO bindings VALUES(?,?,?,?,?,?)',
                       (binding_id, user_id, provider, label, upstream_hash, time.time()))
        return self.binding(user_id, binding_id)

    def remove_binding(self, user_id, binding_id):
        with self.connection(True) as db:
            db.execute('DELETE FROM bindings WHERE user_id=? AND id=?', (user_id, binding_id))

    def login(self, username, password):
        with self.connection() as db:
            row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        # Unknown users still incur the password hashing cost.
        encoded = row['password'] if row else '00' * 16 + ':' + '00' * 64
        valid = password_valid(password, encoded)
        return dict(row) if valid and row and row['enabled'] else None

    def rate(self, key, maximum, window):
        now = time.time()
        with self.connection(True) as db:
            row = db.execute('SELECT * FROM limits WHERE key=?', (key,)).fetchone()
            if not row or now - row['started'] >= window:
                db.execute('INSERT OR REPLACE INTO limits VALUES(?,?,1)', (key, now))
                return True
            if row['count'] >= maximum:
                return False
            db.execute('UPDATE limits SET count=count+1 WHERE key=?', (key,))
            return True

    def register(self, redirects):
        client_id = secrets.token_urlsafe(24)
        with self.connection(True) as db:
            db.execute('INSERT INTO clients VALUES(?,?,?)', (client_id, json.dumps(redirects), time.time()))
        return client_id

    def client_redirects(self, client_id):
        with self.connection() as db:
            row = db.execute('SELECT redirects FROM clients WHERE id=?', (client_id,)).fetchone()
            return json.loads(row['redirects']) if row else []

    def ticket(self, params):
        ticket = secrets.token_urlsafe(32)
        with self.connection(True) as db:
            db.execute('INSERT INTO tickets VALUES(?,?,?)', (digest(ticket), json.dumps(params), time.time() + 600))
        return ticket

    def ticket_params(self, ticket):
        with self.connection() as db:
            row = db.execute('SELECT params FROM tickets WHERE id=? AND expires>?', (digest(ticket), time.time())).fetchone()
            return json.loads(row['params']) if row else None

    def authorize(self, ticket, user_id):
        code = secrets.token_urlsafe(32)
        with self.connection(True) as db:
            row = db.execute('SELECT params FROM tickets WHERE id=? AND expires>?', (digest(ticket), time.time())).fetchone()
            if not row or not db.execute('SELECT id FROM users WHERE id=? AND enabled=1', (user_id,)).fetchone():
                raise ValueError('授权请求已失效')
            p = json.loads(row['params'])
            db.execute('DELETE FROM tickets WHERE id=?', (digest(ticket),))
            db.execute('INSERT INTO codes VALUES(?,?,?,?,?,?,?)', (
                digest(code), user_id, p['client_id'], p['redirect_uri'],
                p['code_challenge'], p['resource'], time.time() + 120))
        return code, p

    def exchange(self, params, resource):
        now = time.time()
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        with self.connection(True) as db:
            if params['grant_type'] == 'authorization_code':
                row = db.execute('SELECT * FROM codes WHERE hash=?', (digest(params.get('code', '')),)).fetchone()
                verifier = params.get('code_verifier', '')
                if (not row or row['expires'] <= now or row['client_id'] != params.get('client_id')
                        or row['redirect'] != params.get('redirect_uri') or row['resource'] != resource
                        or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier)
                        or not hmac.compare_digest(row['challenge'], pkce(verifier))):
                    raise ValueError('invalid_grant')
                family = secrets.token_urlsafe(24)
                # A login grant cannot outlive the user's enabled status.
                table = 'codes'
            else:
                row = db.execute('SELECT * FROM tokens WHERE hash=? AND kind=?',
                                 (digest(params.get('refresh_token', '')), 'refresh')).fetchone()
                if (not row or row['expires'] <= now or row['client_id'] != params.get('client_id')
                        or row['resource'] != resource):
                    raise ValueError('invalid_grant')
                family, table = row['family'], 'tokens'
            if not db.execute('SELECT id FROM users WHERE id=? AND enabled=1', (row['user_id'],)).fetchone():
                raise ValueError('invalid_grant')
            if table == 'tokens':
                db.execute('DELETE FROM tokens WHERE family=?', (family,))
            else:
                db.execute('DELETE FROM codes WHERE hash=?', (row['hash'],))
            for raw, kind, ttl in ((access, 'access', 3600), (refresh, 'refresh', 30 * 86400)):
                db.execute('INSERT INTO tokens VALUES(?,?,?,?,?,?,?)', (
                    digest(raw), kind, row['user_id'], row['client_id'], resource, family, now + ttl))
        return {'access_token': access, 'token_type': 'Bearer', 'expires_in': 3600,
                'refresh_token': refresh, 'scope': 'search'}

    def authenticate(self, token, resource):
        with self.connection() as db:
            row = db.execute('''SELECT u.* FROM tokens t JOIN users u ON t.user_id=u.id
                WHERE t.hash=? AND t.kind='access' AND t.expires>? AND t.resource=? AND u.enabled=1''',
                (digest(token), time.time(), resource)).fetchone()
            return dict(row) if row else None

    def revoke(self, token, client_id):
        with self.connection(True) as db:
            row = db.execute('SELECT family FROM tokens WHERE hash=? AND client_id=?', (digest(token), client_id)).fetchone()
            if row:
                db.execute('DELETE FROM tokens WHERE family=?', (row['family'],))

    def quota(self, user_id, now=None):
        now = time.time() if now is None else now
        with self.connection() as db:
            user = db.execute('SELECT daily_limit,is_admin FROM users WHERE id=? AND enabled=1', (user_id,)).fetchone()
            if not user:
                raise ValueError('账号已停用')
            rows = db.execute('''SELECT status,COUNT(*) n FROM searches WHERE user_id=? AND day=?
                AND (status='done' OR (status='pending' AND created>?)) GROUP BY status''',
                (user_id, day_key(now), now - 180)).fetchall()
        counts = {r['status']: r['n'] for r in rows}
        unlimited = bool(user['is_admin'])
        reset = datetime.fromtimestamp(now, SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return {'daily_limit': None if unlimited else user['daily_limit'], 'used': counts.get('done', 0),
                'in_progress': counts.get('pending', 0), 'unlimited': unlimited,
                'remaining': None if unlimited else max(0, user['daily_limit'] - sum(counts.values())),
                'resets_at': reset.isoformat()}

    def reserve(self, user_id, request_id, query):
        now = time.time()
        with self.connection(True) as db:
            user = db.execute('SELECT daily_limit,is_admin FROM users WHERE id=? AND enabled=1', (user_id,)).fetchone()
            if not user:
                raise ValueError('account_disabled')
            old = db.execute('SELECT * FROM searches WHERE user_id=? AND request_id=?', (user_id, request_id)).fetchone()
            if old:
                if old['query'] != query:
                    raise ValueError('request_id_conflict')
                if old['status'] == 'done':
                    return dict(old), False
                if old['status'] == 'pending' and old['created'] > now - 180:
                    raise ValueError('search_in_progress')
            if not user['is_admin']:
                count = db.execute('''SELECT COUNT(*) FROM searches WHERE user_id=? AND day=?
                    AND (status='done' OR (status='pending' AND created>?))''', (user_id, day_key(now), now - 180)).fetchone()[0]
                if count >= user['daily_limit']:
                    raise ValueError('daily_limit_reached')
            # A retry after failure receives a new internal ID, so a late worker cannot finish it.
            if old:
                db.execute('DELETE FROM searches WHERE id=?', (old['id'],))
            search_id = secrets.token_urlsafe(24)
            db.execute('INSERT INTO searches VALUES(?,?,?,?,?,?,?,NULL)',
                       (search_id, user_id, request_id, query, day_key(now), 'pending', now))
            row = db.execute('SELECT * FROM searches WHERE id=?', (search_id,)).fetchone()
            return dict(row), True

    def finish(self, search_id, result):
        with self.connection(True) as db:
            db.execute("UPDATE searches SET status='done',result=? WHERE id=? AND status='pending'",
                       (json.dumps(result, ensure_ascii=False), search_id))

    def fail(self, search_id):
        with self.connection(True) as db:
            db.execute("UPDATE searches SET status='failed' WHERE id=? AND status='pending'", (search_id,))

    def search(self, user_id, search_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM searches WHERE id=? AND user_id=? AND status='done'", (search_id, user_id)).fetchone()
            return dict(row) if row else None

    def cleanup(self):
        now = time.time()
        with self.connection(True) as db:
            for table in ('tickets', 'codes', 'tokens', 'web_sessions'):
                db.execute(f'DELETE FROM {table} WHERE expires<?', (now,))
            db.execute('DELETE FROM limits WHERE started<?', (now - 86400,))
            db.execute('DELETE FROM searches WHERE created<?', (now - 31 * 86400,))
            # Keep current-day quota counts but discard old search content after one day.
            db.execute('UPDATE searches SET result=NULL WHERE created<?', (now - 86400,))
