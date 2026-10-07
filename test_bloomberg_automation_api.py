import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import bloomberg_main_bridge as bridge
from bloomberg_tech_scheduler import Scheduler


class AutomationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for name, value in {
            'DATA': root, 'STORE': root / 'articles.json', 'INBOX': root / 'inbox',
            'COLUMN_DIR': root / 'columns', 'SCHEDULER': Scheduler(root / 'scheduler.sqlite3')
        }.items():
            mock = patch.object(bridge, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.client = TestClient(bridge.app)
        self.url = 'https://www.bloomberg.com/news/articles/2026-10-07/example'

    def post(self, action, **values):
        return self.client.post('/automation/tech/' + action, json={'owner': 'browser', **values})

    def claim(self):
        step = self.post('tick', immediate=True).json()
        step = self.post('discovery', run_id=step['run_id'], discovery={
            'url': 'https://www.bloomberg.com/technology', 'links': [{'url': self.url}]
        }).json()
        self.assertEqual(step['action'], 'article')
        return step['run_id']

    def capture(self, published):
        return {'url': self.url, 'title': 'Tech article', 'published_at': published,
                'paragraphs': ['Technology research and markets are changing rapidly. ' * 7] * 4,
                'body_selector': '.body-content', 'capture_version': 2}

    def test_save_receipt_replay_and_expected_url(self):
        run = self.claim()
        capture = self.capture(datetime.now(timezone.utc).isoformat())
        wrong = {**capture, 'url': self.url + '-wrong'}
        self.assertEqual(self.post('result', run_id=run, capture=wrong).status_code, 409)
        first = self.post('result', run_id=run, capture=capture)
        self.assertTrue(first.json()['saved'])
        self.assertEqual(first.json(), self.post('result', run_id=run, capture=capture).json())
        stored = json.loads(bridge.STORE.read_text(encoding='utf-8'))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]['automation_attempt_id'], run)

    def test_old_article_not_saved(self):
        run = self.claim()
        result = self.post('result', run_id=run, capture=self.capture((datetime.now(timezone.utc) - timedelta(hours=73)).isoformat()))
        self.assertEqual(result.json()['status'], 'expired')
        self.assertFalse(bridge.STORE.exists())

    def test_missing_publication_time_requires_review(self):
        run = self.claim()
        self.assertEqual(self.post('result', run_id=run, capture=self.capture(None)).json()['status'], 'missing_date')

    def test_discovery_failure_keeps_stage_and_detail(self):
        step = self.post('tick', immediate=True, column='finance').json()
        result = self.post('result', run_id=step['run_id'], error='network_error',
                           error_detail='discovery HTTP 422: No supported article links found').json()
        self.assertFalse(result['saved'])
        self.assertEqual(result['stage'], 'discover')
        self.assertIn('HTTP 422', result['detail'])
        self.assertEqual(json.loads(bridge.SCHEDULER.status()['last_run']['result']), result)

    def test_webpage_cannot_change_schedule(self):
        response = self.client.post('/automation/tech/settings', headers={'Origin': 'https://example.com'},
                                    json={'owner': 'browser', 'enabled': True})
        self.assertEqual(response.status_code, 403)

    def test_discovery_subscription_gate_pauses(self):
        run = self.post('tick', immediate=True).json()['run_id']
        result = self.post('discovery', run_id=run, discovery={'url': 'https://www.bloomberg.com/technology', 'gated': True})
        self.assertEqual(result.json()['status'], 'subscription_gate')
        self.assertEqual(bridge.SCHEDULER.status()['pause_reason'], 'paused_auth')

    def test_finance_capture_preserves_takeaways_and_merges_memberships(self):
        catalog = self.client.get('/columns').json()['columns']
        self.assertEqual({c['id'] for c in catalog}, {'tech', 'finance', 'economics', 'bigtake', 'ai-today'})
        run = self.post('tick', immediate=True, column='finance').json()
        self.assertEqual(run['column'], 'finance')
        wrong = self.post('discovery', run_id=run['run_id'], discovery={
            'url': 'https://www.bloomberg.com/technology', 'links': [{'url': self.url}]})
        self.assertEqual(wrong.status_code, 400)
        self.post('discovery', run_id=run['run_id'], discovery={
            'url': 'https://www.bloomberg.com/industries/finance', 'links': [{'url': self.url}]})
        capture = {**self.capture(datetime.now(timezone.utc).isoformat()),
                   'takeaways': ['A separate AI summary.'], 'takeaways_source': 'Bloomberg AI',
                   'takeaways_status': 'captured', 'takeaways_capture_version': 1}
        self.assertTrue(self.post('result', run_id=run['run_id'], capture=capture).json()['saved'])
        bridge.discover_column('economics', bridge.ColumnDiscovery(url='https://www.bloomberg.com/economics', links=[bridge.ColumnLink(url=self.url)]))
        article = json.loads(bridge.STORE.read_text(encoding='utf-8'))[0]
        self.assertEqual(article['columns'], ['economics', 'finance'])
        self.assertEqual(article['takeaways'], ['A separate AI summary.'])
        self.assertEqual(article['word_count'], sum(len(p.split()) for p in capture['paragraphs']))
        self.assertEqual(bridge.queue('economics')['articles'], [])

    def test_column_configuration_rejects_external_or_article_urls(self):
        for url in ['https://example.com/markets', self.url, 'https://www.bloomberg.com:443/markets']:
            response = self.client.post('/columns/configure', json={'name': 'Invalid', 'url': url})
            self.assertEqual(response.status_code, 400)
        response = self.client.post('/columns/configure', json={'name': 'Markets', 'url': 'https://www.bloomberg.com/markets'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('markets', [item['id'] for item in response.json()['columns']])
        self.assertEqual(self.client.get('/queue?column=../unknown').status_code, 404)

    def test_ai_today_requires_discovered_editions_before_enabling(self):
        ai = next(item for item in self.client.get('/columns').json()['columns'] if item['id'] == 'ai-today')
        self.assertFalse(ai['enabled'])
        self.assertEqual(self.client.post('/columns/configure', json={**ai, 'enabled': True}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
