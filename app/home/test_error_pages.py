"""Custom error responses, including rendering during an application failure."""
from unittest.mock import patch

from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import path

from wagtail.models import Page, Site

from .models import ContactPage, HomePage, ProjectIndexPage


def unavailable_view(request):
    raise RuntimeError('Simulated application failure')


urlpatterns = [path('unavailable/', unavailable_view)]


class ErrorMarkupAssertions:
    def assert_error_markup(self, html, code, heading):
        soup = BeautifulSoup(html, 'html.parser')
        self.assertEqual(len(soup.select('main')), 1)
        self.assertEqual(len(soup.select('h1')), 1)
        self.assertEqual(soup.h1.get_text(strip=True), heading)
        self.assertEqual(soup.select_one('.error-page__code').get_text(strip=True), code)
        self.assertEqual(soup.select_one('.error-page')['aria-labelledby'], soup.h1['id'])
        ids = [element['id'] for element in soup.select('[id]')]
        self.assertEqual(len(ids), len(set(ids)))
        diagrams = soup.select('.error-page svg')
        self.assertTrue(diagrams)
        for svg in diagrams:
            self.assertEqual(svg.get('aria-hidden'), 'true')
            self.assertEqual(svg.get('focusable'), 'false')
            self.assertTrue(svg.get('viewbox'))
            self.assertFalse(svg.select('text, image, script, foreignObject'))
        for link in soup.select('.error-page a'):
            self.assertTrue(link.get('href'))
            self.assertTrue(link.get_text(strip=True))
        return soup


@override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False)
class PageNotFoundTests(ErrorMarkupAssertions, TestCase):
    @classmethod
    def setUpTestData(cls):
        Site.objects.all().delete()
        cls.home = Page.get_first_root_node().add_child(
            instance=HomePage(title='Home', slug='error-page-home')
        )
        Site.objects.create(hostname='testserver', root_page=cls.home, is_default_site=True)
        cls.work = cls.home.add_child(instance=ProjectIndexPage(title='Work', slug='selected-work'))
        cls.contact = cls.home.add_child(instance=ContactPage(title='Contact', slug='get-in-touch'))

    def test_missing_route_uses_custom_template_and_site_navigation(self):
        response = self.client.get('/a-route-that-does-not-exist/')

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')
        self.assertTemplateUsed(response, 'base.html')
        self.assertContains(response, 'The requested route could not be resolved.', status_code=404)
        soup = self.assert_error_markup(response.content, '404', 'Page not found.')
        self.assertEqual(soup.select_one('.skip-link')['href'], '#main-content')
        self.assertEqual(soup.select_one('.site-brand')['href'], self.home.url)
        for selector in ('.site-nav--desktop', '.site-nav--mobile'):
            links = {link['href'] for link in soup.select(f'{selector} a')}
            self.assertIn(self.work.url, links)
            self.assertIn(self.contact.url, links)
        recovery = soup.select_one('[aria-label="Error recovery"]')
        self.assertEqual([link['href'] for link in recovery.select('a')],
                         [self.home.url, self.contact.url])

    def test_unpublished_contact_is_omitted_but_home_remains_available(self):
        self.contact.unpublish()
        response = self.client.get('/another-missing-route/')

        self.assertEqual(response.status_code, 404)
        soup = BeautifulSoup(response.content, 'html.parser')
        links = soup.select('.error-page__actions a')
        self.assertEqual([link['href'] for link in links], [self.home.url])
        self.assertNotIn('href=""', response.content.decode())


@override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False)
class ServerErrorTests(ErrorMarkupAssertions, SimpleTestCase):
    # SimpleTestCase forbids database queries, even when the test database exists.
    def assert_server_error_markup(self, html):
        soup = self.assert_error_markup(html, '500', 'Temporarily unavailable.')
        self.assertIn('Please try reloading the page', soup.get_text())
        self.assertIn("browser's back button", soup.get_text())
        self.assertFalse(soup.select('script, img, iframe, .site-nav'))
        self.assertTrue(soup.select_one('link[rel="stylesheet"][href$="css/custom.css"]'))

    def test_template_renders_with_no_context_or_database(self):
        self.assert_server_error_markup(render_to_string('500.html'))

    @override_settings(ROOT_URLCONF=__name__, MIDDLEWARE=[])
    def test_real_500_handler_survives_without_site_navigation_or_request_context(self):
        failure = AssertionError('500 must not depend on application context')
        with (
            patch('wagtail.models.Site.find_for_request', side_effect=failure),
            patch('home.templatetags.navigation_tags.site_for_request', side_effect=failure),
            patch('home.templatetags.navigation_tags.site_destinations', side_effect=failure),
            patch('django.template.context.RequestContext.bind_template', side_effect=failure),
        ):
            response = Client(raise_request_exception=False).get('/unavailable/')

        self.assertEqual(response.status_code, 500)
        self.assertTemplateUsed(response, '500.html')
        self.assertTemplateNotUsed(response, 'base.html')
        self.assert_server_error_markup(response.content)
