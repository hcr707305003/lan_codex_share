const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function fixture(origin = 'https://codex.example.com') {
  const sent = [];
  const prefix = '/proxy/localhost:1122/';
  class Element {
    constructor(attrs) { this.attrs = attrs; }
    getAttribute(name) { return this.attrs[name] ?? null; }
    setAttribute(name, value) { this.attrs[name] = value; }
    querySelectorAll() { return []; }
  }
  class Socket { constructor(url) { this.url = url; } }
  class Image extends Element {
    constructor() { super({}); }
    get src() { return this.attrs.src; }
    set src(value) { this.attrs.src = value; }
  }
  Socket.OPEN = 1;
  class XHR { open(...args) { this.args = args; } }
  const events = {};
  const context = vm.createContext({
    URL, Request, Element, HTMLImageElement: Image, XMLHttpRequest: XHR, WebSocket: Socket, EventSource: Socket,
    location: new URL(origin + prefix + 'page'),
    document: {
      baseURI: origin + prefix + 'page',
      currentScript: {dataset: {prefix, upstream: 'http://localhost:1122'}},
      documentElement: {}, addEventListener: (name, handler) => {events[name] = handler;},
    },
    MutationObserver: class { constructor(callback) { events.mutations = callback; } observe() {} },
    history: {pushState: (...args) => sent.push(args), replaceState: (...args) => sent.push(args)},
    fetch: (...args) => {sent.push(args); return Promise.resolve();},
  });
  context.window = context;
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../lan_codex_share/web/proxy-client.js'), 'utf8'), context);
  return {context, sent, events, Element, base: 'https://codex.example.com' + prefix};
}

test('fetch and Request stay inside their target and keep external URLs unchanged', async () => {
  const {context: c, sent, base} = fixture();
  for (const [input, expected] of [
    ['/api?q=1', base + 'api?q=1'], ['relative', base + 'relative'],
    ['http://localhost:1122/data', base + 'data'],
    [base + 'already', base + 'already'], ['https://example.org/data', 'https://example.org/data'],
  ]) {
    c.fetch(input);
    assert.equal(sent.at(-1)[0], expected);
  }
  await c.fetch(new Request('https://codex.example.com/data', {method: 'POST', body: 'payload'}));
  assert.equal(sent.at(-1)[0].url, base + 'data');
  assert.equal(sent.at(-1)[0].method, 'POST');
});

test('local cross-port fetch URLs select their own prefix and preserve public ports', () => {
  for (const origin of ['https://codex.example.com', 'http://192.168.1.20:9000']) {
    const {context: c, sent} = fixture(origin);
    for (const [input, path] of [
      ['http://localhost:13333/api?q=a%2Fb#x', '/proxy/localhost:13333/api?q=a%2Fb#x'],
      ['http://127.0.0.1:13333/api', '/proxy/127.0.0.1:13333/api'],
      ['//192.168.1.20:8080/api', '/proxy/192.168.1.20:8080/api'],
      ['http://10.0.0.1/api', '/proxy/10.0.0.1:80/api'],
      ['http://[::1]:8080/api', '/proxy/[::1]:8080/api'],
      ['http://172.31.255.1:8080/api', '/proxy/172.31.255.1:8080/api'],
      ['/proxy/localhost:13333/api', '/proxy/localhost:13333/api'],
      [origin + '/proxy/localhost:13333/api', '/proxy/localhost:13333/api'],
    ]) {
      c.fetch(input);
      assert.equal(sent.at(-1)[0], origin + path);
    }
  }
});

