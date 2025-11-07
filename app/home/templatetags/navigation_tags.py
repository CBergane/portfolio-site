from django import template
from wagtail.models import Page, Site

register = template.Library()


@register.simple_tag()
def get_site_root():
    """
    Get the site root page (home page)
    """
    return Page.objects.filter(depth=2).first()


@register.inclusion_tag('home/tags/main_navigation.html', takes_context=True)
def main_navigation(context):
    """
    Hämta alla publicerade pages som ska visas i menyn
    """
    request = context['request']
    
    # Hämta site via Wagtail Site-modellen
    try:
        site = Site.find_for_request(request)
    except:
        # Fallback till default site
        site = Site.objects.filter(is_default_site=True).first()
    
    if not site:
        return {'menu_pages': [], 'request': request}
    
    root_page = site.root_page
    
    # Hämta alla direkta barn till root som är publicerade och ska visas i menyn
    menu_pages = root_page.get_children().live().in_menu()
    
    return {
        'menu_pages': menu_pages,
        'request': request,
    }