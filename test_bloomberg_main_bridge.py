import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import bloomberg_main_bridge as bridge

from bloomberg_main_bridge import BodyBlock, Capture, normalize_main_url, validate_capture


class MainBridgeTests(unittest.TestCase):
    url = 'https://www.bloomberg.com/news/articles/2026-10-04/example'

    def test_rejects_other_sources_and_homepage(self):
        for url in ('https://www.bnnbloomberg.ca/business/2026/10/04/example/', 'https://www.bloomberg.com/'):
            with self.assertRaises(ValueError):
                normalize_main_url(url)

    def test_verification_and_subscription_gate_are_not_article_successes(self):
        self.assertEqual(validate_capture(Capture(url=self.url, blocked=True))[1], 'blocked')
        self.assertEqual(validate_capture(Capture(url=self.url, gated=True))[1], 'subscription_gate')

    def test_body_requires_matching_container_and_substantial_paragraphs(self):
        paragraphs = ['This is a long sentence about markets and financial news. ' * 5] * 4
        missing_container = Capture(url=self.url, title='Title', paragraphs=paragraphs)
        self.assertEqual(validate_capture(missing_container)[1], 'needs_body_inspection')
        body = missing_container.model_copy(update={'body_selector': '.body-copy'})
        self.assertEqual(validate_capture(body)[1], 'body_candidate')

    def test_related_reading_is_excluded_from_body(self):
        paragraphs = ['This is a long sentence about markets and financial news. ' * 5] * 4
        paragraphs.insert(1, 'Read More: Another article that is not part of this story')
        capture = Capture(url=self.url, title='Title', paragraphs=paragraphs, body_selector='.body-content')
        _, state, cleaned = validate_capture(capture)
        self.assertEqual(state, 'body_candidate')
        self.assertEqual(len(cleaned), 4)
        self.assertFalse(any(p.startswith('Read More:') for p in cleaned))

    def test_short_paragraphs_and_list_items_are_preserved(self):
        blocks = [BodyBlock(kind='p', text='This is a long sentence about financial markets. ' * 6) for _ in range(4)]
        blocks.extend([BodyBlock(kind='h2', text='Stocks to watch'), BodyBlock(kind='li', text='Company A'), BodyBlock(kind='li', text='Company B'), BodyBlock(kind='p', text='A brief conclusion.')])
        capture = Capture(url=self.url, title='Title', body_selector='.body-content', body_blocks=blocks, capture_version=2)
        _, state, cleaned = validate_capture(capture)
        self.assertEqual(state, 'body_candidate')
        self.assertEqual(cleaned[-4:], ['Stocks to watch', 'Company A', 'Company B', 'A brief conclusion.'])

    def test_live_dom_extraction_keeps_lists_without_duplicate_nested_text(self):
        from pathlib import Path
        from playwright.sync_api import sync_playwright
        source = (Path(__file__).parent / 'bloomberg_main_extension' / 'worker.js').read_text(encoding='utf-8')
        function = source[source.index('function extractArticle()'):source.index('function extractTechLinks()')].strip()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page()
            page.set_content('<h1>Title</h1><div class="body-content"><p>A brief paragraph.</p><h2>Stocks to watch</h2><ul><li>Company A</li><li><p>Company B</p></li></ul><p><a href="https://www.bloomberg.com/news/articles/2026-10-04/other">Related article without prefix</a></p></div>')
            result = page.evaluate('(' + function + ')()')
            browser.close()
        self.assertEqual(result['paragraphs'], ['A brief paragraph.', 'Stocks to watch', 'Company A', 'Company B'])
        self.assertEqual(result['capture_version'], 2)

    def test_tech_dom_uses_article_links_in_content_and_deduplicates(self):
        from playwright.sync_api import sync_playwright
        source = (Path(__file__).parent / 'bloomberg_main_extension' / 'worker.js').read_text(encoding='utf-8')
        function = source[source.index('function extractTechLinks()'):source.index('async function captureTab')].strip()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page()
            page.set_content('<header><a href="https://www.bloomberg.com/news/articles/2026-10-05/unrelated">Unrelated</a></header><main><a href="https://www.bloomberg.com/news/articles/2026-10-05/ai?tracking=1">AI news</a><a href="https://www.bloomberg.com/news/articles/2026-10-05/ai">Duplicate</a><a href="https://www.bloomberg.com/news/newsletters/2026-10-05/tech-in-depth">Tech newsletter</a><a href="https://www.bnnbloomberg.ca/business/2026/10/05/other">Other site</a><a href="https://www.bloomberg.com/news/videos/2026-10-05/clip">Video</a></main>')
            result = page.evaluate('(' + function + ')()')
            browser.close()
        self.assertEqual([link['title'] for link in result['links']], ['AI news', 'Tech newsletter'])

    def test_dom_uses_current_body_before_longer_adjacent_article(self):
        from playwright.sync_api import sync_playwright
        source = (Path(__file__).parent / 'bloomberg_main_extension' / 'worker.js').read_text(encoding='utf-8')
        function = source[source.index('function extractArticle()'):source.index('function extractTechLinks()')].strip()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page()
            page.set_content('<h1>Current story</h1><div class="body-content"><p>Current article body.</p><h3><a href="https://www.bloomberg.com/news/articles/2026-10-05/related">Related headline</a></h3></div><div class="body-content"><p>' + 'Wrong adjacent article body. ' * 100 + '</p></div>')
            result = page.evaluate('(' + function + ')()')
            browser.close()
        self.assertEqual(result['paragraphs'], ['Current article body.'])


class TechQueueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.overrides = patch.multiple(bridge, STORE=root / 'articles.json', INBOX=root / 'inbox', COLUMN_DIR=root / 'columns')
        self.overrides.start()
        self.addCleanup(self.overrides.stop)

    def discovery(self):
        return bridge.ColumnDiscovery(url='https://www.bloomberg.com/technology', links=[
            bridge.ColumnLink(url='https://www.bloomberg.com/news/articles/2026-10-05/ai', title='AI'),
            bridge.ColumnLink(url='https://www.bloomberg.com/news/articles/2026-10-05/ai?tracking=1', title='Duplicate'),
            bridge.ColumnLink(url='https://www.bloomberg.com/news/newsletters/2026-10-05/tech-in-depth', title='Newsletter'),
            bridge.ColumnLink(url='https://www.bnnbloomberg.ca/business/2026/10/05/other')])

    def test_queue_uses_only_discovered_column_and_skips_updated_capture(self):
        result = bridge.discover_column('tech', self.discovery())
        self.assertEqual(result['candidate_count'], 2)
        articles = bridge.queue(column='tech')['articles']
        self.assertEqual(len(articles), 2)
        paragraphs = ['A substantial paragraph about technology and financial markets. ' * 6] * 4
        capture = bridge.Capture(url=articles[0]['url'], title='AI', paragraphs=paragraphs, body_selector='.body-content', capture_version=2, column='tech')
        self.assertTrue(bridge.capture_article(capture)['saved'])
        stored = json.loads(bridge.STORE.read_text(encoding='utf-8'))
        self.assertEqual(stored[0]['columns'], ['tech'])
        self.assertEqual(len(bridge.queue(column='tech')['articles']), 1)

    def test_column_capture_rejects_article_outside_discovered_queue(self):
        from fastapi import HTTPException
        bridge.discover_column('tech', self.discovery())
        with self.assertRaises(HTTPException) as error:
            bridge.capture_article(bridge.Capture(url='https://www.bloomberg.com/news/articles/2026-10-05/politics', column='tech'))
        self.assertEqual(error.exception.status_code, 400)

    def test_wrong_column_page_and_robot_screen_do_not_create_queue(self):
        from fastapi import HTTPException
        for discovery in [bridge.ColumnDiscovery(url='https://www.bloomberg.com/markets'), bridge.ColumnDiscovery(url='https://www.bloomberg.com/technology', blocked=True)]:
            with self.assertRaises(HTTPException):
                bridge.discover_column('tech', discovery)
        self.assertFalse(bridge.COLUMN_DIR.exists())

    def test_duplicate_body_under_different_url_is_not_saved(self):
        first = 'https://www.bloomberg.com/news/articles/2026-10-05/first'
        second = 'https://www.bloomberg.com/news/articles/2026-10-05/second'
        paragraphs = ['A substantial paragraph about technology and financial markets. ' * 6] * 4
        capture = bridge.Capture(url=first, title='First story', paragraphs=paragraphs, body_selector='.body-content', capture_version=2)
        self.assertTrue(bridge.capture_article(capture)['saved'])
        output = bridge.capture_article(capture.model_copy(update={'url': second, 'title': 'Different story'}))
        self.assertEqual(output, {'status': 'duplicate_body', 'saved': False})
        self.assertEqual(len(json.loads(bridge.STORE.read_text(encoding='utf-8'))), 1)


if __name__ == '__main__':
    unittest.main()
