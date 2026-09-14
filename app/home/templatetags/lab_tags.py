"""Presentation helpers for the Lab landing page."""
from django import template
from bs4 import BeautifulSoup

register = template.Library()


@register.filter
def lab_summary_text(value):
    """Keep a legacy rich-text overview readable as one plain-text paragraph."""
    soup = BeautifulSoup(str(value), 'html.parser')
    for block in soup.find_all(['p', 'div', 'li', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        block.insert_after(' ')
    return ' '.join(soup.get_text().split())


@register.filter
def lab_area_count(entries_by_type, lab_type):
    """Count the already-loaded public entries without querying again."""
    return len(entries_by_type.get(lab_type, []))
