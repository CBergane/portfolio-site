"""Rendered SEO and crawl endpoints use public, site-owned content only."""
from io import BytesIO
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from PIL import Image
from wagtail.images import get_image_model
from wagtail.models import (
    Collection, CollectionViewRestriction, Page, PageViewRestriction, Site,
)

from ..models import (
    BlogCategory, BlogIndexPage, BlogPage, ContactPage, HomePage, LabPage,
    ProjectIndexPage, ProjectPage, SEOSettings,
)


@override_settings(ALLOWED_HOSTS=['testserver', 'nested.example', 'other.example', 'alias.example'])
class PublicSEOTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cache.clear()
        Site.objects.all().delete()
        cls.home = cls.publish(Page.get_first_root_node(), HomePage(title='Home', slug='portfolio'))
        cls.site = Site.objects.create(hostname='testserver', root_page=cls.home, is_default_site=True)
        cls.seo = SEOSettings.objects.create(site=cls.site)
        cls.work = cls.publish(cls.home, ProjectIndexPage(title='Projects', slug='projects'))
        cls.notes = cls.publish(cls.home, BlogIndexPage(title='Blog', slug='blog'))
        cls.lab = cls.publish(cls.home, LabPage(title='Lab', slug='lab'))
        cls.contact = cls.publish(cls.home, ContactPage(title='Contact', slug='contact'))
        cls.project = cls.publish(cls.work, ProjectPage(
            title='Security project', slug='security-project', intro='A controlled security experiment.',
        ))
        category = BlogCategory.objects.create(name='Research', slug='research')
        for number in range(10):
            cls.publish(cls.notes, BlogPage(
                title=f'Note {number}', slug=f'note-{number}', intro='A technical note.', categories=category,
            ))

    @staticmethod
    def publish(parent, page):
        parent.add_child(instance=page)
        page.save_revision().publish()
        return page

    def html(self, page, query='', **request_options):
        response = self.client.get(page.get_url() + query, **request_options)
        self.assertEqual(response.status_code, 200)
        return BeautifulSoup(response.content, 'html.parser')

    def render(self, page, *, preview=False):
        request = RequestFactory().get(page.get_url(), HTTP_HOST='testserver')
        request.is_preview = preview
        return BeautifulSoup(render_to_string(
            page.get_template(request), page.get_context(request), request=request,
        ), 'html.parser')

    def image(self, collection=None):
        buffer = BytesIO()
        Image.new('RGB', (1200, 630), '#242b33').save(buffer, format='PNG')
        image = get_image_model().objects.create(
            title='Synthetic share image',
            collection=collection or Collection.get_first_root_node(),
            file=SimpleUploadedFile('share.png', buffer.getvalue(), content_type='image/png'),
        )
        self.seo.og_image = image
        self.seo.save()
        return image

    def locations(self, **request_options):
        response = self.client.get('/sitemap.xml', **request_options)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/xml')
        xml = ElementTree.fromstring(response.content)
        return [node.text for node in xml.findall('{*}url/{*}loc')]

    def test_page_specific_seo_is_used_in_all_metadata(self):
        self.project.seo_title = 'Security assessment & engineering'
        self.project.search_description = 'Controlled assessment with clear scope and limitations.'
        self.project.save_revision().publish()
        soup = self.html(self.project)
        title = 'Security assessment & engineering | Christian Bergane - Portfolio'
        self.assertEqual(soup.title.get_text(), title)
        for key in ('og:title', 'twitter:title'):
            self.assertEqual(soup.find('meta', attrs={'property' if key.startswith('og:') else 'name': key})['content'], title)
        for key in ('description', 'og:description', 'twitter:description'):
            self.assertEqual(soup.find('meta', attrs={'property' if key.startswith('og:') else 'name': key})['content'],
                             self.project.search_description)

    def test_homepage_has_current_default_seo_without_writing_settings(self):
        original = self.seo.meta_description
        soup = self.html(self.home)
        self.assertIn('IT Security, Infrastructure & Web Development', soup.title.get_text())
        description = soup.find('meta', attrs={'name': 'description'})['content']
        self.assertTrue(description.startswith('IT Security'))
        self.assertNotIn('Site Reliability Engineer', description)
        self.assertIsNone(soup.find('meta', attrs={'name': 'keywords'}))
        self.seo.refresh_from_db()
        self.assertEqual(self.seo.meta_description, original)

    def test_custom_shared_description_remains_an_editorial_choice(self):
        self.seo.meta_description = 'An owner-authored site description.'
        self.seo.save()
        soup = self.html(self.lab)
        self.assertEqual(soup.find('meta', attrs={'name': 'description'})['content'], self.seo.meta_description)

    def test_intro_is_a_plain_text_fallback_and_metadata_is_escaped(self):
        self.project.intro = '<strong>Security</strong> & engineering ' + 'detail ' * 30
        self.project.seo_title = 'A "quoted" <title>'
        self.project.save_revision().publish()
        soup = self.html(self.project)
        description = soup.find('meta', attrs={'name': 'description'})['content']
        self.assertTrue(description.startswith('Security & engineering'))
        self.assertLessEqual(len(description), 160)
        self.assertNotIn('<strong>', description)
        self.assertEqual(len(soup.find_all('title')), 1)
        self.assertIn('A "quoted" <title>', soup.title.get_text())

    def test_canonical_and_open_graph_url_ignore_tracking_and_arbitrary_queries(self):
        soup = self.html(self.project, '?utm_source=audit&next=https://other.example/')
        expected = 'http://testserver/projects/security-project/'
        self.assertEqual(soup.find('link', rel='canonical')['href'], expected)
        self.assertEqual(soup.find('meta', property='og:url')['content'], expected)

    def test_canonical_uses_the_configured_site_host_and_forwarded_https(self):
        soup = self.html(self.home, HTTP_HOST='alias.example', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(soup.find('link', rel='canonical')['href'], 'https://testserver/')

    def test_unfiltered_notes_pagination_has_its_own_canonical(self):
        soup = self.html(self.notes, '?page=2&utm_source=audit')
        expected = 'http://testserver/blog/?page=2'
        self.assertEqual(soup.find('link', rel='canonical')['href'], expected)
        self.assertEqual(soup.find('meta', property='og:url')['content'], expected)

    def test_invalid_or_first_page_canonical_matches_the_rendered_page(self):
        for query, suffix in (('?page=invalid', ''), ('?page=1', ''), ('?page=999', '?page=2')):
            with self.subTest(query=query):
                soup = self.html(self.notes, query)
                self.assertEqual(soup.find('link', rel='canonical')['href'], 'http://testserver/blog/' + suffix)

    def test_filtered_indexes_are_followable_without_an_incorrect_canonical(self):
        for page, query in ((self.work, '?tech=python'), (self.work, '?category=security'),
                            (self.work, '?status=ongoing'), (self.notes, '?category=research&page=2'),
                            (self.notes, '?tag=python')):
            with self.subTest(page=page.title, query=query):
                soup = self.html(page, query)
                self.assertEqual(soup.find('meta', attrs={'name': 'robots'})['content'], 'noindex,follow')
                self.assertIsNone(soup.find('link', rel='canonical'))

    def test_empty_filters_do_not_disable_indexing(self):
        for page in (self.work, self.notes):
            soup = self.html(page, '?category=&tech=&status=&tag=')
            self.assertIsNotNone(soup.find('link', rel='canonical'))
            self.assertIsNone(soup.find('meta', attrs={'name': 'robots'}))

    def test_configured_public_share_image_is_used_for_both_cards(self):
        image = self.image()
        soup = self.html(self.home, HTTP_X_FORWARDED_PROTO='https')
        og = soup.find('meta', property='og:image')
        self.assertTrue(og['content'].startswith('https://testserver/media/'))
        self.assertEqual(soup.find('meta', attrs={'name': 'twitter:image'})['content'], og['content'])
        self.assertEqual(soup.find('meta', property='og:image:alt')['content'], image.title)
        self.assertEqual(soup.find('meta', attrs={'name': 'twitter:card'})['content'], 'summary_large_image')

    def test_missing_share_image_uses_a_summary_card(self):
        soup = self.html(self.home)
        self.assertIsNone(soup.find('meta', property='og:image'))
        self.assertEqual(soup.find('meta', attrs={'name': 'twitter:card'})['content'], 'summary')

    def test_missing_image_file_does_not_break_public_page_rendering(self):
        cache.clear()
        image = self.image()
        image.file.storage.delete(image.file.name)
        soup = self.html(self.home)
        self.assertIsNone(soup.find('meta', property='og:image'))
        self.assertEqual(soup.find('meta', attrs={'name': 'twitter:card'})['content'], 'summary')

    def test_inherited_private_image_collection_never_creates_or_exposes_a_rendition(self):
        parent = Collection.get_first_root_node().add_child(name='Private images')
        child = parent.add_child(name='Inherited private images')
        image = self.image(child)
        for restriction_type in ('login', 'password', 'groups'):
            with self.subTest(restriction_type=restriction_type):
                restriction = CollectionViewRestriction.objects.create(
                    collection=parent, restriction_type=restriction_type, password='synthetic',
                )
                soup = self.html(self.home)
                self.assertIsNone(soup.find('meta', property='og:image'))
                self.assertIsNone(soup.find('meta', attrs={'name': 'twitter:image'}))
                self.assertFalse(image.renditions.exists())
                restriction.delete()

    def test_explicitly_public_image_collection_is_allowed(self):
        collection = Collection.get_first_root_node().add_child(name='Public images')
        CollectionViewRestriction.objects.create(collection=collection, restriction_type='none')
        self.image(collection)
        self.assertIsNotNone(self.html(self.home).find('meta', property='og:image'))

    def test_private_draft_and_preview_pages_do_not_publish_discovery_metadata(self):
        image = self.image()
        PageViewRestriction.objects.create(page=self.home, restriction_type='login')
        for page, preview in ((self.home, False), (self.project, False), (self.project, True)):
            with self.subTest(page=page.title, preview=preview):
                soup = self.render(page, preview=preview)
                self.assertIsNone(soup.find('link', rel='canonical'))
                self.assertIsNone(soup.find('meta', property='og:image'))
                self.assertIsNone(soup.find('meta', property='og:url'))
                self.assertEqual(soup.find('meta', attrs={'name': 'robots'})['content'], 'noindex,nofollow')
        PageViewRestriction.objects.all().delete()
        self.project.live = False
        soup = self.render(self.project)
        self.assertIsNone(soup.find('link', rel='canonical'))
        self.assertIsNone(soup.find('meta', property='og:image'))
        self.assertFalse(image.renditions.exists())

    def test_preview_of_a_public_page_does_not_create_a_share_rendition(self):
        image = self.image()
        soup = self.render(self.home, preview=True)
        self.assertIsNone(soup.find('link', rel='canonical'))
        self.assertIsNone(soup.find('meta', property='og:image'))
        self.assertFalse(image.renditions.exists())

    def test_draft_project_image_is_not_used_as_an_automatic_share_image(self):
        image = self.image()
        self.seo.og_image = None
        self.seo.save()
        self.project.hero_image = image
        self.project.save_revision()
        self.project.unpublish()
        self.assertIsNone(self.html(self.home).find('meta', property='og:image'))
        self.assertFalse(image.renditions.exists())

    def test_sitemap_is_valid_xml_and_contains_public_pages(self):
        locations = self.locations()
        self.assertIn('http://testserver/', locations)
        self.assertIn('http://testserver/projects/security-project/', locations)
        self.assertEqual(len(locations), len(set(locations)))

    def test_sitemap_excludes_drafts_and_inherited_private_pages(self):
        self.work.add_child(instance=ProjectPage(title='Draft', slug='draft', intro='Hidden', live=False))
        PageViewRestriction.objects.create(page=self.work, restriction_type='login')
        locations = self.locations()
        self.assertFalse(any('/projects/' in url for url in locations))
        self.assertIn('http://testserver/blog/', locations)

    def test_sitemaps_are_isolated_from_other_and_nested_sites(self):
        nested = self.publish(self.home, HomePage(title='Nested', slug='nested'))
        Site.objects.create(hostname='nested.example', root_page=nested)
        nested_lab = self.publish(nested, LabPage(title='Nested lab', slug='lab'))
        other = self.publish(self.home.get_parent(), HomePage(title='Other', slug='other'))
        Site.objects.create(hostname='other.example', root_page=other)
        self.assertFalse(any('nested' in url or 'other' in url for url in self.locations()))
        self.assertEqual(set(self.locations(HTTP_HOST='nested.example')),
                         {'http://nested.example/', 'http://nested.example/lab/'})
        self.assertEqual(nested_lab.get_parent().pk, nested.pk)

    def test_sitemap_respects_forwarded_https(self):
        self.assertTrue(all(url.startswith('https://testserver/')
                            for url in self.locations(HTTP_X_FORWARDED_PROTO='https')))

    def test_fully_private_site_has_an_empty_valid_sitemap(self):
        PageViewRestriction.objects.create(page=self.home, restriction_type='login')
        self.assertEqual(self.locations(), [])

    def test_robots_is_plain_text_and_announces_the_existing_sitemap_route(self):
        response = self.client.get('/robots.txt', HTTP_HOST='testserver', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain; charset=utf-8')
        text = response.content.decode()
        self.assertIn('User-agent: *\nAllow: /', text)
        self.assertIn('Sitemap: https://testserver/sitemap.xml', text)
        for path in ('/cms-backend-2025/', '/secret-django-control/', '/documents/'):
            self.assertIn('Disallow: ' + path, text)
        self.assertNotIn('Disallow: /\n', text)

    def test_robots_supports_head_and_rejects_post(self):
        self.assertEqual(self.client.head('/robots.txt').status_code, 200)
        self.assertEqual(self.client.post('/robots.txt').status_code, 405)

    def test_robots_and_sitemap_preserve_a_script_prefix(self):
        from django.urls import get_script_prefix, set_script_prefix

        previous = get_script_prefix()
        try:
            set_script_prefix('/portfolio/')
            request = RequestFactory().get('/portfolio/robots.txt', HTTP_HOST='testserver')
            from ..views import robots
            self.assertIn('Sitemap: http://testserver/portfolio/sitemap.xml', robots(request).content.decode())
            self.assertTrue(all('/portfolio/' in url for url in self.locations()))
        finally:
            set_script_prefix(previous)

    def test_professional_hierarchy_and_historical_background_are_rendered(self):
        soup = self.html(self.home)
        self.assertEqual(soup.select_one('.site-brand__descriptor').get_text(strip=True),
                         'IT SECURITY / INFRASTRUCTURE / WEB DEVELOPMENT')
        self.assertIn('IT Security, grounded in infrastructure.', soup.select_one('.signal-hero__statement').get_text())
        self.assertIn('Information security and infrastructure', soup.select_one('.hero-meta').get_text())
        self.assertEqual(soup.select_one('#signal-title').get_text(strip=True), 'Learning informs the work.')
        self.assertEqual([heading.get_text() for heading in soup.select('.capability h3')],
                         ['IT Security', 'Infrastructure', 'Web Development'])
        intro = soup.select_one('.position-section__copy').get_text(' ', strip=True)
        self.assertIn('previous SRE experience', intro)
        self.assertIn('professional kitchens', intro)
        self.assertIn('IT Security', intro)
        self.assertIn('IT Security', soup.select_one('.site-footer__identity').get_text())
        self.assertIn('IT Security, infrastructure or secure web development', self.html(self.contact).get_text())

    def test_existing_editorial_home_body_and_contact_intro_are_preserved(self):
        self.home.body = '<p>Owner-authored background.</p>'
        self.home.save_revision().publish()
        self.contact.intro = '<p>Owner-authored contact invitation.</p>'
        self.contact.save_revision().publish()
        self.assertIn('Owner-authored background.', self.html(self.home).get_text())
        soup = self.html(self.contact)
        self.assertIn('Owner-authored contact invitation.', soup.get_text())
        self.assertNotIn('For IT Security, infrastructure or secure web development', soup.get_text())
