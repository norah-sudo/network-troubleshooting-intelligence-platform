(() => {
  'use strict';

  function init() {
    const choices = [...document.querySelectorAll('.choice[data-case]')];
    const originalArrows = new Map(choices.map((choice) => [
      choice,
      choice.querySelector('.choice-arrow')?.innerHTML || '',
    ]));
    const selectedIcon = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l5 5L20 5"/></svg>';
    const caseRegion = document.getElementById('case-region');
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let selectedCase = '';

    function selectCase(caseId, { focus = true, scroll = true, smooth = true } = {}) {
      const template = document.getElementById(`case-${caseId}`);
      if (!caseRegion || !(template instanceof HTMLTemplateElement)) return;

      if (selectedCase !== caseId) {
        caseRegion.replaceChildren(template.content.cloneNode(true));
        caseRegion.hidden = false;
        caseRegion.setAttribute('aria-labelledby', 'case-heading');
        selectedCase = caseId;
      }

      choices.forEach((choice) => {
        const active = choice.dataset.case === caseId;
        choice.classList.toggle('active', active);
        choice.setAttribute('aria-pressed', String(active));
        const label = choice.querySelector('.selection-label');
        if (label) label.textContent = active ? 'Selected case' : 'Open case';
        const arrow = choice.querySelector('.choice-arrow');
        if (arrow) arrow.innerHTML = active ? selectedIcon : originalArrows.get(choice);
      });

      const heading = caseRegion.querySelector('#case-heading');
      if (focus) heading?.focus({ preventScroll: true });
      if (scroll) {
        heading?.scrollIntoView({
          behavior: smooth && !reducedMotion.matches ? 'smooth' : 'auto',
          block: 'start',
        });
      }
    }

    choices.forEach((choice) => {
      choice.addEventListener('click', () => selectCase(choice.dataset.case));
    });

    function selectFromHash(initial = false) {
      const match = /^#case-(s0[1-4])$/.exec(window.location.hash);
      if (match) selectCase(match[1], { focus: false, smooth: !initial });
    }

    selectFromHash(true);
    window.addEventListener('popstate', () => selectFromHash());
    window.addEventListener('hashchange', () => selectFromHash());

    const viewer = document.getElementById('image-viewer');
    const viewerImage = document.getElementById('viewer-image');
    const viewerTitle = document.getElementById('viewer-title');
    const viewerCaption = document.getElementById('viewer-caption');
    const viewport = document.getElementById('viewer-scroll');
    const scale = document.getElementById('viewer-scale');
    const closeButton = document.getElementById('viewer-close');
    const fitButton = document.getElementById('viewer-fit');
    const originalButton = document.getElementById('viewer-original');

    // Keep ordinary image links usable in browsers without native modal dialogs.
    if (!viewer || typeof viewer.showModal !== 'function' || !viewerImage ||
        !viewerTitle || !viewerCaption || !viewport || !scale || !closeButton ||
        !fitButton || !originalButton) return;

    let opener = null;
    let previousOverflow = null;
    let drag = null;

    function setFit(fit) {
      viewport.classList.toggle('fit', fit);
      fitButton.setAttribute('aria-pressed', String(fit));
      originalButton.setAttribute('aria-pressed', String(!fit));
      scale.textContent = fit ? 'Fit' : '100%';
      viewport.scrollTo(0, 0);
    }

    function endDrag() {
      if (!drag) return;
      const pointerId = drag.pointerId;
      drag = null;
      viewport.classList.remove('dragging');
      if (viewport.hasPointerCapture(pointerId)) viewport.releasePointerCapture(pointerId);
    }

    document.addEventListener('click', (event) => {
      const link = event.target.closest?.('a.open-image');
      if (!link || event.defaultPrevented || event.button !== 0 ||
          event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

      const title = link.dataset.imageTitle || 'Evidence image';
      viewerTitle.textContent = title;
      viewerCaption.textContent = link.dataset.imageCaption || '';
      viewerImage.alt = link.querySelector('img')?.alt || title;
      viewerImage.src = link.href;
      setFit(false);

      try {
        viewer.showModal();
      } catch {
        return;
      }

      event.preventDefault();
      opener = link;
      previousOverflow = {
        body: document.body.style.overflow,
        root: document.documentElement.style.overflow,
      };
      document.body.style.overflow = 'hidden';
      document.documentElement.style.overflow = 'hidden';
      closeButton.focus({ preventScroll: true });
    });

    closeButton.addEventListener('click', () => viewer.close());
    fitButton.addEventListener('click', () => setFit(true));
    originalButton.addEventListener('click', () => setFit(false));
    viewerImage.addEventListener('load', () => viewport.scrollTo(0, 0));
    viewerImage.draggable = false;

    document.addEventListener('keydown', (event) => {
      if (!viewer.open || event.key !== 'Tab') return;
      const focusable = [...viewer.querySelectorAll(
        'a[href], button, input, select, textarea, [tabindex], [contenteditable="true"]',
      )].filter((element) => element.tabIndex >= 0 &&
        !element.matches(':disabled, [aria-disabled="true"]') &&
        !element.closest('[inert]') && element.getClientRects().length);
      event.preventDefault();
      if (!focusable.length) return;
      const current = focusable.indexOf(document.activeElement);
      const next = current < 0 ? (event.shiftKey ? focusable.length - 1 : 0) :
        (current + (event.shiftKey ? -1 : 1) + focusable.length) % focusable.length;
      focusable[next].focus({ preventScroll: true });
    }, true);

    viewer.addEventListener('click', (event) => {
      if (event.target !== viewer) return;
      const bounds = viewer.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right ||
          event.clientY < bounds.top || event.clientY > bounds.bottom) viewer.close();
    });

    viewer.addEventListener('close', () => {
      endDrag();
      if (previousOverflow) {
        document.body.style.overflow = previousOverflow.body;
        document.documentElement.style.overflow = previousOverflow.root;
        previousOverflow = null;
      }
      if (opener?.isConnected) opener.focus({ preventScroll: true });
      opener = null;
    });

    viewport.addEventListener('pointerdown', (event) => {
      if (event.pointerType !== 'mouse' || event.button !== 0 ||
          viewport.classList.contains('fit')) return;
      if (viewport.scrollWidth <= viewport.clientWidth &&
          viewport.scrollHeight <= viewport.clientHeight) return;
      drag = {
        pointerId: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        left: viewport.scrollLeft,
        top: viewport.scrollTop,
      };
      viewport.setPointerCapture(event.pointerId);
      viewport.classList.add('dragging');
      event.preventDefault();
    });

    viewport.addEventListener('pointermove', (event) => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      viewport.scrollLeft = drag.left - (event.clientX - drag.x);
      viewport.scrollTop = drag.top - (event.clientY - drag.y);
    });
    viewport.addEventListener('pointerup', endDrag);
    viewport.addEventListener('pointercancel', endDrag);
    viewport.addEventListener('lostpointercapture', endDrag);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
