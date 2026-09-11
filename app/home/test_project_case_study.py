"""Optional case-study content must preserve existing project pages."""
from datetime import date
from importlib import import_module
from io import BytesIO
from types import SimpleNamespace

from bs4 import BeautifulSoup
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from wagtail.admin.panels import InlinePanel, MultiFieldPanel
from wagtail.fields import RichTextField, StreamField
from wagtail.images import get_image_model
from wagtail.models import Page, Site
from wagtail.search import index

from .models import HomePage, ProjectIndexPage, ProjectPage, ProjectPageTechStack, TechStack
from .reading import reading_minutes


SECTIONS = {
    'architecture': ('project-architecture', 'Architecture'),
    'security_considerations': ('project-security', 'Security Considerations'),
    'testing_validation': ('project-testing', 'Testing / Validation'),
    'outcome': ('project-outcome', 'Outcome'),
    'lessons_learned': ('project-lessons', 'Lessons Learned'),
}
NEW_FIELDS = {'role', *SECTIONS}


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class ProjectCaseStudyRenderingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.home = Page.get_first_root_node().add_child(
            instance=HomePage(title='Portfolio', slug='case-study-home')
        )
        Site.objects.all().delete()
        Site.objects.create(hostname='testserver', root_page=cls.home, is_default_site=True)
        cls.index = cls.home.add_child(instance=ProjectIndexPage(title='Work', slug='work'))
        cls.project = cls.index.add_child(instance=ProjectPage(
            title='Legacy system', slug='legacy-system', date=date(2026, 1, 1),
            intro='Original project introduction.',
            problem='<p>Original problem.</p>', solution='<p>Original solution.</p>',
            body=[('heading', 'Implementation'), ('markdown', 'Original **documentation**.')],
        ))

    def render(self):
        request = RequestFactory().get(self.project.url)
        html = render_to_string(
            self.project.get_template(request), self.project.get_context(request), request=request
        )
        return BeautifulSoup(html, 'html.parser')

    def populate_sections(self):
        for field, (_, heading) in SECTIONS.items():
            setattr(self.project, field, f'<p>{heading} content with <strong>detail</strong>.</p>')

    def assert_section(self, field):
        section_id, heading = SECTIONS[field]
        setattr(self.project, field, '<p>Specific <strong>technical detail</strong>.</p>')
        soup = self.render()
        section = soup.select_one(f'section[aria-labelledby="{section_id}"]')
        self.assertIsNotNone(section)
        self.assertEqual(section.h2.get_text(strip=True), heading)
        self.assertEqual(section.strong.string, 'technical detail')
        self.assertIsNotNone(section.find_parent(attrs={'data-reading-body': True}))
        for other, (other_id, _) in SECTIONS.items():
            if other != field:
                self.assertIsNone(soup.find(id=other_id))

    def test_legacy_page_serves_at_existing_url_with_new_fields_blank(self):
        self.project.refresh_from_db()
        for field in NEW_FIELDS:
            self.assertEqual(getattr(self.project, field), '')
        self.assertEqual(self.project.url, '/work/legacy-system/')
        response = self.client.get(self.project.url)
        self.assertEqual(response.status_code, 200)
        for text in ('Original project introduction.', 'Original problem.', 'Original solution.', 'documentation'):
            self.assertContains(response, text)
        self.assertContains(response, 'data-reading-document')
        self.assertContains(response, 'data-reading-nav')

    def test_blank_case_study_fields_produce_no_sections_or_headings(self):
        self.project.problem = self.project.solution = ''
        self.project.body = []
        soup = self.render()
        self.assertFalse(soup.select('[data-reading-body] section, [data-reading-body] h2'))
        self.assertFalse(soup.select('.project-page__case-study'))

    def test_blank_new_fields_produce_no_new_sections_on_legacy_page(self):
        soup = self.render()
        for section_id, heading in SECTIONS.values():
            self.assertIsNone(soup.find(id=section_id))
            self.assertIsNone(soup.find('h2', string=heading))

    def test_role_renders_in_metadata_and_facts_and_is_escaped(self):
        self.project.role = 'Developer <script>alert(1)</script>'
        soup = self.render()
        for selector in ('.project-page__metadata', '.project-page__facts'):
            label = soup.select_one(selector).find('dt', string='Role')
            self.assertEqual(label.find_next_sibling('dd').get_text(), self.project.role)
            self.assertIsNone(label.parent.find('script'))

    def test_blank_role_has_no_label_or_value(self):
        self.assertFalse(self.render().find_all('dt', string='Role'))

    def test_architecture_renders(self):
        self.assert_section('architecture')

    def test_security_considerations_render(self):
        self.assert_section('security_considerations')

    def test_testing_validation_renders(self):
        self.assert_section('testing_validation')

    def test_outcome_renders(self):
        self.assert_section('outcome')

    def test_lessons_learned_render(self):
        self.assert_section('lessons_learned')

    def test_problem_and_solution_keep_editorial_panels_with_semantic_headings(self):
        soup = self.render()
        for field in ('problem', 'solution'):
            section = soup.select_one(f'section[aria-labelledby="project-{field}"]')
            self.assertIn('project-page__editorial-panel', section['class'])
            self.assertEqual(section.h2.name, 'h2')
            self.assertIn(field.title(), section.h2.get_text())
            self.assertEqual(section.div.p.string, f'Original {field}.')

    def test_problem_and_solution_are_independently_optional(self):
        for present, absent in (('problem', 'solution'), ('solution', 'problem')):
            with self.subTest(present=present):
                setattr(self.project, present, '<p>Present content</p>')
                setattr(self.project, absent, '')
                soup = self.render()
                self.assertIsNotNone(soup.find(id=f'project-{present}'))
                self.assertIsNone(soup.find(id=f'project-{absent}'))

    def test_all_existing_body_block_types_render_unchanged(self):
        buffer = BytesIO()
        Image.new('RGB', (4, 4), 'white').save(buffer, format='PNG')
        image = get_image_model().objects.create(
            title='Diagram', file=SimpleUploadedFile('diagram.png', buffer.getvalue(), content_type='image/png')
        )
        self.project.body = [
            ('heading', 'Implementation'),
            ('markdown', 'Original **documentation**.'),
            ('code', {'language': 'html', 'code': '<h2>escaped code</h2>'}),
            ('image', {'image': image, 'caption': 'System diagram', 'attribution': 'Project author'}),
            ('quote', {'quote': 'Measured results', 'author': 'Engineer'}),
        ]
        body = self.render().select_one('section[aria-labelledby="project-documentation"]')
        self.assertEqual(body.select_one('.block-heading').string, 'Implementation')
        self.assertEqual(body.strong.string, 'documentation')
        self.assertEqual(body.code.string, '<h2>escaped code</h2>')
        self.assertIsNone(body.pre.find('h2'))
        self.assertEqual(body.figure.img['alt'], 'Diagram')
        self.assertIn('System diagram', body.figcaption.get_text())
        self.assertIn('Project author', body.figcaption.get_text())
        self.assertEqual(body.blockquote.p.string, 'Measured results')
        self.assertEqual(body.cite.string, 'Engineer')

    def test_github_and_live_links_keep_urls_labels_and_attributes(self):
        self.project.github_url = 'https://github.com/example/project'
        self.project.live_url = 'https://example.com/demo?view=project'
        soup = self.render()
        source = soup.select_one('.project-page__actions a.project-page__button-outline')
        live = soup.select_one('.project-page__actions a.button--primary')
        self.assertEqual(source['href'], self.project.github_url)
        self.assertEqual(source['target'], '_blank')
        self.assertEqual(source['rel'], ['noopener', 'noreferrer'])
        self.assertTrue(source.get_text(strip=True).startswith('View source'))
        self.assertEqual(live['href'], self.project.live_url)
        self.assertNotIn('target', live.attrs)
        self.assertEqual(live['rel'], ['noopener', 'noreferrer'])
        self.assertTrue(live.get_text(strip=True).startswith('View live'))

    def test_tech_stack_keeps_primary_first_and_existing_tags(self):
        for name, primary in (('Python', False), ('Django', True), ('PostgreSQL', False)):
            tech = TechStack.objects.create(name=name, slug=name.lower())
            ProjectPageTechStack.objects.create(page=self.project, tech=tech, is_primary=primary)
        tags = self.render().select('.project-page__facts-tech dd .project-page__tech-tag')
        self.assertEqual([tag.string for tag in tags], ['Django', 'Python', 'PostgreSQL'])

    def test_title_is_only_h1(self):
        self.populate_sections()
        self.assertEqual([h.get_text() for h in self.render().find_all('h1')], [self.project.title])

    def test_section_order_semantics_and_unique_ids(self):
        self.populate_sections()
        # Repeated authored headings must not receive conflicting template IDs.
        self.project.body = [('heading', 'Architecture'), ('heading', 'Architecture')]
        soup = self.render()
        content = soup.select_one('[data-reading-body]')
        sections = content.select('section[aria-labelledby]')
        self.assertEqual([s['aria-labelledby'] for s in sections], [
            'project-problem', 'project-solution', 'project-architecture',
            'project-documentation', 'project-security', 'project-testing',
            'project-outcome', 'project-lessons',
        ])
        for section in sections:
            heading = section.find('h2', recursive=False)
            self.assertIsNotNone(heading)
            self.assertEqual(heading['id'], section['aria-labelledby'])
            self.assertTrue(heading.get_text(strip=True))
            self.assertIsNone(section.find_parent(['p', 'h1', 'h2', 'h3']))
        ids = [element['id'] for element in soup.select('[id]')]
        self.assertEqual(len(ids), len(set(ids)))
        for element in soup.select('[aria-labelledby]'):
            for target in element['aria-labelledby'].split():
                self.assertIsNotNone(soup.find(id=target))
        self.assertEqual(len(soup.select('[data-reading-body]')), 1)
        self.assertEqual(len(soup.select('script[src="/static/js/reading.js"]')), 1)

    def test_legacy_revision_without_new_field_keys_can_be_loaded_and_published(self):
        revision = self.project.save_revision()
        revision.content = {key: value for key, value in revision.content.items() if key not in NEW_FIELDS}
        revision.save(update_fields=['content'])
        restored = revision.as_object()
        for field in NEW_FIELDS:
            self.assertEqual(getattr(restored, field), '')
        revision.publish()
        self.project.refresh_from_db()
        self.assertEqual(self.project.problem, '<p>Original problem.</p>')
        self.assertEqual(self.client.get(self.project.url).status_code, 200)


