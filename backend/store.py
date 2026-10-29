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

from cryptography.fernet import Fernet, InvalidToken

SHANGHAI = timezone(timedelta(hours=8))
MCP_TOKEN_DAYS = 7


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
                CREATE TABLE IF NOT EXISTS mcp_token_secrets (
                    hash TEXT PRIMARY KEY, ciphertext BLOB NOT NULL);
                CREATE TRIGGER IF NOT EXISTS delete_mcp_token_secret AFTER DELETE ON tokens
                    BEGIN DELETE FROM mcp_token_secrets WHERE hash=OLD.hash; END;
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
                CREATE TABLE IF NOT EXISTS quark_accounts (
                    user_id INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, ciphertext BLOB NOT NULL,
                    allow_writes INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL);
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

    def quark_cipher(self, create=False):
        # QUARK_SECRET_KEY may be supplied by a secret manager, outside the DB volume.
        key = os.environ.get('QUARK_SECRET_KEY')
        if key:
            return Fernet(key.encode('ascii'))
        path = self.path.with_name(self.path.name + '.quark.key')
        if create and not path.exists():
            # Called under the SQLite write lock, also serializing multiple workers.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(Fernet.generate_key())
                stream.flush()
                os.fsync(stream.fileno())
        return Fernet(path.read_bytes())

    def quark_account(self, user_id, secret=False):
        with self.connection() as db:
            row = db.execute('''SELECT q.* FROM quark_accounts q JOIN users u ON u.id=q.user_id
                WHERE q.user_id=? AND u.enabled=1''', (user_id,)).fetchone()
        if not row:
            return None
        value = {'id': row['id'], 'updated_at': row['updated']}
        if secret:
            payload = json.loads(self.quark_cipher().decrypt(row['ciphertext']))
            if payload.get('user_id') != user_id or payload.get('binding_id') != row['id']:
                raise ValueError('credential_owner_mismatch')
            value['cookie'] = payload['cookie']
        return value

    def bind_quark(self, user_id, cookie):
        with self.connection(True) as db:
            if not db.execute('SELECT 1 FROM users WHERE id=? AND enabled=1', (user_id,)).fetchone():
                raise ValueError('account_disabled')
            binding_id = secrets.token_hex(16)
            encrypted = self.quark_cipher(create=True).encrypt(json.dumps({
                'user_id': user_id, 'binding_id': binding_id, 'cookie': cookie}).encode())
            # Rebinding creates a new namespace: old operations cannot run on a new account.
            db.execute('INSERT OR REPLACE INTO quark_accounts VALUES(?,?,?,?,?)',
                       (user_id, binding_id, encrypted, 1, time.time()))
        return self.quark_account(user_id)

    def unbind_quark(self, user_id):
        with self.connection(True) as db:
            db.execute('DELETE FROM quark_accounts WHERE user_id=?', (user_id,))

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
                for statement in ('DELETE FROM tokens WHERE user_id=?',
                                  'DELETE FROM codes WHERE user_id=?',
                                  'DELETE FROM web_sessions WHERE user_id=?'):
                    db.execute(statement, (row['id'],))

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
                    'auto_check': True, 'hide_invalid': True, 'include_words': '',
                    'exclude_words': '', 'match_mode': 'any', 'verification_defaults_v2': True}
        migrate = None
        with self.connection(value is not None) as db:
            if value is not None:
                # Mark the preference so a later explicit opt-out is respected.
                value = {**value, 'verification_defaults_v2': True}
                db.execute('INSERT OR REPLACE INTO preferences VALUES(?,?)', (user_id, json.dumps(value)))
            row = db.execute('SELECT value FROM preferences WHERE user_id=?', (user_id,)).fetchone()
            saved = json.loads(row['value']) if row else None
            if saved is not None and saved.get('verification_defaults_v2') is not True:
                # One-time migration: older accounts had verification off by default.
                saved.update(auto_check=True, hide_invalid=True, verification_defaults_v2=True)
                if value is not None:
                    db.execute('UPDATE preferences SET value=? WHERE user_id=?', (json.dumps(saved), user_id))
                else:
                    migrate = saved
        if migrate is not None:
            with self.connection(True) as db:
                db.execute('UPDATE preferences SET value=? WHERE user_id=?', (json.dumps(migrate), user_id))
        return {**defaults, **(saved or {})}

    @staticmethod
    def history_query(value):
        try:
            decoded = json.loads(value)
            return decoded.get('query', '') if isinstance(decoded, dict) else value
        except (ValueError, TypeError):
            return value

    @staticmethod
    def history_key(query):
        return ' '.join(unicodedata.normalize('NFKC', query).split()).casefold()

    def recent(self, user_id):
        items, seen = [], set()
        with self.connection() as db:
            rows = db.execute("""SELECT id,query,created FROM searches WHERE user_id=?
                AND status='done' AND created>? AND result IS NOT NULL ORDER BY created DESC,id DESC""",
                (user_id, time.time() - 86400))
            for row in rows:
                query = self.history_query(row['query'])
                key = self.history_key(query)
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append({'id': row['id'], 'query': query, 'created': row['created']})
                if len(items) == 12:
                    break
        return items

    def delete_history(self, user_id, search_id=None):
        with self.connection(True) as db:
            rows = db.execute("""SELECT id,query FROM searches WHERE user_id=?
                AND status='done' AND query<>''""", (user_id,)).fetchall()
            if search_id is not None:
                target = next((row for row in rows if row['id'] == search_id), None)
                if target is None:
                    return None
                # History groups repeated keywords; remove the whole displayed group.
                key = self.history_key(self.history_query(target['query']))
                rows = [row for row in rows if self.history_key(self.history_query(row['query'])) == key]
            ids = [row['id'] for row in rows]
            # Searches also form the quota and request-id ledger. Erase content,
            # retaining completed rows so deletion cannot refund or bypass quota.
            db.executemany("UPDATE searches SET query='',result=NULL WHERE user_id=? AND id=?",
                           ((user_id, search_id) for search_id in ids))
        return ids

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

    def mcp_token_cipher(self, create=False):
        key_path = self.path.with_name(self.path.name + '.mcp.key')
        if create and not key_path.exists():
            # Callers hold the database write lock when creating the shared key.
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(Fernet.generate_key())
                stream.flush()
                os.fsync(stream.fileno())
        return Fernet(key_path.read_bytes())

    def mcp_token_status(self, user_id, resource, reveal=False):
        with self.connection() as db:
            row = db.execute("""SELECT t.hash,t.expires,s.ciphertext FROM tokens t
                LEFT JOIN mcp_token_secrets s ON s.hash=t.hash WHERE t.user_id=? AND t.resource=?
                AND t.client_id='dsh-cli' AND t.kind='access' AND t.expires>? ORDER BY t.expires DESC LIMIT 1""",
                (user_id, resource, time.time())).fetchone()
        value = {'active': bool(row), 'expires_at': row['expires'] if row else None}
        if reveal:
            value['token'] = None
            if row and row['ciphertext']:
                try:
                    raw = self.mcp_token_cipher().decrypt(row['ciphertext']).decode()
                    if hmac.compare_digest(digest(raw), row['hash']):
                        value['token'] = raw
                except (InvalidToken, OSError, ValueError):
                    pass  # Hash-only legacy tokens or lost keys require explicit regeneration.
        return value

    def issue_mcp_token(self, username, resource, days=MCP_TOKEN_DAYS):
        """Issue a long-lived Bearer token for MCP clients that cannot do OAuth."""
        if not 1 <= days <= 3650:
            raise ValueError('有效期需为 1–3650 天')
        raw = 'rh_mcp_' + secrets.token_urlsafe(32)
        with self.connection(True) as db:
            row = db.execute('SELECT id FROM users WHERE username=? AND enabled=1', (username,)).fetchone()
            if not row:
                raise ValueError('账号不存在或已停用')
            encrypted = self.mcp_token_cipher(create=True).encrypt(raw.encode())
            # One active CLI token per account; reissuing rotates the old one.
            db.execute("DELETE FROM tokens WHERE user_id=? AND client_id='dsh-cli'", (row['id'],))
            db.execute('INSERT INTO tokens VALUES(?,?,?,?,?,?,?)', (
                digest(raw), 'access', row['id'], 'dsh-cli', resource,
                secrets.token_urlsafe(24), time.time() + days * 86400))
            db.execute('INSERT INTO mcp_token_secrets VALUES(?,?)', (digest(raw), encrypted))
        return raw

    def revoke_mcp_token(self, username):
        with self.connection(True) as db:
            row = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
            if not row:
                raise ValueError('账号不存在')
            return db.execute("DELETE FROM tokens WHERE user_id=? AND client_id='dsh-cli'",
                              (row['id'],)).rowcount

    def mcp_tokens(self):
        with self.connection() as db:
            rows = db.execute('''SELECT u.username, t.expires FROM tokens t
                JOIN users u ON u.id=t.user_id WHERE t.client_id='dsh-cli' ORDER BY u.username''').fetchall()
            return [{'username': row['username'],
                     'expires': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(row['expires']))}
                    for row in rows]


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
            for statement in ('DELETE FROM tickets WHERE expires<?',
                              'DELETE FROM codes WHERE expires<?',
                              'DELETE FROM tokens WHERE expires<?',
                              'DELETE FROM web_sessions WHERE expires<?'):
                db.execute(statement, (now,))
            db.execute('DELETE FROM limits WHERE started<?', (now - 86400,))
            db.execute('DELETE FROM searches WHERE created<?', (now - 31 * 86400,))
            # Keep current-day quota counts but discard old search content after one day.
            db.execute("UPDATE searches SET query='',result=NULL WHERE created<? AND (query<>'' OR result IS NOT NULL)", (now - 86400,))
