(function (root) {
  'use strict';
  const KEY = 'lan-codex-preview-width';
  function bounds(viewport, sidebar) {
    const mobile = viewport <= 820;
    const max = Math.max(0, viewport - sidebar - (viewport >= 1200 ? 360 : 0));
    const min = Math.min(360, max);
    const initial = viewport >= 1200 ? Math.max(420, Math.min(viewport * .45, 760)) : 640;
    return {min, max, defaultWidth: Math.min(max, Math.max(min, initial)), mobile};
  }
  function createPreviewResize(host) {
    const {shell, panel, handle} = host;
    const win = host.window || window;
    let storage, preferred = null, drag = null, width = 0;
    const listeners = [];
    try {
      storage = host.storage || win.localStorage;
      const value = Number(storage.getItem(KEY));
      if (Number.isFinite(value) && value > 0) preferred = value;
    } catch (_) { /* Private browsing/storage policies must not disable resizing. */ }
    function limits() {
      return bounds(win.innerWidth, shell.querySelector('.sidebar')?.getBoundingClientRect().width || 0);
    }
    function apply(value) {
      const b = limits();
      handle.tabIndex = b.mobile ? -1 : 0;
      if (b.mobile) { shell.style.removeProperty('--preview-width'); return; }
      width = Math.round(Math.min(b.max, Math.max(b.min, value)));
      shell.style.setProperty('--preview-width', width + 'px');
      handle.setAttribute('aria-valuemin', b.min);
      handle.setAttribute('aria-valuemax', b.max);
      handle.setAttribute('aria-valuenow', width);
      handle.setAttribute('aria-valuetext', width + ' 像素');
    }
    function release() {
      const previous = drag; drag = null;
      shell.classList.remove('preview-resizing');
      if (previous && handle.hasPointerCapture(previous.id)) handle.releasePointerCapture(previous.id);
    }
    function cancel() { release(); apply(preferred ?? limits().defaultWidth); }
    function refresh() { cancel(); }
    function save() {
      preferred = width;
      try { storage?.setItem(KEY, String(preferred)); } catch (_) { /* Keep in-memory preference. */ }
    }
    function reset() {
      preferred = null;
      try { storage?.removeItem(KEY); } catch (_) { /* Reset still works for this page. */ }
      cancel();
    }
    function enabled() { return shell.classList.contains('preview-open') && !limits().mobile; }
    function on(target, name, listener) {
      target.addEventListener(name, listener); listeners.push(() => target.removeEventListener(name, listener));
    }
    on(handle, 'pointerdown', event => {
      if (event.button !== 0 || drag || !enabled()) return;
      event.preventDefault();
      handle.focus?.({preventScroll: true});
      drag = {id: event.pointerId, x: event.clientX, width};
      handle.setPointerCapture(event.pointerId);
      shell.classList.add('preview-resizing');
    });
    on(handle, 'pointermove', event => {
      if (!drag || drag.id !== event.pointerId) return;
      if (!enabled()) { cancel(); return; }
      apply(drag.width + drag.x - event.clientX);
    });
    on(handle, 'pointerup', event => {
      if (!drag || drag.id !== event.pointerId) return;
      if (enabled()) save();
      cancel();
    });
    for (const name of ['pointercancel', 'lostpointercapture']) on(handle, name, event => {
      if (drag?.id === event.pointerId) cancel();
    });
    on(handle, 'dblclick', () => { if (enabled()) reset(); });
    on(handle, 'keydown', event => {
      if (!enabled() || !['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return;
      event.preventDefault();
      if (event.key === 'Home') reset();
      else { release(); apply(width + (event.key === 'ArrowLeft' ? 20 : -20)); save(); }
    });
    on(win, 'resize', refresh);
    on(win, 'blur', cancel);
    // Observe only open/close transitions, not our dragging class mutations.
    let wasOpen = shell.classList.contains('preview-open');
    const observer = win.MutationObserver ? new win.MutationObserver(() => {
      const open = shell.classList.contains('preview-open');
      if (open !== wasOpen) { wasOpen = open; refresh(); }
    }) : null;
    observer?.observe(shell, {attributes: true, attributeFilter: ['class']});
    refresh();
    return {refresh, cancel, destroy() { cancel(); observer?.disconnect(); listeners.forEach(remove => remove()); }};
  }
  const api = {bounds, createPreviewResize};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else {
    root.PreviewResize = api;
    const shell = document.querySelector('.app-shell');
    const panel = document.getElementById('file-preview');
    const handle = document.getElementById('preview-resize');
    if (shell && panel && handle) createPreviewResize({shell, panel, handle});
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
