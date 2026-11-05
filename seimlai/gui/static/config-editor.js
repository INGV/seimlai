(() => {
    let panels;
    let frame = 0;
    let activeSection;

    function update() {
        frame = 0;
        const page = panels.querySelector('.seimlai-config');
        if (!page || !page.getClientRects().length) {
            activeSection = undefined;
            return;
        }
        const nav = page.querySelector('.seimlai-config-nav');
        const sections = [...page.querySelectorAll('.seimlai-config-section')];
        if (!nav || !sections.length) return;
        const links = [...nav.querySelectorAll('[data-section]')];
        const boundary = nav.getBoundingClientRect().bottom + 16;
        let active = sections[0];
        for (const section of sections) {
            if (section.getBoundingClientRect().top <= boundary) active = section;
        }
        if (Math.ceil(window.scrollY + window.innerHeight) >= document.documentElement.scrollHeight - 2) {
            active = sections[sections.length - 1];
        }
        for (const link of links) {
            if (link.dataset.section === active.id) {
                link.setAttribute('aria-current', 'location');
                if (activeSection !== active.id) {
                    const buttonRect = link.getBoundingClientRect();
                    const navRect = nav.getBoundingClientRect();
                    const delta = buttonRect.left < navRect.left ? buttonRect.left - navRect.left
                        : Math.max(0, buttonRect.right - navRect.right);
                    if (delta) nav.scrollBy({left: delta, behavior: 'smooth'});
                }
            } else {
                link.removeAttribute('aria-current');
            }
        }
        activeSection = active.id;
    }

    function schedule() {
        if (!frame) frame = requestAnimationFrame(update);
    }

    const panelObserver = new MutationObserver(records => {
        const selector = '.seimlai-config, .seimlai-config-nav, .seimlai-config-section';
        const changed = records.some(record => [...record.addedNodes, ...record.removedNodes].some(node =>
            node.nodeType === 1 && (node.matches(selector) || node.querySelector(selector))
        ));
        if (changed) schedule();
    });

    function mount() {
        panels = document.querySelector('.seimlai-panels');
        if (!panels) return;
        mountObserver.disconnect();
        panelObserver.observe(panels, {childList: true, subtree: true});
        window.addEventListener('scroll', schedule, {passive: true});
        window.addEventListener('resize', schedule);
        panels.addEventListener('animationend', schedule);
        panels.addEventListener('transitionend', schedule);
        schedule();
    }

    const mountObserver = new MutationObserver(mount);
    mountObserver.observe(document.body, {childList: true, subtree: true});
    mount();
})();
