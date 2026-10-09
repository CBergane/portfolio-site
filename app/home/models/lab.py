from django.db import models
from modelcluster.fields import ParentalKey
from wagtail import blocks
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.fields import RichTextField, StreamField
from wagtail.models import Orderable, Page
from wagtail.search import index
from wagtailmarkdown.blocks import MarkdownBlock

from ..blocks import CodeBlock, ImageBlock, QuoteBlock
from ..navigation import public_site_pages


class LabPage(Page):
    """A lab introduction and catalogue owned by a single site homepage."""

    parent_page_types = ["home.HomePage"]
    subpage_types = ["home.LabEntryPage"]
    max_count_per_parent = 1

    intro = RichTextField(blank=True, help_text="Introduce the lab and its purpose.")
    hero_image = models.ForeignKey(
        'wagtailimages.Image', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
        help_text="Optional image or diagram suitable for public viewing."
    )
    overview = RichTextField(blank=True, help_text="The environment's purpose and scope.")
    platform_architecture = RichTextField(blank=True, help_text="Platform design and architectural decisions.")
    networking = RichTextField(blank=True, help_text="Networking principles and design, without private connection details.")
    containerization = RichTextField(blank=True, help_text="Workloads, containers and how they are managed.")
    security_controls = RichTextField(blank=True, help_text="Security practices and controls suitable for public documentation.")
    operations_recovery = RichTextField(blank=True, help_text="Operational practices, validation and recovery approach.")
    current_experiments = RichTextField(blank=True, help_text="Current investigations, experiments and learning.")

    # Legacy document fields retained for editorial content and migration tooling.
    section_definitions = (
        ('overview', 'lab-overview', 'System Overview'),
        ('platform_architecture', 'lab-platform', 'Platform Architecture'),
        ('networking', 'lab-networking', 'Networking'),
        ('containerization', 'lab-containers', 'Workloads & Containers'),
        ('security_controls', 'lab-security', 'Security Controls'),
        ('operations_recovery', 'lab-operations', 'Operations & Recovery'),
        ('current_experiments', 'lab-experiments', 'Current Experiments'),
    )

    search_fields = Page.search_fields + [
        index.SearchField('intro'),
        index.SearchField('overview'),
        index.SearchField('platform_architecture'),
        index.SearchField('networking'),
        index.SearchField('containerization'),
        index.SearchField('security_controls'),
        index.SearchField('operations_recovery'),
        index.SearchField('current_experiments'),
    ]

    content_panels = Page.content_panels + [
        MultiFieldPanel([
            FieldPanel('intro'), FieldPanel('hero_image'),
        ], heading="Basic Info"),
        MultiFieldPanel([FieldPanel('overview')], heading="Lab Overview"),
        MultiFieldPanel([
            FieldPanel('platform_architecture'), FieldPanel('networking'),
            FieldPanel('containerization'),
        ], heading="Infrastructure"),
        MultiFieldPanel([
            FieldPanel('security_controls'), FieldPanel('operations_recovery'),
        ], heading="Security & Operations"),
        MultiFieldPanel([FieldPanel('current_experiments')], heading="Current Work"),
    ]

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['lab_entries'] = public_site_pages(LabEntryPage, request).child_of(self).order_by(
            'path'
        ).defer_streamfields().select_related('hero_image').prefetch_related(
            models.Prefetch('tech_stack_items', queryset=LabEntryPageTechStack.objects.select_related('tech'))
        )
        # Reuse the catalogue's result cache for the small editorial signal.
        context['featured_lab_entries'] = [entry for entry in context['lab_entries'] if entry.is_featured]
        return context

    class Meta:
        verbose_name = "Lab Page"


