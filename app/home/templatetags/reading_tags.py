from django import template

from home.navigation import adjacent_content
from home.reading import reading_minutes

register = template.Library()
register.filter('reading_minutes', reading_minutes)


@register.simple_tag(takes_context=True)
def reading_neighbors(context, navigation):
    return adjacent_content(context.get('request'), context.get('page'), navigation)
