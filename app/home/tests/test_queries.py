"""Representative public listings; related data must not cost queries per card."""
from datetime import date, datetime, timezone
from io import BytesIO

from PIL import Image
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from wagtail.images import get_image_model
from wagtail.models import Page, PageViewRestriction, Site

from ..models import (
    BlogCategory, BlogIndexPage, BlogPage, ContactPage, HomePage,
    HomePageProject, LabPage, ProjectCategory, ProjectIndexPage,
    ProjectPage, ProjectPageTechStack, SEOSettings, SocialMediaSettings, TechStack,
)
from ..reading import reading_minutes
from ..templatetags.navigation_tags import get_site_navigation


@override_settings(ALLOWED_HOSTS=['testserver', 'nested.example', 'other.example'])
class PublicQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Rendition caches outlive rolled-back image IDs from other test classes.
        cache.clear()
        Site.objects.all().delete()
        cls.home = cls.publish(Page.get_first_root_node(), HomePage(title='Query home', slug='query-home'))
        cls.site = Site.objects.create(hostname='testserver', root_page=cls.home, is_default_site=True)
        SEOSettings.objects.create(site=cls.site)
        SocialMediaSettings.objects.create(site=cls.site)
        cls.work = cls.publish(cls.home, ProjectIndexPage(title='Work', slug='work'))
        cls.notes = cls.publish(cls.home, BlogIndexPage(title='Notes', slug='notes'))
        cls.publish(cls.home, LabPage(title='Lab', slug='lab'))
        cls.publish(cls.home, ContactPage(title='Contact', slug='contact'))
        cls.project_categories = [ProjectCategory.objects.create(name=name, slug=name.lower())
                                  for name in ('Platform', 'Security')]
        cls.blog_categories = [BlogCategory.objects.create(name=name, slug=name.lower())
                               for name in ('Systems', 'Research')]
        cls.techs = [TechStack.objects.create(name=name, slug=name.lower()) for name in ('Python', 'Django')]
        cls.projects, cls.posts = [], []
        for number in range(12):
            published_at = datetime(2026, 1, number + 1, tzinfo=timezone.utc)
            source = BytesIO()
            Image.new('RGB', (32, 24), color=(number * 10, 80, 120)).save(source, format='PNG')
            image = get_image_model().objects.create(
                title=f'Query image {number}',
                file=SimpleUploadedFile(f'query-{number}.png', source.getvalue(), content_type='image/png'),
            )
            image.get_renditions('width-1000', 'fill-1200x800', 'fill-280x120')
            body = [
                ('markdown', 'word ' * 201),
                ('image', {'image': image, 'caption': 'A diagram', 'attribution': 'Test author'}),
                ('code', {'language': 'python', 'code': 'print("hello")'}),
                ('quote', {'quote': 'A short quote', 'author': 'Test author'}),
            ]
            project = cls.work.add_child(instance=ProjectPage(
                title=f'Public project {number}', slug=f'project-{number}', intro='Project summary',
                date=date(2026, 1, number + 1), category=cls.project_categories[number % 2],
                first_published_at=published_at,
                hero_image=image, body=body, live=False,
            ))
            for order, tech in enumerate(cls.techs):
                ProjectPageTechStack.objects.create(page=project, tech=tech, sort_order=order)
            project.save_revision().publish()
            cls.projects.append(project)
            post = cls.notes.add_child(instance=BlogPage(
                title=f'Public note {number}', slug=f'note-{number}', intro='Note summary',
                date=date(2026, 1, number + 1), categories=cls.blog_categories[number % 2],
                first_published_at=published_at,
                body=body, live=False,
            ))
            post.tags.add('python', 'django')
            post.save_revision().publish()
            cls.posts.append(post)

    @staticmethod
    def publish(parent, page):
        parent.add_child(instance=page)
        page.save_revision().publish()
        return page

    def request(self, params=None, host='testserver'):
        return RequestFactory().get('/', params or {}, HTTP_HOST=host)

    def render(self, page, params=None):
        request = self.request(params)
        return render_to_string(page.get_template(request), page.get_context(request), request=request)

    def test_project_card_relations_are_loaded_in_bulk(self):
        for count in (1, 6, 12):
            with self.subTest(projects=count):
                cache.clear()
                context = self.work.get_context(self.request())
                with self.assertNumQueries(3):
                    projects = list(context['projects'][:count])
                with self.assertNumQueries(0):
                    for project in projects:
                        self.assertTrue(project.category.name)
                        self.assertEqual([item.tech.name for item in project.tech_stack_items.all()], ['Python', 'Django'])
                        self.assertTrue(project.hero_image.get_rendition('width-1000').file)
                self.assertTrue(all('body' in project.get_deferred_fields() for project in projects))

    def test_blog_card_relations_and_reading_time_are_loaded_in_bulk(self):
        for page_number, count in ((1, 9), (2, 3)):
            with self.subTest(page=page_number):
                context = self.notes.get_context(self.request({'page': page_number}))
                with self.assertNumQueries(2):
                    posts = list(context['posts'])
                self.assertEqual(len(posts), count)
                with self.assertNumQueries(0):
                    for post in posts:
                        self.assertTrue(post.categories.name)
                        self.assertEqual({tag.slug for tag in post.tags.all()}, {'python', 'django'})
                        self.assertEqual(reading_minutes(post), 2)

    def test_homepage_card_renditions_are_loaded_in_bulk(self):
        for curated in (False, True):
            with self.subTest(curated=curated):
                cache.clear()
                if curated:
                    for order, project in enumerate(reversed(self.projects[:3])):
                        HomePageProject.objects.create(home_page=self.home, project=project, sort_order=order)
                context = self.home.get_context(self.request())
                projects = [context['primary_project'], *context['supporting_projects']]
                self.assertEqual([project.pk for project in projects],
                                 [project.pk for project in reversed(self.projects[:3] if curated else self.projects[-3:])])
                with self.assertNumQueries(0):
                    for position, project in enumerate(projects):
                        self.assertTrue(project.category.name)
                        spec = 'fill-1200x800' if position == 0 else 'fill-280x120'
                        self.assertTrue(project.hero_image.get_rendition(spec).file)
                self.assertTrue(all('body' in project.get_deferred_fields() for project in projects))

    def test_rendered_query_counts_do_not_grow_per_card(self):
        for page, params, expected in (
            (self.work, {}, 22),
            (self.work, {'category': 'platform', 'tech': 'python,django'}, 22),
            (self.notes, {}, 21),
            (self.notes, {'page': 2}, 21),
            (self.home, {}, 25),
        ):
            with self.subTest(page=type(page).__name__, params=params):
                cache.clear()
                Site.get_site_root_paths()
                with self.assertNumQueries(expected):
                    html = self.render(page, params)
                self.assertIn('Public ', html)

    def test_reading_time_uses_current_text_without_loading_images_or_writing(self):
        BlogPage.objects.filter(pk=self.posts[0].pk).update(reading_time=99)
        post = BlogPage.objects.get(pk=self.posts[0].pk)
        serialized = post.body.get_prep_value()
        with self.assertNumQueries(0):
            self.assertEqual(reading_minutes(post), 2)
            self.assertEqual(post.body.get_prep_value(), serialized)
        self.assertEqual(post.reading_time, 99)
        post.body[1].value['caption'] = 'caption ' * 400
        with self.assertNumQueries(0):
            self.assertEqual(reading_minutes(post), 4)
        post.save()
        post.refresh_from_db()
        self.assertEqual(post.reading_time, 4)
        with self.assertNumQueries(0):
            self.assertEqual(reading_minutes(post), 4)

    def test_navigation_is_reused_only_in_the_same_render_context(self):
        context = Context({'request': self.request(), 'page': self.home})
        first = get_site_navigation(context)
        with self.assertNumQueries(0):
            self.assertEqual(get_site_navigation(context), first)
        self.work.unpublish()
        fresh = Context({'request': self.request(), 'page': self.home})
        self.assertIsNone(get_site_navigation(fresh)['work'])

    def test_navigation_cache_distinguishes_page_branches_and_requests(self):
        second = self.publish(self.home, ProjectIndexPage(title='Second work', slug='second-work'))
        detail = self.publish(second, ProjectPage(title='Second detail', slug='second-detail', intro='Summary'))
        context = Context({'request': self.request(), 'page': self.projects[0]})
        self.assertEqual(get_site_navigation(context)['work'].pk, self.work.pk)
        context['page'] = detail
        self.assertEqual(get_site_navigation(context)['work'].pk, second.pk)
        nested = self.publish(self.home, HomePage(title='Nested', slug='nested'))
        Site.objects.create(hostname='nested.example', root_page=nested)
        nested_work = self.publish(nested, ProjectIndexPage(title='Nested work', slug='nested-work'))
        context['request'] = self.request(host='nested.example')
        self.assertEqual(get_site_navigation(context)['root'].pk, nested.pk)
        self.assertEqual(get_site_navigation(context)['work'].pk, nested_work.pk)

    def test_filters_pagination_and_ordering_survive_prefetching(self):
        context = self.work.get_context(self.request({'category': 'platform', 'tech': 'python,django'}))
        self.assertEqual([page.pk for page in context['projects']],
                         [page.pk for page in reversed(self.projects[::2])])
        context = self.notes.get_context(self.request({'category': 'systems', 'tag': 'python', 'page': 'invalid'}))
        self.assertEqual(context['posts'].number, 1)
        self.assertEqual([page.pk for page in context['posts']], [page.pk for page in reversed(self.posts[::2])])
        self.assertEqual(self.notes.get_context(self.request({'page': '999'}))['posts'].number, 2)

    def test_optimized_views_exclude_draft_private_and_other_site_content(self):
        nested = self.publish(self.home, HomePage(title='Nested', slug='nested'))
        Site.objects.create(hostname='nested.example', root_page=nested)
        other = self.publish(self.home.get_parent(), HomePage(title='Other', slug='other'))
        Site.objects.create(hostname='other.example', root_page=other)
        restricted = self.publish(self.home, Page(title='Restricted branch', slug='restricted'))
        PageViewRestriction.objects.create(page=restricted, restriction_type='login')
        hidden_projects = []
        for model, index, category_field, category in (
            (ProjectPage, self.work, 'category', self.project_categories[0]),
            (BlogPage, self.notes, 'categories', self.blog_categories[0]),
        ):
            for number, parent in enumerate((index, index, restricted, nested, other)):
                page = parent.add_child(instance=model(
                    title=f'Hidden {model.__name__} {number}', slug=f'hidden-{model.__name__.lower()}-{number}',
                    intro='Hidden summary', live=False, **{category_field: category},
                ))
                if number:
                    page.save_revision().publish()
                if number == 1:
                    PageViewRestriction.objects.create(page=page, restriction_type='login')
                if model is ProjectPage:
                    hidden_projects.append(page)
        for order, project in enumerate(hidden_projects):
            HomePageProject.objects.create(home_page=self.home, project=project, sort_order=order)
        for page in (self.work, self.notes, self.home):
            with self.subTest(page=type(page).__name__):
                html = self.render(page)
                self.assertNotIn('Hidden ', html)
        context = self.home.get_context(self.request())
        self.assertIsNone(context['primary_project'])
        self.assertEqual(context['published_project_count'], 12)
        self.assertEqual(context['published_note_count'], 12)
        self.assertEqual(context['latest_project'].pk, self.projects[-1].pk)
        self.assertEqual(context['latest_note'].pk, self.posts[-1].pk)
