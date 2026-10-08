from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models
from django.utils import timezone
from modelcluster.contrib.taggit import ClusterTaggableManager
from modelcluster.fields import ParentalKey
from taggit.models import TaggedItemBase
from wagtail import blocks
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField, StreamField
from wagtail.models import Page
from wagtail.search import index
from wagtailmarkdown.blocks import MarkdownBlock

from ..blocks import CodeBlock, ImageBlock, QuoteBlock
from ..navigation import public_site_pages
from .snippets import BlogCategory


class BlogPageTag(TaggedItemBase):
    content_object = ParentalKey(
        'home.BlogPage',
        related_name='tagged_items',
        on_delete=models.CASCADE
    )


class BlogIndexPage(Page):
    """
    Blog listing page
    """
    intro = RichTextField(blank=True)

    content_panels = Page.content_panels + [
        FieldPanel('intro'),
    ]

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)

        # Get all published blog posts
        all_posts = public_site_pages(BlogPage, request).descendant_of(self).order_by('-first_published_at')

        # Filter by category if provided
        category = request.GET.get('category')
        if category:
            all_posts = all_posts.filter(categories__slug=category)

        # Filter by tag if provided
        tag = request.GET.get('tag')
        if tag:
            all_posts = all_posts.filter(tags__slug=tag)

        # Pagination
        paginator = Paginator(all_posts, 9)  # 9 posts per page
        page = request.GET.get('page')

        try:
            posts = paginator.page(page)
        except PageNotAnInteger:
            posts = paginator.page(1)
        except EmptyPage:
            posts = paginator.page(paginator.num_pages)

        context['posts'] = posts
        context['categories'] = BlogCategory.objects.all()
        context['selected_category'] = category
        context['selected_tag'] = tag

        return context

    class Meta:
        verbose_name = "Blog Index Page"


class BlogPage(Page):
    """
    Individual blog post
    """
    date = models.DateField("Post date", default=timezone.now)
    intro = models.CharField(max_length=250, help_text="Short intro (meta description)")
    body = StreamField([
        ('heading', blocks.CharBlock(
            form_classname="title",
            template='blocks/heading_block.html'
        )),
        ('markdown', MarkdownBlock(  # Ändrat från paragraph till markdown
            icon='pilcrow',
            template='blocks/markdown_block.html'
        )),
        ('code', CodeBlock()),
        ('image', ImageBlock()),
        ('quote', QuoteBlock()),
    ], use_json_field=True)

    categories = models.ForeignKey(
        'home.BlogCategory',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='blog_posts'
    )

    tags = ClusterTaggableManager(through=BlogPageTag, blank=True)

    # Reading time (auto-calculated)
    reading_time = models.IntegerField(default=5, help_text="Minutes to read")

    def save(self, *args, **kwargs):
        from ..reading import reading_minutes

        self.reading_time = reading_minutes(self)
        super().save(*args, **kwargs)

    search_fields = Page.search_fields + [
        index.SearchField('intro'),
        index.SearchField('body'),
    ]

    content_panels = Page.content_panels + [
        FieldPanel('date'),
        FieldPanel('intro'),
        FieldPanel('categories'),
        FieldPanel('tags'),
        FieldPanel('body'),
    ]

    class Meta:
        verbose_name = "Blog Post"
        ordering = ['-date']
