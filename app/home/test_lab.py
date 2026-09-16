"""Lab landing page rendering, editor constraints and site-owned navigation."""
from importlib import import_module
from io import BytesIO

from bs4 import BeautifulSoup
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import migrations, models
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from wagtail.admin.panels import MultiFieldPanel
from wagtail.fields import RichTextField
from wagtail.images import get_image_model
from wagtail.models import Page, PageViewRestriction, Site
from wagtail.search import index

from .models import BlogIndexPage, BlogPage, ContactPage, HomePage, LabEntryPage, LabPage, ProjectIndexPage, ProjectPage
from .navigation import site_destinations
from .templatetags.navigation_tags import main_navigation


SECTIONS = (
    ('overview', 'lab-overview', 'System Overview'),
    ('platform_architecture', 'lab-platform', 'Platform Architecture'),
    ('networking', 'lab-networking', 'Networking'),
    ('containerization', 'lab-containers', 'Workloads & Containers'),
    ('security_controls', 'lab-security', 'Security Controls'),
    ('operations_recovery', 'lab-operations', 'Operations & Recovery'),
    ('current_experiments', 'lab-experiments', 'Current Experiments'),
)
LOCAL_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


@override_settings(CACHES=LOCAL_CACHE)
class LabPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Site.objects.all().delete()
        cls.home = Page.get_first_root_node().add_child(instance=HomePage(title='Home', slug='lab-home'))
        Site.objects.create(hostname='testserver', root_page=cls.home, is_default_site=True)
        cls.lab = cls.home.add_child(instance=LabPage(title='Infrastructure lab', slug='lab'))

    def render(self):
        request = RequestFactory().get('/lab/')
        return BeautifulSoup(render_to_string(
            self.lab.get_template(request), self.lab.get_context(request), request=request
        ), 'html.parser')

    def test_lab_serves_at_editor_selected_slug_with_empty_optional_content(self):
        self.assertEqual(self.lab.url, '/lab/')
        response = self.client.get(self.lab.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home/lab_page.html')
        self.assertContains(response, self.lab.title)

    def test_empty_fields_omit_section_wrappers_headings_and_index(self):
        soup = self.render()
        self.assertFalse(soup.select('.lab-section, .lab-layout, .lab-index, .lab-intro, .lab-visual'))
        for _, section_id, title in SECTIONS:
            self.assertIsNone(soup.find(id=section_id))
            self.assertIsNone(soup.find('h2', string=title))
            self.assertIsNone(soup.find('a', href=f'#{section_id}'))

    def test_old_fields_remain_available_but_only_overview_is_rendered(self):
        for field, section_id, title in SECTIONS:
            with self.subTest(field=field):
                setattr(self.lab, field, '<p>Example <strong>engineering detail</strong>.</p>')
                soup = self.render()
                self.assertFalse(soup.select('.lab-section, .lab-layout, .lab-index'))
                self.assertIsNone(soup.find(id=section_id))
                if field == 'overview':
                    self.assertEqual(soup.select_one('.lab-why-copy').get_text(), 'Example engineering detail.')
                else:
                    self.assertNotIn('engineering detail', soup.get_text())
                    self.assertIsNone(soup.select_one('.lab-why'))
                self.lab.save()
                self.lab.refresh_from_db()
                self.assertEqual(getattr(self.lab, field), '<p>Example <strong>engineering detail</strong>.</p>')
                setattr(self.lab, field, '')

    def test_all_sections_have_expected_order_unique_ids_and_one_h1(self):
        for field, _, title in SECTIONS:
            setattr(self.lab, field, f'<p>{title} explanation.</p>')
        self.lab.intro = '<p>An editable <strong>introduction</strong>.</p>'
        soup = self.render()
        self.assertEqual([h.get_text() for h in soup.find_all('h1')], [self.lab.title])
        self.assertEqual([h.get_text() for h in soup.select('.lab-landing h2')], [
            'Why I Run a Lab', 'How I Use It', 'Labs',
        ])
        self.assertFalse(soup.select('.lab-index'))
        ids = [element['id'] for element in soup.select('[id]')]
        self.assertEqual(len(ids), len(set(ids)))
        for section in soup.select('.lab-landing-section'):
            self.assertEqual(section.h2['id'], section['aria-labelledby'])
            self.assertIsNone(section.find_parent(['p', 'h1', 'h2']))
        self.assertEqual(soup.select_one('.lab-intro strong').string, 'introduction')

    def test_sparse_legacy_fields_do_not_create_document_sections(self):
        self.lab.networking = '<p>Network design.</p>'
        self.lab.current_experiments = '<p>Current work.</p>'
        soup = self.render()
        self.assertFalse(soup.select('.lab-section, .lab-index, .lab-why'))
        self.assertNotIn('Network design.', soup.get_text())
        self.assertNotIn('Current work.', soup.get_text())

    def test_hero_uses_editor_title_intro_and_experimental_systems_label(self):
        self.lab.title = 'A place to investigate'
        self.lab.intro = '<p>Experiments in <strong>security and automation</strong>.</p>'
        soup = self.render()
        self.assertEqual(soup.h1.string, self.lab.title)
        self.assertEqual(soup.select_one('.lab-hero .eyebrow').get_text(), 'LAB / EXPERIMENTAL SYSTEMS')
        self.assertEqual(soup.select_one('.lab-intro strong').string, 'security and automation')
        self.assertIsNone(soup.select_one('.lab-visual'))

    def test_overview_renders_full_rich_text_without_truncation(self):
        self.lab.overview = '<p>' + 'word ' * 100 + '<strong>Complete ending.</strong></p><ul><li>Reusable knowledge</li></ul>'
        original = self.lab.overview
        soup = self.render()
        narrative = soup.select_one('.lab-why-copy')
        self.assertEqual(narrative.strong.string, 'Complete ending.')
        self.assertEqual(narrative.li.string, 'Reusable knowledge')
        self.assertGreater(len(narrative.get_text().split()), 100)
        self.assertEqual(self.lab.overview, original)
        self.assertEqual(soup.find(id='lab-why-title').string, 'Why I Run a Lab')

    def test_overview_preserves_paragraphs_links_and_escaped_text(self):
        self.lab.overview = '<p>First paragraph.</p><p>Next &amp; &lt;example&gt; <a href="https://example.com/">reference</a>.</p>'
        narrative = self.render().select_one('.lab-why-copy')
        self.assertEqual(len(narrative.find_all('p')), 2)
        self.assertIn('Next & <example>', narrative.get_text())
        self.assertEqual(narrative.a['href'], 'https://example.com/')
        self.assertIsNone(narrative.find('example'))
        self.lab.overview = ''
        self.assertFalse(self.render().select('.lab-why'))

    def test_empty_catalogue_has_meaningful_empty_state(self):
        soup = self.render()
        self.assertEqual(soup.find(id='lab-catalogue-title').string, 'Labs')
        self.assertFalse(soup.select('.lab-exploring, .lab-records'))
        self.assertEqual(soup.select_one('.lab-empty').string, 'No published lab entries yet.')

    def test_previous_index_architecture_is_absent(self):
        soup = self.render()
        self.assertFalse(soup.select('.lab-focus, .lab-foundation, .lab-areas, .lab-all, .lab-principles, .lab-area-list'))
        for heading in ('Current Focus', 'Lab Foundation', 'Lab Areas', 'All Labs', 'Operating Principles'):
            self.assertIsNone(soup.find('h2', string=heading))

    def test_four_principles_are_compact_editorial_guidance(self):
        soup = self.render()
        markers = soup.select('.lab-method-list > li')
        self.assertEqual([item.h3.get_text(' ', strip=True) for item in markers], ['01 / Build', '02 / Isolate', '03 / Observe', '04 / Document'])
        for item in markers:
            self.assertTrue(item.p.get_text(strip=True))
            self.assertLessEqual(len(item.p.get_text().split()), 14)
        self.assertFalse(soup.select('.lab-method img, .lab-method svg'))

    def test_hero_image_renders_rendition_with_dimensions_and_alt_text(self):
        buffer = BytesIO()
        Image.new('RGB', (8, 4), 'white').save(buffer, format='PNG')
        self.lab.hero_image = get_image_model().objects.create(
            title='Public architecture diagram',
            file=SimpleUploadedFile('lab-diagram.png', buffer.getvalue(), content_type='image/png'),
        )
        image = self.render().select_one('.lab-visual img')
        self.assertEqual(image['alt'], 'Public architecture diagram')
        self.assertTrue(image['src'])
        self.assertGreater(int(image['width']), 0)
        self.assertGreater(int(image['height']), 0)

    def test_no_reading_progress_or_lab_javascript(self):
        self.lab.overview = '<p>Overview.</p>'
        soup = self.render()
        self.assertFalse(soup.select('.lab-page script, [data-reading-document], [data-reading-progress]'))
        self.assertFalse(soup.select('script[src*="reading.js"]'))
        self.assertFalse(soup.select('.lab-index'))

    def test_admin_panels_and_optional_fields(self):
        groups = [panel for panel in LabPage.content_panels if isinstance(panel, MultiFieldPanel)]
        self.assertEqual([(panel.heading, [child.field_name for child in panel.children]) for panel in groups], [
            ('Basic Info', ['intro', 'hero_image']),
            ('Lab Overview', ['overview']),
            ('Infrastructure', ['platform_architecture', 'networking', 'containerization']),
            ('Security & Operations', ['security_controls', 'operations_recovery']),
            ('Current Work', ['current_experiments']),
        ])
        form = LabPage.get_edit_handler().get_form_class()
        for field in ['intro', 'hero_image', *[field for field, _, _ in SECTIONS]]:
            self.assertTrue(LabPage._meta.get_field(field).blank)
            self.assertFalse(form.base_fields[field].required)
        for field in ['intro', *[field for field, _, _ in SECTIONS]]:
            self.assertIsInstance(LabPage._meta.get_field(field), RichTextField)
        hero = LabPage._meta.get_field('hero_image')
        self.assertTrue(hero.null)
        self.assertEqual(hero.remote_field.on_delete, models.SET_NULL)
        self.assertEqual(hero.remote_field.related_name, '+')

    def test_page_tree_constraints_allow_one_lab_per_home_not_globally(self):
        other_home = self.home.get_parent().add_child(instance=HomePage(title='Other', slug='other-home'))
        Site.objects.create(hostname='other.example', root_page=other_home)
        self.assertFalse(LabPage.can_create_at(self.home))
        self.assertTrue(LabPage.can_create_at(other_home))
        self.assertFalse(LabPage.can_create_at(self.home.get_parent()))
        self.assertFalse(Page.can_create_at(self.lab))
        self.assertEqual(LabPage.allowed_parent_page_models(), [HomePage])
        self.assertEqual(LabPage.allowed_subpage_models(), [LabEntryPage])
        other_home.add_child(instance=LabPage(title='Other lab', slug='lab'))
        self.assertEqual(LabPage.objects.count(), 2)

    def test_search_indexes_all_prose_and_not_image(self):
        fields = {field.field_name for field in LabPage.search_fields if isinstance(field, index.SearchField)}
        self.assertTrue({'intro', *[field for field, _, _ in SECTIONS]}.issubset(fields))
        self.assertNotIn('hero_image', fields)

    def test_migration_only_creates_lab_schema(self):
        migration = import_module('home.migrations.0006_labpage').Migration
        self.assertIn(('home', '0005_projectpage_case_study'), migration.dependencies)
        self.assertEqual(len(migration.operations), 1)
        operation = migration.operations[0]
        self.assertIsInstance(operation, migrations.CreateModel)
        self.assertEqual(operation.name, 'LabPage')
        self.assertEqual({name for name, _ in operation.fields}, {
            'page_ptr', 'intro', 'hero_image', *[field for field, _, _ in SECTIONS],
        })


@override_settings(CACHES=LOCAL_CACHE, ALLOWED_HOSTS=['testserver', 'other.example', 'nested.example'])
class LabNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Site.objects.all().delete()
        cls.home = Page.get_first_root_node().add_child(instance=HomePage(title='Home', slug='lab-nav-home'))
        Site.objects.create(hostname='testserver', root_page=cls.home, is_default_site=True)
        cls.work = cls.home.add_child(instance=ProjectIndexPage(title='Work', slug='work'))
        cls.notes = cls.home.add_child(instance=BlogIndexPage(title='Notes', slug='notes'))
        cls.contact = cls.home.add_child(instance=ContactPage(title='Contact', slug='contact'))

    def items(self, page=None, host='testserver'):
        return main_navigation({
            'request': RequestFactory().get('/', HTTP_HOST=host), 'page': page or self.home,
        })['nav_items']

    def create_lab(self, parent=None, **kwargs):
        return (parent or self.home).add_child(instance=LabPage(title='Systems', slug='systems', **kwargs))

    def test_lab_is_absent_without_page_and_existing_navigation_unchanged(self):
        self.assertEqual([item['label'] for item in self.items()], ['WORK', 'ABOUT', 'NOTES', 'CONTACT'])

    def test_live_public_lab_uses_resolved_url_in_correct_position(self):
        lab = self.create_lab(live=False)
        lab.save_revision().publish()
        items = self.items()
        self.assertEqual([item['label'] for item in items], ['WORK', 'LAB', 'ABOUT', 'NOTES', 'CONTACT'])
        self.assertEqual(items[1]['url'], '/systems/')
        self.assertFalse(items[1]['is_active'])

    def test_lab_active_style_and_aria_current_render_in_both_navigation_menus(self):
        lab = self.create_lab()
        soup = BeautifulSoup(self.client.get(lab.url).content, 'html.parser')
        links = soup.select('a[data-nav-label="LAB"]')
        self.assertEqual(len(links), 2)
        for link in links:
            self.assertEqual(link['aria-current'], 'page')
            self.assertIn('site-nav__link--active', link['class'])
        self.assertEqual([item['label'] for item in self.items(lab) if item['is_active']], ['LAB'])

    def test_draft_lab_is_omitted(self):
        self.create_lab(live=False)
        self.assertNotIn('LAB', [item['label'] for item in self.items()])

    def test_private_lab_is_omitted(self):
        lab = self.create_lab()
        PageViewRestriction.objects.create(page=lab, restriction_type='login')
        self.assertNotIn('LAB', [item['label'] for item in self.items()])

    def test_inherited_privacy_omits_lab(self):
        self.create_lab()
        PageViewRestriction.objects.create(page=self.home, restriction_type='login')
        self.assertNotIn('LAB', [item['label'] for item in self.items()])

    def test_other_site_cannot_supply_lab(self):
        other = self.home.get_parent().add_child(instance=HomePage(title='Other', slug='other'))
        Site.objects.create(hostname='other.example', root_page=other)
        lab = self.create_lab(other)
        self.assertNotIn('LAB', [item['label'] for item in self.items()])
        request = RequestFactory().get('/', HTTP_HOST='other.example')
        self.assertEqual(site_destinations(request)['lab'], lab)

    def test_nested_site_owns_its_lab_and_cannot_fall_back_to_outer_lab(self):
        nested = self.home.add_child(instance=HomePage(title='Nested', slug='nested'))
        Site.objects.create(hostname='nested.example', root_page=nested)
        nested_lab = self.create_lab(nested)
        self.assertNotIn('LAB', [item['label'] for item in self.items()])
        outer_lab = self.create_lab()
        outer_request = RequestFactory().get('/', HTTP_HOST='testserver')
        nested_request = RequestFactory().get('/', HTTP_HOST='nested.example')
        self.assertEqual(site_destinations(outer_request)['lab'], outer_lab)
        self.assertEqual(site_destinations(nested_request)['lab'], nested_lab)
        nested_lab.unpublish()
        self.assertIsNone(site_destinations(nested_request)['lab'])

    def test_existing_destinations_and_active_states_are_preserved_with_lab(self):
        before = self.items()
        self.create_lab()
        self.assertEqual([item for item in self.items() if item['label'] != 'LAB'], before)
        project = self.work.add_child(instance=ProjectPage(title='Project', slug='project', intro='Summary'))
        note = self.notes.add_child(instance=BlogPage(title='Note', slug='note', intro='Summary'))
        for page, label in ((project, 'WORK'), (note, 'NOTES'), (self.contact, 'CONTACT')):
            with self.subTest(label=label):
                self.assertEqual([item['label'] for item in self.items(page) if item['is_active']], [label])
        self.assertFalse(any(item['is_active'] for item in self.items(self.home)))
        self.assertEqual(next(item['url'] for item in self.items() if item['label'] == 'ABOUT'), '/#operating-principle')

    def test_missing_request_has_no_navigation_destinations(self):
        self.create_lab()
        self.assertIsNone(site_destinations(None)['lab'])
        self.assertEqual(main_navigation({})['nav_items'], [])
