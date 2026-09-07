/* Progressive enhancement for the rendered document only; never stored content. */
(function () {
    const documentPage = document.querySelector('[data-reading-document]');
    if (!documentPage || documentPage.dataset.readingReady) return;
    documentPage.dataset.readingReady = 'true';
    const body = documentPage.querySelector('[data-reading-body]');
    const disclosure = documentPage.querySelector('[data-reading-nav]');
    const progress = documentPage.querySelector('[data-reading-progress]');
    const status = documentPage.querySelector('[data-reading-status]');
    const icon = documentPage.querySelector('[data-reading-link-icon]');
    const header = document.querySelector('[data-site-header]');
    if (!body || !disclosure) return;

    const headings = Array.from(body.querySelectorAll('h2, h3')).filter(heading =>
        heading.textContent.trim() && !heading.closest('pre, code, nav, aside, header, footer, [data-reading-exclude], [hidden]')
    );
    const counts = new Map();
    document.querySelectorAll('[id]').forEach(element => counts.set(element.id, (counts.get(element.id) || 0) + 1));
    const validID = id => id && !/[\t\n\f\r \u0000]/u.test(id);
    const preserved = new Set(headings.filter(h => validID(h.id) && counts.get(h.id) === 1));
    const used = new Set(Array.from(document.querySelectorAll('[id]'))
        .filter(element => !headings.includes(element) || preserved.has(element)).map(element => element.id));
    const labels = headings.map(heading => heading.textContent.trim().replace(/\s+/g, ' '));
    const links = [];
    let statusTimer;
    let feedbackControl;
    let copySequence = 0;
    let active = null;
    let allowHashUpdates = false;
    let offset = 108;
    let observer;
    let frame = 0;
    const desktop = window.matchMedia('(min-width: 1024px)');
    const list = disclosure.querySelector('[data-reading-links]');

    headings.forEach((heading, index) => {
        if (!preserved.has(heading)) {
            const slug = labels[index].normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase()
                .replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '') || 'section';
            let id = slug;
            let suffix = 2;
            while (used.has(id)) id = slug + '-' + suffix++;
            heading.id = id;
        }
        used.add(heading.id);
        const permalink = document.createElement('button');
        permalink.type = 'button';
        permalink.className = 'reading-permalink';
        permalink.setAttribute('aria-label', 'Copy link to ' + labels[index]);
        permalink.title = 'Copy section link';
        if (icon) permalink.appendChild(icon.content.cloneNode(true));
        else permalink.textContent = '#';
        permalink.addEventListener('click', async () => {
            const attempt = ++copySequence;
            const url = new URL(window.location.href);
            url.hash = heading.id;
            window.clearTimeout(statusTimer);
            if (feedbackControl) delete feedbackControl.dataset.copyState;
            feedbackControl = permalink;
            try {
                if (!navigator.clipboard) throw new Error('Clipboard unavailable');
                await navigator.clipboard.writeText(url.href);
                if (attempt !== copySequence) return;
                permalink.dataset.copyState = 'copied';
                status.textContent = 'Link copied to ' + labels[index] + '.';
            } catch (error) {
                if (attempt !== copySequence) return;
                permalink.dataset.copyState = 'failed';
                status.textContent = 'Could not copy the section link. Try again.';
            }
            statusTimer = window.setTimeout(() => {
                delete permalink.dataset.copyState;
                status.textContent = '';
            }, 2500);
        });
        heading.appendChild(permalink);
        if (headings.length < 2) return;
        const item = document.createElement('li');
        if (heading.tagName === 'H3') item.className = 'reading-nav__subsection';
        const link = document.createElement('a');
        link.href = '#' + encodeURIComponent(heading.id);
        link.textContent = labels[index];
        link.addEventListener('click', event => {
            if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            allowHashUpdates = false;
            if (window.location.hash !== link.hash) history.pushState(history.state, '', link.hash);
            visit(heading, true);
        });
        item.appendChild(link);
        list.appendChild(item);
        links.push(link);
    });

    function setActive(heading, updateHash = false) {
        if (active === heading) return;
        active = heading;
        links.forEach((link, index) => {
            if (headings[index] === heading) link.setAttribute('aria-current', 'location');
            else link.removeAttribute('aria-current');
        });
        // Scrolling replaces only the current entry. Explicit anchor visits push
        // an entry; initial hashes and history restoration are never rewritten.
        if (heading && updateHash && allowHashUpdates) {
            history.replaceState(history.state, '', '#' + encodeURIComponent(heading.id));
        }
    }

    function currentHeading() {
        let current = headings[0];
        for (const heading of headings) {
            if (heading.getBoundingClientRect().top > offset + 1) break;
            current = heading;
        }
        return current;
    }

    function visit(heading, focus) {
        if (!desktop.matches) disclosure.open = false;
        if (focus) {
            if (!heading.hasAttribute('tabindex')) heading.tabIndex = -1;
            heading.focus({ preventScroll: true });
        }
        heading.scrollIntoView({ block: 'start', behavior: 'instant' });
        setActive(heading);
        scheduleProgress();
    }

    function restoreHash() {
        allowHashUpdates = false;
        let id;
        try { id = decodeURIComponent(window.location.hash.slice(1)); } catch (error) { return; }
        const heading = headings.find(item => item.id === id);
        if (heading) visit(heading, true);
    }

    function observeHeadings() {
        if (observer) observer.disconnect();
        if (!headings.length || !('IntersectionObserver' in window)) return;
        observer = new IntersectionObserver(() => {
            setActive(currentHeading(), body.getBoundingClientRect().top <= offset);
        }, { rootMargin: '-' + offset + 'px 0px 0px 0px', threshold: [0, 1] });
        headings.forEach(heading => observer.observe(heading));
    }

    function updateProgress() {
        frame = 0;
        if (!progress) return;
        const region = body.getBoundingClientRect();
        const available = Math.max(1, window.innerHeight - offset);
        const distance = region.height - available;
        progress.hidden = distance < 160;
        const fraction = distance > 0 ? Math.max(0, Math.min(1, (offset - region.top) / distance)) : 0;
        progress.style.setProperty('--reading-progress', fraction);
    }

    function scheduleProgress() {
        if (!frame) frame = window.requestAnimationFrame(updateProgress);
    }

    function measureHeader() {
        const height = header ? header.getBoundingClientRect().height : 0;
        const nextOffset = Math.ceil(height + 24);
        documentPage.style.setProperty('--reading-header-height', height + 'px');
        documentPage.style.setProperty('--reading-offset', nextOffset + 'px');
        if (nextOffset !== offset || !observer) {
            offset = nextOffset;
            observeHeadings();
        }
        scheduleProgress();
    }

    function adaptDisclosure() {
        disclosure.open = desktop.matches;
        scheduleProgress();
    }
    if (headings.length >= 2) {
        disclosure.hidden = false;
        adaptDisclosure();
        // Native details/summary provides expanded state and keyboard behavior.
        desktop.addEventListener('change', adaptDisclosure);
    } else disclosure.remove();

    // Activation is observer-only. The single passive scroll listener updates
    // the transform-based progress line, never section selection or layout.
    window.addEventListener('scroll', scheduleProgress, { passive: true });
    window.addEventListener('resize', measureHeader);
    window.addEventListener('wheel', () => { allowHashUpdates = true; }, { passive: true });
    window.addEventListener('touchmove', () => { allowHashUpdates = true; }, { passive: true });
    document.addEventListener('keydown', event => {
        if (!event.target.closest('input, textarea, select, button, a, summary, [contenteditable]') &&
            ['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End', ' '].includes(event.key)) allowHashUpdates = true;
    });
    document.addEventListener('pointerdown', event => {
        if (event.clientX >= document.documentElement.clientWidth) allowHashUpdates = true;
    });
    window.addEventListener('hashchange', restoreHash);
    window.addEventListener('popstate', restoreHash);
    window.addEventListener('pageshow', () => { allowHashUpdates = false; measureHeader(); });
    if ('ResizeObserver' in window) {
        const resize = new ResizeObserver(measureHeader);
        resize.observe(body);
        if (header) resize.observe(header);
    }
    measureHeader();
    setActive(currentHeading());
    restoreHash();
    window.addEventListener('load', restoreHash, { once: true });
})();
