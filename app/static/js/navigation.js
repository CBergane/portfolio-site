(function () {
    const button = document.getElementById('mobile-menu-btn');
    const menu = document.getElementById('mobile-menu');
    const header = document.querySelector('[data-site-header]');
    if (!button || !menu || !header) return;

    const desktop = window.matchMedia('(min-width: 768px)');
    const background = Array.from(document.querySelectorAll('.site-main, .site-footer, .skip-link'));
    let savedScroll = 0;
    let savedStyle = null;
    let savedInert = [];
    menu.hidden = true;
    button.hidden = false;
    document.documentElement.classList.add('navigation-ready');

    function closeMenu() {
        if (menu.hidden) return;
        menu.hidden = true;
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-label', 'Open menu');
        document.documentElement.classList.remove('menu-open');
        if (savedStyle === null) document.body.removeAttribute('style');
        else document.body.setAttribute('style', savedStyle);
        background.forEach(function (element, index) { element.inert = savedInert[index]; });
        window.scrollTo({ top: savedScroll, behavior: 'instant' });
    }

    button.addEventListener('click', function () {
        if (!menu.hidden) { closeMenu(); return; }
        if (desktop.matches) return;
        savedScroll = window.scrollY;
        savedStyle = document.body.getAttribute('style');
        savedInert = background.map(function (element) { return element.inert; });
        background.forEach(function (element) { element.inert = true; });
        document.body.style.position = 'fixed';
        document.body.style.top = '-' + savedScroll + 'px';
        document.body.style.width = '100%';
        document.documentElement.classList.add('menu-open');
        menu.hidden = false;
        button.setAttribute('aria-expanded', 'true');
        button.setAttribute('aria-label', 'Close menu');
    });

    document.addEventListener('keydown', function (event) {
        if (menu.hidden) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            closeMenu();
            button.focus({ preventScroll: true });
        } else if (event.key === 'Tab') {
            const controls = Array.from(header.querySelectorAll('a[href], button'))
                .filter(function (element) { return element.getClientRects().length; });
            const first = controls[0];
            const last = controls[controls.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault(); last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault(); first.focus();
            }
        }
    });
    menu.querySelectorAll('a').forEach(function (link) {
        link.addEventListener('click', closeMenu);
    });
    desktop.addEventListener('change', function () { if (desktop.matches) closeMenu(); });
    window.addEventListener('pagehide', closeMenu);
})();
