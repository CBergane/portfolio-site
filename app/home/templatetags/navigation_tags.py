from django import template

from home.navigation import site_destinations, site_for_request

register = template.Library()


@register.simple_tag(takes_context=True)
def get_site_root(context):
    site = site_for_request(context.get('request'))
    return site.root_page if site else None


@register.simple_tag(takes_context=True)
def get_site_navigation(context):
    return site_destinations(context.get('request'), context.get('page'))


@register.inclusion_tag('home/tags/main_navigation.html', takes_context=True)
def main_navigation(context):
    request = context.get('request')
    current_page = context.get('page')
    destinations = get_site_navigation(context)
    nav_items = []
    for label, key in (('WORK', 'work'), ('ABOUT', 'root'), ('NOTES', 'notes'), ('CONTACT', 'contact')):
        destination = destinations[key]
        url = destination.get_url(request=request) if destination else None
        if not url:
            continue
        is_active = bool(label != 'ABOUT' and current_page and (
            current_page.pk == destination.pk or current_page.is_descendant_of(destination)
        ))
        nav_items.append({
            'label': label,
            'url': url + '#operating-principle' if label == 'ABOUT' else url,
            'is_active': is_active,
        })
    return {'nav_items': nav_items}
