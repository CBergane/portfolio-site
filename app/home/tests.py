import base64
from datetime import date
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse
from wagtail.images import get_image_model
from wagtail.models import Page, Site

from .models import (
    BlogPage, BlogIndexPage, ContactPage, ContactSubmission, HomePage, HomePageProject, ProjectCategory, ProjectIndexPage,
    ProjectPage, ProjectPageTechStack, TechStack,
)
from .templatetags.navigation_tags import main_navigation


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
        with patch('home.htb.get_htb_profile', return_value={}):
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
    def valid_payload(self):
        return {
            'name': 'Ada Lovelace',
            'email': 'ada@example.com',
            'subject': 'Systems review',
            'message': 'I would like to discuss a systems review.',
        }

    @patch('home.views.send_discord_notification')
    def test_valid_contact_submission_is_stored_and_notified(self, notify):
        response = self.client.post(reverse('contact_submit'), self.valid_payload())

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

        response = self.client.post(reverse('contact_submit'), payload)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['success'], False)
        self.assertIn('message', response.json()['errors'])
        self.assertFalse(ContactSubmission.objects.exists())
        notify.assert_not_called()


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
        self.assertNotIn('<svg', image_rendered)


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
