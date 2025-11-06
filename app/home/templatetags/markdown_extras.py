from django import template
import markdown as md

register = template.Library()

@register.filter(name='markdown')
def markdown_format(text):
    """
    Convert markdown to HTML with proper list rendering
    """
    return md.markdown(
        text,
        extensions=[
            'extra',           # Tables, fenced code, etc
            'nl2br',           # Newline to <br>
            'sane_lists',      # Better list handling
            'codehilite',      # Syntax highlighting
        ]
    )