class LabEntryPage(Page):
    """A publishable experiment or technical investigation within a lab."""

    parent_page_types = ["home.LabPage"]
    subpage_types = []

    LAB_TYPE_CHOICES = [
        ('infrastructure', 'Infrastructure'),
        ('security', 'Security'),
        ('automation', 'Automation'),
        ('observability', 'Observability'),
        ('research', 'Research'),
    ]

    intro = models.CharField(max_length=300, help_text="Short public summary of the lab or experiment.")
    lab_type = models.CharField(
        max_length=20,
        choices=LAB_TYPE_CHOICES,
        default='research',
        help_text="Primary area for this lab or experiment.",
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'), ('experimenting', 'Experimenting'),
            ('documented', 'Documented'), ('paused', 'Paused'), ('archived', 'Archived'),
        ],
        default='active',
    )
    is_featured = models.BooleanField(
        default=False,
        help_text="Feature this entry in the Current Focus section of the Lab index.",
    )
    hero_image = models.ForeignKey(
        'wagtailimages.Image', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    github_url = models.URLField(blank=True, help_text="Optional public repository URL")
    objective = RichTextField(blank=True, help_text="What are you trying to build, test or understand?")
    architecture = RichTextField(blank=True, help_text="Environment, components and technical design.")
    implementation = RichTextField(blank=True, help_text="How the lab was built or configured.")
    security_considerations = RichTextField(blank=True, help_text="Security controls, risks, assumptions and boundaries.")
    findings = RichTextField(blank=True, help_text="Observations, results, problems discovered or lessons from the lab.")
    next_steps = RichTextField(blank=True, help_text="Planned improvements, unanswered questions or future work.")
    body = StreamField([
        ('heading', blocks.CharBlock(form_classname="title", template='blocks/heading_block.html')),
        ('markdown', MarkdownBlock(icon='pilcrow', template='blocks/markdown_block.html')),
        ('code', CodeBlock()),
        ('image', ImageBlock()),
        ('quote', QuoteBlock()),
    ], use_json_field=True, blank=True)

    section_definitions = (
        ('objective', 'lab-entry-objective', 'Objective'),
        ('architecture', 'lab-entry-architecture', 'Architecture'),
        ('implementation', 'lab-entry-implementation', 'Implementation'),
        ('security_considerations', 'lab-entry-security', 'Security Considerations'),
        ('body', 'lab-entry-documentation', 'Technical Documentation'),
        ('findings', 'lab-entry-findings', 'Findings / Observations'),
        ('next_steps', 'lab-entry-next-steps', 'Next Steps'),
    )

    search_fields = Page.search_fields + [
        index.SearchField('intro'),
        index.SearchField('objective'),
        index.SearchField('architecture'),
        index.SearchField('implementation'),
        index.SearchField('security_considerations'),
        index.SearchField('findings'),
        index.SearchField('next_steps'),
        index.SearchField('body'),
    ]

    content_panels = Page.content_panels + [
        MultiFieldPanel([
            FieldPanel('intro'), FieldPanel('hero_image'),
        ], heading="Basic Info"),
        MultiFieldPanel([
            FieldPanel('lab_type'), FieldPanel('status'), FieldPanel('is_featured'),
            InlinePanel('tech_stack_items', label='Tech stack'),
        ], heading="Lab Classification & Technology"),
        MultiFieldPanel([FieldPanel('github_url')], heading="Links"),
        MultiFieldPanel([
            FieldPanel('objective'), FieldPanel('architecture'), FieldPanel('implementation'),
            FieldPanel('security_considerations'), FieldPanel('findings'), FieldPanel('next_steps'),
        ], heading="Lab Documentation"),
        MultiFieldPanel([FieldPanel('body')], heading="Technical Documentation"),
    ]

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['lab_parent'] = self.get_parent()
        context['lab_entry_sections'] = [
            {'field': field, 'id': section_id, 'title': title, 'content': getattr(self, field)}
            for field, section_id, title in self.section_definitions
            if getattr(self, field)
        ]
        context['tech_items'] = self.tech_stack_items.select_related('tech').order_by('-is_primary', 'sort_order', 'pk')
        return context

    class Meta:
        verbose_name = "Lab Project"


class LabEntryPageTechStack(Orderable):
    page = ParentalKey('home.LabEntryPage', related_name='tech_stack_items', on_delete=models.CASCADE)
    tech = models.ForeignKey('home.TechStack', on_delete=models.CASCADE, related_name='+')
    is_primary = models.BooleanField(default=False, blank=True)

    panels = [FieldPanel('tech'), FieldPanel('is_primary')]

    def __str__(self):
        return self.tech.name
