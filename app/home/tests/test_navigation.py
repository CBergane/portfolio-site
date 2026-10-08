"""Navigation behavior and regression tests."""
from datetime import date

from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from wagtail.models import Page, PageViewRestriction, Site

from ..models import (
    BlogIndexPage, BlogPage, ContactPage, HomePage, HomePageProject, ProjectIndexPage, ProjectPage,
)
from ..navigation import public_site_pages, site_destinations
from ..templatetags.navigation_tags import main_navigation


class NavigationResolutionTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/', HTTP_HOST='testserver')
        root = Page.get_first_root_node()
        Site.objects.filter(is_default_site=True).update(is_default_site=False)
        self.home = HomePage(title='Home', slug='navigation-home')
        root.add_child(instance=self.home)
        self.home.save_revision().publish()
        Site.objects.create(hostname='testserver', port=80, root_page=self.home, is_default_site=True)
        self.work = ProjectIndexPage(title='A localized title', slug='navigation-work')
        self.home.add_child(instance=self.work)
        self.work.save_revision().publish()
        self.notes = BlogIndexPage(title='Another localized title', slug='navigation-notes')
        self.home.add_child(instance=self.notes)
        self.notes.save_revision().publish()
        self.contact = ContactPage(title='Reach out', slug='navigation-contact')
        self.home.add_child(instance=self.contact)
        self.contact.save_revision().publish()

    @override_settings(TURNSTILE_SITE_KEY='public-test-key', TURNSTILE_SECRET_KEY='private-test-key')
    def test_turnstile_is_contact_only_and_exposes_only_the_site_key(self):
        from bs4 import BeautifulSoup

        context = self.contact.get_context(self.request)
        self.assertEqual(context['turnstile_site_key'], 'public-test-key')
        html = render_to_string('home/contact_page.html', context, request=self.request)
        soup = BeautifulSoup(html, 'html.parser')
        widget = soup.select_one('#contact-form .cf-turnstile')
        self.assertEqual(widget['data-sitekey'], 'public-test-key')
        self.assertEqual(widget['data-action'], 'contact')
        self.assertEqual(widget['data-refresh-expired'], 'auto')
        self.assertIsNotNone(soup.select_one('script[src="https://challenges.cloudflare.com/turnstile/v0/api.js"]'))
        self.assertNotIn('private-test-key', html)
        home_html = render_to_string('home/home_page.html', self.home.get_context(self.request), request=self.request)
        self.assertNotIn('challenges.cloudflare.com/turnstile', home_html)
        self.assertNotIn('public-test-key', home_html)
        context['form_submitted'] = True
        success_html = render_to_string('home/contact_page.html', context, request=self.request)
        self.assertNotIn('challenges.cloudflare.com/turnstile', success_html)

    def test_navigation_uses_fixed_labels_and_marks_project_descendants_active(self):
        project = ProjectPage(title='Case study', slug='navigation-case-study', intro='Summary', date=date(2026, 1, 1), live=False)
        self.work.add_child(instance=project)
        project.save_revision().publish()

        items = main_navigation({'request': self.request, 'page': project})['nav_items']

        self.assertEqual([item['label'] for item in items], ['WORK', 'ABOUT', 'NOTES', 'CONTACT'])
        self.assertTrue(items[0]['is_active'])
        self.assertFalse(items[2]['is_active'])
        self.assertTrue(items[1]['url'].endswith('#operating-principle'))

    def items(self, page=None):
        return main_navigation({'request': self.request, 'page': page or self.home})['nav_items']

    def test_notes_and_contact_activate_only_their_own_branches(self):
        note = BlogPage(title='A note', slug='a-note', intro='Summary')
        self.notes.add_child(instance=note)
        child = Page(title='Contact details', slug='details')
        self.contact.add_child(instance=child)
        for current, expected in ((note, 'NOTES'), (self.contact, 'CONTACT'), (child, 'CONTACT')):
            with self.subTest(expected=expected, page=current.title):
                self.assertEqual([item['label'] for item in self.items(current) if item['is_active']], [expected])

    def test_homepage_does_not_claim_about_is_the_current_page(self):
        self.assertFalse(any(item['is_active'] for item in self.items()))

    def test_destinations_do_not_depend_on_titles_slugs_or_direct_parent(self):
        folder = Page(title='Container', slug='container')
        self.home.add_child(instance=folder)
        self.work.move(folder, pos='last-child')
        self.work.refresh_from_db()
        self.work.title = 'Renamed archive'
        self.work.slug = 'a-different-address'
        self.work.save()
        work = next(item for item in self.items() if item['label'] == 'WORK')
        self.assertEqual(work['url'], self.work.get_url(request=self.request))

    def test_drafts_and_private_branches_are_omitted(self):
        self.work.unpublish()
        PageViewRestriction.objects.create(page=self.notes, restriction_type='password', password='test')
        self.assertEqual([item['label'] for item in self.items()], ['ABOUT', 'CONTACT'])

    def test_absent_optional_pages_do_not_render_empty_links(self):
        for page in (self.work, self.notes, self.contact):
            page.unpublish()
        rendered = render_to_string('home/home_page.html', {'page': self.home}, request=self.request)
        self.assertNotIn('href=""', rendered)
        self.assertNotIn('Start a conversation', rendered)
        self.assertNotIn('All projects', rendered)
        self.assertEqual([item['label'] for item in self.items()], ['ABOUT'])

    def test_another_site_cannot_supply_missing_destinations_or_content(self):
        other = HomePage(title='Other site', slug='other-site')
        self.home.get_parent().add_child(instance=other)
        Site.objects.create(hostname='other.example', root_page=other)
        other_work = ProjectIndexPage(title='Work', slug='work')
        other.add_child(instance=other_work)
        project = ProjectPage(title='Other project', slug='other-project', intro='Summary')
        other_work.add_child(instance=project)
        other_notes = BlogIndexPage(title='Notes', slug='notes')
        other.add_child(instance=other_notes)
        note = BlogPage(title='Other note', slug='other-note', intro='Summary')
        other_notes.add_child(instance=note)
        for page in (self.work, self.notes, self.contact):
            page.unpublish()
        HomePageProject.objects.create(home_page=self.home, project=project)
        self.assertEqual([item['label'] for item in self.items()], ['ABOUT'])
        context = self.home.get_context(self.request)
        self.assertIsNone(context['primary_project'])
        self.assertEqual(context['published_project_count'], 0)
        self.assertEqual(context['published_note_count'], 0)

    def test_nested_sites_own_their_subtrees(self):
        nested = HomePage(title='Nested site', slug='nested')
        self.home.add_child(instance=nested)
        Site.objects.create(hostname='nested.example', root_page=nested)
        nested_work = ProjectIndexPage(title='Nested work', slug='nested-work')
        nested.add_child(instance=nested_work)
        project = ProjectPage(title='Nested project', slug='nested-project', intro='Summary')
        nested_work.add_child(instance=project)
        self.work.unpublish()
        self.assertNotIn('WORK', [item['label'] for item in self.items()])
        self.assertFalse(public_site_pages(ProjectPage, self.request).exists())

    def test_index_queries_are_limited_to_their_branch(self):
        second_work = ProjectIndexPage(title='Second archive', slug='second-archive')
        self.home.add_child(instance=second_work)
        second_notes = BlogIndexPage(title='Second notes', slug='second-notes')
        self.home.add_child(instance=second_notes)
        project = ProjectPage(title='Second project', slug='second-project', intro='Summary')
        second_work.add_child(instance=project)
        note = BlogPage(title='Second note', slug='second-note', intro='Summary')
        second_notes.add_child(instance=note)
        self.assertEqual(list(self.work.get_context(self.request)['projects']), [])
        self.assertEqual(list(self.notes.get_context(self.request)['posts']), [])
        self.assertEqual(site_destinations(self.request, project)['work'].pk, second_work.pk)
        self.assertEqual(site_destinations(self.request, note)['notes'].pk, second_notes.pk)

    def test_site_root_with_a_url_prefix_is_used_for_brand_and_about(self):
        from django.urls import get_script_prefix, set_script_prefix

        previous = get_script_prefix()
        try:
            set_script_prefix('/portfolio/')
            request = RequestFactory().get('/portfolio/', HTTP_HOST='testserver')
            items = main_navigation({'request': request, 'page': self.home})['nav_items']
            self.assertEqual(next(item['url'] for item in items if item['label'] == 'ABOUT'),
                             '/portfolio/#operating-principle')
            rendered = render_to_string('home/home_page.html', {'page': self.home}, request=request)
            self.assertIn('href="/portfolio/" class="site-brand"', rendered)
        finally:
            set_script_prefix(previous)

    def test_private_content_is_excluded_from_homepage_selection_and_registry(self):
        project = ProjectPage(title='Private project', slug='private-project', intro='Summary')
        self.work.add_child(instance=project)
        PageViewRestriction.objects.create(page=project, restriction_type='password', password='test')
        HomePageProject.objects.create(home_page=self.home, project=project)
        context = self.home.get_context(self.request)
        self.assertIsNone(context['primary_project'])
        self.assertIsNone(context['latest_project'])
        self.assertEqual(context['published_project_count'], 0)

    def test_rendered_foundation_has_unique_ids_and_accessible_icons(self):
        from bs4 import BeautifulSoup
        from pathlib import Path
        from django.template.loader import get_template

        for path in (Path(__file__).parents[1] / 'templates').rglob('*.html'):
            get_template(path.relative_to(Path(__file__).parents[1] / 'templates').as_posix())
        context = self.home.get_context(self.request)
        rendered = render_to_string('home/home_page.html', context, request=self.request)
        soup = BeautifulSoup(rendered, 'html.parser')
        ids = [element['id'] for element in soup.select('[id]')]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(soup.select('.system-blueprint'))
        for svg in soup.select('svg'):
            self.assertTrue(svg.get('viewbox'))
            self.assertEqual(svg.get('aria-hidden'), 'true')
        for link in soup.select('a'):
            self.assertTrue(link.get('href'))
            if link.get('href', '').startswith('/'):
                self.assertNotEqual(link.get('target'), '_blank')
            if link.get('target') == '_blank':
                self.assertTrue({'noopener', 'noreferrer'}.issubset(link.get('rel', [])))
        self.assertFalse(soup.select('#mobile-menu[hidden]'))
        self.assertTrue(soup.select('#mobile-menu-btn[hidden]'))

    def test_home_hero_keeps_responsive_art_decorative_and_content_semantic(self):
        from bs4 import BeautifulSoup
        from django.contrib.staticfiles import finders

        rendered = render_to_string('home/home_page.html', self.home.get_context(self.request),
                                    request=self.request)
        soup = BeautifulSoup(rendered, 'html.parser')
        hero = soup.select_one('#overview')
        self.assertIn('signal-hero__grid', hero.find('div', recursive=False)['class'])
        art = hero.select_one('.hero-art')
        self.assertEqual(art['aria-hidden'], 'true')
        picture = art
        self.assertEqual(picture.name, 'picture')
        sources = picture.select('source')
        self.assertEqual([source['type'] for source in sources], ['image/avif', 'image/webp'])
        image = picture.img
        self.assertEqual(image['alt'], '')
        self.assertEqual(image['loading'], 'eager')
        self.assertEqual(image['fetchpriority'], 'high')
        self.assertEqual((image['width'], image['height']), ('1916', '821'))
        for source in [*sources, image]:
            candidates = [candidate.strip().split() for candidate in source['srcset'].split(',')]
            self.assertEqual([size for _, size in candidates], ['960w', '1600w', '1916w'])
            for url, _ in candidates:
                self.assertIsNotNone(finders.find(url.removeprefix('/static/')))
            self.assertEqual(source['sizes'], image['sizes'])
        self.assertNotIn('.png', str(picture))
        self.assertIsNone(art.svg)
        self.assertFalse(art.select('text, a, button, [tabindex]'))
        self.assertEqual(hero.h1.get_text(' ', strip=True), 'Christian Bergane')
        self.assertIn('IT Security, grounded in infrastructure.', hero.get_text())
        self.assertIn('IT Security, Infrastructure, Web Development', hero.get_text())
        self.assertIsNone(art.find(id='hero-title'))
        self.assertEqual(hero.select_one('.signal-hero__actions a')['href'], '#selected-systems')
        self.assertEqual(hero.select('.signal-hero__actions a')[1]['href'], self.contact.get_url(self.request))
        section_ids = ['overview', 'selected-systems', 'operating-principle', 'capabilities', 'current-signal']
        self.assertEqual([link['href'] for link in soup.select('.section-rail a')],
                         ['#' + section_id for section_id in section_ids])
        for section_id in section_ids:
            self.assertIsNotNone(soup.find('section', id=section_id))
        self.assertIsNotNone(soup.select_one('script[src$="js/home.js"]'))

    def test_no_request_has_no_fabricated_navigation(self):
        self.assertEqual(main_navigation({})['nav_items'], [])