test('cross-port requests preserve payload and wrappers map streams and DOM resources', async () => {
  const {context: c, sent, events, Element} = fixture();
  const mapped = 'https://codex.example.com/proxy/localhost:13333/';
  await c.fetch(new Request('http://localhost:13333/write', {method: 'POST', body: 'payload', headers: {'X-Service': 'value'}, credentials: 'omit'}));
  const forwarded = sent.at(-1)[0];
  assert.equal(forwarded.url, mapped + 'write');
  assert.equal(forwarded.method, 'POST');
  assert.equal(forwarded.credentials, 'omit');
  assert.equal(forwarded.headers.get('X-Service'), 'value');
  assert.equal(new TextDecoder().decode(sent.at(-1)[1].body), 'payload');
  const xhr = new c.XMLHttpRequest();
  xhr.open('POST', 'http://localhost:13333/upload', true);
  assert.equal(xhr.args[1], mapped + 'upload');
  assert.equal(new c.WebSocket('ws://localhost:13333/ws').url, mapped.replace('https:', 'wss:') + 'ws');
  assert.equal(new c.EventSource('http://localhost:13333/events').url, mapped + 'events');
  const image = new Element({src: 'http://localhost:13333/image.png'});
  events.mutations([{type: 'childList', addedNodes: [image]}]);
  assert.equal(image.attrs.src, mapped + 'image.png');
  events.mutations([{type: 'attributes', target: image, addedNodes: []}]);
  assert.equal(image.attrs.src, mapped + 'image.png');
  const detached = new c.HTMLImageElement();
  detached.src = 'http://localhost:13333/detached.png';
  assert.equal(detached.src, mapped + 'detached.png');
  detached.setAttribute('src', 'http://localhost:13333/attribute.png');
  assert.equal(detached.src, mapped + 'attribute.png');
});

test('cross-port mapping never rewrites public, metadata, credentialed or TLS upstream URLs', () => {
  const {context: c, sent} = fixture();
  for (const input of [
    'https://localhost:13333/api', 'https://localhost:1122/api',
    'http://example.com:13333/api', 'http://8.8.8.8/api', 'http://169.254.169.254/',
    'http://172.32.0.1/', 'http://user:pass@localhost:13333/', 'http://localhost:0/',
    'http://localhost:65536/', 'http://localhost.evil.example:80/',
  ]) {
    c.fetch(input);
    assert.equal(sent.at(-1)[0], input);
  }
  assert.equal(new c.WebSocket('wss://localhost:13333/ws').url, 'wss://localhost:13333/ws');
});

test('Request init overrides and FormData remain usable after cross-port mapping', async () => {
  const {context: c, sent} = fixture();
  const form = new FormData();
  form.set('name', 'cross-port');
  await c.fetch(new Request('http://localhost:13333/form', {method:'POST', body:form}));
  const [request, options] = sent.at(-1);
  const payload = new TextDecoder().decode(options.body);
  const boundary = request.headers.get('Content-Type').split('boundary=')[1];
  assert.ok(payload.includes('--' + boundary));
  assert.ok(payload.includes('cross-port'));
  await c.fetch(new Request('http://localhost:13333/form', {method:'POST', body:'old'}), {method:'PUT', body:'new', headers:{'X-Override':'yes'}});
  assert.equal(sent.at(-1)[0].method, 'PUT');
  assert.equal(sent.at(-1)[0].headers.get('X-Override'), 'yes');
  assert.equal(new TextDecoder().decode(sent.at(-1)[1].body), 'new');
});

test('XHR, WebSocket, EventSource and history map into the same prefix', () => {
  const {context: c, sent, base} = fixture();
  const xhr = new c.XMLHttpRequest();
  xhr.open('POST', '/upload', true);
  assert.equal(xhr.args[1], base + 'upload');
  assert.equal(new c.WebSocket('ws://localhost:1122/ws').url, base.replace('https:', 'wss:') + 'ws');
  assert.equal(c.WebSocket.OPEN, 1);
  assert.equal(new c.EventSource('/events').url, base + 'events');
  c.history.pushState({}, '', '/next');
  assert.equal(sent.at(-1)[2], base + 'next');
  c.history.replaceState({}, '', '#tab');
  assert.equal(sent.at(-1)[2], '#tab');
});

test('navigation adapts links and forms without changing non-HTTP schemes', () => {
  const {events, Element, base} = fixture();
  const form = new Element({action: '/login'});
  events.submit({target: form});
  assert.equal(form.attrs.action, base + 'login');
  const anchor = new Element({href: 'mailto:user@example.com'});
  events.click({target: {closest: () => anchor}});
  assert.equal(anchor.attrs.href, 'mailto:user@example.com');
});
