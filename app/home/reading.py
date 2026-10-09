"""Read-only estimates from article content, independent of saved metadata."""
import math
import re

import markdown
from bs4 import BeautifulSoup
from wagtail.blocks import StreamValue


def visible_text(value, *, is_markdown=False):
    source = str(getattr(value, 'source', value) or '')
    if is_markdown:
        source = markdown.markdown(source, extensions=['extra'])
    soup = BeautifulSoup(source, 'html.parser')
    for element in soup.select('script, style, nav'):
        element.decompose()
    return soup.get_text(' ', strip=True)


def reading_minutes(page):
    """200 words/minute, rounded up; empty readable content returns zero.

    Count body text, code, image captions and quotes, plus project case-study
    prose. Never render image renditions or count page metadata/TOC.
    Never write to the database; callers decide whether to persist the result.
    """
    parts = []
    body = getattr(page, 'body', ()) or ()
    # Serialized text avoids resolving image choosers, including on lazy streams.
    blocks = body.get_prep_value() if isinstance(body, StreamValue) else (
        {'type': block.block_type, 'value': block.value} for block in body
    )
    for block in blocks:
        value = block['value']
        if block['type'] == 'code':
            parts.append(str(value.get('code', '')))
        elif block['type'] in ('image', 'quote'):
            keys = ('caption', 'attribution') if block['type'] == 'image' else ('quote', 'author')
            parts.extend(visible_text(value.get(key, '')) for key in keys)
        else:
            parts.append(visible_text(value, is_markdown=block['type'] == 'markdown'))
    for field in (
        'problem', 'solution', 'architecture', 'security_considerations',
        'testing_validation', 'outcome', 'lessons_learned',
    ):
        parts.append(visible_text(getattr(page, field, '')))
    words = re.findall(r"\b\w+(?:['’\-]\w+)*\b", ' '.join(parts), flags=re.UNICODE)
    return math.ceil(len(words) / 200) if words else 0
