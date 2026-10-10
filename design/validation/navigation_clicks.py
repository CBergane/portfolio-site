"""Browser regressions using synthetic, in-memory Django pages and local assets.

Requires the app dependencies, Playwright and an installed Chromium browser.
Supply --htmx-script with a local copy of the site's pinned HTMX 1.9.10 to test
actual swaps too. Browser requests never reach external services or production.
"""
import argparse
import mimetypes
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.test_settings'


def render_fixtures():
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.test import Client
    from home.models import HomePage, ProjectIndexPage, ProjectPage, BlogIndexPage, BlogPage, ContactPage, LabPage
    from wagtail.models import Page, Site

    assert settings.DATABASES['default']['NAME'] == ':memory:'
    call_command('migrate', verbosity=0)
    Site.objects.all().delete()
    home = Page.get_first_root_node().add_child(instance=HomePage(title='Home', slug='preview'))
    Site.objects.create(hostname='testserver', root_page=home, is_default_site=True)
    work = home.add_child(instance=ProjectIndexPage(title='Work', slug='projects'))
    notes = home.add_child(instance=BlogIndexPage(title='Notes', slug='blog'))
    home.add_child(instance=ContactPage(title='Contact', slug='contact'))
    home.add_child(instance=LabPage(title='Lab', slug='lab'))
    for number in range(3):
        work.add_child(instance=ProjectPage(title=f'Synthetic project {number}', slug=f'project-{number}', intro='Controlled test content.'))
        notes.add_child(instance=BlogPage(title=f'Synthetic note {number}', slug=f'note-{number}', intro='Controlled test content.'))
    client = Client()
    documents = {}
    for path in ('/', '/projects/', '/lab/', '/blog/', '/contact/'):
        response = client.get(path)
        assert response.status_code == 200, path
        documents[path] = response.content
    return documents


def click(page, selector):
    link = page.locator(selector)
    box = link.bounding_box()
    assert box, ('navigation control is hidden', selector)
    point = [box['x'] + box['width'] / 2, box['y'] + box['height'] / 2]
    assert link.evaluate('(node, [x, y]) => node.contains(document.elementFromPoint(x, y))', point), ('pointer intercepted', selector)
    # Raw pointer clicks expose dropped events instead of retrying until they work.
    page.mouse.click(*point)


def unlocked(page):
    page.wait_for_function("""() => document.querySelector('#mobile-menu').hidden &&
        !document.documentElement.classList.contains('menu-open') &&
        document.body.style.position !== 'fixed' &&
        [...document.querySelectorAll('.site-main, .site-footer, .skip-link')].every(node => !node.inert)""")


def settled_section(page, target):
    page.wait_for_function("""id => {
        const node = document.getElementById(id);
        const top = node.getBoundingClientRect().top;
        return id === 'overview' ? Math.abs(scrollY) < 1 :
            Math.abs(top - parseFloat(getComputedStyle(node).scrollMarginTop)) < 1;
    }""", arg=target)
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def rail_regression(page, smooth):
    page.goto('http://testserver/', wait_until='load')
    page.wait_for_function("!document.querySelector('.section-rail__status').hidden")
    link = page.locator('.section-rail a[href="#overview"]')
    if smooth:
        page.evaluate("document.querySelector('#current-signal').scrollIntoView({behavior:'instant', block:'start'})")
        page.wait_for_function("!document.querySelector('.section-rail__status').hidden")
        page.evaluate("scrollTo({top:document.documentElement.scrollHeight, behavior:'smooth'})")
        page.wait_for_function("document.querySelector('#current-signal').getBoundingClientRect().bottom < innerHeight * .15 + 100")
    before = link.bounding_box()
    point = [before['x'] + before['width'] / 2, before['y'] + before['height'] / 2]
    page.mouse.move(*point)
    page.mouse.down()
    if smooth:
        page.wait_for_timeout(150)
    else:
        page.evaluate("scrollTo({top:document.documentElement.scrollHeight, behavior:'instant'})")
    page.wait_for_function("document.querySelector('.section-rail__status').hidden")
    after = link.bounding_box()
    assert abs(before['y'] - after['y']) < .5, ('section links moved during a click', before, after)
    assert link.evaluate('(node, [x, y]) => node.contains(document.elementFromPoint(x, y))', point), 'pointer left section link'
    page.mouse.up()
    page.wait_for_url('http://testserver/#overview')
    settled_section(page, 'overview')


def desktop_navigation(page):
    for label, path in (('WORK', '/projects/'), ('LAB', '/lab/'), ('ABOUT', '/#operating-principle'), ('NOTES', '/blog/'), ('CONTACT', '/contact/')):
        page.goto('http://testserver/', wait_until='load')
        page.evaluate("scrollTo({top:document.documentElement.scrollHeight, behavior:'instant'})")
        click(page, f'.site-nav--desktop a[data-nav-label="{label}"]')
        page.wait_for_url('http://testserver' + path)
        if label == 'ABOUT':
            settled_section(page, 'operating-principle')
            # Clicking an existing hash must still return to its section.
            page.evaluate("scrollTo({top:0, behavior:'instant'})")
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            click(page, '.site-nav--desktop a[data-nav-label="ABOUT"]')
            settled_section(page, 'operating-principle')


