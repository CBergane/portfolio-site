(function () {
    const home = document.querySelector('.home-page');
    if (!home || !('IntersectionObserver' in window)) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sections = Array.from(home.querySelectorAll('section[id]'));
    const railLinks = Array.from(home.querySelectorAll('.section-rail a'));
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
})();
