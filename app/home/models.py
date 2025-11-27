from django.db import models
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone
from modelcluster.fields import ParentalManyToManyField
from modelcluster.models import ClusterableModel
from django import forms
from wagtail.models import Orderable
from wagtail.admin.panels import InlinePanel
from wagtail.snippets.panels import SnippetChooserPanel

from wagtail.models import Page
from wagtail.fields import RichTextField, StreamField
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.search import index
from wagtail import blocks
from wagtail.images.blocks import ImageChooserBlock
from wagtail.snippets.models import register_snippet
from wagtailmarkdown.blocks import MarkdownBlock
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting

from modelcluster.fields import ParentalKey
from modelcluster.contrib.taggit import ClusterTaggableManager
from taggit.models import TaggedItemBase


# ============= SITE SETTINGS =============

@register_setting
class SocialMediaSettings(BaseSiteSetting):
    """
    Social media links and contact info - editable from Wagtail admin
    """
    github_url = models.URLField(blank=True, help_text="GitHub profile URL")
    linkedin_url = models.URLField(blank=True, help_text="LinkedIn profile URL")
    twitter_url = models.URLField(blank=True, help_text="Twitter/X profile URL")
    email = models.EmailField(blank=True, help_text="Contact email address")
    phone = models.CharField(max_length=20, blank=True, help_text="Contact phone number")
    location = models.CharField(max_length=100, default="Stockholm, Sweden", help_text="Your location")
    
    # HTB/TryHackMe profiles
    hackthebox_url = models.URLField(blank=True, help_text="HackTheBox profile URL")
    tryhackme_url = models.URLField(blank=True, help_text="TryHackMe profile URL")
    
    # HTB Stats (manually updated)
    htb_rank = models.CharField(
        max_length=50,
        blank=True,
        default="Noob",
        help_text="Your HTB rank (e.g., Hacker, Pro Hacker, Elite)"
    )
    htb_boxes_owned = models.IntegerField(
        default=0,
        help_text="Number of boxes you've owned"
    )
    htb_user_owns = models.IntegerField(
        default=0,
        help_text="User-owned flags"
    )
    htb_system_owns = models.IntegerField(
        default=0,
        help_text="System-owned flags"
    )
    htb_challenges = models.IntegerField(
        default=0,
        help_text="Challenges solved"
    )
    
    # About text
    footer_text = models.CharField(
        max_length=255,
        default="Site Reliability Engineer | Security Enthusiast | HTB Player",
        help_text="Short bio for footer"
    )
    
    panels = [
        MultiFieldPanel([
            FieldPanel('email'),
            FieldPanel('phone'),
            FieldPanel('location'),
        ], heading="Contact Info"),
        
        MultiFieldPanel([
            FieldPanel('github_url'),
            FieldPanel('linkedin_url'),
            FieldPanel('twitter_url'),
            FieldPanel('hackthebox_url'),
            FieldPanel('tryhackme_url'),
        ], heading="Social Media Links"),
        
        MultiFieldPanel([
            FieldPanel('htb_rank'),
            FieldPanel('htb_boxes_owned'),
            FieldPanel('htb_user_owns'),
            FieldPanel('htb_system_owns'),
            FieldPanel('htb_challenges'),
        ], heading="HackTheBox Stats"),
        
        FieldPanel('footer_text'),
    ]
    
    class Meta:
        verbose_name = "Social Media Settings"

@register_setting
class NavigationSettings(BaseSiteSetting):
    """
    Settings for which pages show in main navigation
    """
    show_in_navigation = models.BooleanField(
        default=True,
        help_text="Enable/disable automatic navigation"
    )
    
    panels = [
        FieldPanel('show_in_navigation'),
    ]
    
    class Meta:
        verbose_name = "Navigation Settings"


@register_setting
class SEOSettings(BaseSiteSetting):
    """
    SEO and meta tag settings
    """
    site_name = models.CharField(
        max_length=100,
        default="Christian Bergane - Portfolio",
        help_text="Site name for meta tags"
    )
    meta_description = models.TextField(
        max_length=160,
        default="Site Reliability Engineer specializing in infrastructure, security, and automation. Based in Stockholm, Sweden.",
        help_text="Default meta description (max 160 characters)"
    )
    meta_keywords = models.CharField(
        max_length=255,
        default="SRE, DevOps, Security, Infrastructure, Django, Python, Proxmox",
        help_text="Default meta keywords (comma-separated)"
    )
    og_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        help_text="Default Open Graph image"
    )
    google_analytics_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="Google Analytics tracking ID (e.g., G-XXXXXXXXXX)"
    )
    
    panels = [
        FieldPanel('site_name'),
        FieldPanel('meta_description'),
        FieldPanel('meta_keywords'),
        FieldPanel('og_image'),
        FieldPanel('google_analytics_id'),
    ]
    
    class Meta:
        verbose_name = "SEO Settings"

