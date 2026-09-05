from django import template
from wagtail.models import Site

from home.models import BlogIndexPage, ContactPage, ProjectIndexPage

register = template.Library()


def _site_for_request(request):
    try:
        return Site.find_for_request(request)
    except Site.DoesNotExist:
        return Site.objects.filter(is_default_site=True).first()


@register.simple_tag(takes_context=True)
def get_site_root(context):
    request = context.get('request')
    site = _site_for_request(request) if request else None
    return site.root_page if site else None


@register.inclusion_tag('home/tags/main_navigation.html', takes_context=True)
def main_navigation(context):
    request = context.get('request')
    site = _site_for_request(request) if request else None
    if not site:
        return {'nav_items': []}
    root_page = site.root_page
    current_page = context.get('page')

    def first_child(page_type):
        return page_type.objects.live().public().child_of(root_page).first()

    work_page = first_child(ProjectIndexPage)
    notes_page = first_child(BlogIndexPage)
    contact_page = first_child(ContactPage)
    root_url = root_page.get_url(request=request)
    destinations = [
        ('WORK', work_page.get_url(request=request), work_page) if work_page else None,
        ('ABOUT', f'{root_url}#operating-principle', root_page) if root_url else None,
        ('NOTES', notes_page.get_url(request=request), notes_page) if notes_page else None,
        ('CONTACT', contact_page.get_url(request=request), contact_page) if contact_page else None,
    ]
    nav_items = []
    for item in destinations:
        if not item:
            continue
        label, url, destination = item
        is_active = bool(current_page and (
            False if label == 'ABOUT'
            else current_page.pk == destination.pk or current_page.is_descendant_of(destination)
        ))
        nav_items.append({'label': label, 'url': url, 'is_active': is_active})
    return {'nav_items': nav_items}
