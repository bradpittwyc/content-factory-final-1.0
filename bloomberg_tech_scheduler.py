"""Persistent, single-article Bloomberg Tech scheduler (browser executes work)."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

INTERVAL = 7200
TECH_URL = 'https://www.bloomberg.com/technology'


class Scheduler:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS config (
                    id INTEGER PRIMARY KEY, enabled INTEGER, due REAL,
                    pause TEXT, last_seen REAL);
                INSERT OR IGNORE INTO config (id,enabled,due,pause,last_seen) VALUES (1,0,0,'',0);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, owner TEXT, phase TEXT, started REAL,
                    lease REAL, url TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS candidates (
                    url TEXT PRIMARY KEY, first_seen REAL, last_seen REAL,
                    state TEXT, attempts INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS candidate_columns (
                    url TEXT, column_id TEXT, PRIMARY KEY(url,column_id));
            ''')
            db.execute('BEGIN IMMEDIATE')
            if 'interval_seconds' not in {row[1] for row in db.execute('PRAGMA table_info(config)')}:
                db.execute(f'ALTER TABLE config ADD COLUMN interval_seconds INTEGER NOT NULL DEFAULT {INTERVAL}')
            # Existing Tech jobs and queue keep their history after migration.
            if 'column_id' not in {row[1] for row in db.execute('PRAGMA table_info(runs)')}:
                db.execute("ALTER TABLE runs ADD COLUMN column_id TEXT NOT NULL DEFAULT 'tech'")
            if 'last_column' not in {row[1] for row in db.execute('PRAGMA table_info(config)')}:
                db.execute("ALTER TABLE config ADD COLUMN last_column TEXT NOT NULL DEFAULT ''")
                db.execute("INSERT OR IGNORE INTO candidate_columns SELECT url,'tech' FROM candidates")
                latest = db.execute('SELECT column_id FROM runs ORDER BY started DESC LIMIT 1').fetchone()
                if latest:
                    db.execute('UPDATE config SET last_column=?', (latest['column_id'],))
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def status(self):
        with self.transaction() as db:
            config = dict(db.execute('SELECT * FROM config').fetchone())
            run = db.execute('SELECT * FROM runs ORDER BY started DESC LIMIT 1').fetchone()
            counts = dict(db.execute('SELECT state,COUNT(*) FROM candidates GROUP BY state').fetchall())
            return {'protocol_version': 1, 'enabled': bool(config['enabled']),
                    'interval_minutes': config['interval_seconds'] // 60, 'max_attempts_per_run': 1,
                    'next_due_at': config['due'] or None, 'pause_reason': config['pause'],
                    'browser_last_seen': config['last_seen'] or None,
                    'last_run': dict(run) if run else None, 'queue_counts': counts}

    def configure(self, enabled, now=None, interval_minutes=None):
        if interval_minutes is not None and (type(interval_minutes) is not int or not 2 <= interval_minutes <= 1440):
            raise ValueError('interval_minutes must be an integer between 2 and 1440')
        now = time.time() if now is None else now
        with self.transaction() as db:
            config = db.execute('SELECT * FROM config').fetchone()
            interval = interval_minutes * 60 if interval_minutes is not None else config['interval_seconds']
            changed = interval != config['interval_seconds']
            db.execute('UPDATE config SET interval_seconds=?', (interval,))
            if enabled:
                # Repeated enabling must not keep postponing the first run.
                due = config['due'] if config['enabled'] and not config['pause'] and not changed else now + interval
                db.execute("UPDATE config SET enabled=1,pause='',due=?", (due,))
            else:
                db.execute("UPDATE config SET enabled=0,pause='paused_user'")
                db.execute("UPDATE runs SET phase='stopped' WHERE phase IN ('discover','article')")
        return self.status()

    def tick(self, owner, immediate=False, now=None, columns=None, column=None):
        now = time.time() if now is None else now
        columns = columns if columns is not None else [{'id': 'tech', 'url': TECH_URL, 'enabled': True}]
        catalog = {item['id']: item for item in columns}
        if column and (not immediate or column not in catalog):
            raise ValueError('Unknown column or column selection outside a manual run')
        with self.transaction() as db:
            db.execute('UPDATE config SET last_seen=?', (now,))
            config = db.execute('SELECT * FROM config').fetchone()
            if immediate:
                db.execute("UPDATE config SET pause=''")
            if config['pause'] and not immediate:
                return {'action': 'idle', 'pause_reason': config['pause']}
            current = db.execute("SELECT * FROM runs WHERE phase IN ('discover','article') LIMIT 1").fetchone()
            if current:
                if current['owner'] != owner and current['lease'] > now:
                    return {'action': 'busy'}
                if now - current['started'] > 180:
                    db.execute("UPDATE runs SET phase='timeout',result=? WHERE id=?",
                               (json.dumps({'status': 'timeout', 'saved': False}), current['id']))
                    if current['url']:
                        db.execute("UPDATE candidates SET state=CASE WHEN attempts>=3 THEN 'needs_review' ELSE 'pending' END WHERE url=?", (current['url'],))
                    return {'action': 'idle'}
                db.execute('UPDATE runs SET owner=?,lease=? WHERE id=?', (owner, now + 120, current['id']))
                return {'action': current['phase'], 'run_id': current['id'],
                        'url': current['url'] or catalog.get(current['column_id'], {}).get('url', TECH_URL),
                        'column': current['column_id']}
            if not immediate and (not config['enabled'] or now < config['due']):
                return {'action': 'idle'}
            eligible = [item['id'] for item in columns if item.get('enabled')]
            if not column and not eligible:
                return {'action': 'idle', 'pause_reason': 'no_enabled_columns'}
            if not column:
                previous = config['last_column']
                column = eligible[(eligible.index(previous) + 1) % len(eligible)] if previous in eligible else eligible[0]
            run_id = str(uuid.uuid4())
            db.execute('INSERT INTO runs (id,owner,phase,started,lease,url,result,column_id) VALUES (?,?,?,?,?,?,?,?)',
                       (run_id, owner, 'discover', now, now + 120, '', None, column))
            db.execute('UPDATE config SET due=?,last_column=?', (now + config['interval_seconds'], column))
            db.execute('DELETE FROM runs WHERE started<? AND phase NOT IN (\'discover\',\'article\')', (now - 30 * 86400,))
            return {'action': 'discover', 'run_id': run_id, 'url': catalog[column]['url'], 'column': column}

    @staticmethod
    def active(db, run_id, owner, phase, now):
        run = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not run or run['owner'] != owner or run['phase'] != phase or run['lease'] < now:
            raise ValueError('Task is stopped, expired, or owned by another browser')
        return run

    def discover(self, run_id, owner, urls, seen, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            run = self.active(db, run_id, owner, 'discover', now)
            for url in urls:
                db.execute("INSERT INTO candidates VALUES (?,?,?,'pending',0) ON CONFLICT(url) DO UPDATE SET last_seen=excluded.last_seen",
                           (url, now, now))
                db.execute('INSERT OR IGNORE INTO candidate_columns VALUES (?,?)', (url, run['column_id']))
            for url in seen:
                db.execute("UPDATE candidates SET state='saved' WHERE url=?", (url,))
            # Standalone interactive features use a separate, unverified body layout.
            # Keep them in the manual snapshot without spending the automatic article budget.
            db.execute("UPDATE candidates SET state='manual_only' WHERE state='pending' AND url LIKE 'https://www.bloomberg.com/features/%'")
            # Old undiscovered items do not accumulate forever. Current snapshot tombstones remain.
            db.execute('DELETE FROM candidates WHERE last_seen<?', (now - 30 * 86400,))
            db.execute('DELETE FROM candidate_columns WHERE url NOT IN (SELECT url FROM candidates)')
            candidates = db.execute("SELECT url,attempts,first_seen FROM candidates WHERE state='pending' AND attempts<3 AND url IN (SELECT url FROM candidate_columns WHERE column_id=?)", (run['column_id'],)).fetchall()
            order = {url: index for index, url in enumerate(urls)}
            # Current section order beats age inherited from a different section's queue.
            candidate = min(candidates, key=lambda item: (item['attempts'], order.get(item['url'], len(order)), item['first_seen']), default=None)
            if not candidate:
                db.execute("UPDATE runs SET phase='completed',result=? WHERE id=?",
                           (json.dumps({'status': 'empty_queue', 'saved': False}), run_id))
                return {'action': 'done', 'status': 'empty_queue', 'saved': False}
            url = candidate['url']
            db.execute('UPDATE candidates SET attempts=attempts+1 WHERE url=?', (url,))
            db.execute("UPDATE runs SET phase='article',url=?,lease=? WHERE id=?", (url, now + 120, run_id))
            return {'action': 'article', 'run_id': run_id, 'url': url, 'column': run['column_id']}

    def finish(self, run_id, owner, callback, now=None):
        """Callback writes idempotently to the article store before recording receipt."""
        now = time.time() if now is None else now
        with self.transaction() as db:
            previous = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
            if previous and previous['owner'] == owner and previous['result']:
                return json.loads(previous['result'])
            if not previous:
                raise ValueError('Unknown task')
            run = self.active(db, run_id, owner, previous['phase'], now)
            if run['phase'] not in ('discover', 'article'):
                raise ValueError('Task is no longer active')
            result = callback(dict(run))
            state = result['status']
            pause = state in ('blocked', 'subscription_gate', 'tab_closed')
            if pause:
                db.execute('UPDATE config SET pause=?', ('paused_user' if state == 'tab_closed' else 'paused_auth',))
            if run['url']:
                candidate = db.execute('SELECT attempts FROM candidates WHERE url=?', (run['url'],)).fetchone()
                target = ('saved' if result.get('saved') else 'expired' if state == 'expired' else
                          'pending' if state in ('network_error', 'timeout', 'blocked', 'subscription_gate', 'tab_closed') and candidate['attempts'] < 3 else 'needs_review')
                db.execute('UPDATE candidates SET state=? WHERE url=?', (target, run['url']))
            db.execute('UPDATE runs SET phase=?,result=? WHERE id=?',
                       ('paused' if pause else 'completed', json.dumps(result, ensure_ascii=False), run_id))
            return result
