from django import template
from wagtail.models import Page

register = template.Library()


@register.simple_tag()
def get_site_root():
    """
    Get the site root page (home page)
    """
    return Page.objects.filter(depth=2).first()


@register.inclusion_tag('tags/main_navigation.html', takes_context=True)
def main_navigation(context):
    """
    Get main navigation pages (direct children of home page)
    """
    request = context['request']
    site_root = get_site_root()
    
    if site_root:
        pages = site_root.get_children().live().in_menu()
    else:
        pages = []
    
    return {
        'pages': pages,
        'request': request,
    }