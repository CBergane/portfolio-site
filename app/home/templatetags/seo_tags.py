"""SEO from existing editorial fields, without publishing preview assets."""
from urllib.parse import urljoin

from django import template
from django.utils.text import Truncator
from wagtail.images.models import SourceImageIOError
from wagtail.models import CollectionViewRestriction, Page

from ..models import BlogIndexPage, HomePage, ProjectIndexPage, SEOSettings
from ..reading import visible_text
from ..seo import public_url


register = template.Library()
DEFAULT_DESCRIPTION = (
    'IT Security focused on vulnerability assessment, threat analysis and risk, '
    'supported by Linux infrastructure and secure Python web development.'
)


@register.simple_tag(takes_context=True)
def page_seo(context):
    request, page = context.get('request'), context.get('page')
    settings = context['settings']['home']['SEOSettings']
    title = getattr(page, 'seo_title', '').strip() or getattr(page, 'title', '')
    if isinstance(page, HomePage) and not page.seo_title.strip():
        title = 'IT Security, Infrastructure & Web Development'
    title = f'{title} | {settings.site_name}' if title else settings.site_name

    description = settings.meta_description.strip()
    if not description or description == SEOSettings._meta.get_field('meta_description').default:
        # Replace only the old default at render time; preserve authored CMS text.
        description = DEFAULT_DESCRIPTION
    intro = visible_text(getattr(page, 'intro', ''))
    description = (getattr(page, 'search_description', '').strip()
                   or Truncator(intro).chars(160) or description)

    public = bool(page and page.pk and page.live and not getattr(request, 'is_preview', False)
                  and Page.objects.live().public().filter(pk=page.pk).exists())
    metadata = {'title': title, 'description': description, 'robots': 'noindex,nofollow'}
    if not public:
        return metadata

    url = public_url(request, page.get_full_url(request=request))
    filters = ()
    if isinstance(page, ProjectIndexPage):
        filters = ('status', 'category', 'tech')
    elif isinstance(page, BlogIndexPage):
        filters = ('category', 'tag')
        posts = context['posts']
        if posts.number > 1:
            url += f'?page={posts.number}'
    filtered = any(value for key in filters for value in request.GET.getlist(key))
    metadata.update(url=url, canonical=None if filtered else url,
                    robots='noindex,follow' if filtered else '')

    image = settings.og_image
    if image and not image.collection.get_view_restrictions().exclude(
        restriction_type=CollectionViewRestriction.NONE,
    ).exists():
        try:
            rendition = image.get_rendition('fill-1200x630')
        except SourceImageIOError:
            return metadata
        metadata.update(image_url=urljoin(url, rendition.url), image_alt=image.title)
    return metadata
