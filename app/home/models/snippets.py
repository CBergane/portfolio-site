from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.snippets.models import register_snippet


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
