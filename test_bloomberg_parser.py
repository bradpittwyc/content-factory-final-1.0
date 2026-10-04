import json
import unittest

from bloomberg_bulk import article_url
from bloomberg_store import parse_bloomberg_html


class BloombergParserTests(unittest.TestCase):
    def story(self, metadata=None, body_class="b-article-body"):
        paragraphs = "".join(
            f"<p>Paragraph {i} " + "This is a detailed sentence about financial markets. " * 6 + "</p>"
            for i in range(4)
        )
        return (
            '<h1>Story title</h1>'
            f'<script type="application/ld+json">{json.dumps(metadata or {})}</script>'
            f'<article class="{body_class}">{paragraphs}</article>'
            '<aside><p>RECOMMENDATION SHOULD NOT APPEAR ' + 'unrelated content ' * 50 + '</p></aside>'
        )

    def test_body_excludes_recommendations_and_preserves_metadata(self):
        metadata = {
            "@type": "ReportageNewsArticle", "datePublished": "2026-10-01T12:00:00Z",
            "author": [{"name": "Reuters"}], "isAccessibleForFree": True
        }
        article = parse_bloomberg_html(self.story(metadata), "https://www.bnnbloomberg.ca/story/")
        self.assertEqual(article["paragraph_count"], 4)
        self.assertNotIn("RECOMMENDATION", " ".join(article["paragraphs"]))
        self.assertEqual(article["published_at"], metadata["datePublished"])
        self.assertEqual(article["authors"], ["Reuters"])

    def test_missing_body_does_not_accept_page_paragraphs(self):
        self.assertIsNone(parse_bloomberg_html(self.story(body_class="recommendations"), "https://example.com"))

    def test_paywalled_or_short_article_is_rejected(self):
        self.assertIsNone(parse_bloomberg_html(self.story({"@type": "NewsArticle", "isAccessibleForFree": False}), "https://example.com"))
        self.assertIsNone(parse_bloomberg_html('<h1>Title</h1><article class="b-article-body"><p>Short text</p></article>', "https://example.com"))

    def test_unknown_publication_date_is_not_fabricated(self):
        article = parse_bloomberg_html(self.story(), "https://example.com")
        self.assertIsNone(article["published_at"])
        self.assertEqual(article["authors"], [])

    def test_url_normalization_limits_discovery_to_stories(self):
        self.assertEqual(article_url('/business/2026/10/01/story/?utm_source=test'), 'https://www.bnnbloomberg.ca/business/2026/10/01/story/')
        self.assertIsNone(article_url('https://example.com/business/2026/10/01/story/'))
        self.assertIsNone(article_url('/video/2026/10/01/clip/'))
        self.assertIsNone(article_url('/faq/2026/10/01/help/'))
        self.assertIsNone(article_url('/press-releases/2026/10/01/company-announcement/'))
        self.assertIsNone(article_url('/investment-trends/2026/10/01/sponsored-story/'))
        self.assertIsNone(article_url('/business/'))


if __name__ == '__main__':
    unittest.main()
