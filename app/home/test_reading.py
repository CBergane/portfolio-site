from datetime import date, datetime, timezone
from types import SimpleNamespace

from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from wagtail.models import Page, PageViewRestriction, Site

from .models import BlogIndexPage, BlogPage, HomePage, ProjectIndexPage, ProjectPage
from .navigation import adjacent_content, site_destinations
from .reading import reading_minutes, visible_text


class ReadingTimeTests(SimpleTestCase):
    def page(self, *blocks, **fields):
        return SimpleNamespace(body=[SimpleNamespace(block_type=kind, value=value) for kind, value in blocks], **fields)

    def test_html_ignores_markup_and_navigation(self):
        page = self.page(('rich_text', '<p>' + 'word ' * 200 + '</p><nav>' + 'link ' * 500 + '</nav>'))
        self.assertEqual(reading_minutes(page), 1)
        self.assertEqual(visible_text('<p>One &amp; two</p><script>ignore()</script>'), 'One & two')

    def test_markdown_counts_visible_labels_not_urls_or_syntax(self):
        page = self.page(('markdown', '[word](https://example.com/a/long/address) ' * 201))
        self.assertEqual(reading_minutes(page), 2)
        self.assertEqual(reading_minutes(self.page(('markdown', '## **Short**\n\nA `small` note.'))), 1)

    def test_empty_and_short_content(self):
        self.assertEqual(reading_minutes(self.page()), 0)
        self.assertEqual(reading_minutes(self.page(('markdown', ' \n---\n'))), 0)
        self.assertEqual(reading_minutes(self.page(('heading', 'One'))), 1)

    def test_rounding_is_ceiling_at_200_words(self):
        for count, expected in ((1, 1), (200, 1), (201, 2), (400, 2), (401, 3)):
            with self.subTest(words=count):
                self.assertEqual(reading_minutes(self.page(('markdown', 'word ' * count))), expected)

    def test_structured_content_and_project_prose_share_estimate(self):
        page = self.page(('code', {'code': 'token ' * 100, 'language': 'python'}),
                         ('quote', {'quote': 'word ' * 90, 'author': 'Author'}),
                         ('image', {'image': 12345, 'caption': 'word ' * 10}),
                         problem='<p>Problem</p>', solution='<p>Solution</p>')
        self.assertEqual(reading_minutes(page), 2)

    def test_estimate_ignores_saved_reading_time_and_intro_without_writing(self):
        page = BlogPage(title='Title', intro='word ' * 100, reading_time=99,
                        body=[('markdown', 'word ' * 201)])
        self.assertEqual(reading_minutes(page), 2)
        self.assertEqual(page.reading_time, 99)

class ReadingTimePersistenceTests(TestCase):
    def setUp(self):
        self.home = Page.get_first_root_node().add_child(
            instance=HomePage(title='Reading time', slug='reading-time')
        )
        self.index = self.home.add_child(
            instance=BlogIndexPage(title='Notes', slug='notes')
        )

    def test_blog_save_uses_shared_reading_time_estimator(self):
        page = BlogPage(
            title='Reading estimate',
            slug='reading-estimate',
            intro='Intro text is metadata and should not affect reading time.',
            reading_time=99,
            body=[
                ('markdown', 'word ' * 201),
            ],
        )

        page = self.index.add_child(instance=page)
        page.refresh_from_db()

        self.assertEqual(page.reading_time, 2)
        self.assertEqual(reading_minutes(page), 2)


