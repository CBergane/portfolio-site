from django.db import models
from modelcluster.fields import ParentalKey
from wagtail.admin.panels import FieldPanel, InlinePanel, PageChooserPanel
from wagtail.fields import RichTextField
from wagtail.models import Orderable, Page

from ..navigation import public_site_pages


class HomePage(Page):
    """
    Main landing page
    """
    body = RichTextField(blank=True)

    content_panels = Page.content_panels + [
        FieldPanel('body'),
        InlinePanel('selected_projects', label='Selected project', max_num=3),
    ]

    def get_context(self, request, *args, **kwargs):
        from .blog import BlogPage
        from .projects import ProjectPage

        context = super().get_context(request, *args, **kwargs)
        selected_project_ids = list(
            self.selected_projects.order_by('sort_order').values_list('project_id', flat=True)
        )
        published_projects = public_site_pages(ProjectPage, request).defer_streamfields()
        published_notes = public_site_pages(BlogPage, request).defer_streamfields()
        project_cards = published_projects.select_related('category', 'hero_image').prefetch_related(
            'hero_image__renditions'
        )

        if selected_project_ids:
            available_projects = project_cards.filter(
                id__in=selected_project_ids
            )
            projects_by_id = {project.id: project for project in available_projects}
            selected_projects = [
                projects_by_id[project_id]
                for project_id in selected_project_ids
                if project_id in projects_by_id
            ]
        else:
            selected_projects = list(
                project_cards.order_by('-date', '-first_published_at')[:3]
            )

        context['primary_project'] = selected_projects[0] if selected_projects else None
        context['supporting_projects'] = selected_projects[1:]
        context['total_projects'] = published_projects.count()
        context['published_project_count'] = context['total_projects']
        context['published_note_count'] = published_notes.count()
        context['latest_project'] = (
            published_projects.order_by('-date', '-first_published_at').first()
            if selected_project_ids else context['primary_project']
        )
        context['latest_note'] = published_notes.order_by('-date', '-first_published_at').first()
        return context

    class Meta:
        verbose_name = "Home Page"


class HomePageProject(Orderable):
    """An editor-curated, ordered project selection for the homepage."""
    home_page = ParentalKey(
        'home.HomePage',
        related_name='selected_projects',
        on_delete=models.CASCADE,
    )
    project = models.ForeignKey(
        'home.ProjectPage',
        related_name='+',
        on_delete=models.CASCADE,
    )

    panels = [
        PageChooserPanel('project', ['home.ProjectPage']),
    ]

    def __str__(self):
        return self.project.title
