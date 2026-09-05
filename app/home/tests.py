from datetime import date
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse
from wagtail.models import Page, Site

from .models import ContactSubmission, HomePage, HomePageProject, ProjectIndexPage, ProjectPage


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