# ============= SNIPPETS =============

@register_snippet
class BlogCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, max_length=100)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=10, blank=True, help_text="Emoji icon")
    color = models.CharField(max_length=7, default='#9FEF00', help_text="Hex color code (e.g. #9FEF00)")
    
    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('description'),
        FieldPanel('icon'),
        FieldPanel('color'),
    ]

    class Meta:
        verbose_name = "Blog Category"
        verbose_name_plural = "Blog Categories"
        ordering = ['name']

    def __str__(self):
        return f"{self.icon} {self.name}" if self.icon else self.name


# ============= TAGS =============

class BlogPageTag(TaggedItemBase):
    content_object = ParentalKey(
        'home.BlogPage',
        related_name='tagged_items',
        on_delete=models.CASCADE
    )


# ============= STREAMFIELD BLOCKS =============

class CodeBlock(blocks.StructBlock):
    """
    Code block with syntax highlighting
    """
    language = blocks.ChoiceBlock(
        choices=[
            ('python', 'Python'),
            ('javascript', 'JavaScript'),
            ('bash', 'Bash/Shell'),
            ('html', 'HTML'),
            ('css', 'CSS'),
            ('sql', 'SQL'),
            ('json', 'JSON'),
            ('yaml', 'YAML'),
            ('dockerfile', 'Dockerfile'),
        ],
        default='python'
    )
    code = blocks.TextBlock()

    class Meta:
        template = 'blocks/code_block.html'
        icon = 'code'


class ImageBlock(blocks.StructBlock):
    """
    Image with caption
    """
    image = ImageChooserBlock()
    caption = blocks.CharBlock(required=False)
    attribution = blocks.CharBlock(required=False)

    class Meta:
        template = 'blocks/image_block.html'
        icon = 'image'


class QuoteBlock(blocks.StructBlock):
    """
    Blockquote with author
    """
    quote = blocks.TextBlock()
    author = blocks.CharBlock(required=False)

    class Meta:
        template = 'blocks/quote_block.html'
        icon = 'openquote'


# ============= PAGES =============

class HomePage(Page):
    """
    Main landing page
    """
    body = RichTextField(blank=True)

    content_panels = Page.content_panels + [
        FieldPanel('body'),
    ]
    
    def get_context(self, request, *args, **kwargs):
        from .models import ProjectPage
        context = super().get_context(request, *args, **kwargs)
        context['total_projects'] = ProjectPage.objects.live().count()
        return context

    class Meta:
        verbose_name = "Home Page"


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
        all_posts = BlogPage.objects.live().public().order_by('-first_published_at')
        
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
        # Calculate reading time (average 200 words per minute)
        # Calculate reading time (average 200 wpm) from markdown blocks
        word_count = 0
        for block in self.body:
            if block.block_type == 'markdown' and hasattr(block.value, 'source'):
                word_count += len(block.value.source.split())

        self.reading_time = max(1, round(word_count / 200))
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

# ============= PROJECT SNIPPETS =============

@register_snippet
class TechStack(models.Model):
    """
    Technology tags for projects (reusable)
    """
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, max_length=100)
    icon = models.CharField(
        max_length=50,
        help_text="Emoji or icon",
        default="⚙️"
    )
    color = models.CharField(
        max_length=7,
        default="#9fef00",
        help_text="Hex color for badge (e.g. #9fef00)"
    )
    
    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('icon'),
        FieldPanel('color'),
    ]
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = "Tech Stack"
        verbose_name_plural = "Tech Stack"
        ordering = ['name']


@register_snippet
class ProjectCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, max_length=100)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=10, blank=True, help_text="Emoji icon")
    color = models.CharField(max_length=7, default='#00BAFF', help_text="Hex color code (e.g. #00BAFF)")
    
    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('description'),
        FieldPanel('icon'),
        FieldPanel('color'),
    ]

    class Meta:
        verbose_name = "Project Category"
        verbose_name_plural = "Project Categories"
        ordering = ['name']

    def __str__(self):
        return f"{self.icon} {self.name}" if self.icon else self.name

# ============= PROJECT PAGES =============

class ProjectPageTechStack(Orderable):
    page = ParentalKey(
        "home.ProjectPage",
        related_name="tech_stack_items",
        on_delete=models.CASCADE,
    )

    tech = models.ForeignKey(
        "home.TechStack",
        on_delete=models.CASCADE,
        related_name="+",  # inget baklänges-relationsbrus
    )

    is_primary = models.BooleanField(default=False, blank=True)

    panels = [
        SnippetChooserPanel("tech"),
        FieldPanel("is_primary"),
    ]

    def __str__(self):
        return f"{self.tech.name}"


