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


def render_fixtures(hero_image=None, reference_html=None):
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
        overview='<p>A lab provides room to move from a working example to an understood system. It makes it possible to follow a change through its consequences, inspect a failure and try again.</p><p>These documented environments connect hands-on work with <strong>repeatable learning</strong>.</p>',
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
    cases = {
        lab.url: {'entries': [entry.url for entry in entries], 'featured': [entry.url for entry in entries[:2]], 'overview': True, 'hero': False},
        empty.url: {'entries': [], 'featured': [], 'overview': False, 'hero': False},
    }
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        documents[path] = response.content
    lab.hero_image = diagram
    if hero_image:
        lab.hero_image = get_image_model().objects.create(
            title='Existing Lab systems artwork',
            file=SimpleUploadedFile(hero_image.name, hero_image.read_bytes()),
        )
    lab.save()
    documents['/lab-with-image/'] = client.get(lab.url).content
    cases['/lab-with-image/'] = {**cases[lab.url], 'hero': True}
    LabEntryPage.objects.filter(pk__in=[entry.pk for entry in entries]).update(is_featured=False)
    documents['/lab-without-featured/'] = client.get(lab.url).content
    cases['/lab-without-featured/'] = {**cases[lab.url], 'hero': True, 'featured': []}
    for count in (1, 3, 12):
        variant = home.add_child(instance=LabPage(title=f'Lab catalogue with {count} entries', slug=f'lab-{count}'))
        variant_entries = [variant.add_child(instance=LabEntryPage(
            title=f'Documented environment {number + 1}', slug=f'environment-{number + 1}',
            intro='A documented environment for investigating system behaviour.',
            is_featured=number < 3,
        )) for number in range(count)]
        # Verify editorial ordering, including a move that differs from creation order.
        if count > 1:
            variant_entries[-1].move(variant_entries[0], pos='left')
            variant_entries = [variant_entries[-1], *variant_entries[:-1]]
        documents[variant.url] = client.get(variant.url).content
        cases[variant.url] = {
            'entries': [entry.url for entry in variant_entries],
            'featured': [entry.url for entry in variant_entries if entry.is_featured][:2],
            'overview': False, 'hero': False,
        }
        for entry in variant_entries:
            documents[entry.url] = client.get(entry.url).content
    if reference_html:
        # Copy only public prose into the disposable database, never production data.
        from bs4 import BeautifulSoup
        reference = BeautifulSoup(reference_html.read_bytes(), 'html.parser')
        lab.intro = reference.select_one('.lab-intro').decode_contents()
        lab.overview = reference.select_one('.lab-why-copy').decode_contents()
        lab.save()
        documents['/lab-current-copy/'] = client.get(lab.url).content
        cases['/lab-current-copy/'] = {**cases['/lab-without-featured/'], 'overview': True}
    return documents, Path(settings.MEDIA_ROOT), cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(tempfile.gettempdir()) / 'portfolio-lab-index-v2-review')
    parser.add_argument('--hero-image', type=Path, help='Existing artwork to use in disposable fixtures; the source file is never modified.')
    parser.add_argument('--reference-html', type=Path, help='Saved public Lab HTML for an additional fixture using its current intro and overview.')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    documents, media_root, cases = render_fixtures(args.hero_image, args.reference_html)
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
        for javascript, motion in ((True, 'no-preference'), (True, 'reduce'), (False, 'no-preference'), (False, 'reduce')):
            context = browser.new_context(java_script_enabled=javascript, reduced_motion=motion)
            context.route('**/*', serve)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
            for path, expected in cases.items():
                for width in (320, 375, 480, 768, 1024, 1440):
                    page.set_viewport_size({'width': width, 'height': 900})
                    page.goto('http://testserver' + path, wait_until='networkidle')
                    # Load every optional image, including records below the viewport.
                    page.locator('.lab-landing img').evaluate_all("images => images.forEach(image => image.loading = 'eager')")
                    page.wait_for_function("[...document.querySelectorAll('.lab-landing img')].every(image => image.complete && image.naturalWidth > 0)")
                    result = page.evaluate("""() => {
                        const ids = [...document.querySelectorAll('[id]')].map(node => node.id);
                        const rect = selector => document.querySelector(selector)?.getBoundingClientRect().toJSON();
                        const artwork = document.querySelector('.lab-hero .lab-visual');
                        const artworkStyle = artwork && getComputedStyle(artwork);
                        return {
                            overflow: document.documentElement.scrollWidth > innerWidth,
                            h1: document.querySelectorAll('h1').length,
                            duplicateIds: ids.length !== new Set(ids).size,
                            sections: [...document.querySelectorAll('.lab-landing > section > h2, .lab-exploring > h2')].map(node => node.textContent),
                            entries: [...document.querySelectorAll('.lab-catalogue .lab-record-link')].map(node => node.getAttribute('href')),
                            featured: [...document.querySelectorAll('.lab-exploring a')].map(node => node.getAttribute('href')),
                            records: document.querySelectorAll('.lab-record').length,
                            oldUI: document.querySelectorAll('.lab-focus, .lab-foundation, .lab-area-list, .lab-principle-list').length,
                            signalRecords: document.querySelectorAll('.lab-exploring .lab-record, .lab-exploring img').length,
                            principles: [...document.querySelectorAll('.lab-method-list h3')].map(node => node.textContent),
                            heroCopy: rect('.lab-hero-copy'), heroImage: rect('.lab-hero .lab-visual'),
                            heroFirst: document.querySelector('.lab-landing').firstElementChild.matches('.lab-hero'),
                            copyFirst: !artwork || Boolean(document.querySelector('.lab-hero-copy').compareDocumentPosition(artwork) & Node.DOCUMENT_POSITION_FOLLOWING),
                            copyAboveArtwork: !artwork || Number(getComputedStyle(document.querySelector('.lab-hero-copy')).zIndex) > (Number(artworkStyle.zIndex) || 0),
                            artworkIntegrated: !artwork || (artworkStyle.borderTopWidth === '0px' && artworkStyle.backgroundColor === 'rgba(0, 0, 0, 0)' && artworkStyle.boxShadow === 'none' && getComputedStyle(artwork, '::after').backgroundImage.includes('linear-gradient')),
                            methodItems: [...document.querySelectorAll('.lab-method-list > li')].map(node => node.getBoundingClientRect().toJSON()),
                            methodNumbers: [...document.querySelectorAll('.lab-method-number')].map(node => ({text: node.textContent, width: node.getBoundingClientRect().width})),
                            whyHeading: rect('#lab-why-title'), whyCopy: rect('.lab-why-copy'),
                            emptyState: Boolean(document.querySelector('.lab-empty')),
                            imagesLoaded: [...document.querySelectorAll('.lab-landing img')].every(img => img.naturalWidth > 0 && img.alt && Number(img.getAttribute('width')) > 0 && Number(img.getAttribute('height')) > 0),
                            animations: document.querySelector('.lab-landing').getAnimations({subtree: true}).length
                        };
                    }""")
                    assert not result['overflow'] and not result['duplicateIds'], result
                    assert result['h1'] == 1 and result['imagesLoaded'] and result['animations'] == 0, result
                    assert result['entries'] == expected['entries'] and result['featured'] == expected['featured'], result
                    assert result['records'] == len(expected['entries']), result
                    assert result['emptyState'] == (not expected['entries']), result
                    assert result['oldUI'] == 0 and result['signalRecords'] == 0, result
                    assert result['principles'] == ['01 / Build', '02 / Isolate', '03 / Observe', '04 / Document'], result
                    assert result['heroFirst'] and result['copyFirst'] and result['copyAboveArtwork'] and result['artworkIntegrated'], result
                    assert all(number['width'] > 0 for number in result['methodNumbers']), result
                    columns = 4 if width >= 1024 else 2 if width > 480 else 1
                    assert len({round(item['top']) for item in result['methodItems']}) == 4 // columns, result
                    headings = (['Why I Run a Lab'] if expected['overview'] else []) + ['How I Use It', 'Labs']
                    if expected['featured']:
                        headings.append('Currently Exploring')
                    else:
                        assert page.locator('.lab-exploring').count() == 0
                    assert result['sections'] == headings, result
                    assert bool(result.get('heroImage')) == expected['hero'], result
                    if expected['hero']:
                        copy, artwork = result['heroCopy'], result['heroImage']
                        if width >= 1024:
                            # Only the faded lead-in may extend toward the copy column.
                            assert artwork['left'] >= copy['right'] - copy['width'] * .1, result
                            assert .9 <= artwork['width'] / copy['width'] <= 1.15 and artwork['height'] <= 421, result
                            assert artwork['top'] < copy['bottom'] and copy['top'] < artwork['bottom'], result
                        else:
                            assert artwork['top'] >= copy['bottom'] and artwork['height'] <= 281, result
                    if expected['entries']:
                        link = page.locator('.lab-record-link').first
                        assert link.get_attribute('aria-label').startswith('Explore lab: ')
                        for selector in ('.lab-record-link', '.lab-exploring a'):
                            if page.locator(selector).count():
                                target = page.locator(selector).first
                                target.focus()
                                assert target.evaluate("node => node === document.activeElement && getComputedStyle(node).outlineStyle !== 'none'")
                                page.keyboard.press('Shift+Tab')
                                page.keyboard.press('Tab')
                                assert target.evaluate("node => node === document.activeElement && getComputedStyle(node).outlineStyle !== 'none'")
                    if motion == 'reduce' and (javascript or expected['hero'] or not expected['entries']):
                        page.evaluate("document.activeElement.blur(); scrollTo({top: 0, behavior: 'instant'})")
                        suffix = '' if javascript else '-no-js'
                        page.screenshot(path=str(args.output / f'{path.strip("/")}-{width}{suffix}.png'), full_page=True)
                        if expected['hero']:
                            page.screenshot(path=str(args.output / f'{path.strip("/")}-{width}{suffix}-top.png'))
                    if expected['entries']:
                        link.focus()
                        link.press('Enter')
                        page.wait_for_url('http://testserver' + expected['entries'][0])
                        assert page.locator('.lab-entry-page h1').count() == 1
                    results.append({'path': path, 'width': width, 'javascript': javascript, 'motion': motion, **result})
            context.close()
        browser.close()
    (args.output / 'results.json').write_text(json.dumps({'results': results, 'errors': errors}, indent=2), encoding='utf-8')
    assert not errors, errors
    print(f'{len(results)} responsive checks passed; no console errors. Evidence: {args.output}')


if __name__ == '__main__':
    main()
