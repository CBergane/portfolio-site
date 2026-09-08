import base64
from datetime import date
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, TestCase, override_settings
from django.core.cache import cache
from django.urls import reverse
from wagtail.images import get_image_model
from wagtail.models import Page, PageViewRestriction, Site

from .models import (
    BlogPage, BlogIndexPage, ContactPage, ContactSubmission, HomePage, HomePageProject, ProjectCategory, ProjectIndexPage,
    ProjectPage, ProjectPageTechStack, TechStack,
)
from .templatetags.navigation_tags import main_navigation
from .navigation import public_site_pages, site_destinations


class HomePageProjectSelectionTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/')
        self.root_page = Page.get_first_root_node()
        Site.objects.filter(is_default_site=True).update(is_default_site=False)
        Site.objects.create(
            hostname='testserver',
            port=80,
            root_page=self.root_page,
            is_default_site=True,
        )

        self.home_page = HomePage(title='Portfolio home', slug='portfolio-home')
        self.root_page.add_child(instance=self.home_page)
        self.home_page.save_revision().publish()

        self.project_index = ProjectIndexPage(title='Projects', slug='projects')
        self.home_page.add_child(instance=self.project_index)
        self.project_index.save_revision().publish()
        self.blog_index = BlogIndexPage(title='Notes', slug='notes')
        self.home_page.add_child(instance=self.blog_index)
        self.blog_index.save_revision().publish()

    def create_project(self, title, slug, project_date, published=True):
        project = ProjectPage(
            title=title,
            slug=slug,
            intro=f'{title} intro',
            date=project_date,
            live=False,
        )
        self.project_index.add_child(instance=project)
        revision = project.save_revision()
        if published:
            revision.publish()
        project.refresh_from_db()
        return project

    def create_note(self, title, slug, note_date, published=True):
        note = BlogPage(
            title=title,
            slug=slug,
            intro=f'{title} intro',
            date=note_date,
            live=False,
        )
        self.blog_index.add_child(instance=note)
        revision = note.save_revision()
        if published:
            revision.publish()
        note.refresh_from_db()
        return note

    def get_home_context(self):
        return self.home_page.get_context(self.request)

    def test_selected_projects_follow_editor_order(self):
        first = self.create_project('First selected', 'first-selected', date(2026, 1, 1))
        second = self.create_project('Second selected', 'second-selected', date(2026, 2, 1))
        third = self.create_project('Third selected', 'third-selected', date(2026, 3, 1))
        HomePageProject.objects.create(home_page=self.home_page, project=third, sort_order=0)
        HomePageProject.objects.create(home_page=self.home_page, project=first, sort_order=1)
        HomePageProject.objects.create(home_page=self.home_page, project=second, sort_order=2)

        context = self.get_home_context()

        self.assertEqual(context['primary_project'].pk, third.pk)
        self.assertEqual(
            [project.pk for project in context['supporting_projects']],
            [first.pk, second.pk],
        )

    def test_unpublished_selected_projects_are_excluded(self):
        unpublished = self.create_project(
            'Unpublished selected', 'unpublished-selected', date(2026, 3, 1), published=False
        )
        published = self.create_project('Published selected', 'published-selected', date(2026, 2, 1))
        HomePageProject.objects.create(home_page=self.home_page, project=unpublished, sort_order=0)
        HomePageProject.objects.create(home_page=self.home_page, project=published, sort_order=1)

        unpublished.refresh_from_db()
        published.refresh_from_db()
        self.assertFalse(unpublished.live)
        self.assertFalse(ProjectPage.objects.live().filter(pk=unpublished.pk).exists())
        self.assertFalse(ProjectPage.objects.live().public().filter(pk=unpublished.pk).exists())
        self.assertTrue(published.live)
        self.assertTrue(ProjectPage.objects.live().public().filter(pk=published.pk).exists())

        context = self.get_home_context()

        self.assertEqual(context['primary_project'].pk, published.pk)
        self.assertEqual(context['supporting_projects'], [])

    def test_unselected_homepage_falls_back_to_latest_live_projects(self):
        oldest = self.create_project('Oldest', 'oldest', date(2026, 1, 1))
        middle = self.create_project('Middle', 'middle', date(2026, 2, 1))
        recent = self.create_project('Recent', 'recent', date(2026, 3, 1))
        newest = self.create_project('Newest', 'newest', date(2026, 4, 1))

        context = self.get_home_context()

        self.assertEqual(context['primary_project'].pk, newest.pk)
        self.assertEqual(
            [project.pk for project in context['supporting_projects']],
            [recent.pk, middle.pk],
        )
        self.assertNotIn(oldest.pk, [project.pk for project in context['supporting_projects']])

    def test_homepage_uses_internal_project_page_urls(self):
        project = self.create_project('Internal link', 'internal-link', date(2026, 1, 1))
        HomePageProject.objects.create(home_page=self.home_page, project=project, sort_order=0)
        context = self.get_home_context()
        context['page'] = self.home_page

        rendered = render_to_string('home/home_page.html', context, request=self.request)

        self.assertIn(f'href="{project.get_url(request=self.request)}"', rendered)

    def test_signal_registry_uses_only_live_public_content_and_latest_dates(self):
        self.create_project('Older system', 'older-system', date(2026, 1, 1))
        latest_project = self.create_project('Latest system', 'latest-system', date(2026, 3, 1))
        self.create_project('Draft system', 'draft-system', date(2026, 4, 1), published=False)
        self.create_note('Older note', 'older-note', date(2026, 1, 1))
        latest_note = self.create_note('Latest note', 'latest-note', date(2026, 3, 1))
        self.create_note('Draft note', 'draft-note', date(2026, 4, 1), published=False)

        context = self.get_home_context()
        context['page'] = self.home_page
        rendered = render_to_string('home/home_page.html', context, request=self.request)

        self.assertEqual(context['published_project_count'], 2)
        self.assertEqual(context['published_note_count'], 2)
        self.assertEqual(context['latest_project'].pk, latest_project.pk)
        self.assertEqual(context['latest_note'].pk, latest_note.pk)
        self.assertIn(f'href="{latest_project.get_url(request=self.request)}"', rendered)
        self.assertIn(f'href="{latest_note.get_url(request=self.request)}"', rendered)

    def test_signal_registry_handles_empty_published_content(self):
        context = self.get_home_context()

        self.assertEqual(context['published_project_count'], 0)
        self.assertEqual(context['published_note_count'], 0)
        self.assertIsNone(context['latest_project'])
        self.assertIsNone(context['latest_note'])