class ProjectIndexPage(Page):
    """
    Projects listing page
    """
    intro = RichTextField(blank=True)
    
    content_panels = Page.content_panels + [
        FieldPanel('intro'),
    ]
    
    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        
        # Get all published projects
        all_projects = ProjectPage.objects.live().public().order_by('-date')
        
        # Filter by category if provided
        category = request.GET.get('category')
        if category:
            all_projects = all_projects.filter(category__slug=category)
        
        # Filter by tech if provided
        tech = request.GET.get('tech')
        if tech:
            all_projects = all_projects.filter(tech_stack_items__tech__slug=tech).distinct()
        
        # Filter by status if provided
        status = request.GET.get('status')
        if status:
            all_projects = all_projects.filter(status=status)
        
        context['projects'] = all_projects
        context['categories'] = ProjectCategory.objects.all()
        context['tech_stacks'] = TechStack.objects.all()
        context['selected_category'] = category
        context['selected_tech'] = tech
        context['selected_status'] = status
        
        return context
    
    class Meta:
        verbose_name = "Project Index Page"


class ProjectPage(Page):
    """
    Individual project page
    """
    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('in_progress', 'In Progress'),
        ('archived', 'Archived'),
        ('ongoing', 'Ongoing'),
    ]
    
    date = models.DateField("Project date", default=timezone.now)
    intro = models.CharField(max_length=250, help_text="Short description")
    
    # Hero image
    hero_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )
    
    # Project details
    category = models.ForeignKey(
        'home.ProjectCategory',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='projects'
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='completed'
    )
    
    # Links
    github_url = models.URLField(blank=True, help_text="GitHub repository URL")
    live_url = models.URLField(blank=True, help_text="Live demo URL")
    
    # Content
    body = StreamField([
        ('heading', blocks.CharBlock(
            form_classname="title",
            template='blocks/heading_block.html'
        )),
        ('markdown', MarkdownBlock(
            icon='pilcrow',
            template='blocks/markdown_block.html'
        )),
        ('code', CodeBlock()),
        ('image', ImageBlock()),
        ('quote', QuoteBlock()),
    ], use_json_field=True, blank=True)
    
    # Problem/Solution (for case studies)
    problem = RichTextField(blank=True, help_text="What problem did this solve?")
    solution = RichTextField(blank=True, help_text="How did you solve it?")
    
    # Metadata
    duration = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g. '2 weeks', '3 months'"
    )
    
    search_fields = Page.search_fields + [
        index.SearchField('intro'),
        index.SearchField('body'),
    ]
    
    content_panels = Page.content_panels + [
        MultiFieldPanel([
            FieldPanel('date'),
            FieldPanel('intro'),
            FieldPanel('hero_image'),
        ], heading="Basic Info"),
        
        MultiFieldPanel([
            FieldPanel('category'),
            FieldPanel('status'),
            InlinePanel("tech_stack_items", label="Tech stack"),
            FieldPanel('duration'),
        ], heading="Project Details"),
        
        MultiFieldPanel([
            FieldPanel('github_url'),
            FieldPanel('live_url'),
        ], heading="Links"),
        
        FieldPanel('body'),
        
        MultiFieldPanel([
            FieldPanel('problem'),
            FieldPanel('solution'),
        ], heading="Case Study (Optional)"),
    ]
    
    class Meta:
        verbose_name = "Project"
        ordering = ['-date']


# ============= CONTACT FORM =============

class ContactSubmission(models.Model):
    """
    Store contact form submissions in database
    """
    name = models.CharField(max_length=255)
    email = models.EmailField()
    subject = models.CharField(max_length=255, blank=True)
    message = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Status tracking
    read = models.BooleanField(default=False)
    replied = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.name} - {self.submitted_at.strftime('%Y-%m-%d %H:%M')}"
    
    class Meta:
        verbose_name = "Contact Submission"
        verbose_name_plural = "Contact Submissions"
        ordering = ['-submitted_at']


class ContactPage(Page):
    """
    Contact form page
    """
    intro = RichTextField(blank=True)
    thank_you_text = RichTextField(
        blank=True,
        help_text="Text shown after successful submission"
    )
    
    content_panels = Page.content_panels + [
        FieldPanel('intro'),
        FieldPanel('thank_you_text'),
    ]
    
    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['form_submitted'] = request.GET.get('submitted') == 'true'
        return context
    
    class Meta:
        verbose_name = "Contact Page"