@override_settings(ALLOWED_HOSTS=['testserver', 'work.example', 'notes.example',
                                'nested-site.example', 'other-site.example'])
class DetailIndexNavigationTests(TestCase):
    """Legacy sibling details remain siblings; only navigation is resolved."""

    def setUp(self):
        self.request = RequestFactory().get('/', HTTP_HOST='testserver')
        Site.objects.all().delete()
        self.home = Page.get_first_root_node().add_child(
            instance=HomePage(title='Home', slug='detail-navigation')
        )
        self.site = Site.objects.create(
            hostname='testserver', root_page=self.home, is_default_site=True
        )
        self.cases = (
            (ProjectPage, ProjectIndexPage, 'work', 'home/project_page.html',
             '.project-page__breadcrumb a, .project-page__back-link'),
            (BlogPage, BlogIndexPage, 'notes', 'home/blog_page.html',
             '.blog-page__breadcrumb a, .blog-page__aside > a'),
        )

    def add(self, parent, model, slug, **kwargs):
        return parent.add_child(instance=model(title=slug, slug=slug, **kwargs))

    def assert_destination(self, case, detail, expected, request=None):
        from bs4 import BeautifulSoup

        _, _, key, template, selector = case
        request = request or self.request
        self.assertEqual(site_destinations(request, detail)[key], expected)
        rendered = render_to_string(template, detail.get_context(request), request=request)
        soup = BeautifulSoup(rendered, 'html.parser')
        links = soup.select(selector)
        if expected is None:
            self.assertEqual(links, [])
        else:
            self.assertEqual(len(links), 2)
            self.assertEqual([link['href'] for link in links],
                             [expected.get_url(request=request)] * 2)
        root_url = Site.find_for_request(request).root_page.get_url(request=request)
        for link in links + soup.select('[data-nav-label="WORK"], [data-nav-label="NOTES"]'):
            self.assertNotEqual(link['href'], root_url)
            self.assertNotEqual(link.get('target'), '_blank')

    def test_correctly_nested_project_page(self):
        case = self.cases[0]
        index = self.add(self.home, case[1], 'engineering-archive')
        detail = self.add(index, case[0], 'case-study', intro='Summary')
        self.assert_destination(case, detail, index)

    def test_correctly_nested_blog_page(self):
        case = self.cases[1]
        index = self.add(self.home, case[1], 'field-journal')
        detail = self.add(index, case[0], 'entry', intro='Summary')
        self.assert_destination(case, detail, index)

    def test_legacy_project_sibling_uses_site_index_without_moving(self):
        case = self.cases[0]
        detail = self.add(self.home, case[0], 'testing', intro='Summary')
        index = self.add(self.home, case[1], 'engineering-archive')
        self.assert_destination(case, detail, index)
        detail.refresh_from_db()
        self.assertEqual(detail.get_parent().pk, self.home.pk)

    def test_legacy_blog_sibling_uses_site_index_without_moving(self):
        case = self.cases[1]
        detail = self.add(self.home, case[0], 'testing-notes', intro='Summary')
        index = self.add(self.home, case[1], 'field-journal')
        self.assert_destination(case, detail, index)
        detail.refresh_from_db()
        self.assertEqual(detail.get_parent().pk, self.home.pk)

    def test_nearest_matching_ancestor_wins_over_site_default_and_parent(self):
        for case in self.cases:
            with self.subTest(kind=case[2]):
                outer = self.add(self.home, case[1], case[2] + '-outer')
                nearest = self.add(outer, case[1], 'nearest')
                folder = self.add(nearest, Page, 'folder')
                detail = self.add(folder, case[0], 'detail', intro='Summary')
                self.assert_destination(case, detail, nearest)

    def test_missing_indexes_omit_breadcrumb_and_back_links(self):
        for case in self.cases:
            with self.subTest(kind=case[2]):
                detail = self.add(self.home, case[0], case[2] + '-detail', intro='Summary')
                self.assert_destination(case, detail, None)

    def test_draft_or_private_indexes_cannot_supply_fallback(self):
        for case in self.cases:
            with self.subTest(kind=case[2]):
                self.add(self.home, case[1], case[2] + '-draft', live=False)
                private = self.add(self.home, case[1], case[2] + '-private')
                PageViewRestriction.objects.create(page=private, restriction_type='password', password='test')
                detail = self.add(self.home, case[0], case[2] + '-detail', intro='Summary')
                self.assert_destination(case, detail, None)

    def test_invalid_nearest_ancestor_uses_valid_site_fallback(self):
        for case in self.cases:
            for state in ('draft', 'private'):
                with self.subTest(kind=case[2], state=state):
                    fallback = self.add(self.home, case[1], case[2] + '-' + state)
                    invalid = self.add(fallback, case[1], 'invalid', live=state != 'draft')
                    if state == 'private':
                        PageViewRestriction.objects.create(page=invalid, restriction_type='password', password='test')
                    detail = self.add(invalid, case[0], 'detail', intro='Summary')
                    self.assert_destination(case, detail, fallback)

    def test_multiple_sites_cannot_supply_missing_indexes(self):
        for nested in (False, True):
            other = self.add(self.home if nested else self.home.get_parent(), HomePage,
                             'nested-site' if nested else 'other-site')
            Site.objects.create(hostname=other.slug + '.example', root_page=other)
            for case in self.cases:
                with self.subTest(kind=case[2], nested=nested):
                    other_index = self.add(other, case[1], case[2] + '-archive')
                    detail = self.add(self.home, case[0], other.slug + '-' + case[2], intro='Summary')
                    self.assert_destination(case, detail, None)
                    other_detail = self.add(other, case[0], case[2] + '-detail', intro='Summary')
                    request = RequestFactory().get('/', HTTP_HOST=other.slug + '.example')
                    self.assert_destination(case, other_detail, other_index, request)

    def test_nested_site_detail_cannot_use_outer_site_ancestor(self):
        for case in self.cases:
            with self.subTest(kind=case[2]):
                outer = self.add(self.home, case[1], case[2] + '-outer')
                nested = self.add(outer, HomePage, 'nested')
                Site.objects.create(hostname=case[2] + '.example', root_page=nested)
                detail = self.add(nested, case[0], 'detail', intro='Summary')
                request = RequestFactory().get('/', HTTP_HOST=case[2] + '.example')
                self.assert_destination(case, detail, None, request)
                own_index = self.add(nested, case[1], 'own-archive')
                self.assert_destination(case, detail, own_index, request)

    def test_index_typed_site_root_never_renders_under_index_label(self):
        for case in self.cases:
            with self.subTest(kind=case[2]):
                index_root = self.add(self.home, case[1], case[2] + '-site-root')
                Site.objects.create(hostname=case[2] + '.example', root_page=index_root)
                detail = self.add(index_root, case[0], 'detail', intro='Summary')
                request = RequestFactory().get('/', HTTP_HOST=case[2] + '.example')
                self.assert_destination(case, detail, None, request)
