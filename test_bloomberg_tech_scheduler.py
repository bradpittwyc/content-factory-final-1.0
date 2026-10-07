import tempfile
import unittest
from pathlib import Path
from bloomberg_tech_scheduler import Scheduler, INTERVAL


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'scheduler.sqlite3'
        self.scheduler = Scheduler(self.path)

    def start(self):
        self.scheduler.configure(True, now=100)
        return self.scheduler.tick('browser', now=100 + INTERVAL)

    def test_interval_change_reschedules_and_survives_restart(self):
        self.scheduler.configure(True, now=100)
        self.scheduler.configure(True, now=200, interval_minutes=10)
        restarted = Scheduler(self.path)
        self.assertEqual(restarted.status()['interval_minutes'], 10)
        self.assertEqual(restarted.status()['next_due_at'], 800)
        self.assertEqual(restarted.tick('browser', now=799)['action'], 'idle')
        self.assertEqual(restarted.tick('browser', now=800)['action'], 'discover')
        self.assertEqual(restarted.status()['next_due_at'], 1400)
        restarted.configure(True, now=900)
        self.assertEqual(restarted.status()['next_due_at'], 1400)

    def test_two_minute_schedule_does_not_overlap_an_active_run(self):
        self.scheduler.configure(True, now=100, interval_minutes=2)
        self.assertEqual(self.scheduler.status()['next_due_at'], 220)
        run = self.scheduler.tick('browser', now=220)
        self.assertEqual(self.scheduler.status()['next_due_at'], 340)
        self.assertEqual(self.scheduler.tick('browser', now=340)['run_id'], run['run_id'])
        self.assertEqual(self.scheduler.status()['next_due_at'], 340)
        self.scheduler.discover(run['run_id'], 'browser', [], [], now=341)
        self.assertNotEqual(self.scheduler.tick('browser', now=342)['run_id'], run['run_id'])

    def article(self):
        run = self.start()
        step = self.scheduler.discover(run['run_id'], 'browser', ['first', 'second'], [], now=7310)
        return step

    def test_first_run_waits_two_hours_and_restart_preserves_plan(self):
        self.scheduler.configure(True, now=100)
        self.assertEqual(self.scheduler.tick('browser', now=7299)['action'], 'idle')
        self.assertEqual(Scheduler(self.path).tick('browser', now=7300)['action'], 'discover')
        self.assertEqual(self.scheduler.status()['next_due_at'], 14500)

    def test_repeated_enable_does_not_postpone_schedule(self):
        self.scheduler.configure(True, now=100)
        self.scheduler.configure(True, now=1000)
        self.assertEqual(self.scheduler.status()['next_due_at'], 7300)

    def test_parallel_browser_cannot_claim_live_task(self):
        first = self.start()
        self.assertEqual(self.scheduler.tick('other', now=7301)['action'], 'busy')
        recovered = Scheduler(self.path).tick('browser', now=7302)
        self.assertEqual(first['run_id'], recovered['run_id'])

    def test_one_article_only_and_duplicate_result_is_idempotent(self):
        step = self.article()
        calls = []
        def callback(run):
            calls.append(run['url'])
            return {'saved': True, 'status': 'body_candidate'}
        self.scheduler.finish(step['run_id'], 'browser', callback, now=7320)
        self.scheduler.finish(step['run_id'], 'browser', callback, now=7321)
        self.assertEqual(calls, ['first'])
        self.assertEqual(self.scheduler.tick('browser', now=7322)['action'], 'idle')
        run = self.scheduler.tick('browser', now=14500)
        next_step = self.scheduler.discover(run['run_id'], 'browser', ['first', 'second'], ['first'], now=14501)
        self.assertEqual(next_step['url'], 'second')

    def test_failed_article_does_not_block_next_new_article(self):
        step = self.article()
        self.scheduler.finish(step['run_id'], 'browser', lambda _: {'saved': False, 'status': 'needs_body_inspection'}, now=7320)
        run = self.scheduler.tick('browser', now=14500)
        step = self.scheduler.discover(run['run_id'], 'browser', ['first', 'second'], [], now=14501)
        self.assertEqual(step['url'], 'second')

    def test_auth_pause_requires_resume(self):
        step = self.article()
        self.scheduler.finish(step['run_id'], 'browser', lambda _: {'saved': False, 'status': 'subscription_gate'}, now=7320)
        self.assertEqual(self.scheduler.tick('browser', now=14500)['pause_reason'], 'paused_auth')
        self.scheduler.configure(True, now=15000)
        self.assertEqual(self.scheduler.status()['next_due_at'], 22200)

    def test_stop_rejects_late_result(self):
        step = self.article()
        self.scheduler.configure(False, now=7315)
        with self.assertRaises(ValueError):
            self.scheduler.finish(step['run_id'], 'browser', lambda _: self.fail('must not write'), now=7320)

    def test_expired_owner_cannot_submit_after_takeover(self):
        run = self.start()
        self.scheduler.tick('other', now=7421)
        with self.assertRaises(ValueError):
            self.scheduler.discover(run['run_id'], 'browser', ['first'], [], now=7422)

    def test_resume_after_sleep_does_not_replay_missed_cycles(self):
        self.scheduler.configure(True, now=100)
        run = self.scheduler.tick('browser', now=100000)
        self.assertEqual(self.scheduler.status()['next_due_at'], 107200)
        self.scheduler.discover(run['run_id'], 'browser', [], [], now=100001)
        self.assertEqual(self.scheduler.tick('browser', now=100002)['action'], 'idle')

    def test_columns_rotate_under_one_global_two_hour_budget(self):
        columns = [{'id': 'tech', 'url': 'https://www.bloomberg.com/technology', 'enabled': True},
                   {'id': 'finance', 'url': 'https://www.bloomberg.com/industries/finance', 'enabled': True}]
        self.scheduler.configure(True, now=100)
        first = self.scheduler.tick('browser', now=7300, columns=columns)
        self.assertEqual(first['column'], 'tech')
        self.scheduler.discover(first['run_id'], 'browser', [], [], now=7301)
        self.assertEqual(self.scheduler.tick('browser', now=7302, columns=columns)['action'], 'idle')
        second = self.scheduler.tick('browser', now=14500, columns=columns)
        self.assertEqual(second['column'], 'finance')

    def test_column_queue_does_not_claim_another_columns_article(self):
        self.article()
        self.scheduler.configure(False, now=7311)
        columns = [{'id': 'finance', 'url': 'https://www.bloomberg.com/industries/finance', 'enabled': True}]
        run = self.scheduler.tick('browser', immediate=True, now=7312, columns=columns, column='finance')
        result = self.scheduler.discover(run['run_id'], 'browser', ['finance-only'], [], now=7313)
        self.assertEqual(result['url'], 'finance-only')

    def test_interactive_feature_does_not_consume_article_attempt(self):
        run = self.start()
        feature = 'https://www.bloomberg.com/features/2026-special-story'
        news = 'https://www.bloomberg.com/news/articles/2026-10-07/example'
        step = self.scheduler.discover(run['run_id'], 'browser', [feature, news], [], now=7310)
        self.assertEqual(step['url'], news)
        with self.scheduler.transaction() as db:
            row = db.execute('SELECT state,attempts FROM candidates WHERE url=?', (feature,)).fetchone()
            self.assertEqual((row['state'], row['attempts']), ('manual_only', 0))

    def test_current_column_order_beats_inherited_queue_age(self):
        self.article()
        self.scheduler.configure(False, now=7311)
        run = self.scheduler.tick('browser', immediate=True, now=7312)
        step = self.scheduler.discover(run['run_id'], 'browser', ['new-headline', 'second'], [], now=7313)
        self.assertEqual(step['url'], 'new-headline')

    def test_shared_url_is_saved_once_across_columns(self):
        step = self.article()
        self.scheduler.finish(step['run_id'], 'browser', lambda _: {'status': 'body_candidate', 'saved': True}, now=7320)
        columns = [{'id': 'finance', 'url': 'https://www.bloomberg.com/industries/finance', 'enabled': True}]
        run = self.scheduler.tick('browser', immediate=True, now=7400, columns=columns, column='finance')
        result = self.scheduler.discover(run['run_id'], 'browser', ['first'], ['first'], now=7401)
        self.assertEqual(result['status'], 'empty_queue')

    def test_old_database_migrates_queue_and_preserves_last_column(self):
        import sqlite3
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE config (id INTEGER PRIMARY KEY,enabled INTEGER,due REAL,pause TEXT,last_seen REAL);
                INSERT INTO config VALUES (1,1,7300,'',0);
                CREATE TABLE runs (id TEXT PRIMARY KEY,owner TEXT,phase TEXT,started REAL,lease REAL,url TEXT,result TEXT);
                INSERT INTO runs VALUES ('old','browser','completed',100,200,'first','{}');
                CREATE TABLE candidates (url TEXT PRIMARY KEY,first_seen REAL,last_seen REAL,state TEXT,attempts INTEGER DEFAULT 0);
                INSERT INTO candidates VALUES ('first',100,100,'saved',1);
            """)
        db.close()
        self.assertEqual(self.scheduler.status()['last_run']['column_id'], 'tech')
        with self.scheduler.transaction() as db:
            self.assertEqual(db.execute('SELECT column_id FROM candidate_columns').fetchone()[0], 'tech')
            self.assertEqual(db.execute('SELECT last_column FROM config').fetchone()[0], 'tech')


if __name__ == '__main__':
    unittest.main()
