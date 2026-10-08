from urllib.parse import urlencode

from django.db import models
from django.utils import timezone
from modelcluster.fields import ParentalKey
from wagtail import blocks
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.fields import RichTextField, StreamField
from wagtail.models import Orderable, Page
from wagtail.search import index
from wagtailmarkdown.blocks import MarkdownBlock

from ..blocks import CodeBlock, ImageBlock, QuoteBlock
from ..navigation import public_site_pages
from .snippets import ProjectCategory, TechStack


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
        FieldPanel("tech"),
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

        # Base queryset
        all_projects = public_site_pages(ProjectPage, request).descendant_of(self).order_by(
            '-date'
        ).defer_streamfields().select_related('category', 'hero_image').prefetch_related(
            models.Prefetch('tech_stack_items', queryset=ProjectPageTechStack.objects.select_related('tech')),
            'hero_image__renditions',
        )

        def get_multi(key: str) -> list[str]:
            """
            Supports:
              ?tech=django&tech=python
            and backwards compat:
              ?tech=django,python
            """
            values = request.GET.getlist(key)
            if len(values) == 1 and "," in values[0]:
                values = [v.strip() for v in values[0].split(",") if v.strip()]

            # de-dupe, keep order
            out: list[str] = []
            for v in values:
                if v and v not in out:
                    out.append(v)
            return out

        selected_status = (request.GET.get('status') or "").strip()
        selected_categories = get_multi('category')
        selected_techs = get_multi('tech')

        # Apply filters (OR semantics for multi-tech / multi-category)
        if selected_categories:
            all_projects = all_projects.filter(category__slug__in=selected_categories)

        if selected_techs:
            all_projects = all_projects.filter(
                tech_stack_items__tech__slug__in=selected_techs
            ).distinct()

        if selected_status:
            all_projects = all_projects.filter(status=selected_status)

        # Helpers to build querystrings (toggle + keep other params)
        def build_qs(*, status=None, toggle_category=None, toggle_tech=None, clear_all=False) -> str:
            cats = list(selected_categories)
            techs = list(selected_techs)
            stat = selected_status

            if clear_all:
                cats, techs, stat = [], [], ""

            if status is not None:
                stat = (status or "").strip()

            if toggle_category:
                if toggle_category in cats:
                    cats.remove(toggle_category)
                else:
                    cats.append(toggle_category)

            if toggle_tech:
                if toggle_tech in techs:
                    techs.remove(toggle_tech)
                else:
                    techs.append(toggle_tech)

            pairs: list[tuple[str, str]] = []
            if stat:
                pairs.append(("status", stat))
            for c in cats:
                pairs.append(("category", c))
            for t in techs:
                pairs.append(("tech", t))
            return urlencode(pairs, doseq=True)

        # Build link models for template (så templaten slipper komplex URL-logik)
        categories = ProjectCategory.objects.all()
        tech_stacks = TechStack.objects.all()

        status_defs = [
            ("completed", "✓ completed"),
            ("in_progress", "⏳ in progress"),
            ("ongoing", "∞ ongoing"),
            ("archived", "📦 archived"),
        ]
        status_label_map = {
            "completed": "COMPLETED",
            "in_progress": "IN PROGRESS",
            "ongoing": "ONGOING",
            "archived": "ARCHIVED",
        }

        status_links = []
        for value, _legacy_label in status_defs:
            label = status_label_map[value]
            is_active = (selected_status == value)
            # klick på aktiv status -> toggla av status (behåll övriga filter)
            qs = build_qs(status="" if is_active else value)
            status_links.append({
                "value": value,
                "label": label,
                "is_active": is_active,
                "qs": qs,
            })

        category_links = []
        for cat in categories:
            is_active = (cat.slug in selected_categories)
            qs = build_qs(toggle_category=cat.slug)
            category_links.append({
                "obj": cat,
                "is_active": is_active,
                "qs": qs,
            })

        tech_links = []
        for tech in tech_stacks:
            is_active = (tech.slug in selected_techs)
            qs = build_qs(toggle_tech=tech.slug)
            tech_links.append({
                "obj": tech,
                "is_active": is_active,
                "qs": qs,
            })

        # Active chips (med "x" för att ta bort) + status-färg som matchar UI
        status_chip_style = {
            "completed": "border-color: rgba(0,186,255,0.35); color: rgba(0,186,255,0.95);",
            "in_progress": "border-color: rgba(234,179,8,0.35); color: rgba(234,179,8,0.95);",
            "ongoing": "border-color: rgba(0,186,255,0.35); color: rgba(0,186,255,0.95);",
            "archived": "border-color: rgba(107,114,128,0.45); color: rgba(209,213,219,0.95);",
        }

        active_chips = []

        if selected_status:
            active_chips.append({
                "label": status_label_map.get(selected_status, selected_status.replace("_", " ")),
                "qs_remove": build_qs(status=""),  # clear status
                "style": status_chip_style.get(
                    selected_status,
                    "border-color: rgba(159,239,0,0.25); color: rgba(159,239,0,0.9);",
                ),
            })

        for cat in categories:
            if cat.slug in selected_categories:
                active_chips.append({
                    "label": f"{cat.icon} {cat.name}" if cat.icon else cat.name,
                    "qs_remove": build_qs(toggle_category=cat.slug),
                    "style": f"border-color: {cat.color}40; color: {cat.color};",
                })

        for tech in tech_stacks:
            if tech.slug in selected_techs:
                active_chips.append({
                    "label": f"{tech.icon} {tech.name}" if tech.icon else tech.name,
                    "qs_remove": build_qs(toggle_tech=tech.slug),
                    "style": f"border-color: {tech.color}40; color: {tech.color};",
                })

        active_count = (1 if selected_status else 0) + len(selected_categories) + len(selected_techs)

        context['projects'] = all_projects
        context['categories'] = categories
        context['tech_stacks'] = tech_stacks

        # Multi-select vars
        context['selected_status'] = selected_status
        context['selected_categories'] = selected_categories
        context['selected_techs'] = selected_techs

        # Backwards-compat (om någon annan template använder gamla)
        context['selected_category'] = selected_categories[0] if selected_categories else ""
        context['selected_tech'] = selected_techs[0] if selected_techs else ""

        # Prebuilt links & chips for templates
        context['status_links'] = status_links
        context['category_links'] = category_links
        context['tech_links'] = tech_links
        context['active_chips'] = active_chips
        context['active_count'] = active_count
        context['is_all_active'] = (active_count == 0)

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

    # Optional structured case study
    problem = RichTextField(blank=True, help_text="What problem did this solve?")
    solution = RichTextField(blank=True, help_text="How did you solve it?")
    architecture = RichTextField(
        blank=True,
        help_text="System architecture, design and important technical decisions"
    )
    security_considerations = RichTextField(
        blank=True,
        help_text="Security considerations, controls, risks and design decisions"
    )
    testing_validation = RichTextField(
        blank=True,
        help_text="How the project was tested, validated or verified"
    )
    outcome = RichTextField(
        blank=True,
        help_text="Result, outcome or current state of the project"
    )
    lessons_learned = RichTextField(
        blank=True,
        help_text="Important lessons, trade-offs or improvements identified"
    )

    # Metadata
    duration = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g. '2 weeks', '3 months'"
    )
    role = models.CharField(
        max_length=120,
        blank=True,
        help_text="Your role or responsibility in the project"
    )

    search_fields = Page.search_fields + [
        index.SearchField('intro'),
        index.SearchField('body'),
        index.SearchField('problem'),
        index.SearchField('solution'),
        index.SearchField('architecture'),
        index.SearchField('security_considerations'),
        index.SearchField('testing_validation'),
        index.SearchField('outcome'),
        index.SearchField('lessons_learned'),
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
            FieldPanel('role'),
        ], heading="Project Details"),

        MultiFieldPanel([
            FieldPanel('github_url'),
            FieldPanel('live_url'),
        ], heading="Links"),

        MultiFieldPanel([
            FieldPanel('problem'),
            FieldPanel('solution'),
            FieldPanel('architecture'),
            FieldPanel('security_considerations'),
            FieldPanel('testing_validation'),
            FieldPanel('outcome'),
            FieldPanel('lessons_learned'),
        ], heading="Case Study"),

        MultiFieldPanel([
            FieldPanel('body'),
        ], heading="Technical Documentation"),
    ]

    class Meta:
        verbose_name = "Project"
        ordering = ['-date']
