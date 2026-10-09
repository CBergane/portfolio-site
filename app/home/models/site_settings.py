from django.db import models
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting


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
