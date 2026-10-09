"""Project listing behavior and regression tests."""
import base64
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from wagtail.images import get_image_model
from wagtail.models import Page, Site

from ..models import (
    HomePage, ProjectCategory, ProjectIndexPage, ProjectPage, ProjectPageTechStack, TechStack,
)


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
