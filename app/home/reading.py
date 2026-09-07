"""Read-only estimates from article content, independent of saved metadata."""
import math
import re

import markdown
from bs4 import BeautifulSoup


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

    Count body text, code, image captions and quotes, plus project problem and
    solution prose. Never render image renditions or count page metadata/TOC.
    This helper is side-effect free; callers decide whether to persist the result.
    """
    parts = []
    for block in getattr(page, 'body', ()) or ():
        value = block.value
        if block.block_type == 'code':
            parts.append(str(value.get('code', '')))
        elif block.block_type in ('image', 'quote'):
            keys = ('caption', 'attribution') if block.block_type == 'image' else ('quote', 'author')
            parts.extend(visible_text(value.get(key, '')) for key in keys)
        else:
            parts.append(visible_text(value, is_markdown=block.block_type == 'markdown'))
    for field in ('problem', 'solution'):
        parts.append(visible_text(getattr(page, field, '')))
    words = re.findall(r"\b\w+(?:['’\-]\w+)*\b", ' '.join(parts), flags=re.UNICODE)
    return math.ceil(len(words) / 200) if words else 0