def mobile_navigation(page, width):
    page.goto('http://testserver/', wait_until='load')
    page.evaluate("scrollTo({top:1200, behavior:'instant'})")
    saved = page.evaluate('scrollY')
    click(page, '#mobile-menu-btn')
    assert page.locator('#mobile-menu-btn').get_attribute('aria-expanded') == 'true'
    assert page.evaluate("document.querySelector('main').inert && document.body.style.position === 'fixed'")
    page.locator('#mobile-menu a').last.focus()
    page.keyboard.press('Tab')
    assert page.locator('.site-brand').evaluate('node => node === document.activeElement')
    page.keyboard.press('Shift+Tab')
    assert page.locator('#mobile-menu a').last.evaluate('node => node === document.activeElement')
    page.keyboard.press('Escape')
    unlocked(page)
    assert page.evaluate('scrollY') == saved
    assert page.locator('#mobile-menu-btn').evaluate('node => node === document.activeElement')
    click(page, '#mobile-menu-btn')
    page.set_viewport_size({'width':768, 'height':812})
    unlocked(page)
    page.set_viewport_size({'width':width, 'height':812})
    for label, path in (('WORK', '/projects/'), ('LAB', '/lab/'), ('ABOUT', '/#operating-principle'), ('NOTES', '/blog/'), ('CONTACT', '/contact/')):
        page.goto('http://testserver/', wait_until='load')
        click(page, '#mobile-menu-btn')
        click(page, f'#mobile-menu a[data-nav-label="{label}"]')
        page.wait_for_url('http://testserver' + path)
        unlocked(page)
        if label == 'ABOUT':
            settled_section(page, 'operating-principle')
        else:
            page.go_back(wait_until='load')
            unlocked(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--htmx-script', type=Path)
    args = parser.parse_args()
    documents = render_fixtures()
    from django.contrib.staticfiles import finders

    def serve(route):
        url = urlsplit(route.request.url)
        path = unquote(url.path)
        if url.hostname == 'unpkg.com' and args.htmx_script:
            route.fulfill(status=200, content_type='application/javascript', body=args.htmx_script.read_bytes())
        elif url.hostname != 'testserver':
            route.fulfill(status=200, content_type='application/javascript', body='')
        elif path == '/navigation-fragment/':
            route.fulfill(status=200, content_type='text/html', body='<p>Local HTMX fragment</p>')
        elif path in documents:
            route.fulfill(status=200, content_type='text/html', body=documents[path])
        elif path.startswith('/static/') and (asset := finders.find(path.removeprefix('/static/'))):
            route.fulfill(status=200, content_type=mimetypes.guess_type(asset)[0] or 'application/octet-stream', body=Path(asset).read_bytes())
        else:
            route.fulfill(status=404, body='Not found')

    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        print('Chromium:', browser.version, flush=True)
        for motion in ('no-preference', 'reduce'):
            for width in (320, 375, 767, 768, 1024, 1366):
                context = browser.new_context(viewport={'width':width, 'height':812}, reduced_motion=motion)
                context.route('**/*', serve)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                if width < 768:
                    mobile_navigation(page, width)
                else:
                    desktop_navigation(page)
                if width == 1366:
                    for target in ('overview', 'selected-systems', 'operating-principle', 'capabilities', 'current-signal'):
                        page.goto('http://testserver/', wait_until='load')
                        click(page, f'.section-rail a[href="#{target}"]')
                        settled_section(page, target)
                    rail_regression(page, smooth=False)
                    for _ in range(3):
                        rail_regression(page, smooth=True)
                if args.htmx_script:
                    page.goto('http://testserver/', wait_until='load')
                    assert page.evaluate('htmx.version') == '1.9.10'
                    page.evaluate("""() => {
                        const target = document.createElement('div');
                        document.body.appendChild(target);
                        return htmx.ajax('GET', '/navigation-fragment/', {target});
                    }""")
                    page.wait_for_function("document.body.textContent.includes('Local HTMX fragment')")
                    if width < 768:
                        click(page, '#mobile-menu-btn')
                        click(page, '#mobile-menu a[data-nav-label="WORK"]')
                    else:
                        click(page, '.site-nav--desktop a[data-nav-label="WORK"]')
                    page.wait_for_url('http://testserver/projects/')
                    unlocked(page)
                print(f'PASS {width}px / {motion}: pointer clicks, navigation and recovery', flush=True)
                context.close()
        # Reserve the readout before scripts run, as well as during scrolling.
        def delayed_initialization(route):
            if urlsplit(route.request.url).path in ('/static/js/navigation.js', '/static/js/home.js'):
                route.fulfill(status=200, content_type='application/javascript', body='')
            else:
                serve(route)
        context = browser.new_context(viewport={'width':1366, 'height':812})
        context.route('**/*', delayed_initialization)
        page = context.new_page()
        page.goto('http://testserver/', wait_until='load')
        link = page.locator('.section-rail a[href="#overview"]')
        before = link.bounding_box()
        point = [before['x'] + before['width'] / 2, before['y'] + before['height'] / 2]
        page.mouse.move(*point)
        page.mouse.down()
        page.evaluate("""() => {
            document.documentElement.classList.add('navigation-ready');
            const status = document.querySelector('.section-rail__status');
            status.textContent = 'Overview';
            status.hidden = false;
        }""")
        assert abs(link.bounding_box()['y'] - before['y']) < .5, 'links moved when the readout initialized'
        page.mouse.up()
        page.wait_for_url('http://testserver/#overview')
        settled_section(page, 'overview')
        context.close()
        print('PASS early click while the section readout initializes', flush=True)
        browser.close()
    assert not errors, errors
    if not args.htmx_script:
        print('SKIP real HTMX swap checks: supply --htmx-script with a local pinned script.')


if __name__ == '__main__':
    main()
