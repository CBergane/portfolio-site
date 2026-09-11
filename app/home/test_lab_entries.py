"""Lab project documents and child discovery preserve the existing Lab overview."""
from importlib import import_module
from io import BytesIO

from bs4 import BeautifulSoup
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from wagtail.admin.panels import InlinePanel, MultiFieldPanel
from wagtail.images import get_image_model
from wagtail.models import Page, PageViewRestriction, Site
from wagtail.search import index

from .models import (
    BlogIndexPage, BlogPage, ContactPage, HomePage, LabEntryPage, LabEntryPageTechStack,
    LabPage, ProjectIndexPage, ProjectPage, TechStack,
)
from .templatetags.navigation_tags import main_navigation


SECTIONS = (
    ('objective', 'lab-entry-objective', 'Objective'),
    ('architecture', 'lab-entry-architecture', 'Architecture'),
    ('implementation', 'lab-entry-implementation', 'Implementation'),
    ('security_considerations', 'lab-entry-security', 'Security Considerations'),
    ('body', 'lab-entry-documentation', 'Technical Documentation'),
    ('findings', 'lab-entry-findings', 'Findings / Observations'),
    ('next_steps', 'lab-entry-next-steps', 'Next Steps'),
)
LOCAL_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


@override_settings(CACHES=LOCAL_CACHE, ALLOWED_HOSTS=['testserver', 'other.example', 'nested.example'])
class LabEntryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Site.objects.all().delete()
        cls.home = Page.get_first_root_node().add_child(instance=HomePage(title='Home', slug='entry-home'))
        Site.objects.create(hostname='testserver', root_page=cls.home, is_default_site=True)
        cls.lab = cls.home.add_child(instance=LabPage(
            title='Infrastructure', slug='systems', overview='<p>Existing overview.</p>',
        ))

    def request(self, host='testserver'):
        return RequestFactory().get('/', HTTP_HOST=host)

    def create_entry(self, slug='experiment', parent=None, **fields):
        return (parent or self.lab).add_child(instance=LabEntryPage(
            title=slug.replace('-', ' ').title(), slug=slug, intro='Public experiment summary.', **fields,
        ))

    def render(self, page):
        request = self.request()
        return BeautifulSoup(render_to_string(
            page.get_template(request), page.get_context(request), request=request
        ), 'html.parser')

    def entries(self, lab=None, host='testserver'):
        return list((lab or self.lab).get_context(self.request(host))['lab_entries'])

    def image(self):
        buffer = BytesIO()
        Image.new('RGB', (8, 4), 'white').save(buffer, format='PNG')
        return get_image_model().objects.create(
            title='Public diagram',
            file=SimpleUploadedFile('experiment.png', buffer.getvalue(), content_type='image/png'),
        )

    def add_technologies(self, entry):
        for order, (name, primary) in enumerate((('Python', False), ('Django', True))):
            tech, _ = TechStack.objects.get_or_create(name=name, slug=name.lower())
            LabEntryPageTechStack.objects.create(page=entry, tech=tech, sort_order=order, is_primary=primary)

    def test_tree_constraints_allow_multiple_entries_only_under_lab(self):
        self.assertEqual(LabPage.allowed_subpage_models(), [LabEntryPage])
        self.assertEqual(LabEntryPage.allowed_parent_page_models(), [LabPage])
        self.assertEqual(LabEntryPage.allowed_subpage_models(), [])
        self.assertTrue(LabEntryPage.can_create_at(self.lab))
        self.assertFalse(LabEntryPage.can_create_at(self.home))
        first = self.create_entry()
        self.assertFalse(Page.can_create_at(first))
        self.assertTrue(LabEntryPage.can_create_at(self.lab))
        second = self.create_entry('second')
        self.assertEqual(self.entries(), [first, second])

    def test_detail_serves_with_one_h1_and_actual_parent_back_link(self):
        entry = self.create_entry()
        response = self.client.get('/systems/experiment/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home/lab_entry_page.html')
        soup = BeautifulSoup(response.content, 'html.parser')
        self.assertEqual([h.get_text() for h in soup.find_all('h1')], [entry.title])
        self.assertEqual(soup.select_one('.lab-entry-back')['href'], '/systems/')
        self.assertIn(self.lab.title, soup.select_one('.lab-entry-back').get_text())
        self.assertIn(entry.intro, soup.get_text())

    def test_populated_sections_and_plain_anchor_index_have_exact_order_and_unique_ids(self):
        entry = self.create_entry()
        for field, _, title in SECTIONS:
            setattr(entry, field, [('markdown', '**Technical notes**')] if field == 'body' else f'<p>{title} <strong>detail</strong>.</p>')
        soup = self.render(entry)
        self.assertEqual([h.get_text() for h in soup.select('.lab-section > h2')], [title for _, _, title in SECTIONS])
        self.assertEqual([h['id'] for h in soup.select('.lab-section > h2')], [sid for _, sid, _ in SECTIONS])
        self.assertEqual([link['href'] for link in soup.select('.lab-index a')], [f'#{sid}' for _, sid, _ in SECTIONS])
        for section in soup.select('.lab-section'):
            self.assertEqual(section['aria-labelledby'], section.h2['id'])
            self.assertIsNotNone(section.select_one('.prose strong'))
            self.assertIsNone(section.find_parent(['p', 'h1', 'h2']))
        ids = [element['id'] for element in soup.select('[id]')]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(soup.find_all('h1')), 1)
        self.assertFalse(soup.select('[data-reading-document], [data-reading-progress], script[src*="reading.js"]'))

    def test_empty_content_omits_all_section_wrappers_headings_and_index(self):
        soup = self.render(self.create_entry())
        self.assertFalse(soup.select('.lab-section, .lab-layout, .lab-index'))
        for _, sid, title in SECTIONS:
            self.assertIsNone(soup.find(id=sid))
            self.assertIsNone(soup.find('h2', string=title))
            self.assertIsNone(soup.find('a', href=f'#{sid}'))

    def test_each_section_is_independently_optional(self):
        entry = self.create_entry()
        for field, sid, title in SECTIONS:
            with self.subTest(field=field):
                setattr(entry, field, [('markdown', 'Content')] if field == 'body' else '<p>Content</p>')
                soup = self.render(entry)
                self.assertEqual([h['id'] for h in soup.select('.lab-section > h2')], [sid])
                self.assertEqual([a['href'] for a in soup.select('.lab-index a')], [f'#{sid}'])
                self.assertEqual(soup.find('h2', id=sid).string, title)
                setattr(entry, field, [] if field == 'body' else '')

    def test_all_project_streamfield_block_types_render(self):
        entry = self.create_entry()
        entry.body = [
            ('heading', 'Detailed notes'),
            ('markdown', '**Bold notes** and [reference](https://example.com/)'),
            ('code', {'language': 'html', 'code': '<h2>Escaped example</h2>'}),
            ('image', {'image': self.image(), 'caption': 'Diagram caption', 'attribution': 'Author'}),
            ('quote', {'quote': 'Observation', 'author': 'Researcher'}),
        ]
        soup = self.render(entry)
        body = soup.select_one('[aria-labelledby="lab-entry-documentation"]')
        self.assertEqual(body.select_one('.block-heading').string, 'Detailed notes')
        self.assertEqual(body.strong.string, 'Bold notes')
        self.assertEqual(body.code.string, '<h2>Escaped example</h2>')
        self.assertIsNone(body.pre.find('h2'))
        self.assertEqual(body.figure.img['alt'], 'Public diagram')
        self.assertIn('Diagram caption', body.figcaption.get_text())
        self.assertIn('Author', body.figcaption.get_text())
        self.assertEqual(body.blockquote.p.string, 'Observation')
        self.assertEqual(body.cite.string, 'Researcher')

    def test_every_status_is_publishable_without_finished_documentation(self):
        for status, label in LabEntryPage._meta.get_field('status').choices:
            with self.subTest(status=status):
                entry = self.create_entry(status, status=status, live=False)
                entry.save_revision().publish()
                entry.refresh_from_db()
                self.assertTrue(entry.live)
                self.assertIn(label, self.render(entry).select_one('.lab-hero .eyebrow').get_text())
        self.assertEqual(len(self.entries()), 5)

    def test_github_link_is_optional_and_has_safe_external_link_attributes(self):
        entry = self.create_entry()
        self.assertIsNone(self.render(entry).select_one('.lab-entry-repository'))
        entry.github_url = 'https://github.com/example/experiment'
        link = self.render(entry).select_one('.lab-entry-repository')
        self.assertEqual(link['href'], entry.github_url)
        self.assertEqual(link['target'], '_blank')
        self.assertEqual(link['rel'], ['noopener', 'noreferrer'])

    def test_technology_uses_existing_snippets_primary_first_and_is_optional(self):
        entry = self.create_entry()
        self.assertFalse(self.render(entry).select('.lab-entry-technologies'))
        self.add_technologies(entry)
        self.assertEqual([item.string for item in self.render(entry).select('.lab-entry-technologies li')], ['Django', 'Python'])
        self.assertEqual(LabEntryPageTechStack._meta.get_field('tech').remote_field.model, TechStack)
        self.assertEqual(TechStack.objects.count(), 2)

    def test_hero_image_is_optional_and_renders_normal_rendition(self):
        entry = self.create_entry()
        self.assertIsNone(self.render(entry).select_one('.lab-visual'))
        entry.hero_image = self.image()
        image = self.render(entry).select_one('.lab-visual img')
        self.assertEqual(image['alt'], 'Public diagram')
        self.assertTrue(image['src'])
        self.assertGreater(int(image['width']), 0)
        self.assertGreater(int(image['height']), 0)

    def test_no_index_listing_when_no_public_children(self):
        self.create_entry(live=False)
        soup = self.render(self.lab)
        self.assertFalse(soup.select('.lab-projects'))
        self.assertIsNone(soup.find(id='lab-projects-title'))
        self.assertEqual(soup.find(id='lab-overview').get_text(), 'System Overview')

    def test_live_direct_children_appear_after_existing_overview_without_changing_index(self):
        entry = self.create_entry(status='experimenting')
        soup = self.render(self.lab)
        records = soup.select('.lab-projects-record')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].h3.a['href'], entry.url)
        self.assertIn(entry.title, records[0].h3.get_text())
        self.assertIn(entry.intro, records[0].get_text())
        self.assertIn('Experimenting', records[0].get_text())
        self.assertEqual([h.get_text() for h in soup.select('.lab-page h2')], ['System Overview', 'Lab Projects'])
        self.assertEqual([a['href'] for a in soup.select('.lab-index a')], ['#lab-overview'])

    def test_index_shows_children_even_when_overview_sections_are_empty(self):
        self.lab.overview = ''
        self.create_entry()
        soup = self.render(self.lab)
        self.assertIsNotNone(soup.select_one('.lab-projects'))
        self.assertIsNone(soup.select_one('.lab-index'))

    def test_draft_and_restricted_entries_never_appear(self):
        public = self.create_entry('public')
        self.create_entry('draft', live=False)
        for restriction in ('login', 'password'):
            private = self.create_entry(restriction)
            PageViewRestriction.objects.create(page=private, restriction_type=restriction, password='test-only')
        self.assertEqual(self.entries(), [public])
        self.assertEqual(len(self.render(self.lab).select('.lab-projects-record')), 1)

    def test_inherited_restrictions_hide_child_listing(self):
        self.create_entry()
        PageViewRestriction.objects.create(page=self.lab, restriction_type='login')
        self.assertEqual(self.entries(), [])

    def test_indirect_descendants_do_not_appear(self):
        direct = self.create_entry('direct')
        # Programmatic tree insertion represents legacy content outside editor constraints.
        self.create_entry('indirect', parent=direct)
        self.assertEqual(self.entries(), [direct])

    def test_entries_under_another_lab_and_site_do_not_leak(self):
        local = self.create_entry('local')
        other_home = self.home.get_parent().add_child(instance=HomePage(title='Other', slug='other'))
        Site.objects.create(hostname='other.example', root_page=other_home)
        other_lab = other_home.add_child(instance=LabPage(title='Other Lab', slug='other-lab'))
        foreign = self.create_entry('foreign', parent=other_lab)
        self.assertEqual(self.entries(), [local])
        self.assertEqual(self.entries(other_lab), [])
        self.assertEqual(self.entries(other_lab, 'other.example'), [foreign])

    def test_nested_site_root_entry_is_excluded_from_outer_lab(self):
        local = self.create_entry('local')
        nested = self.create_entry('nested')
        Site.objects.create(hostname='nested.example', root_page=nested)
        self.assertEqual(self.entries(), [local])
        self.assertNotIn(nested.title, self.render(self.lab).select_one('.lab-projects').get_text())

    def test_editor_page_tree_reordering_is_respected(self):
        first = self.create_entry('z-first')
        second = self.create_entry('a-second')
        self.assertEqual([entry.pk for entry in self.entries()], [first.pk, second.pk])
        second.move(first, pos='left')
        self.assertEqual([entry.pk for entry in self.entries()], [second.pk, first.pk])

    def test_index_optional_image_and_technologies_render(self):
        entry = self.create_entry(hero_image=self.image())
        self.add_technologies(entry)
        card = self.render(self.lab).select_one('.lab-projects-record')
        self.assertEqual(card.img['alt'], 'Public diagram')
        self.assertEqual(card.img['loading'], 'lazy')
        self.assertEqual([item.string for item in card.select('.lab-entry-technologies li')], ['Django', 'Python'])

    def test_listing_prefetches_technologies_and_images_without_per_entry_queries(self):
        for number in range(3):
            entry = self.create_entry(f'entry-{number}')
            self.add_technologies(entry)
        queryset = self.lab.get_context(self.request())['lab_entries']
        with self.assertNumQueries(2):
            for entry in queryset:
                self.assertIsNone(entry.hero_image)
                self.assertEqual([item.tech.name for item in entry.tech_stack_items.all()], ['Python', 'Django'])

    def test_lab_navigation_stays_active_for_parent_and_entry(self):
        entry = self.create_entry()
        for page in (self.lab, entry):
            items = main_navigation({'request': self.request(), 'page': page})['nav_items']
            self.assertEqual([item['label'] for item in items if item['is_active']], ['LAB'])
            self.assertEqual(next(item['url'] for item in items if item['label'] == 'LAB'), '/systems/')
        links = self.render(entry).select('[data-nav-label="LAB"]')
        self.assertEqual(len(links), 2)
        for link in links:
            self.assertEqual(link['aria-current'], 'page')
            self.assertIn('site-nav__link--active', link['class'])

    def test_existing_navigation_behaviors_remain_intact(self):
        self.create_entry()
        work = self.home.add_child(instance=ProjectIndexPage(title='Work', slug='work'))
        notes = self.home.add_child(instance=BlogIndexPage(title='Notes', slug='notes'))
        contact = self.home.add_child(instance=ContactPage(title='Contact', slug='contact'))
        project = work.add_child(instance=ProjectPage(title='Project', slug='project', intro='Summary'))
        note = notes.add_child(instance=BlogPage(title='Note', slug='note', intro='Summary'))
        for page, active in ((project, ['WORK']), (note, ['NOTES']), (contact, ['CONTACT']), (self.home, [])):
            with self.subTest(page=page.title):
                items = main_navigation({'request': self.request(), 'page': page})['nav_items']
                self.assertEqual([item['label'] for item in items], ['WORK', 'LAB', 'ABOUT', 'NOTES', 'CONTACT'])
                self.assertEqual([item['label'] for item in items if item['is_active']], active)
                self.assertEqual(items[2]['url'], '/#operating-principle')

    def test_admin_groups_and_optional_documentation(self):
        groups = [panel for panel in LabEntryPage.content_panels if isinstance(panel, MultiFieldPanel)]
        self.assertEqual([(panel.heading, [
            child.relation_name if isinstance(child, InlinePanel) else child.field_name for child in panel.children
        ]) for panel in groups], [
            ('Basic Info', ['intro', 'status', 'hero_image']),
            ('Technology', ['tech_stack_items']), ('Links', ['github_url']),
            ('Lab Documentation', ['objective', 'architecture', 'implementation', 'security_considerations', 'findings', 'next_steps']),
            ('Technical Documentation', ['body']),
        ])
        form = LabEntryPage.get_edit_handler().get_form_class()
        self.assertTrue(form.base_fields['intro'].required)
        self.assertEqual(form.base_fields['intro'].max_length, 300)
        self.assertEqual(LabEntryPage._meta.get_field('status').default, 'active')
        for field in ['hero_image', 'github_url', *[field for field, _, _ in SECTIONS]]:
            self.assertFalse(form.base_fields[field].required)
        self.assertIn('tech_stack_items', form.formsets)

    def test_search_fields_and_reused_block_configuration(self):
        fields = {field.field_name for field in LabEntryPage.search_fields if isinstance(field, index.SearchField)}
        self.assertTrue({'intro', *[field for field, _, _ in SECTIONS]}.issubset(fields))
        self.assertFalse({'hero_image', 'status', 'tech_stack_items'}.intersection(fields))
        entry_blocks = LabEntryPage._meta.get_field('body').stream_block.child_blocks
        project_blocks = ProjectPage._meta.get_field('body').stream_block.child_blocks
        self.assertEqual(list(entry_blocks), ['heading', 'markdown', 'code', 'image', 'quote'])
        for name, block in entry_blocks.items():
            self.assertEqual(type(block), type(project_blocks[name]))
            self.assertEqual(block.meta.template, project_blocks[name].meta.template)
        self.assertEqual(entry_blocks['heading'].meta.form_classname, project_blocks['heading'].meta.form_classname)

    def test_migration_only_creates_new_models_without_altering_lab(self):
        migration = import_module('home.migrations.0007_lab_entry_pages').Migration
        self.assertIn(('home', '0006_labpage'), migration.dependencies)
        self.assertEqual(len(migration.operations), 2)
        self.assertEqual({operation.name for operation in migration.operations}, {'LabEntryPage', 'LabEntryPageTechStack'})
        for operation in migration.operations:
            self.assertIsInstance(operation, migrations.CreateModel)


