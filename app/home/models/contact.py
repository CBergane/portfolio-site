from django.conf import settings
from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Page


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
        context['turnstile_site_key'] = settings.TURNSTILE_SITE_KEY
        return context

    class Meta:
        verbose_name = "Contact Page"
