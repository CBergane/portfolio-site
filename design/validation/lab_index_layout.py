"""Validate Lab presentation in local Chrome using disposable in-memory content.

Uses the same Playwright/Chrome setup as home_hero_layout.py. No server,
production database, content migration or runtime dependency is required.
Run with a Python environment containing the app dependencies and Playwright:
    python design/validation/lab_index_layout.py
"""
import argparse
from io import BytesIO
import json
import mimetypes
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import unquote, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.test_settings'
os.environ['DJANGO_DEBUG'] = '1'


def render_fixtures():
    import django
    django.setup()
    from django.conf import settings
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.core.management import call_command
    from django.test import Client
    from PIL import Image
    from wagtail.images import get_image_model
    from wagtail.models import Page, PageViewRestriction, Site
    from home.models import HomePage, LabPage, LabEntryPage, LabEntryPageTechStack, TechStack

    assert settings.DATABASES['default']['NAME'] == ':memory:'
    call_command('migrate', verbosity=0)
    Site.objects.all().delete()
    home = Page.get_first_root_node().add_child(instance=HomePage(title='Home', slug='preview'))
    Site.objects.create(hostname='testserver', root_page=home, is_default_site=True)
    lab = home.add_child(instance=LabPage(
        title='Lab', slug='lab',
        intro='<p>A working space for experiments in infrastructure, security, automation and observability. Build, investigate and document what happens.</p>',
        overview='<p>A small virtualised platform supports isolated environments and repeatable experiments. The entries document the systems, decisions and findings.</p>',
        **{field: '<p>Legacy documentation retained in the database.</p>'
           for field, _, _ in LabPage.section_definitions if field != 'overview'},
    ))
    buffer = BytesIO()
    Image.new('RGB', (960, 540), '#242b33').save(buffer, format='PNG')
    diagram = get_image_model().objects.create(title='Validation image', file=SimpleUploadedFile(
        'validation.png', buffer.getvalue(), content_type='image/png',
    ))
    titles = ['Proxmox Infrastructure', 'Security Monitoring Lab', 'Infrastructure as Code', 'Detection Engineering', 'Recon Research Environment']
    entries = []
    tech = TechStack.objects.create(name='Python', slug='python')
    for number, ((lab_type, _), title) in enumerate(zip(LabEntryPage.LAB_TYPE_CHOICES, titles)):
        entry = lab.add_child(instance=LabEntryPage(
            title=title, slug=f'entry-{number}', lab_type=lab_type,
            intro='A focused investigation with a repeatable environment, documented decisions and practical findings.',
            status='experimenting', is_featured=number < 3,
            hero_image=diagram if number == 0 else None,
        ))
        LabEntryPageTechStack.objects.create(page=entry, tech=tech, is_primary=True)
        entries.append(entry)
    for slug, live in (('draft', False), ('private', True)):
        hidden = lab.add_child(instance=LabEntryPage(title=slug, slug=slug, intro='Hidden entry', live=live, is_featured=True))
        if live:
            PageViewRestriction.objects.create(page=hidden, restriction_type='login')
    empty = home.add_child(instance=LabPage(title='Empty lab', slug='empty-lab'))
    client = Client()
    paths = [lab.url, empty.url, *[entry.url for entry in entries]]
    documents = {}
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        documents[path] = response.content
    lab.hero_image = diagram
    lab.save()
    documents['/lab-with-image/'] = client.get(lab.url).content
    return documents, Path(settings.MEDIA_ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(tempfile.gettempdir()) / 'portfolio-lab-index-review')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    documents, media_root = render_fixtures()
    from django.contrib.staticfiles import finders

    def serve(route):
        url = urlsplit(route.request.url)
        path = unquote(url.path)
        if url.hostname != 'testserver':
            # Keep the browser check local, including the site's shared CDN script.
            route.fulfill(status=200, content_type='application/javascript', body='')
        elif path in documents:
            route.fulfill(status=200, content_type='text/html; charset=utf-8', body=documents[path])
        else:
            asset = finders.find(path.removeprefix('/static/')) if path.startswith('/static/') else None
            if path.startswith('/media/'):
                asset = media_root / path.removeprefix('/media/')
            if asset and Path(asset).is_file():
                route.fulfill(status=200, content_type=mimetypes.guess_type(str(asset))[0] or 'application/octet-stream', body=Path(asset).read_bytes())
            else:
                route.fulfill(status=404, body='Not found')

    results, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        for javascript, motion in ((True, 'no-preference'), (True, 'reduce'), (False, 'reduce')):
            context = browser.new_context(java_script_enabled=javascript, reduced_motion=motion)
            context.route('**/*', serve)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
            for path in ('/lab/', '/empty-lab/', '/lab-with-image/'):
                for width in (320, 375, 480, 768, 1024, 1440):
                    page.set_viewport_size({'width': width, 'height': 900})
                    page.goto('http://testserver' + path, wait_until='networkidle')
                    result = page.evaluate("""() => {
                        const ids = [...document.querySelectorAll('[id]')].map(node => node.id);
                        return {
                            overflow: document.documentElement.scrollWidth > innerWidth,
                            h1: document.querySelectorAll('h1').length,
                            duplicateIds: ids.length !== new Set(ids).size,
                            sections: [...document.querySelectorAll('.lab-landing h2')].map(node => node.textContent),
                            focus: document.querySelectorAll('.lab-focus .lab-record').length,
                            all: document.querySelectorAll('.lab-all .lab-record').length,
                            counts: [...document.querySelectorAll('.lab-area-list dd')].map(node => node.textContent),
                            imagesLoaded: [...document.querySelectorAll('.lab-landing img')].every(img => img.naturalWidth > 0 && img.alt),
                            animations: document.querySelector('.lab-landing').getAnimations({subtree: true}).length
                        };
                    }""")
                    assert not result['overflow'] and not result['duplicateIds'], result
                    assert result['h1'] == 1 and result['imagesLoaded'] and result['animations'] == 0, result
                    empty = path == '/empty-lab/'
                    assert result['focus'] == (0 if empty else 2) and result['all'] == (0 if empty else 5), result
                    assert result['counts'] == (['0 published entries'] if empty else ['1 published entry']) * 5, result
                    if not empty:
                        assert result['sections'] == ['Current Focus', 'Lab Foundation', 'Lab Areas', 'All Labs', 'Operating Principles'], result
                        link = page.locator('.lab-focus h3 a').first
                        link.focus()
                        assert link.evaluate("node => node === document.activeElement && getComputedStyle(node).outlineStyle !== 'none'")
                    if javascript and motion == 'reduce' and width in (375, 768, 1440):
                        page.evaluate("document.activeElement.blur(); scrollTo({top: 0, behavior: 'instant'})")
                        page.screenshot(path=str(args.output / f'{path.strip("/")}-{width}.png'), full_page=True)
                    results.append({'path': path, 'width': width, 'javascript': javascript, 'motion': motion, **result})
            context.close()
        browser.close()
    (args.output / 'results.json').write_text(json.dumps({'results': results, 'errors': errors}, indent=2), encoding='utf-8')
    assert not errors, errors
    print(f'{len(results)} responsive checks passed; no console errors. Evidence: {args.output}')


if __name__ == '__main__':
    main()
