"""Read-only responsive hero regression checks against a running local preview.

Authoring tool: requires Playwright with a locally installed Chrome browser.
Does not add to the website's runtime or Django test dependencies.

python design/validation/home_hero_layout.py --url http://127.0.0.1:8765/
"""
import argparse
import json
from pathlib import Path
import tempfile

from playwright.sync_api import sync_playwright


WIDTHS = (900, 1024, 1100, 1150, 1198, 1199, 1200, 1201, 1280, 1366, 1440, 1536, 1920)
HEIGHTS = (700, 768, 864, 900, 1000)
SCREENSHOTS = ((1024, 768), (1199, 800), (1200, 800), (1366, 768), (1536, 864), (1920, 1080), (375, 812), (768, 900))
MEASURE = """() => {
    const rect = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
    const art = document.querySelector('.hero-art');
    const image = art.querySelector('img');
    const imageStyle = getComputedStyle(image);
    return {
        viewport: {width: innerWidth, height: innerHeight, dpr: devicePixelRatio},
        hero: rect('.signal-hero'), copy: rect('.signal-hero__content'),
        heading: rect('#hero-title'), statement: rect('.signal-hero__statement'),
        action: rect('.signal-hero__actions .button--primary'),
        header: rect('.site-header'), art: rect('.hero-art'),
        image: rect('.hero-art__image'), next: rect('#selected-systems'),
        artPosition: getComputedStyle(art).position,
        imagePosition: imageStyle.position, imageFit: imageStyle.objectFit,
        imageTransform: imageStyle.transform,
        animations: art.getAnimations({subtree: true}).length,
        hasSvg: Boolean(art.querySelector('svg')),
        overflow: document.documentElement.scrollWidth > innerWidth,
        loaded: document.querySelector('.hero-art img').naturalWidth > 0,
        source: document.querySelector('.hero-art img').currentSrc
    };
}"""


def validate(result):
    width, height = result['viewport']['width'], result['viewport']['height']
    assert not result['overflow'], ('horizontal overflow', result)
    assert result['loaded'], ('image missing', result)
    assert result['artPosition'] == 'absolute', ('artwork entered document flow', result)
    assert result['imagePosition'] == 'absolute', ('image entered document flow', result)
    assert result['imageFit'] == 'cover', ('image does not cover hero', result)
    assert result['imageTransform'] == 'none', ('image transformed', result)
    assert not result['animations'] and not result['hasSvg'], ('hero motion remains', result)
    assert abs(result['next']['top'] - result['hero']['bottom']) < 1, ('gap after hero', result)
    for axis in ('x', 'y', 'width', 'height'):
        assert abs(result['image'][axis] - result['hero'][axis]) < 1, ('image does not fill hero', result)
        assert abs(result['art'][axis] - result['hero'][axis]) < 1, ('picture does not fill hero', result)
    if width >= 900:
        assert result['heading']['top'] >= result['header']['bottom'] - 1, ('heading under header', result)
        assert result['heading']['bottom'] < height, ('heading below viewport', result)
        assert min(result['art']['bottom'], result['copy']['bottom']) > max(result['art']['top'], result['copy']['top']), ('art/copy separated', result)
        assert abs(result['art']['top'] - result['hero']['top']) < 1, ('artwork became another row', result)
        if height >= 700:
            assert result['action']['bottom'] <= height, ('primary action below viewport', result)
            assert result['statement']['bottom'] <= height, ('statement below viewport', result)
            assert result['hero']['height'] <= height + 1, ('hero exceeds one viewport', result)
            assert result['hero']['bottom'] - result['copy']['bottom'] < 160, ('blank band below copy', result)
    elif width < 768:
        assert result['hero']['bottom'] - result['copy']['bottom'] <= 33, ('extra mobile artwork band', result)


def observe_errors(page, errors):
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765/')
    parser.add_argument('--output', type=Path, default=Path(tempfile.gettempdir()) / 'portfolio-hero-layout-review')
    parser.add_argument('--channel', default='chrome')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel, headless=True)
        for scale in (1, 1.25, 1.5, 2):
            context = browser.new_context(device_scale_factor=scale, reduced_motion='reduce')
            page = context.new_page()
            observe_errors(page, errors)
            page.goto(args.url, wait_until='networkidle')
            cases = list(dict.fromkeys([(width, height) for width in WIDTHS for height in HEIGHTS] + list(SCREENSHOTS)))
            for width, height in cases:
                page.set_viewport_size({'width': width, 'height': height})
                page.evaluate("scrollTo({top: 0, behavior: 'instant'})")
                page.wait_for_timeout(80)
                result = page.evaluate(MEASURE)
                validate(result)
                results.append(result)
                if scale == 1 and (width, height) in SCREENSHOTS:
                    page.screenshot(path=str(args.output / f'hero-{width}x{height}.png'))
            print(f'DPR {scale}: {len(cases)} desktop rectangle checks passed', flush=True)
            context.close()

        # Browser zoom equivalents: fixed physical 1536x864, smaller CSS viewport
        # and increased device scale. This exercises the breakpoints zoom selects.
        for zoom in (1.25, 1.5, 2):
            context = browser.new_context(device_scale_factor=zoom, reduced_motion='reduce',
                viewport={'width': round(1536 / zoom), 'height': round(864 / zoom)})
            page = context.new_page()
            observe_errors(page, errors)
            page.goto(args.url, wait_until='networkidle')
            result = page.evaluate(MEASURE)
            validate(result)
            result['zoomEquivalent'] = zoom
            results.append(result)
            page.screenshot(path=str(args.output / f'hero-zoom-{zoom}.png'))
            context.close()

        for javascript, reduced in ((False, 'no-preference'), (True, 'reduce'), (True, 'no-preference')):
            context = browser.new_context(java_script_enabled=javascript, reduced_motion=reduced, device_scale_factor=2)
            page = context.new_page()
            observe_errors(page, errors)
            page.goto(args.url, wait_until='networkidle')
            for width, height in (*SCREENSHOTS, (320, 700)):
                page.set_viewport_size({'width': width, 'height': height})
                page.wait_for_timeout(80)
                result = page.evaluate(MEASURE)
                validate(result)
                result['javascript'] = javascript
                result['reducedMotion'] = reduced
                results.append(result)
                if javascript and reduced == 'no-preference':
                    page.mouse.move(width * .85, height * .45)
                    page.wait_for_timeout(200)
                    after = page.evaluate(MEASURE)
                    validate(after)
                    for element in ('hero', 'copy', 'image', 'next'):
                        assert result[element] == after[element], ('pointer changed geometry', result, after)
                    page.screenshot(path=str(args.output / f'hero-static-{width}x{height}.png'))
                if width in (375, 1024):
                    mode = 'no-js' if not javascript else ('reduced' if reduced == 'reduce' else 'static')
                    page.locator('.signal-hero').screenshot(path=str(args.output / f'hero-{mode}-{width}.png'))
            if javascript:
                page.set_viewport_size({'width': 1366, 'height': 768})
                page.locator('.section-rail a[href="#operating-principle"]').click()
                page.wait_for_function("document.querySelector('.section-rail a[aria-current=\"location\"]').hash === '#operating-principle'")
                assert page.locator('.site-nav__link--section-active').count() > 0
            context.close()
        browser.close()
    (args.output / 'rectangles.json').write_text(json.dumps({'results': results, 'errors': errors}, indent=2), encoding='utf-8')
    assert not errors, errors
    print(f'{len(results)} checks passed; no console errors. Evidence: {args.output}')


if __name__ == '__main__':
    main()
