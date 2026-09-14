'use strict';

// Best-effort adaptation for trusted apps. This is not a same-origin sandbox.
(() => {
  const script = document.currentScript;
  const prefix = script?.dataset.prefix;
  const upstream = script?.dataset.upstream;
  if (!prefix || !upstream || !prefix.startsWith('/proxy/')) return;
  function isLocalHost(host) {
    if (host === 'localhost' || host === '[::1]') return true;
    if (!/^\d+\.\d+\.\d+\.\d+$/.test(host)) return false;
    const parts = host.split('.').map(Number);
    if (parts.some(part => part > 255)) return false;
    return parts[0] === 127 || parts[0] === 10 ||
      (parts[0] === 192 && parts[1] === 168) ||
      (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31);
  }

  function proxyURL(value, websocket = false) {
    const raw = String(value);
    if (!raw || raw.startsWith('#')) return raw;
    let url;
    try { url = new URL(raw, document.baseURI); } catch (_) { return raw; }
    if (!['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol)) return raw;
    if (url.username || url.password) return raw;
    if (url.host === location.host) {
      // A link may already point at a different proxied service.
      if (!url.pathname.startsWith('/proxy/')) url.pathname = prefix.slice(0, -1) + url.pathname;
    } else {
      if (!isLocalHost(url.hostname)) return raw;
      // Protocol-relative resources belong to the HTTP upstream, not its HTTPS facade.
      if (raw.startsWith('//')) url = new URL('http:' + raw);
      if (!['http:', 'ws:'].includes(url.protocol) || url.port === '0') return raw;
      url.pathname = '/proxy/' + url.hostname + ':' + (url.port || '80') + url.pathname;
    }
    url.host = location.host;
    url.protocol = websocket ? (location.protocol === 'https:' ? 'wss:' : 'ws:') : location.protocol;
    // Assigning host without a port can retain the upstream port in URL.
    url.port = location.port;
    return url.href;
  }

  const nativeFetch = window.fetch;
  window.fetch = async function(input, init) {
    if (input instanceof Request) {
      const url = proxyURL(input.url);
      if (url === input.url) return nativeFetch.call(this, input, init);
      const request = new Request(new Request(url, input), init);
      // Copying Request.body creates a streaming upload. Chromium requires H2
      // for that even when the original POST used a plain string/FormData.
      if (request.body) {
        const body = await request.arrayBuffer();
        return nativeFetch.call(this, request, {body});
      }
      return nativeFetch.call(this, request);
    }
    return nativeFetch.call(this, proxyURL(input), init);
  };

  const nativeOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...args) {
    return nativeOpen.call(this, method, proxyURL(url), ...args);
  };
  const NativeWebSocket = window.WebSocket;
  window.WebSocket = class extends NativeWebSocket {
    constructor(url, ...args) { super(proxyURL(url, true), ...args); }
  };
  const NativeEventSource = window.EventSource;
  window.EventSource = class extends NativeEventSource {
    constructor(url, ...args) { super(proxyURL(url), ...args); }
  };
  for (const name of ['pushState', 'replaceState']) {
    const native = history[name];
    history[name] = function(state, unused, url) {
      return native.call(this, state, unused, url == null ? url : proxyURL(url));
    };
  }

  const urlAttributes = ['href', 'src', 'action', 'formaction', 'poster', 'data'];
  const nativeSetAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function(name, value) {
    return nativeSetAttribute.call(this, name,
      urlAttributes.includes(String(name).toLowerCase()) ? proxyURL(value) : value);
  };
  // Resource loads can start before a MutationObserver callback (or while the
  // element is detached). Rewrite URL properties before the native setter runs.
  for (const [type, names] of [
    ['HTMLImageElement', ['src']], ['HTMLScriptElement', ['src']],
    ['HTMLIFrameElement', ['src']], ['HTMLSourceElement', ['src']],
    ['HTMLMediaElement', ['src']], ['HTMLVideoElement', ['poster']],
    ['HTMLLinkElement', ['href']], ['HTMLAnchorElement', ['href']],
    ['HTMLFormElement', ['action']], ['HTMLInputElement', ['src', 'formAction']],
    ['HTMLButtonElement', ['formAction']], ['HTMLObjectElement', ['data']],
  ]) {
    const prototype = window[type]?.prototype;
    if (!prototype) continue;
    for (const name of names) {
      const descriptor = Object.getOwnPropertyDescriptor(prototype, name);
      if (!descriptor?.set || !descriptor.configurable) continue;
      Object.defineProperty(prototype, name, {
        ...descriptor, set(value) { descriptor.set.call(this, proxyURL(value)); },
      });
    }
  }

  function adapt(element) {
    if (!(element instanceof Element)) return;
    for (const name of urlAttributes) {
      const value = element.getAttribute(name);
      if (!value) continue;
      const mapped = proxyURL(value);
      if (mapped !== value) element.setAttribute(name, mapped);
    }
  }
  function adaptTree(root) {
    adapt(root);
    root.querySelectorAll?.('[href],[src],[action],[formaction],[poster],[data]').forEach(adapt);
  }
  // Exclude our own script: its unprefixed URL is intentionally served by Share.
  const observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'attributes' && record.target !== script) adapt(record.target);
      for (const node of record.addedNodes) if (node !== script) adaptTree(node);
    }
  });
  observer.observe(document.documentElement, {
    subtree: true, childList: true, attributes: true,
    attributeFilter: ['href', 'src', 'action', 'formaction', 'poster', 'data'],
  });
  document.addEventListener('click', event => {
    const anchor = event.target.closest?.('a[href]');
    if (anchor) adapt(anchor);
  }, true);
  document.addEventListener('submit', event => adapt(event.target), true);
})();