@override_settings(CACHES=LOCAL_CACHE)
class LabEntryMigrationTests(TransactionTestCase):
    # TransactionTestCase flushes the root page seeded by Wagtail migrations.
    serialized_rollback = True

    def test_existing_unpublished_lab_and_editorial_revision_survive_migration(self):
        home = Page.get_first_root_node().add_child(instance=HomePage(title='Home', slug='migration-home'))
        lab = home.add_child(instance=LabPage(
            title='Draft lab', slug='lab', live=False, intro='<p>Original intro.</p>',
            **{field: f'<p>Original {field} content.</p>' for field, _, _ in LabPage.section_definitions},
        ))
        revision = lab.save_revision()
        revision.refresh_from_db()
        revision_content = revision.content
        executor = MigrationExecutor(connection)
        latest_targets = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest_targets))
        old_target = [('home', '0006_labpage')]
        executor.migrate(old_target)
        old_apps = executor.loader.project_state(old_target).apps
        before = old_apps.get_model('home', 'LabPage').objects.values().get(pk=lab.pk)
        executor = MigrationExecutor(connection)
        executor.migrate([('home', '0007_lab_entry_pages')])
        self.assertEqual(LabPage.objects.values().get(pk=lab.pk), before)
        revision.refresh_from_db()
        self.assertEqual(revision.content, revision_content)
        lab.refresh_from_db()
        self.assertFalse(lab.live)
        self.assertEqual(lab.latest_revision_id, revision.pk)
        restored = revision.as_object()
        for field, _, _ in LabPage.section_definitions:
            self.assertEqual(getattr(restored, field), getattr(lab, field))
        self.assertEqual(LabEntryPage.objects.count(), 0)
