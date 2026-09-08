# Nordic Signal homepage hero

The approved `home-hero-master.png` is 1916 × 821 pixels (2,358,700 bytes).
Keep it as an authoring source; the homepage never requests the PNG.

## Production assets

`build_hero.py` resizes the entire image with Lanczos, without cropping or
upscaling. The nominal 2400-pixel variant is capped at the 1916-pixel master.
Outputs live in `app/static/images/nordic-signal/`.

| Dimensions | AVIF bytes | WebP bytes |
| --- | ---: | ---: |
| 960 × 411 | 45,370 | 59,150 |
| 1600 × 686 | 112,783 | 152,938 |
| 1916 × 821 | 149,970 | 206,686 |

Filenames are `home-hero-{width}.avif` and `home-hero-{width}.webp`.
Encoding uses AVIF quality 65, speed 6, 4:4:4 chroma and WebP quality 86,
method 6. To rebuild, use an isolated authoring environment with Pillow and
pillow-avif-plugin, then run `python design/source-assets/nordic-signal/build_hero.py`
from the repository root. These tools are not website runtime dependencies.

## Integration

- `home_page.html` includes `home/tags/hero_art.html` in the existing
  `.signal-hero`, replacing the old homepage-only system blueprint.
- The picture and inline SVG share a 1916 × 821 coordinate space. The raster is
  intact; only decorative vector geometry moves. The picture has AVIF and WebP
  source sets, matching `sizes`, eager/high-priority loading and explicit
  dimensions. Empty image alt text and `aria-hidden` keep it decorative.
- The hero heading, statement, metadata, actions, section anchors and navigation
  remain semantic HTML. The base template and project topology are unchanged.
- CSS base rules remain in section 09, responsive rules in section 17, and
  motion/input preferences in section 18. Desktop preserves left-side copy;
  tablet/mobile place the central structure in a separate softly faded band.
- `home.js` retains section-location tracking and rail behavior. It resolves the
  artwork over 1500 ms, introduces traces and a slight plane separation, then
  activates the core and runs one 1800 ms packet. Two nodes acknowledge it.
- Idle events start about 6.8, 9.1, 7.6 and 8.4 seconds apart. Pointer response
  uses a 2 px shared rear translation, with restrained additional vector depth
  for middle/foreground layers. A pointer visit permits one soft core pulse.
- Scroll exit is capped at 10 px upward and 18% luminance reduction via opacity.
  Signals stop after the first fifth of the visual scrolls out. An interrupted
  entrance settles; scrolling back never replays it.
- Reduced motion is completely static, including when enabled during an event.
  No-JavaScript uses the final static composition. Touch/coarse pointers do not
  receive depth motion.
- One timer schedules finite events; event-driven animation frames batch a
  layout read before writes. There is no permanent animation-frame loop, filter
  animation, observation sweep, framework, canvas or WebGL. Timers and queued
  frames are cancelled offscreen and on document visibility changes.

## Validation — 2026-09-08

- The focused responsive-asset/semantics/navigation test passes.
- All 64 Django tests pass, using the repository's `config.test_settings`
  (isolated in-memory database). `manage.py check`, `git diff --check` and
  JavaScript syntax validation pass.
- Chrome/Playwright checked Django-rendered local HTML and the real static
  assets at 320, 375, 768, 1024, 1440, 1920 and 2560 px, at viewport height
  1000 px and device scale 1. Screenshots were inspected. No horizontal overflow,
  missing images, console errors or uncaught JavaScript errors; measured CLS 0
  in these local runs. This is not a field-performance measurement.
- At device scale 1, the browser selected the 960 AVIF for 320/375, 1600 AVIF
  for 768/1024, and 1916 AVIF for 1440/1920/2560.
- No-JavaScript and reduced-motion compositions checked at 375 and 1440 px:
  loaded artwork, no overflow and no active hero animations. Existing mobile
  navigation remains expanded when JavaScript is disabled.
- Interaction assertions covered entrance, packet progression, return to idle,
  varied idle timing, pointer entry/leave, single core acknowledgement, touch,
  scroll exit, offscreen cancellation, and return without entrance replay.
- Keyboard checks covered the skip link, section rail and About highlighting.
- Live reduced-motion changes immediately removed motion. Visibility handling
  was tested by emulating document visibility properties and dispatching the
  standard event: no signal occurred during 9.5 seconds hidden; activity resumed
  without a second entrance. Native OS tab-background behavior was not measured.
- The sandbox initially blocked the existing HTMX CDN. The final browser pass
  allowed normal network access and reported no console/network errors.

No deployment, contact security, Django/Wagtail dependencies, commits or merges
are part of this change.