class ContactSubmissionTests(TestCase):
    def setUp(self):
        cache.clear()

    def valid_payload(self):
        return {
            'name': 'Ada Lovelace',
            'email': 'ada@example.com',
            'subject': 'Systems review',
            'message': 'I would like to discuss a systems review.',
        }

    @patch('home.views.send_discord_notification')
    def test_valid_contact_submission_is_stored_and_notified(self, notify):
        response = self.client.post(
            reverse('contact_submit'),
            self.valid_payload(),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)
        submission = ContactSubmission.objects.get()
        self.assertEqual(submission.email, 'ada@example.com')
        notify.assert_called_once_with(submission)
        self.assertIn('last_contact_submission', self.client.session)

    @patch('home.views.send_discord_notification')
    def test_short_message_returns_errors_without_creating_submission(self, notify):
        payload = self.valid_payload()
        payload['message'] = 'Too short'

        response = self.client.post(
            reverse('contact_submit'),
            payload,
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['success'], False)
        self.assertIn('message', response.json()['errors'])
        self.assertFalse(ContactSubmission.objects.exists())
        notify.assert_not_called()

    @patch('home.views.send_discord_notification')
    def test_trusted_proxy_uses_forwarded_client_ip(self, notify):
        response = self.client.post(
            reverse('contact_submit'),
            self.valid_payload(),
            secure=True,
            REMOTE_ADDR='10.89.0.4',
            HTTP_X_FORWARDED_FOR='203.0.113.10, 10.89.0.1',
        )

        self.assertEqual(response.status_code, 200)
        submission = ContactSubmission.objects.get()
        self.assertEqual(submission.ip_address, '203.0.113.10')
        notify.assert_called_once_with(submission)

    @patch('home.views.send_discord_notification')
    def test_untrusted_client_cannot_spoof_forwarded_ip(self, notify):
        response = self.client.post(
            reverse('contact_submit'),
            self.valid_payload(),
            secure=True,
            REMOTE_ADDR='198.51.100.25',
            HTTP_X_FORWARDED_FOR='203.0.113.99',
        )

        self.assertEqual(response.status_code, 200)
        submission = ContactSubmission.objects.get()
        self.assertEqual(submission.ip_address, '198.51.100.25')
        notify.assert_called_once_with(submission)

    @patch('home.views.send_discord_notification')
    def test_trusted_proxy_ignores_spoofed_leftmost_forwarded_ip(self, notify):
        response = self.client.post(
            reverse('contact_submit'),
            self.valid_payload(),
            secure=True,
            REMOTE_ADDR='10.89.0.4',
            HTTP_X_FORWARDED_FOR=(
                '192.0.2.123, 203.0.113.10, 10.89.0.1'
            ),
        )

        self.assertEqual(response.status_code, 200)
        submission = ContactSubmission.objects.get()
        self.assertEqual(submission.ip_address, '203.0.113.10')
        notify.assert_called_once_with(submission)

    @patch('home.views.send_discord_notification')
    def test_url_in_name_is_rejected(self, notify):
        payload = self.valid_payload()
        payload['name'] = 'Dear http://cbergane.se/fekal0911 Admin'

        response = self.client.post(
            reverse('contact_submit'),
            payload,
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['success'], False)
        self.assertIn('name', response.json()['errors'])
        self.assertFalse(ContactSubmission.objects.exists())
        notify.assert_not_called()

    @patch('home.views.send_discord_notification')
    def test_honeypot_is_silently_discarded(self, notify):
        payload = self.valid_payload()
        payload['website'] = 'https://spam.example/'

        response = self.client.post(
            reverse('contact_submit'),
            payload,
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)
        self.assertFalse(ContactSubmission.objects.exists())
        notify.assert_not_called()

    @patch('home.views.send_discord_notification')
    def test_rate_limit_is_per_real_client_ip(self, notify):
        url = reverse('contact_submit')

        for _ in range(3):
            client = Client()
            response = client.post(
                url,
                self.valid_payload(),
                secure=True,
                REMOTE_ADDR='10.89.0.4',
                HTTP_X_FORWARDED_FOR='203.0.113.20, 10.89.0.1',
            )
            self.assertEqual(response.status_code, 200)

        fourth_client = Client()
        response = fourth_client.post(
            url,
            self.valid_payload(),
            secure=True,
            REMOTE_ADDR='10.89.0.4',
            HTTP_X_FORWARDED_FOR='203.0.113.20, 10.89.0.1',
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(ContactSubmission.objects.count(), 3)

        other_client = Client()
        response = other_client.post(
            url,
            self.valid_payload(),
            secure=True,
            REMOTE_ADDR='10.89.0.4',
            HTTP_X_FORWARDED_FOR='203.0.113.21, 10.89.0.1',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactSubmission.objects.count(), 4)


class ProjectIndexFilteringTests(TestCase):
    def setUp(self):
        self.root_page = Page.get_first_root_node()
        Site.objects.filter(is_default_site=True).update(is_default_site=False)
        self.site = Site.objects.create(hostname='testserver', port=80, root_page=self.root_page, is_default_site=True)
        self.home_page = HomePage(title='Portfolio home', slug='portfolio-home')
        self.root_page.add_child(instance=self.home_page)
        self.home_page.save_revision().publish()
        self.index_page = ProjectIndexPage(title='Projects', slug='projects')
        self.home_page.add_child(instance=self.index_page)
        self.index_page.save_revision().publish()
        self.platform = ProjectCategory.objects.create(name='Platform', slug='platform')
        self.security = ProjectCategory.objects.create(name='Security', slug='security')
        self.python = TechStack.objects.create(name='Python', slug='python')
        self.django = TechStack.objects.create(name='Django', slug='django')

    def create_project(self, title, slug, *, category=None, status='completed', live=True, techs=(), hero_image=None):
        project = ProjectPage(title=title, slug=slug, intro='A project summary.', date=date(2026, 1, 1), category=category, status=status, hero_image=hero_image, live=False)
        self.index_page.add_child(instance=project)
        revision = project.save_revision()
        if live:
            revision.publish()
        for tech in techs:
            ProjectPageTechStack.objects.create(page=project, tech=tech)
        return project

    def context(self, params=None):
        request = RequestFactory().get('/projects/', params or {})
        return self.index_page.get_context(request)

    def render_index(self, params=None):
        request = RequestFactory().get('/projects/', params or {}, HTTP_HOST='testserver')
        context = self.index_page.get_context(request)
        context['page'] = self.index_page
        return render_to_string('home/project_index_page.html', context, request=request)

    def test_only_live_projects_are_indexed_and_status_filter_is_bookmarkable(self):
        completed = self.create_project('Completed', 'completed', category=self.platform)
        self.create_project('Draft', 'draft', category=self.platform, live=False)
        self.create_project('In progress', 'in-progress', category=self.security, status='in_progress')

        context = self.context({'status': 'completed'})

        self.assertEqual(list(context['projects']), [completed])
        completed_link = next(link for link in context['status_links'] if link['value'] == 'completed')
        self.assertTrue(completed_link['is_active'])
        self.assertEqual(completed_link['qs'], '')

    def test_multi_category_and_tech_filters_use_existing_or_semantics_and_toggle_urls(self):
        platform = self.create_project('Platform', 'platform-project', category=self.platform, techs=[self.python])
        security = self.create_project('Security', 'security-project', category=self.security, techs=[self.django])
        context = self.context({'category': ['platform', 'security'], 'tech': ['python', 'django']})

        self.assertCountEqual(list(context['projects']), [platform, security])
        category_link = next(link for link in context['category_links'] if link['obj'] == self.platform)
        tech_link = next(link for link in context['tech_links'] if link['obj'] == self.python)
        self.assertNotIn('category=platform', category_link['qs'])
        self.assertNotIn('tech=python', tech_link['qs'])
        self.assertTrue(context['active_count'])
        self.assertTrue(any(chip['qs_remove'] for chip in context['active_chips']))

    def test_filter_labels_are_readable_while_status_query_values_remain_stable(self):
        context = self.context({'status': 'in_progress'})

        labels = {link['value']: link['label'] for link in context['status_links']}

        self.assertEqual(labels, {
            'completed': 'COMPLETED',
            'in_progress': 'IN PROGRESS',
            'ongoing': 'ONGOING',
            'archived': 'ARCHIVED',
        })
        unfiltered_in_progress = next(link for link in self.context()['status_links'] if link['value'] == 'in_progress')
        self.assertEqual(unfiltered_in_progress['qs'], 'status=in_progress')
        in_progress = next(link for link in context['status_links'] if link['value'] == 'in_progress')
        self.assertEqual(in_progress['qs'], '')

    def test_empty_category_and_tech_options_do_not_render_filter_rows(self):
        ProjectCategory.objects.all().delete()
        TechStack.objects.all().delete()

        rendered = self.render_index()

        self.assertIn('>Status<', rendered)
        self.assertNotIn('>Domain<', rendered)
        self.assertNotIn('>Stack<', rendered)

    def test_archive_uses_the_svg_fallback_when_a_project_has_no_hero_image(self):
        self.create_project('Fallback visual', 'fallback-visual')

        fallback_rendered = self.render_index()

        self.assertIn('<svg', fallback_rendered)

    def test_archive_uses_image_media_without_the_svg_fallback_when_available(self):
        image_file = SimpleUploadedFile(
            "project-hero.png",
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ),
            content_type="image/png",
        )

        image = get_image_model().objects.create(
            title="Project hero",
            file=image_file,
        )
        self.create_project('Image visual', 'image-visual', hero_image=image)

        image_rendered = self.render_index()

        self.assertIn('--archive-image:', image_rendered)
        self.assertNotIn('class="project-record__routes"', image_rendered)


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

        for path in (Path(__file__).parent / 'templates').rglob('*.html'):
            get_template(path.relative_to(Path(__file__).parent / 'templates').as_posix())
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
        art = hero.select_one('.hero-art')
        self.assertEqual(art['aria-hidden'], 'true')
        picture = art.select_one('picture')
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
        self.assertEqual(art.svg['aria-hidden'], 'true')
        self.assertEqual(art.svg['focusable'], 'false')
        self.assertFalse(art.select('text, a, button, [tabindex]'))
        self.assertEqual(hero.h1.get_text(' ', strip=True), 'Christian Bergane')
        self.assertIn('I build systems that remain understandable when they fail.', hero.get_text())
        self.assertIn('Web development, Infrastructure, Security', hero.get_text())
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
