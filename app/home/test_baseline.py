"""Compatibility contracts for the existing Wagtail schema and registrations."""
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import connection, models
from django.template.loader import get_template
from django.test import RequestFactory, TestCase
from modelcluster.fields import ParentalKey
from wagtail.contrib.settings.registry import registry
from wagtail.models import Page
from wagtail.snippets.models import get_snippet_models

from . import models as home


MODEL_NAMES = (
    'SocialMediaSettings', 'NavigationSettings', 'SEOSettings', 'BlogCategory',
    'BlogPageTag', 'HomePage', 'LabPage', 'LabEntryPage', 'LabEntryPageTechStack',
    'BlogIndexPage', 'BlogPage', 'TechStack', 'ProjectCategory',
    'ProjectPageTechStack', 'ProjectIndexPage', 'ProjectPage', 'HomePageProject',
    'ContactSubmission', 'ContactPage',
)
PAGE_TEMPLATES = {
    'HomePage': 'home/home_page.html',
    'LabPage': 'home/lab_page.html',
    'LabEntryPage': 'home/lab_entry_page.html',
    'BlogIndexPage': 'home/blog_index_page.html',
    'BlogPage': 'home/blog_page.html',
    'ProjectIndexPage': 'home/project_index_page.html',
    'ProjectPage': 'home/project_page.html',
    'ContactPage': 'home/contact_page.html',
}


class WagtailCompatibilityTests(TestCase):
    def test_model_identities_content_types_and_database_tables(self):
        self.assertEqual(
            {model.__name__ for model in apps.get_app_config('home').get_models()},
            set(MODEL_NAMES),
        )
        tables = set(connection.introspection.table_names())
        for name in MODEL_NAMES:
            with self.subTest(model=name):
                model = getattr(home, name)
                self.assertIs(apps.get_model('home', name), model)
                self.assertEqual(model.__module__, 'home.models')
                self.assertEqual(model._meta.label_lower, f'home.{name.lower()}')
                self.assertEqual(model._meta.db_table, f'home_{name.lower()}')
                self.assertIn(model._meta.db_table, tables)
                content_type = ContentType.objects.get(app_label='home', model=name.lower())
                self.assertIs(content_type.model_class(), model)

    def test_page_inheritance_and_template_paths(self):
        request = RequestFactory().get('/')
        for name, template in PAGE_TEMPLATES.items():
            with self.subTest(model=name):
                model = getattr(home, name)
                self.assertTrue(issubclass(model, Page))
                field = model._meta.get_field('page_ptr')
                self.assertIsInstance(field, models.OneToOneField)
                self.assertIs(field.remote_field.model, Page)
                self.assertTrue(field.remote_field.parent_link)
                self.assertTrue(field.primary_key)
                self.assertEqual(field.column, 'page_ptr_id')
                self.assertIs(field.remote_field.on_delete, models.CASCADE)
                self.assertEqual(model().get_template(request), template)
                self.assertIsNotNone(get_template(template))
        self.assertEqual(home.LabPage.parent_page_types, ['home.HomePage'])
        self.assertEqual(home.LabPage.subpage_types, ['home.LabEntryPage'])
        self.assertEqual(home.LabEntryPage.parent_page_types, ['home.LabPage'])
        self.assertEqual(home.LabEntryPage.subpage_types, [])

    def test_foreign_keys_and_editorial_relationships(self):
        relationships = [
            (home.BlogPage, 'categories', home.BlogCategory, models.ForeignKey, 'blog_posts', models.SET_NULL, True),
            (home.ProjectPage, 'category', home.ProjectCategory, models.ForeignKey, 'projects', models.SET_NULL, True),
            (home.BlogPageTag, 'content_object', home.BlogPage, ParentalKey, 'tagged_items', models.CASCADE, False),
            (home.ProjectPageTechStack, 'page', home.ProjectPage, ParentalKey, 'tech_stack_items', models.CASCADE, False),
            (home.LabEntryPageTechStack, 'page', home.LabEntryPage, ParentalKey, 'tech_stack_items', models.CASCADE, False),
            (home.HomePageProject, 'home_page', home.HomePage, ParentalKey, 'selected_projects', models.CASCADE, False),
            (home.HomePageProject, 'project', home.ProjectPage, models.ForeignKey, '+', models.CASCADE, False),
        ]
        image = apps.get_model('wagtailimages', 'Image')
        site = apps.get_model('wagtailcore', 'Site')
        tag = apps.get_model('taggit', 'Tag')
        relationships.append((home.BlogPageTag, 'tag', tag, models.ForeignKey, 'home_blogpagetag_items', models.CASCADE, False))
        for model in (home.ProjectPageTechStack, home.LabEntryPageTechStack):
            relationships.append((model, 'tech', home.TechStack, models.ForeignKey, '+', models.CASCADE, False))
        for model, field in ((home.SEOSettings, 'og_image'), (home.ProjectPage, 'hero_image'),
                             (home.LabPage, 'hero_image'), (home.LabEntryPage, 'hero_image')):
            relationships.append((model, field, image, models.ForeignKey, '+', models.SET_NULL, True))
        for model in (home.SocialMediaSettings, home.NavigationSettings, home.SEOSettings):
            relationships.append((model, 'site', site, models.OneToOneField, None, models.CASCADE, False))
        for model, name, target, field_type, related_name, on_delete, nullable in relationships:
            with self.subTest(model=model.__name__, field=name):
                field = model._meta.get_field(name)
                self.assertIsInstance(field, field_type)
                self.assertIs(field.remote_field.model, target)
                self.assertEqual(field.remote_field.related_name, related_name)
                self.assertIs(field.remote_field.on_delete, on_delete)
                self.assertEqual(field.null, nullable)
                self.assertEqual(field.column, f'{name}_id')
        self.assertIs(home.BlogPage._meta.get_field('tags').remote_field.through, home.BlogPageTag)

    def test_settings_and_snippets_remain_registered(self):
        self.assertEqual({model for model in registry if model._meta.app_label == 'home'}, {
            home.SocialMediaSettings, home.NavigationSettings, home.SEOSettings,
        })
        self.assertEqual({model for model in get_snippet_models() if model._meta.app_label == 'home'}, {
            home.BlogCategory, home.ProjectCategory, home.TechStack,
        })
