import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import wsj_store as store


class WsjStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, value in [('DATA', root), ('STORE', root / 'articles.json'), ('QUEUE', root / 'queue.json')]:
            mock = patch.object(store, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        app = FastAPI()
        app.include_router(store.router)
        self.client = TestClient(app)
        self.url = 'https://www.wsj.com/tech/ai/example-1234abcd'
        self.payload = {'url': self.url, 'title': 'Example WSJ article', 'body_selector': '.article-content',
                        'body_blocks': [{'kind': 'p', 'text': f'Paragraph {i}. ' + 'Technology research continues. ' * 16} for i in range(4)]}

    def test_capture_dedup_and_short_body(self):
        response = self.client.post('/wsj/capture', json=self.payload).json()
        self.assertTrue(response['saved'])
        self.assertFalse(store.load_articles()[0]['full_text_reviewed'])
        self.assertTrue(self.client.post('/wsj/capture', json=self.payload).json()['saved'])
        self.assertEqual(len(store.load_articles()), 1)
        duplicate = {**self.payload, 'url': self.url.replace('1234abcd', '5678abcd')}
        self.assertEqual(self.client.post('/wsj/capture', json=duplicate).json()['status'], 'duplicate_body')
        short = {**duplicate, 'body_blocks': [{'kind': 'p', 'text': 'A preview.'}]}
        self.assertEqual(self.client.post('/wsj/capture', json=short).json()['status'], 'insufficient_body')

    def test_subscription_and_source_validation(self):
        self.assertFalse(self.client.post('/wsj/capture', json={**self.payload, 'gated': True}).json()['saved'])
        self.assertFalse(store.STORE.exists())
        for url in ['https://www.wsj.com/tech', 'https://www.wsj.com.evil.test/tech/example-1234abcd']:
            self.assertEqual(self.client.post('/wsj/capture', json={**self.payload, 'url': url}).status_code, 400)
        self.assertEqual(self.client.post('/wsj/capture', json=self.payload, headers={'Origin': 'https://evil.test'}).status_code, 403)

    def test_discovery_queue_isolation_and_saved_membership(self):
        payload = {'url': 'https://www.wsj.com/tech', 'links': [{'url': self.url + '?mod=tech', 'title': 'Example'}]}
        self.assertEqual(self.client.post('/wsj/columns/tech/discover', json=payload).json()['count'], 1)
        self.assertEqual(len(self.client.get('/wsj/queue/tech').json()['articles']), 1)
        self.assertEqual(self.client.get('/wsj/queue/world').json()['articles'], [])
        self.client.post('/wsj/capture', json=self.payload)
        self.assertEqual(store.load_articles()[0]['sections'], ['tech'])
        self.assertEqual(self.client.get('/wsj/queue/tech').json()['articles'], [])
        self.assertEqual(self.client.post('/wsj/columns/tech/discover', json={**payload, 'url': 'https://www.wsj.com/world'}).status_code, 400)

    def test_to_amp_url_conversion(self):
        raw = 'https://www.livemint.com/global/inside-bessent-s-treasury-tension-turnover-and-unmet-economic-goals-11791336031458.html'
        expected = 'https://www.livemint.com/global/inside-bessent-s-treasury-tension-turnover-and-unmet-economic-goals/amp-11791336031458.html'
        self.assertEqual(store.to_amp_url(raw), expected)
        self.assertEqual(store.to_amp_url(expected), expected)

    def test_paste_import_endpoint(self):
        body = "\n\n".join([f"This is paragraph {i} of an important Wall Street Journal analysis. " * 8 for i in range(5)])
        res = self.client.post('/wsj/paste-import', json={
            'title': 'Pasted WSJ Article',
            'full_text': body,
            'url': 'https://www.wsj.com/finance/investing/pasted-article-1234abcd',
            'section': 'finance'
        }).json()
        self.assertTrue(res['success'])
        self.assertEqual(res['article']['section'], 'finance')
        self.assertEqual(len(store.load_articles()), 1)

    def test_retention_auto_purge(self):
        now = datetime.now()
        fresh_art = {
            'url': 'https://www.wsj.com/tech/fresh-1234abcd',
            'title': 'Fresh Article',
            'published_at': now.strftime('%Y-%m-%d %H:%M:%S'),
            'scraped_at': now.strftime('%Y-%m-%d %H:%M:%S')
        }
        old_art = {
            'url': 'https://www.wsj.com/tech/old-1234abcd',
            'title': 'Old Article',
            'published_at': (now - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S'),
            'scraped_at': (now - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')
        }
        store.write_json(store.STORE, [fresh_art, old_art])
        articles = store.load_articles()
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]['title'], 'Fresh Article')


if __name__ == '__main__':
    unittest.main()
