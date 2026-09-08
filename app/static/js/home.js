(function () {
    const home = document.querySelector('.home-page');
    if (!home || !('IntersectionObserver' in window)) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sections = Array.from(home.querySelectorAll('section[id]'));
    const railLinks = Array.from(home.querySelectorAll('.section-rail a'));
    const railStatus = home.querySelector('.section-rail__status');
    const navLinks = document.querySelectorAll('.site-nav__link[data-nav-label]');
    const visible = new Map();

    // Assembly affects decorative routes and nodes only. Text is always visible.
    const assembly = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            entry.target.classList.add('is-assembled');
            assembly.unobserve(entry.target);
        });
    }, { threshold: 0, rootMargin: '0px 0px -8% 0px' });
    if (!reduced.matches) {
        sections.forEach(function (section) { assembly.observe(section); });
    }

    const location = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) visible.set(entry.target, entry.boundingClientRect.top);
            else visible.delete(entry.target);
        });
        const active = sections.filter(function (section) { return visible.has(section); })
            .sort(function (a, b) { return visible.get(a) - visible.get(b); })[0];
        railLinks.forEach(function (link) {
            if (active && link.hash === '#' + active.id) link.setAttribute('aria-current', 'location');
            else link.removeAttribute('aria-current');
        });
        if (railStatus) {
            const current = active && railLinks.find(function (link) { return link.hash === '#' + active.id; });
            railStatus.hidden = !current;
            if (current) railStatus.textContent = current.querySelector('b').textContent;
        }
        // Section highlighting never changes server-authored aria-current in primary navigation.
        navLinks.forEach(function (link) {
            link.classList.toggle('site-nav__link--section-active',
                Boolean(active && active.id === 'operating-principle' && link.dataset.navLabel === 'ABOUT'));
        });
    }, { rootMargin: '-15% 0px -65% 0px', threshold: 0 });
    sections.forEach(function (section) { location.observe(section); });
    reduced.addEventListener('change', function () {
        if (reduced.matches) {
            assembly.disconnect();
            sections.forEach(function (section) { section.classList.add('is-assembled'); });
        }
    });

    const hero = home.querySelector('.signal-hero');
    const art = home.querySelector('.hero-art');
    if (!hero || !art) return;
    const picture = art.querySelector('img');
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
    // Rest periods plus the two-second event give 6.8–9.1s between signals.
    const cadence = [4800, 7100, 5600, 6400];
    let cadenceIndex = 0;
    let inView = false;
    let ready = false;
    let entered = false;
    let quiet = false;
    let timer = 0;
    let frame = 0;
    let pointer = null;
    let bounds = null;

    function active() {
        return inView && !document.hidden && !reduced.matches;
    }

    function clearSignal() {
        window.clearTimeout(timer);
        timer = 0;
        art.classList.remove('is-signalling', 'is-acknowledging');
    }

    function scheduleSignal() {
        if (!active() || quiet || !ready || !entered || timer) return;
        timer = window.setTimeout(signal, cadence[cadenceIndex++ % cadence.length]);
    }

    function signal() {
        timer = 0;
        if (!active() || quiet) return;
        art.classList.add('is-signalling');
        timer = window.setTimeout(function () {
            timer = 0;
            art.classList.remove('is-signalling');
            scheduleSignal();
        }, 2000);
    }

    function resetDepth() {
        pointer = null;
        art.classList.remove('is-hovered', 'is-acknowledging');
        art.style.removeProperty('--depth-x');
        art.style.removeProperty('--depth-y');
    }

    function suspend() {
        clearSignal();
        window.cancelAnimationFrame(frame);
        frame = 0;
        // An interrupted entrance settles immediately; returning never replays it.
        art.classList.remove('is-loading', 'is-booting');
        resetDepth();
    }

    function resume() {
        if (!active() || !ready) return;
        if (!entered) {
            entered = true;
            art.classList.remove('is-loading');
            art.classList.add('is-booting');
            timer = window.setTimeout(function () {
                timer = 0;
                art.classList.remove('is-booting');
                signal();
            }, 1500);
        } else {
            scheduleSignal();
        }
        requestFrame();
    }

    // Event-driven frames only: one layout read, then custom-property writes.
    // CSS interpolates tiny depth changes, so there is no permanent rAF loop.
    function updateFrame() {
        frame = 0;
        if (!active()) return;
        const artBounds = art.getBoundingClientRect();
        const progress = Math.min(1, Math.max(0, -artBounds.top / artBounds.height));
        const wasQuiet = quiet;
        quiet = progress > 0.2;
        art.style.setProperty('--exit-y', (-10 * progress).toFixed(2) + 'px');
        art.style.setProperty('--exit-opacity', (1 - 0.18 * progress).toFixed(3));
        if (quiet && !wasQuiet) {
            clearSignal();
            art.classList.remove('is-booting');
        } else if (!quiet && wasQuiet) {
            scheduleSignal();
        }
        if (pointer && bounds && finePointer.matches) {
            const x = Math.max(-1, Math.min(1, (pointer.x - bounds.left) / bounds.width * 2 - 1));
            const y = Math.max(-1, Math.min(1, (pointer.y - bounds.top) / bounds.height * 2 - 1));
            art.style.setProperty('--depth-x', x.toFixed(3));
            art.style.setProperty('--depth-y', y.toFixed(3));
        }
    }

    function requestFrame() {
        if (active() && !frame) frame = window.requestAnimationFrame(updateFrame);
    }

    const artVisibility = new IntersectionObserver(function (entries) {
        inView = entries[0].isIntersecting;
        if (active()) resume();
        else suspend();
    }, { threshold: 0 });
    artVisibility.observe(art);

    if (!reduced.matches && !document.hidden) art.classList.add('is-loading');
    // A failed image still leaves all semantic content and navigation usable.
    function imageReady() {
        ready = true;
        if (reduced.matches) entered = true;
        if (active()) resume();
        else if (reduced.matches || document.hidden) art.classList.remove('is-loading');
    }
    if (picture.complete) imageReady();
    else {
        picture.addEventListener('load', imageReady, { once: true });
        picture.addEventListener('error', function () {
            entered = true;
            imageReady();
        }, { once: true });
    }

    art.addEventListener('pointerenter', function (event) {
        if (!active() || !finePointer.matches || quiet) return;
        bounds = art.getBoundingClientRect();
        pointer = { x: event.clientX, y: event.clientY };
        art.classList.add('is-hovered');
        // One acknowledgement per visit; never compete with the entrance/packet.
        if (entered && !art.classList.contains('is-booting') && !art.classList.contains('is-signalling')) {
            art.classList.add('is-acknowledging');
        }
        requestFrame();
    });
    art.addEventListener('pointermove', function (event) {
        if (!pointer || !active() || !finePointer.matches) return;
        pointer = { x: event.clientX, y: event.clientY };
        requestFrame();
    }, { passive: true });
    art.addEventListener('pointerleave', resetDepth);
    window.addEventListener('scroll', function () {
        if (!active()) return;
        resetDepth();
        requestFrame();
    }, { passive: true });
    window.addEventListener('resize', function () {
        bounds = null;
        resetDepth();
        requestFrame();
    }, { passive: true });
    document.addEventListener('visibilitychange', function () {
        if (document.hidden) suspend();
        else resume();
    });
    window.addEventListener('pagehide', suspend);
    window.addEventListener('pageshow', resume);
    finePointer.addEventListener('change', resetDepth);
    reduced.addEventListener('change', function () {
        if (reduced.matches) {
            entered = true;
            suspend();
            art.style.removeProperty('--exit-y');
            art.style.removeProperty('--exit-opacity');
        } else {
            resume();
        }
    });
})();