@override_settings(ALLOWED_HOSTS=['testserver', 'other.example', 'nested.example'])
class ReadingNavigationTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/', HTTP_HOST='testserver')
        Site.objects.all().delete()
        self.home = Page.get_first_root_node().add_child(instance=HomePage(title='Reading', slug='reading'))
        Site.objects.create(hostname='testserver', root_page=self.home, is_default_site=True)
        self.kinds = ((BlogPage, BlogIndexPage, 'notes'), (ProjectPage, ProjectIndexPage, 'work'))

    def index(self, model, slug, parent=None):
        return (parent or self.home).add_child(instance=model(title=slug, slug=slug))

    def entry(self, model, parent, slug, day=2, **kwargs):
        return parent.add_child(instance=model(title=slug, slug=slug, intro='Summary',
                                               date=date(2026, 1, day), **kwargs))

    def neighbors(self, page):
        return adjacent_content(self.request, page)

    def test_both_types_resolve_previous_next_first_last_and_single(self):
        for model, index_model, key in self.kinds:
            with self.subTest(kind=key):
                index = self.index(index_model, key)
                first = self.entry(model, index, 'first', 1)
                self.assertEqual(self.neighbors(first), {'previous': None, 'next': None})
                middle = self.entry(model, index, 'middle', 2)
                last = self.entry(model, index, 'last', 3)
                self.assertEqual(self.neighbors(middle), {'previous': first, 'next': last})
                self.assertEqual(self.neighbors(first), {'previous': None, 'next': middle})
                self.assertEqual(self.neighbors(last), {'previous': middle, 'next': None})

    def test_live_public_and_inherited_privacy_filtering(self):
        for model, index_model, key in self.kinds:
            with self.subTest(kind=key):
                index = self.index(index_model, key)
                first = self.entry(model, index, 'first', 1)
                draft = self.entry(model, index, 'draft', 2, live=False)
                private = self.entry(model, index, 'private', 2)
                PageViewRestriction.objects.create(page=private, restriction_type='password', password='test')
                folder = index.add_child(instance=Page(title='Private folder', slug='private-folder'))
                PageViewRestriction.objects.create(page=folder, restriction_type='login')
                self.entry(model, folder, 'inherited-private', 2)
                last = self.entry(model, index, 'last', 3)
                self.assertEqual(self.neighbors(first)['next'], last)
                self.assertEqual(self.neighbors(last)['previous'], first)
                self.assertEqual(self.neighbors(draft), {'previous': None, 'next': None})
                self.assertEqual(self.neighbors(private), {'previous': None, 'next': None})

    def test_date_publication_and_pk_ties_are_deterministic(self):
        for model, index_model, key in self.kinds:
            with self.subTest(kind=key):
                index = self.index(index_model, key)
                timestamp = datetime(2026, 1, 2, tzinfo=timezone.utc)
                a = self.entry(model, index, 'z-title', first_published_at=timestamp)
                b = self.entry(model, index, 'a-title', first_published_at=timestamp)
                earlier = self.entry(model, index, 'earlier-publication', first_published_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
                missing = self.entry(model, index, 'missing-publication')
                self.assertEqual(self.neighbors(a), {'previous': earlier, 'next': b})
                self.assertEqual(self.neighbors(earlier)['previous'], missing)
                self.assertIsNone(self.neighbors(b)['next'])

    def test_other_and_nested_sites_never_supply_neighbors(self):
        other = self.index(HomePage, 'other', self.home.get_parent())
        Site.objects.create(hostname='other.example', root_page=other)
        for model, index_model, key in self.kinds:
            with self.subTest(kind=key):
                index = self.index(index_model, key)
                current = self.entry(model, index, 'current')
                other_index = self.index(index_model, key, other)
                self.entry(model, other_index, 'foreign', 3)
                nested = self.index(HomePage, key + '-nested', index)
                Site.objects.create(hostname='nested.example', port=81 if key == 'work' else 80, root_page=nested)
                self.entry(model, nested, 'nested-entry', 3)
                self.assertEqual(self.neighbors(current), {'previous': None, 'next': None})

    def test_nested_and_sibling_indexes_own_their_entries(self):
        for model, index_model, key in self.kinds:
            with self.subTest(kind=key):
                index = self.index(index_model, key)
                current = self.entry(model, index, 'current')
                nested = self.index(index_model, 'nested', index)
                nested_entry = self.entry(model, nested, 'nested-entry', 3)
                sibling = self.index(index_model, key + '-other')
                self.entry(model, sibling, 'sibling-entry', 3)
                self.assertEqual(self.neighbors(current), {'previous': None, 'next': None})
                self.assertEqual(self.neighbors(nested_entry), {'previous': None, 'next': None})

    def test_legacy_siblings_share_resolved_fallback_index(self):
        for model, index_model, key in self.kinds:
            with self.subTest(kind=key):
                legacy = self.entry(model, self.home, key + '-legacy', 1)
                index = self.index(index_model, key)
                nested = self.entry(model, index, 'new', 2)
                self.assertEqual(site_destinations(self.request, legacy)[key], index)
                self.assertEqual(self.neighbors(legacy)['next'], nested)

    def test_missing_private_and_draft_indexes_omit_controls(self):
        for model, index_model, key in self.kinds:
            with self.subTest(kind=key):
                current = self.entry(model, self.home, key + '-entry')
                self.entry(model, self.home, key + '-other', 3)
                self.assertEqual(self.neighbors(current), {'previous': None, 'next': None})
                self.home.add_child(instance=index_model(title='Draft', slug=key + '-draft', live=False))
                private = self.index(index_model, key + '-private')
                PageViewRestriction.objects.create(page=private, restriction_type='login')
                self.assertEqual(self.neighbors(current), {'previous': None, 'next': None})
                self.assertEqual(adjacent_content(None, current), {'previous': None, 'next': None})

    def test_templates_have_shared_hooks_safe_content_and_correct_index_links(self):
        for model, index_model, key in self.kinds:
            with self.subTest(kind=key):
                index = self.index(index_model, key)
                current = self.entry(model, index, 'current', 1, body=[
                    ('heading', '<img src=x onerror=alert(1)>'),
                    ('code', {'language': 'html', 'code': '<h2>Not a heading</h2>'}),
                ])
                neighbor = self.entry(model, index, 'next', 3)
                neighbor.title = '<script>unsafe()</script>'
                neighbor.save()
                html = render_to_string(current.get_template(self.request), current.get_context(self.request), request=self.request)
                soup = BeautifulSoup(html, 'html.parser')
                self.assertEqual(len(soup.select('[data-reading-body]')), 1)
                self.assertEqual(len(soup.select('nav[aria-label="On this page"]')), 1)
                self.assertTrue(soup.select('[data-reading-nav][hidden]'))
                self.assertEqual(len(soup.select('script[src="/static/js/reading.js"]')), 1)
                self.assertFalse(soup.select('[data-reading-body] img, pre h2, .reading-neighbor script'))
                self.assertEqual(soup.select_one('.reading-neighbor')['href'], neighbor.get_url(request=self.request))
                back = '.blog-page__breadcrumb a, .blog-page__aside > a' if key == 'notes' else '.project-page__breadcrumb a, .project-page__back-link'
                self.assertEqual([a['href'] for a in soup.select(back)], [index.get_url(request=self.request)] * 2)
                ids = [element['id'] for element in soup.select('[id]')]
                self.assertEqual(len(ids), len(set(ids)))