class ProjectCaseStudyConfigurationTests(SimpleTestCase):
    def test_admin_groups_and_field_order(self):
        groups = [panel for panel in ProjectPage.content_panels if isinstance(panel, MultiFieldPanel)]
        self.assertEqual([panel.heading for panel in groups], [
            'Basic Info', 'Project Details', 'Links', 'Case Study', 'Technical Documentation',
        ])
        self.assertEqual([
            [child.relation_name if isinstance(child, InlinePanel) else child.field_name for child in panel.children]
            for panel in groups
        ], [
            ['date', 'intro', 'hero_image'],
            ['category', 'status', 'tech_stack_items', 'duration', 'role'],
            ['github_url', 'live_url'],
            ['problem', 'solution', *SECTIONS],
            ['body'],
        ])
        form = ProjectPage.get_edit_handler().get_form_class()
        for field in NEW_FIELDS:
            self.assertIn(field, form.base_fields)
            self.assertFalse(form.base_fields[field].required)

    def test_fields_optional_and_original_streamfield_preserved(self):
        for field in NEW_FIELDS:
            self.assertTrue(ProjectPage._meta.get_field(field).blank)
        self.assertEqual(ProjectPage._meta.get_field('role').max_length, 120)
        for field in SECTIONS:
            self.assertIsInstance(ProjectPage._meta.get_field(field), RichTextField)
        streams = [field for field in ProjectPage._meta.get_fields() if isinstance(field, StreamField)]
        self.assertEqual([field.name for field in streams], ['body'])
        self.assertEqual(list(streams[0].stream_block.child_blocks), ['heading', 'markdown', 'code', 'image', 'quote'])

    def test_substantive_fields_are_searchable_alongside_existing_content(self):
        fields = {field.field_name for field in ProjectPage.search_fields if isinstance(field, index.SearchField)}
        self.assertTrue({'intro', 'body', *SECTIONS}.issubset(fields))

    def test_reading_time_includes_each_new_prose_field_but_not_role(self):
        for field in SECTIONS:
            with self.subTest(field=field):
                page = SimpleNamespace(**{field: '<p>' + 'word ' * 201 + '</p>'})
                self.assertEqual(reading_minutes(page), 2)
        self.assertEqual(reading_minutes(SimpleNamespace(role='word ' * 20)), 0)

    def test_migration_only_adds_six_optional_project_fields(self):
        migration = import_module('home.migrations.0005_projectpage_case_study').Migration
        self.assertEqual(len(migration.operations), 6)
        self.assertEqual({operation.name for operation in migration.operations}, NEW_FIELDS)
        for operation in migration.operations:
            self.assertIsInstance(operation, migrations.AddField)
            self.assertEqual(operation.model_name, 'projectpage')
            self.assertTrue(operation.field.blank)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class ProjectCaseStudyMigrationTests(TransactionTestCase):
    # Restore Wagtail's seeded root even after another migration test flushes it.
    serialized_rollback = True

    def test_existing_project_data_and_tree_survive_field_additions(self):
        page = Page.get_first_root_node().add_child(instance=ProjectPage(
            title='Existing project', slug='existing-project', intro='Keep introduction',
            problem='<p>Keep problem</p>', solution='<p>Keep solution</p>',
            body=[('markdown', '**Keep documentation**')], duration='2 weeks',
            github_url='https://github.com/example/repo', live_url='https://example.com/',
        ))
        tech = TechStack.objects.create(name='Python', slug='python')
        relation = ProjectPageTechStack.objects.create(page=page, tech=tech, is_primary=True)
        revision = page.save_revision()
        revision.content = {key: value for key, value in revision.content.items() if key not in NEW_FIELDS}
        revision.save(update_fields=['content'])
        revision.refresh_from_db()
        saved_revision = revision.content
        old_target = [('home', '0004_homepageproject')]
        new_target = [('home', '0005_projectpage_case_study')]
        executor = MigrationExecutor(connection)
        # Restore the latest schema even when an assertion fails.
        latest_targets = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest_targets))
        executor.migrate(old_target)
        old_apps = executor.loader.project_state(old_target).apps
        old_model = old_apps.get_model('home', 'ProjectPage')
        before = old_model.objects.values().get(pk=page.pk)
        self.assertFalse(NEW_FIELDS.intersection(before))
        executor = MigrationExecutor(connection)
        executor.migrate(new_target)
        new_apps = executor.loader.project_state(new_target).apps
        after = new_apps.get_model('home', 'ProjectPage').objects.values().get(pk=page.pk)
        self.assertEqual({key: value for key, value in after.items() if key not in NEW_FIELDS}, before)
        for field in NEW_FIELDS:
            self.assertEqual(after[field], '')
        revision.refresh_from_db()
        relation.refresh_from_db()
        self.assertEqual(revision.content, saved_revision)
        self.assertEqual(relation.page_id, page.pk)
        self.assertEqual(relation.tech_id, tech.pk)
        self.assertTrue(relation.is_primary)
