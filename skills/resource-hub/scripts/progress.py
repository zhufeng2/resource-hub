"""Durable task queue and short-lived verification reuse; no account credentials."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager, closing
from common import CACHE_ROOT

TTL = 1800

@contextmanager
def database():
    CACHE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = CACHE_ROOT / 'progress.sqlite3'
    with closing(sqlite3.connect(path, timeout=30)) as db, db:
        os.chmod(path, 0o600)
        db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, key TEXT, value TEXT, ts REAL, PRIMARY KEY(kind,key))')
        yield db


def get(kind, key, ttl=None):
    with database() as db:
        row = db.execute('SELECT value,ts FROM records WHERE kind=? AND key=?', (kind,key)).fetchone()
    return json.loads(row[0]) if row and (ttl is None or time.time()-row[1] < ttl) else None


def put(kind, key, value):
    with database() as db:
        db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?,?)', (kind,key,json.dumps(value, ensure_ascii=False),time.time()))


def update_task(task, rows=None, query=None, record=None):
    # One transaction prevents concurrent aliases from losing each other's candidates.
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute("SELECT value FROM records WHERE kind='task' AND key=?", (task,)).fetchone()
        value = json.loads(old[0]) if old else {'queries': [], 'candidates': {}, 'coverage': [], 'saved': []}
        if query and query not in value['queries']:
            value['queries'].append(query)
        for row in rows or []:
            key = row['url']
            previous = value['candidates'].get(key, {})
            sources = set(previous.get('sources', [])) | set(row.get('sources', []))
            if row.get('source'):
                sources.add(row['source'])
            titles = set(previous.get('titles', [])) | {row.get('title', '')}
            merged = dict(previous, **row)
            merged['password'] = row.get('password') or previous.get('password', '')
            merged.update(sources=sorted(sources), titles=sorted(titles - {''}))
            value['candidates'][key] = merged
        if record:
            for field in ('coverage', 'saved'):
                if field in record:
                    if not isinstance(record[field], list):
                        raise ValueError(field + ' 必须是数组')
                    value[field] = record[field]
        db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?,?)', ('task',task,json.dumps(value,ensure_ascii=False),time.time()))
    return value
