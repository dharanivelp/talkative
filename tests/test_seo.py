import unittest
from unittest.mock import patch

from talkative_backend.application import create_app
from talkative_backend.backend import auth


class SeoTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(initialize=False)
        self.client = self.app.test_client()

    def test_homepage_includes_search_and_social_metadata(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<meta name="description"', response.data)
        self.assertIn(b'<link rel="canonical" href="https://talkative.space/">', response.data)
        self.assertIn(b'<meta property="og:title"', response.data)
        self.assertIn(b"Meet people through conversations", response.data)

    def test_sitemap_lists_only_public_pages(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.mimetype, "application/xml")
        self.assertIn(b"https://talkative.space/terms", response.data)
        self.assertIn(b"https://talkative.space/privacy", response.data)
        self.assertNotIn(b"/account", response.data)

    def test_robots_disallows_crawling_in_nonproduction(self):
        with patch.object(auth, "APP_ENV", "development"):
            response = self.client.get("/robots.txt")
        self.assertEqual(response.mimetype, "text/plain")
        self.assertIn(b"Disallow: /", response.data)
        self.assertNotIn(b"Sitemap:", response.data)

    def test_production_robots_excludes_private_routes_and_links_sitemap(self):
        with patch.object(auth, "APP_ENV", "production"):
            response = self.client.get("/robots.txt")
        self.assertIn(b"Disallow: /account", response.data)
        self.assertIn(b"Disallow: /admin", response.data)
        self.assertIn(b"Disallow: /api/", response.data)
        self.assertIn(b"Sitemap: https://talkative.space/sitemap.xml", response.data)


if __name__ == "__main__":
    unittest.main()
