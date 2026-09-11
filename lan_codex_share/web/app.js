'use strict';

const csrf = document.querySelector('meta[name="csrf-token"]').content;
const authGate = document.getElementById('auth-gate');
const authForm = document.getElementById('auth-form');
const authPassword = document.getElementById('auth-password');
const authMessage = document.getElementById('auth-message');
const authSubmit = document.getElementById('auth-submit');
const timeline = document.getElementById('timeline');
const scrollToBottomButton = document.getElementById('scroll-to-bottom');
const input = document.getElementById('input');
const imageInput = document.getElementById('images');
const previews = document.getElementById('previews');
const composer = document.querySelector('.composer');
const composerRegion = document.querySelector('.composer-region');
const notice = document.getElementById('notice');
const queueNode = document.getElementById('queue');
const sendButton = document.getElementById('send');
const connectionPill = document.getElementById('connection-pill');
const connectionLabel = document.getElementById('connection-label');
const processingBanner = document.getElementById('processing-banner');
const queuePanel = document.getElementById('queue-panel');
const queueCount = document.getElementById('queue-count');
const queueList = document.getElementById('queue-list');
const sessionControl = document.getElementById('session-control');
const sessionSelect = document.getElementById('session-select');
const projectList = document.getElementById('project-list');
const modelControl = document.getElementById('model-control');
const modelToggle = document.getElementById('model-toggle');
const modelPanel = document.getElementById('model-panel');
const modelCurrent = document.getElementById('model-current');
const modelSelect = document.getElementById('model-select');
const effortSelect = document.getElementById('effort-select');
const speedSelect = document.getElementById('speed-select');
const modelHelp = document.getElementById('model-help');
const modelApply = document.getElementById('model-apply');
const sidebarThread = document.getElementById('sidebar-thread');
const sidebarTitle = document.getElementById('sidebar-title');
const threadTitle = document.getElementById('thread-title');
const workspacePath = document.getElementById('workspace-path');
const workspaceName = document.getElementById('workspace-name');
const menuToggle = document.getElementById('menu-toggle');
const taskMenu = document.getElementById('task-menu');
const clearQueueButton = document.getElementById('clear-queue');
const releaseSessionButton = document.getElementById('release-session');
const reconnectSessionButton = document.getElementById('reconnect-session');
const resyncButton = document.getElementById('resync');
const cancelButton = document.getElementById('cancel');
const sidebar = document.getElementById('sidebar');
const mobileScrim = document.getElementById('mobile-scrim');
const appShell = document.querySelector('.app-shell');
const mainPanel = document.querySelector('.main-panel');
const filePreview = document.getElementById('file-preview');
const filePreviewTitle = document.getElementById('file-preview-title');
const filePreviewPath = document.getElementById('file-preview-path');
const filePreviewBody = document.getElementById('file-preview-body');
const filePreviewDownload = document.getElementById('file-preview-download');
const imageLightbox = document.getElementById('image-lightbox');
const imageLightboxTitle = document.getElementById('image-lightbox-title');
const imageLightboxStage = document.getElementById('image-lightbox-stage');
const imageLightboxImage = document.getElementById('image-lightbox-image');
const imageLightboxError = document.getElementById('image-lightbox-error');
const imageLightboxClose = document.getElementById('image-lightbox-close');

let selectedFiles = [];
let lastVersion = -1;
let latestSnapshot = null;
let selectedSessionId = new URL(window.location.href).searchParams.get('session') || '';
let sessionOptionSignature = '';
let projectNavigationSignature = '';
let selectionGeneration = 0;
let composing = false;
let refreshing = false;
let refreshQueued = false;
let dragDepth = 0;
let currentFileReference = null;
let previewReturnFocus = null;
let previewRequestId = 0;
let lightboxReturnFocus = null;
let events = null;
let appAuthenticated = false;
const manuallyExpanded = new Set();
const manuallyCollapsed = new Set();
const collapsedProjects = new Set();
const allowedImageTypes = new Set(['image/png', 'image/jpeg', 'image/webp']);
const maxImageBytes = 10 * 1024 * 1024;
const maxImages = 4;
const maxRenderedJson = 100 * 1024;
const bottomRevealThreshold = 160;

function timelineBottomDistance() {
  return Math.max(0, timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight);
}

function syncScrollToBottomButton() {
  const scrollable = timeline.scrollHeight > timeline.clientHeight + 1;
  scrollToBottomButton.hidden = !scrollable || timelineBottomDistance() <= bottomRevealThreshold;
}

function scrollTimelineToBottom() {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  timeline.scrollTo({top: timeline.scrollHeight, behavior: reduceMotion ? 'auto' : 'smooth'});
}

function openImageLightbox(src, name, trigger) {
  lightboxReturnFocus = trigger;
  const label = name || '会话图片';
  imageLightboxTitle.textContent = label;
  imageLightboxImage.alt = label;
  imageLightboxImage.hidden = false;
  imageLightboxError.hidden = true;
  imageLightboxImage.src = src;
  if (!imageLightbox.open) imageLightbox.showModal();
  imageLightboxClose.focus({preventScroll: true});
}

function closeImageLightbox({restoreFocus = true} = {}) {
  if (!imageLightbox.open) return;
  const returnFocus = lightboxReturnFocus;
  lightboxReturnFocus = null;
  imageLightbox.close();
  imageLightboxImage.removeAttribute('src');
  imageLightboxError.hidden = true;
  if (!restoreFocus) return;
  const target = returnFocus?.isConnected ? returnFocus : timeline;
  if (target === timeline) timeline.tabIndex = -1;
  target.focus({preventScroll: true});
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function icon(name, className = '') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  if (className) svg.setAttribute('class', className);
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  svg.setAttribute('aria-hidden', 'true');
  return svg;
}

function statusValue(status) {
  if (status && typeof status === 'object') return String(status.type || status.status || '');
  return String(status || '');
}

function stateLabel(status) {
  const value = statusValue(status);
  return ({
    queued: '排队中', processing: '处理中', streaming: '生成中', inProgress: '处理中',
    completed: '已完成', failed: '失败', interrupted: '已中断', cancelled: '已取消', idle: '空闲',
    released: '已释放',
  })[value] || value || '等待中';
}

function setNotice(text, isError = false) {
  notice.textContent = text;
  notice.classList.toggle('error', isError);
}

function showAuthentication(message = '', isError = false) {
  appAuthenticated = false;
  refreshQueued = false;
  if (events) { events.close(); events = null; }
  appShell.inert = true;
  appShell.setAttribute('aria-hidden', 'true');
  authGate.hidden = false;
  authMessage.textContent = message;
  authMessage.classList.toggle('error', isError);
  requestAnimationFrame(() => authPassword.focus({preventScroll: true}));
}

function hideAuthentication() {
  authGate.hidden = true;
  appShell.inert = false;
  appShell.removeAttribute('aria-hidden');
  authMessage.textContent = '';
  authMessage.classList.remove('error');
  authPassword.value = '';
}

function handleUnauthorized(response) {
  if (response.status !== 401) return false;
  showAuthentication('登录状态已失效，请重新输入密码。', true);
  return true;
}

async function authenticationStatus() {
  const response = await fetch('/api/auth/status', {cache: 'no-store'});
  let result = {};
  try { result = await response.json(); } catch (_) { /* use generic error */ }
  if (!response.ok) throw new Error(result.error || '无法检查登录状态');
  return result;
}

function displayTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('zh-CN', {hour: '2-digit', minute: '2-digit'}).format(date);
}

function shortId(value) {
  const id = String(value || '');
  return id.length > 18 ? `${id.slice(0, 8)}…${id.slice(-6)}` : id;
}

function sessionStatusLabel(session) {
  if (session.connection === 'error') return '加载失败';
  if (session.connection === 'released') return '已释放';
  if (session.status === 'processing') return '处理中';
  const queued = Number(session.queue_size || 0);
  if (queued) return `排队 ${queued}`;
  if (session.connection === 'not_loaded') return '未连接';
  if (session.connection !== 'connected') return '连接中断';
  return '空闲';
}

function sessionNavigationState(session) {
  if (session.connection === 'error') return 'error';
  if (session.connection === 'released') return 'released';
  if (session.status === 'processing') return 'processing';
  if (session.connection === 'not_loaded') return 'not-loaded';
  if (session.connection !== 'connected') return 'disconnected';
  return 'idle';
}

function renderProjectNavigation(snapshot, selected) {
  const catalogMode = snapshot.catalog_mode === true;
  sessionControl.hidden = catalogMode;
  if (!catalogMode) return;
  const projects = Array.isArray(snapshot.projects) ? snapshot.projects : [];
  const signature = JSON.stringify([selected, projects.map(project => [
    project.id, project.name, project.cwd,
    (project.sessions || []).map(session => [
      session.thread_id, session.name, session.status, session.connection, session.queue_size, session.error,
    ]),
  ])]);
  if (signature === projectNavigationSignature) return;
  projectNavigationSignature = signature;
  const fragment = document.createDocumentFragment();
  for (const project of projects) {
    const projectId = String(project.id || project.cwd || project.name || 'project');
    const sessions = Array.isArray(project.sessions) ? project.sessions : [];
    const details = el('details', 'project-group');
    details.open = !collapsedProjects.has(projectId);
    const summary = document.createElement('summary');
    summary.title = String(project.cwd || project.name || 'Codex 项目');
    summary.append(icon('chevron'));
    summary.append(el('span', 'project-heading', project.name || '未分配项目'));
    summary.append(el('span', 'project-count', String(sessions.length)));
    details.append(summary);
    const sessionNodes = el('div', 'project-sessions');
    for (const session of sessions) {
      const id = String(session.thread_id || '');
      if (!id) continue;
      const row = el('div', 'task-entry-row');
      const button = el('button', `task-entry${id === selected ? ' active' : ''}`);
      button.type = 'button';
      button.dataset.sessionId = id;
      button.dataset.state = sessionNavigationState(session);
      if (id === selected) button.setAttribute('aria-current', 'page');
      const name = String(session.name || id);
      const status = sessionStatusLabel(session);
      button.title = `${name}\n${id}\n${status}`;
      button.append(el('span', 'task-name', name));
      button.append(el('span', 'task-id', `${shortId(id)} · ${status}`));
      button.addEventListener('click', () => {
        selectSession(id);
        closeSidebar();
      });
      row.append(button);
      const connection = String(session.connection || '');
      if (connection === 'connected' || connection === 'released') {
        const reconnect = connection === 'released';
        const action = el('button', 'session-connection-action');
        action.type = 'button';
        action.dataset.action = reconnect ? 'reconnect' : 'release';
        const blocked = !reconnect && (session.status === 'processing' || Number(session.queue_size || 0) > 0);
        action.disabled = blocked;
        action.title = blocked
          ? '任务与队列结束后才可释放 Session'
          : reconnect ? '重新连接 Session' : '释放 Session';
        action.setAttribute('aria-label', `${action.title}：${name}`);
        action.append(icon(reconnect ? 'link' : 'unlink'));
        action.addEventListener('click', event => {
          event.stopPropagation();
          changeSessionConnection(id, reconnect, action);
        });
        row.append(action);
      }
      sessionNodes.append(row);
    }
    details.append(sessionNodes);
    details.addEventListener('toggle', () => {
      if (details.open) collapsedProjects.delete(projectId);
      else collapsedProjects.add(projectId);
    });
    fragment.append(details);
  }
  if (!projects.length) fragment.append(el('div', 'empty-state sidebar-empty', '没有可共享的 Codex Session'));
  projectList.replaceChildren(fragment);
}

function renderSessionSelector(snapshot) {
  const sessions = Array.isArray(snapshot.sessions) ? snapshot.sessions : [];
  const selected = String(snapshot.selected_session_id || snapshot.thread_id || '');
  renderProjectNavigation(snapshot, selected);
  if (snapshot.catalog_mode === true) {
    if (selected) {
      selectedSessionId = selected;
      const url = new URL(window.location.href);
      url.searchParams.set('session', selected);
      window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    }
    return;
  }
  sessionControl.hidden = false;
  const signature = JSON.stringify(sessions.map(session => [
    session.thread_id, session.name, session.status, session.connection, session.queue_size,
  ]));
  if (signature !== sessionOptionSignature) {
    sessionOptionSignature = signature;
    sessionSelect.replaceChildren();
    for (const session of sessions) {
      const option = document.createElement('option');
      const id = String(session.thread_id || '');
      const name = String(session.name || '').trim();
      option.value = id;
      option.textContent = `${name && name !== id ? `${name} · ` : ''}${shortId(id)} · ${sessionStatusLabel(session)}`;
      option.title = `${name || 'Codex Session'}\n${id}\n${sessionStatusLabel(session)}`;
      sessionSelect.append(option);
    }
  }
  if (selected) {
    selectedSessionId = selected;
    sessionSelect.value = selected;
    const url = new URL(window.location.href);
    url.searchParams.set('session', selected);
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }
  sessionSelect.disabled = sessions.length <= 1;
  sessionSelect.setAttribute('aria-label', sessions.length > 1 ? `选择共享 Session，共 ${sessions.length} 个` : '当前共享 Session');
}

function clipText(value, limit = maxRenderedJson) {
  const text = String(value ?? '');
  return text.length > limit ? `${text.slice(0, limit)}\n…[浏览器显示已截断]` : text;
}

function safeJson(value) {
  try { return clipText(JSON.stringify(value, null, 2)); }
  catch (_) { return '[无法序列化内容]'; }
}

function parseLocalFileTarget(value) {
  let target = String(value || '').trim();
  if (target.startsWith('<') && target.endsWith('>')) target = target.slice(1, -1).trim();
  try { target = decodeURIComponent(target); } catch (_) { /* preserve malformed input */ }
  if (/^file:\/\/\/[a-z]:[\\/]/i.test(target)) target = target.slice(8);
  let path = target;
  let line = null;
  let column = null;
  const position = target.match(/^(.*?):(\d+)(?::(\d+))?$/);
  if (position) {
    path = position[1];
    line = Number(position[2]);
    column = position[3] ? Number(position[3]) : null;
  }
  if (!/^[a-z]:[\\/]/i.test(path)) return null;
  return {path, line, column};
}

function appendLink(parent, label, rawTarget, originalToken) {
  const target = String(rawTarget || '').replace(/^<|>$/g, '').trim();
  const local = parseLocalFileTarget(target);
  if (local) {
    const link = el('a', 'local-file-link', label);
    link.href = '#';
    link.title = `在右侧查看 ${local.path}`;
    link.addEventListener('click', event => {
      event.preventDefault();
      openFilePreview(local);
    });
    parent.append(link);
    return;
  }
  if (/^https?:\/\//i.test(target)) {
    const link = el('a', '', label);
    link.href = target;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    parent.append(link);
    return;
  }
  parent.append(document.createTextNode(originalToken));
}

function appendInline(parent, text, allowLineBreaks = false) {
  const source = String(text || '');
  const pattern = /(`[^`]+`|\[([^\]]+)\]\((<[^>\n]+>|[^)\n]+)\)|\*\*([^\n]+?)\*\*|<br\s*\/?>)/gi;
  let cursor = 0;
  for (const match of source.matchAll(pattern)) {
    if (match.index > cursor) parent.append(document.createTextNode(source.slice(cursor, match.index)));
    const token = match[0];
    if (token.startsWith('`')) {
      parent.append(el('code', '', token.slice(1, -1)));
    } else if (token.startsWith('**')) {
      const strong = el('strong');
      appendInline(strong, match[4], allowLineBreaks);
      parent.append(strong);
    } else if (/^<br\s*\/?>$/i.test(token)) {
      parent.append(allowLineBreaks ? el('br') : document.createTextNode(token));
    } else {
      appendLink(parent, match[2], match[3], token);
    }
    cursor = match.index + token.length;
  }
  if (cursor < source.length) parent.append(document.createTextNode(source.slice(cursor)));
}

function splitTableRow(line) {
  const cells = [''];
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '\\' && i + 1 < line.length) {
      const next = line[++i];
      cells[cells.length - 1] += next === '|' ? '|' : `\\${next}`;
    } else if (char === '|') {
      cells.push('');
    } else {
      cells[cells.length - 1] += char;
    }
  }
  if (cells.length === 1) return null;
  if (!cells[0].trim()) cells.shift();
  if (cells.length && !cells[cells.length - 1].trim()) cells.pop();
  return cells.length ? cells.map(cell => cell.trim()) : null;
}

function tableHeaderAt(lines, index) {
  const headers = splitTableRow(lines[index]);
  const delimiters = splitTableRow(lines[index + 1] || '');
  if (!headers || !delimiters || headers.length !== delimiters.length
      || !delimiters.every(cell => /^:?-{3,}:?$/.test(cell))) return null;
  return {
    headers,
    alignments: delimiters.map(cell => cell.endsWith(':') ? (cell.startsWith(':') ? 'center' : 'right') : 'left'),
  };
}

function appendTableRow(section, cells, alignments, isHeader = false) {
  const row = el('tr');
  alignments.forEach((alignment, index) => {
    const cell = el(isHeader ? 'th' : 'td');
    if (isHeader) cell.scope = 'col';
    cell.style.textAlign = alignment;
    // Only this explicit line-break token is supported; arbitrary HTML stays text.
    appendInline(cell, cells[index] || '', true);
    row.append(cell);
  });
  section.append(row);
}

function renderMarkdown(text) {
  const root = el('div', 'answer');
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
  let paragraph = [];
  let list = null;
  let inFence = false;
  let fenceLines = [];
  let fenceLanguage = '';

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const p = el('p');
    appendInline(p, paragraph.join('\n'));
    root.append(p);
    paragraph = [];
  };
  const flushList = () => { list = null; };
  const flushFence = () => {
    const pre = el('pre');
    pre.append(el('code', fenceLanguage ? `language-${fenceLanguage}` : '', fenceLines.join('\n')));
    root.append(pre);
    fenceLines = [];
    fenceLanguage = '';
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const fence = line.match(/^```\s*([^\s]*)/);
    if (fence) {
      flushParagraph(); flushList();
      if (inFence) flushFence();
      else fenceLanguage = fence[1] || '';
      inFence = !inFence;
      continue;
    }
    if (inFence) { fenceLines.push(line); continue; }
    const tableHeader = tableHeaderAt(lines, index);
    if (tableHeader) {
      flushParagraph(); flushList();
      const wrapper = el('div', 'markdown-table-scroll');
      wrapper.tabIndex = 0;
      wrapper.setAttribute('role', 'region');
      wrapper.setAttribute('aria-label', '表格，可横向滚动');
      const table = el('table');
      const head = el('thead');
      const body = el('tbody');
      appendTableRow(head, tableHeader.headers, tableHeader.alignments, true);
      index += 1; // Skip the Markdown delimiter row.
      while (index + 1 < lines.length) {
        const next = lines[index + 1];
        if (/^\s*(?:```|#{1,6}\s|>|[-*+]\s|\d+[.)]\s)/.test(next)) break;
        const cells = splitTableRow(next);
        if (!cells) break;
        appendTableRow(body, cells, tableHeader.alignments);
        index += 1;
      }
      table.append(head, body);
      wrapper.append(table);
      root.append(wrapper);
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    const quote = line.match(/^>\s?(.*)$/);
    if (heading) {
      flushParagraph(); flushList();
      const h = el(`h${heading[1].length}`); appendInline(h, heading[2]); root.append(h);
    } else if (bullet || numbered) {
      flushParagraph();
      const kind = bullet ? 'ul' : 'ol';
      if (!list || list.tagName.toLowerCase() !== kind) { list = el(kind); root.append(list); }
      const li = el('li'); appendInline(li, (bullet || numbered)[1]); list.append(li);
    } else if (quote) {
      flushParagraph(); flushList();
      const block = el('blockquote'); appendInline(block, quote[1]); root.append(block);
    } else if (!line.trim()) {
      flushParagraph(); flushList();
    } else {
      flushList(); paragraph.push(line);
    }
  }
  if (inFence) flushFence();
  flushParagraph();
  return root;
}

function fileEndpoint(path) {
  const params = new URLSearchParams({path});
  return `/api/files/view?${params}`;
}

function fileDownloadEndpoint(path) {
  const params = new URLSearchParams({path});
  return `/api/files/download?${params}`;
}

function setFileDownload(reference = null) {
  if (!reference?.path) {
    filePreviewDownload.removeAttribute('href');
    filePreviewDownload.setAttribute('aria-disabled', 'true');
    filePreviewDownload.tabIndex = -1;
    return;
  }
  filePreviewDownload.href = fileDownloadEndpoint(reference.path);
  filePreviewDownload.setAttribute('aria-disabled', 'false');
  filePreviewDownload.removeAttribute('tabindex');
}

function previewState(message, isError = false) {
  filePreviewBody.replaceChildren(el('div', `file-preview-state${isError ? ' error' : ''}`, message));
}

function previewWarning(message) {
  return el('div', 'file-preview-warning', message);
}

function formatBytes(size) {
  const value = Number(size || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function renderCodePreview(content, reference) {
  const scroll = el('div', 'code-view');
  const fragment = document.createDocumentFragment();
  const lines = String(content || '').replace(/\r\n?/g, '\n').split('\n');
  const targetLine = reference.line ? Math.min(Math.max(reference.line, 1), lines.length) : null;
  lines.forEach((text, index) => {
    const number = index + 1;
    const row = el('div', `code-line${number === targetLine ? ' target-line' : ''}`);
    row.dataset.line = String(number);
    row.append(el('span', 'line-number', number), el('span', 'line-content', text || ' '));
    fragment.append(row);
  });
  scroll.append(fragment);
  filePreviewBody.append(scroll);
  if (targetLine) {
    requestAnimationFrame(() => {
      const target = scroll.querySelector(`[data-line="${targetLine}"]`);
      if (target) {
        const previewRect = filePreviewBody.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const centeredTop = filePreviewBody.scrollTop
          + targetRect.top - previewRect.top
          - (filePreviewBody.clientHeight - targetRect.height) / 2;
        filePreviewBody.scrollTop = Math.max(0, centeredTop);
      }
      if (reference.column) filePreviewBody.scrollLeft = Math.max(0, (reference.column - 1) * 8 - 120);
    });
  }
}

function resetOuterLayoutScroll() {
  for (const element of [appShell, mainPanel, document.documentElement, document.body]) {
    if (!element) continue;
    element.scrollLeft = 0;
    element.scrollTop = 0;
  }
}

async function openFilePreview(reference) {
  if (!appShell.classList.contains('preview-open')) {
    const active = document.activeElement;
    previewReturnFocus = active instanceof HTMLElement && !filePreview.contains(active) ? active : null;
  }
  currentFileReference = reference;
  const requestId = ++previewRequestId;
  setFileDownload();
  appShell.classList.add('preview-open');
  resetOuterLayoutScroll();
  filePreview.setAttribute('aria-hidden', 'false');
  const filename = reference.path.split(/[\\/]/).pop() || '文件预览';
  filePreviewTitle.textContent = filename;
  filePreviewPath.textContent = reference.path;
  previewState('正在读取文件…');
  try {
    const endpoint = fileEndpoint(reference.path);
    const response = await fetch(endpoint, {cache: 'no-store'});
    if (handleUnauthorized(response)) throw new Error('需要密码登录');
    if (requestId !== previewRequestId) return;
    if (!response.ok) {
      let message = '无法读取文件';
      try { message = (await response.json()).error || message; } catch (_) { /* keep generic error */ }
      throw new Error(message);
    }
    const contentType = response.headers.get('Content-Type') || '';
    filePreviewBody.replaceChildren();
    if (contentType.includes('application/json')) {
      const data = await response.json();
      if (requestId !== previewRequestId) return;
      filePreviewTitle.textContent = data.name || filename;
      filePreviewPath.textContent = `${data.relativePath || reference.path} · ${formatBytes(data.size)}`;
      if (data.encodingWarning) filePreviewBody.append(previewWarning('文件不是有效 UTF-8，无法解码的字节已替换显示。'));
      if (data.kind === 'markdown') {
        const markdown = renderMarkdown(data.content || '');
        markdown.classList.add('file-markdown');
        filePreviewBody.append(markdown);
      } else {
        renderCodePreview(data.content || '', reference);
      }
    } else {
      if (contentType.startsWith('image/')) {
        const image = document.createElement('img');
        image.className = 'file-preview-image';
        image.src = endpoint;
        image.alt = filename;
        filePreviewBody.append(image);
      } else if (contentType.includes('application/pdf')) {
        const object = document.createElement('object');
        object.className = 'file-preview-pdf';
        object.data = endpoint;
        object.type = 'application/pdf';
        object.append(el('p', '', '当前浏览器无法内嵌显示 PDF。'));
        filePreviewBody.append(object);
      } else {
        throw new Error('此文件类型不支持浏览器预览');
      }
    }
    setFileDownload(reference);
    filePreviewBody.focus({preventScroll: true});
  } catch (error) {
    if (requestId === previewRequestId) previewState(error.message || '无法读取文件', true);
  }
}

function closeFilePreview() {
  if (!appShell.classList.contains('preview-open')) return;
  previewRequestId += 1;
  const returnFocus = previewReturnFocus;
  previewReturnFocus = null;
  setFileDownload();
  filePreviewBody.blur();
  appShell.classList.remove('preview-open');
  filePreview.setAttribute('aria-hidden', 'true');
  resetOuterLayoutScroll();
  requestAnimationFrame(() => {
    const target = returnFocus?.isConnected ? returnFocus : timeline;
    if (target === timeline) timeline.tabIndex = -1;
    target.focus({preventScroll: true});
    resetOuterLayoutScroll();
  });
}

function userText(item) {
  if (typeof item.text === 'string') return item.text;
  return (item.content || []).filter(part => part?.type === 'text').map(part => part.text || '').join('\n');
}

function imageRecords(item) {
  const result = [];
  const seen = new Set();
  for (const image of item.images || []) {
    if (!image?.id || seen.has(image.id)) continue;
    seen.add(image.id);
    result.push({id: image.id, name: image.name || '上传图片'});
  }
  for (const part of item.content || []) {
    if (part?.type !== 'localImage' || !part.imageId || seen.has(part.imageId)) continue;
    seen.add(part.imageId);
    result.push({id: part.imageId, name: part.name || '图片'});
  }
  return result;
}

function renderGallery(images) {
  const gallery = el('div', 'gallery');
  for (const image of images) {
    const src = `/api/images/${encodeURIComponent(image.id)}`;
    const label = image.name || '会话图片';
    const button = el('button', 'gallery-image');
    button.type = 'button';
    button.setAttribute('aria-label', `放大查看 ${label}`);
    const img = document.createElement('img');
    img.src = src;
    img.alt = label;
    img.loading = 'lazy';
    button.append(img);
    button.addEventListener('click', () => openImageLightbox(src, label, button));
    gallery.append(button);
  }
  return gallery;
}

function renderUserMessage(item) {
  const article = el('article', 'message user');
  const meta = el('div', 'message-meta');
  meta.append(el('span', '', item.sourceIp || '用户'));
  const time = el('time', '', displayTime(item.createdAt));
  if (item.createdAt) time.dateTime = item.createdAt;
  meta.append(time);
  article.append(meta);
  const text = userText(item);
  if (text) article.append(el('div', 'user-bubble', text));
  const images = imageRecords(item);
  if (images.length) article.append(renderGallery(images));
  if (item.status && statusValue(item.status) !== 'completed') {
    const footer = el('div', 'message-pending-footer');
    footer.append(el('span', `message-state ${statusValue(item.status)}`, stateLabel(item.status)));
    article.append(footer);
  }
  return article;
}

function renderQueue(pending) {
  const items = Array.isArray(pending) ? pending : [];
  queuePanel.hidden = items.length === 0;
  queueCount.textContent = `${items.length} 条消息`;
  if (!items.length) {
    queueList.replaceChildren();
    return;
  }

  const fragment = document.createDocumentFragment();
  items.forEach((item, index) => {
    const row = el('article', 'queue-item');
    row.setAttribute('role', 'listitem');
    row.append(el('span', 'queue-position', String(index + 1)));

    const content = el('div', 'queue-content');
    const text = userText(item).trim();
    const images = imageRecords(item);
    content.append(el('div', 'queue-text', text || (images.length ? `图片消息（${images.length} 张）` : '空消息')));
    const meta = el('div', 'queue-meta');
    meta.append(el('span', 'queue-source', item.sourceIp || '用户'));
    if (item.createdAt) meta.append(el('span', '', displayTime(item.createdAt)));
    if (images.length) meta.append(el('span', '', `${images.length} 张图片`));
    content.append(meta);
    row.append(content);

    const cancel = el('button', 'queue-cancel', '取消');
    cancel.type = 'button';
    cancel.setAttribute('aria-label', `取消第 ${index + 1} 条排队消息`);
    cancel.addEventListener('click', () => cancelQueuedMessage(String(item.id || ''), cancel));
    row.append(cancel);
    fragment.append(row);
  });
  queueList.replaceChildren(fragment);
}

async function cancelQueuedMessage(messageId, button) {
  if (!messageId) return setNotice('消息 ID 无效。', true);
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  try {
    const result = await mutate('/api/queue/cancel', {message_id: messageId});
    setNotice(result.cancelled ? '已取消排队消息。' : '消息已经开始处理或不在队列中。');
    await refresh();
  } catch (error) {
    setNotice(error.message, true);
  } finally {
    button.removeAttribute('aria-busy');
    if (button.isConnected) button.disabled = false;
  }
}

const activityInfo = {
  reasoning: ['brain', '思考摘要'], plan: ['file', '计划'], commandExecution: ['terminal', '命令'],
  fileChange: ['file', '文件修改'], mcpToolCall: ['tool', 'MCP 工具'], dynamicToolCall: ['tool', '工具调用'],
  collabAgentToolCall: ['tool', '协作 Agent'], subAgentActivity: ['tool', '子 Agent 活动'],
  webSearch: ['search', '网页搜索'], imageView: ['image', '查看图片'], imageGeneration: ['image', '生成图片'],
  sleep: ['tool', '等待'], planUpdate: ['file', '计划更新'], contextCompaction: ['tool', '上下文压缩'],
  enteredReviewMode: ['search', '进入审查'], exitedReviewMode: ['search', '结束审查'],
  agentMessage: ['brain', '过程说明'], turnDiff: ['file', '任务 Diff'],
};

function activityTitle(item) {
  const type = item.type || 'activity';
  if (type === 'commandExecution') return Array.isArray(item.command) ? item.command.join(' ') : item.command || '执行命令';
  if (type === 'mcpToolCall') return [item.server, item.tool].filter(Boolean).join(' · ') || 'MCP 工具调用';
  if (type === 'dynamicToolCall') return item.tool || item.name || '工具调用';
  if (type === 'webSearch') return item.query || item.action?.query || '网页搜索';
  if (type === 'fileChange') return `${(item.changes || []).length || ''} 个文件修改`.trim();
  if (type === 'reasoning') return '思考摘要';
  if (type === 'plan') return '执行计划';
  if (type === 'agentMessage') return '过程说明';
  if (type === 'turnDiff') return '任务产生的 Diff';
  return activityInfo[type]?.[1] || type;
}

function appendLabeledPre(body, label, value) {
  if (value === undefined || value === null || value === '') return;
  if (label) body.append(el('p', 'secondary', label));
  body.append(el('pre', '', typeof value === 'string' ? clipText(value) : safeJson(value)));
}

function renderActivityBody(item) {
  const body = el('div', 'activity-body');
  const type = item.type;
  if (type === 'reasoning') {
    for (const part of item.summary || []) if (part) body.append(renderMarkdown(part));
  } else if (type === 'plan' || type === 'agentMessage') {
    if (item.text) body.append(renderMarkdown(item.text));
    if (item.plan) appendLabeledPre(body, '计划数据', item.plan);
  } else if (type === 'commandExecution') {
    if (item.cwd) body.append(el('p', 'secondary', `目录：${item.cwd}`));
    appendLabeledPre(body, '', item.aggregatedOutput || item.output || '');
    const facts = [];
    if (item.exitCode !== undefined) facts.push(`退出码 ${item.exitCode}`);
    if (item.durationMs !== undefined) facts.push(`${item.durationMs} ms`);
    if (facts.length) body.append(el('p', 'secondary', facts.join(' · ')));
  } else if (type === 'fileChange') {
    const list = el('div', 'change-list');
    for (const change of item.changes || []) {
      const row = el('div', 'change-row');
      row.append(el('span', 'change-kind', change.kind || change.type || '修改'));
      row.append(el('span', '', change.path || change.file || safeJson(change)));
      list.append(row);
    }
    if (list.childElementCount) body.append(list);
    appendLabeledPre(body, '', item.diff || item.aggregatedOutput || '');
  } else if (type === 'mcpToolCall' || type === 'dynamicToolCall') {
    appendLabeledPre(body, '参数', item.arguments || item.input);
    if (item.progress?.length) appendLabeledPre(body, '进度', item.progress.join('\n'));
    appendLabeledPre(body, '结果', item.result || item.output);
    appendLabeledPre(body, '错误', item.error);
  } else if (type === 'webSearch') {
    if (item.query) body.append(el('p', '', item.query));
    appendLabeledPre(body, '', item.action || item.results || item.result);
  } else if (type === 'turnDiff') {
    appendLabeledPre(body, '', item.diff);
  } else {
    const omitted = new Set(['id', 'type', 'status']);
    const payload = Object.fromEntries(Object.entries(item).filter(([key]) => !omitted.has(key)));
    if (Object.keys(payload).length) appendLabeledPre(body, '', payload);
  }
  return body;
}

function renderActivity(item) {
  const info = activityInfo[item.type] || ['tool', item.type || '活动'];
  const card = el('article', 'activity-card');
  const heading = el('div', 'activity-heading');
  heading.append(icon(info[0]));
  heading.append(el('span', 'activity-title', activityTitle(item)));
  heading.append(el('span', 'activity-kind', info[1]));
  if (item.status) heading.append(el('span', `activity-status ${statusValue(item.status)}`, stateLabel(item.status)));
  card.append(heading, renderActivityBody(item));
  return card;
}

function isFinalAnswer(item) {
  if (item.type !== 'agentMessage') return false;
  return item.phase !== 'commentary';
}

function renderActivities(turn, items, active) {
  if (!items.length && !turn.diff) return null;
  const turnId = String(turn.id || 'unknown');
  const details = el('details', 'activity-group');
  details.open = manuallyExpanded.has(turnId) || (active && !manuallyCollapsed.has(turnId));
  const summary = el('summary');
  summary.append(icon('chevron', 'chevron'));
  summary.append(el('span', 'activity-summary-label', active ? '正在处理' : '查看过程'));
  const count = items.length + (turn.diff ? 1 : 0);
  summary.append(el('span', 'activity-count', `${count} 项`));
  const list = el('div', 'activity-list');
  for (const item of items) list.append(renderActivity(item));
  if (turn.diff) list.append(renderActivity({id: `${turnId}-diff`, type: 'turnDiff', diff: turn.diff}));
  details.append(summary, list);
  summary.addEventListener('click', () => {
    if (details.open) { manuallyCollapsed.add(turnId); manuallyExpanded.delete(turnId); }
    else { manuallyExpanded.add(turnId); manuallyCollapsed.delete(turnId); }
  });
  return details;
}

function renderTurn(turn) {
  const section = el('section', 'turn');
  section.dataset.turnId = turn.id || '';
  const status = statusValue(turn.status);
  const active = ['inProgress', 'processing', 'streaming'].includes(status);
  const activities = [];
  const answers = [];
  for (const item of turn.items || []) {
    if (item.type === 'userMessage') section.append(renderUserMessage(item));
    else if (isFinalAnswer(item)) answers.push(item);
    else activities.push(item);
  }
  const activityGroup = renderActivities(turn, activities, active);
  if (activityGroup) section.append(activityGroup);
  for (const answer of answers) {
    const article = el('article', 'message assistant');
    const meta = el('div', 'message-meta');
    meta.append(el('span', '', 'Codex'));
    if (answer.createdAt) meta.append(el('time', '', displayTime(answer.createdAt)));
    article.append(meta, renderMarkdown(answer.text || ''));
    section.append(article);
  }
  if (status && !['completed', 'inProgress', 'processing', 'streaming'].includes(status)) {
    section.append(el('div', `turn-status ${status}`, `任务${stateLabel(status)}`));
  }
  if (turn.error) section.append(el('div', 'turn-status failed', typeof turn.error === 'string' ? turn.error : safeJson(turn.error)));
  return section;
}

function render(snapshot) {
  latestSnapshot = snapshot;
  renderSessionSelector(snapshot);
  const thread = snapshot.thread || {};
  const connection = snapshot.connection || 'disconnected';
  const processing = snapshot.status === 'processing';
  const released = connection === 'released';
  const name = thread.name || thread.preview || '局域网共享 Codex 会话';
  const threadId = snapshot.thread_id || thread.id || '';
  threadTitle.textContent = name;
  sidebarTitle.textContent = name;
  sidebarThread.textContent = threadId ? shortId(threadId) : '尚未连接';
  workspacePath.textContent = thread.cwd || '真实 Codex Session';
  if (thread.cwd) workspaceName.textContent = String(thread.cwd).replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '工作区';
  connectionPill.className = `connection-pill ${processing ? 'processing' : connection}`;
  connectionLabel.textContent = released ? '已释放' : connection !== 'connected' ? '连接断开' : processing ? 'Codex 处理中' : '已连接';
  processingBanner.hidden = !processing;
  document.title = processing ? `处理中 · ${name}` : name;
  const queueSize = Number(snapshot.queue_size || 0);
  queueNode.textContent = `队列 ${queueSize}`;
  clearQueueButton.disabled = queueSize === 0;
  releaseSessionButton.hidden = released;
  releaseSessionButton.disabled = connection !== 'connected' || processing || queueSize > 0;
  reconnectSessionButton.hidden = !released;
  reconnectSessionButton.disabled = !released;
  resyncButton.disabled = released || processing;
  cancelButton.disabled = released;
  input.disabled = released;
  imageInput.disabled = released;
  input.placeholder = released ? 'Session 已释放，重新连接后可发送消息' : '给 Codex 发送消息';
  composer.classList.toggle('session-released', released);
  renderModelControls(snapshot, processing, queueSize);
  updateSendState();
  if (snapshot.last_error) setNotice(snapshot.last_error, true);
  else if (snapshot.catalog_error) setNotice(snapshot.catalog_error, true);
  else if (snapshot.last_notice) setNotice(snapshot.last_notice);

  if (snapshot.version === lastVersion) return;
  lastVersion = snapshot.version;
  const nearBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 120;
  const previousTop = timeline.scrollTop;
  const fragment = document.createDocumentFragment();
  const turns = thread.turns || [];
  const pending = snapshot.pending || [];
  renderQueue(pending);
  for (const turn of turns) fragment.append(renderTurn(turn));
  if (!turns.length) {
    const empty = el('div', 'empty-state');
    empty.append(el('p', '', pending.length ? '排队消息会在开始处理后出现在这里。' : '这个 Session 还没有消息。'));
    fragment.append(empty);
  }
  timeline.replaceChildren(fragment);
  if (nearBottom || previousTop === 0) timeline.scrollTop = timeline.scrollHeight;
  else timeline.scrollTop = previousTop;
  syncScrollToBottomButton();
}

const effortLabels = {
  minimal: '最少', low: '低', medium: '中', high: '高', xhigh: '极高', max: '最大', ultra: 'Ultra',
};

function selectedModelEntry() {
  return (latestSnapshot?.model_catalog || []).find(item => item.model === modelSelect.value);
}

function renderEffortOptions(entry, selected) {
  effortSelect.replaceChildren();
  for (const effort of entry?.supported_reasoning_efforts || []) {
    const option = document.createElement('option');
    option.value = effort.value;
    option.textContent = effortLabels[effort.value] || effort.value;
    if (effort.description) option.title = effort.description;
    effortSelect.append(option);
  }
  const fallback = entry?.default_reasoning_effort || '';
  effortSelect.value = Array.from(effortSelect.options).some(option => option.value === selected) ? selected : fallback;
}

function renderSpeedOptions(entry, selected) {
  speedSelect.replaceChildren();
  const defaultTier = (entry?.service_tiers || []).find(tier => tier.id === entry?.default_service_tier);
  const defaultOption = document.createElement('option');
  defaultOption.value = '';
  defaultOption.textContent = defaultTier ? `默认（${defaultTier.name}）` : '默认';
  speedSelect.append(defaultOption);
  for (const tier of entry?.service_tiers || []) {
    const option = document.createElement('option');
    option.value = tier.id;
    option.textContent = tier.name || tier.id;
    option.title = tier.description || '';
    speedSelect.append(option);
  }
  speedSelect.value = Array.from(speedSelect.options).some(option => option.value === selected) ? selected : '';
}

function populateModelPanel() {
  const catalog = latestSnapshot?.model_catalog || [];
  const settings = latestSnapshot?.model_settings || {};
  modelSelect.replaceChildren();
  for (const entry of catalog) {
    const option = document.createElement('option');
    option.value = entry.model;
    option.textContent = entry.display_name || entry.model;
    option.title = entry.description || '';
    modelSelect.append(option);
  }
  if (catalog.some(entry => entry.model === settings.model)) modelSelect.value = settings.model;
  renderEffortOptions(selectedModelEntry(), settings.reasoning_effort || '');
  renderSpeedOptions(selectedModelEntry(), settings.service_tier || '');
}

function renderModelControls(snapshot, processing, queueSize) {
  const catalog = snapshot.model_catalog || [];
  const settings = snapshot.model_settings || {};
  const current = catalog.find(item => item.model === settings.model);
  modelCurrent.textContent = current?.display_name || settings.model || '不可用';
  modelToggle.disabled = !catalog.length || snapshot.connection !== 'connected';
  const blocked = processing || queueSize > 0;
  modelSelect.disabled = blocked;
  effortSelect.disabled = blocked;
  speedSelect.disabled = blocked;
  modelApply.disabled = blocked || !catalog.length;
  modelHelp.textContent = blocked ? '任务与队列完成后可调整设置。' : '调整会同步到所有页面，并应用于后续任务。';
  modelPanel.classList.toggle('blocked', blocked);
  if (!modelPanel.hidden && !blocked) populateModelPanel();
}

async function refresh() {
  if (!appAuthenticated) return;
  if (refreshing) { refreshQueued = true; return; }
  refreshing = true;
  const generation = selectionGeneration;
  try {
    const query = selectedSessionId ? `?session_id=${encodeURIComponent(selectedSessionId)}` : '';
    const response = await fetch(`/api/snapshot${query}`, {cache: 'no-store'});
    let snapshot = {};
    try { snapshot = await response.json(); } catch (_) { /* use generic error */ }
    if (handleUnauthorized(response)) throw new Error(snapshot.error || '需要密码登录');
    if (!response.ok) throw new Error(snapshot.error || '无法读取共享会话');
    if (generation === selectionGeneration) render(snapshot);
  } finally {
    refreshing = false;
    if (refreshQueued) { refreshQueued = false; refresh().catch(error => setNotice(error.message, true)); }
  }
}

async function mutate(path, payload = {}) {
  return mutateForSession(path, selectedSessionId || null, payload);
}

async function mutateForSession(path, sessionId, payload = {}) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify({...payload, session_id: sessionId}),
  });
  let result = {};
  try { result = await response.json(); } catch (_) { /* use generic error */ }
  if (handleUnauthorized(response)) throw new Error(result.error || '需要密码登录');
  if (!response.ok) throw new Error(result.error || '请求失败');
  return result;
}

function startEvents() {
  if (events) return;
  events = new EventSource('/api/events');
  events.addEventListener('update', () => refresh().catch(error => setNotice(error.message, true)));
  events.onopen = () => { if (!latestSnapshot?.last_error) setNotice('已连接真实 Codex Session。'); };
  events.onerror = async () => {
    try {
      const status = await authenticationStatus();
      if (status.required && !status.authenticated) {
        showAuthentication('登录状态已失效，请重新输入密码。', true);
        return;
      }
    } catch (_) { /* keep EventSource retry behavior */ }
    setNotice('实时连接暂时断开，浏览器正在重连…', true);
  };
}

async function startAuthenticatedApp() {
  if (appAuthenticated) return;
  appAuthenticated = true;
  hideAuthentication();
  startEvents();
  await refresh();
}

async function bootstrapAuthentication() {
  try {
    const status = await authenticationStatus();
    if (status.required && !status.authenticated) {
      showAuthentication();
      return;
    }
    await startAuthenticatedApp();
  } catch (error) {
    showAuthentication(error.message || '无法连接共享服务，请稍后刷新。', true);
  }
}

async function changeSessionConnection(sessionId, reconnect, button) {
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  try {
    const path = reconnect ? '/api/session/reconnect' : '/api/session/release';
    const result = await mutateForSession(path, sessionId);
    const changed = reconnect ? result.reconnected : result.released;
    setNotice(changed
      ? reconnect ? 'Session 已重新连接。' : 'Session 已释放，可在本机 Codex 客户端中打开。'
      : reconnect ? 'Session 已经处于连接状态。' : 'Session 已经释放。');
    await refresh();
  } catch (error) {
    setNotice(error.message, true);
  } finally {
    button.removeAttribute('aria-busy');
    if (button.isConnected) button.disabled = false;
  }
}

function fileToPayload(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`无法读取 ${file.name}`));
    reader.onload = () => resolve({
      name: file.name || `clipboard-${Date.now()}.${file.type === 'image/jpeg' ? 'jpg' : file.type.split('/')[1]}`,
      mime: file.type,
      data: String(reader.result).split(',', 2)[1],
    });
    reader.readAsDataURL(file);
  });
}

function renderPreviews() {
  previews.replaceChildren();
  selectedFiles.forEach((file, index) => {
    const card = el('div', 'preview');
    const img = document.createElement('img');
    img.src = URL.createObjectURL(file);
    img.alt = file.name || `待发送图片 ${index + 1}`;
    img.onload = () => URL.revokeObjectURL(img.src);
    const remove = el('button');
    remove.type = 'button';
    remove.setAttribute('aria-label', `移除 ${file.name || '图片'}`);
    remove.append(icon('close'));
    remove.addEventListener('click', () => { selectedFiles.splice(index, 1); renderPreviews(); updateSendState(); });
    card.append(img, remove);
    previews.append(card);
  });
}

function updateSendState() {
  autoGrow();
  const connected = (latestSnapshot?.connection || 'connected') === 'connected';
  sendButton.disabled = !connected || (!input.value.trim() && !selectedFiles.length);
}

function addImageFiles(files) {
  const all = Array.from(files || []);
  const candidates = all.filter(file => allowedImageTypes.has(file.type));
  const accepted = candidates.filter(file => file.size <= maxImageBytes);
  const available = Math.max(0, maxImages - selectedFiles.length);
  selectedFiles.push(...accepted.slice(0, available));
  renderPreviews(); updateSendState();
  if (all.length !== candidates.length) setNotice('仅支持 PNG、JPEG 和 WebP 图片。', true);
  else if (candidates.length !== accepted.length) setNotice('单张图片不能超过 10 MB。', true);
  else if (accepted.length > available) setNotice('每条消息最多选择 4 张图片。', true);
  else if (accepted.length) setNotice(`已加入 ${Math.min(accepted.length, available)} 张图片。`);
}

function autoGrow() {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 210)}px`;
}

async function sendCurrentMessage() {
  const text = input.value.trim();
  if (!text && !selectedFiles.length) return setNotice('请输入文字或选择图片。', true);
  sendButton.disabled = true;
  setNotice('正在上传并加入队列…');
  try {
    const images = await Promise.all(selectedFiles.map(fileToPayload));
    await mutate('/api/messages', {text, images});
    input.value = '';
    imageInput.value = '';
    selectedFiles = [];
    renderPreviews(); autoGrow();
    setNotice('已发送，正在等待 Codex 处理。');
    await refresh();
  } catch (error) {
    setNotice(error.message, true);
  } finally {
    updateSendState();
  }
}

function closeMenu() { taskMenu.hidden = true; menuToggle.setAttribute('aria-expanded', 'false'); }
function closeModelPanel() { modelPanel.hidden = true; modelToggle.setAttribute('aria-expanded', 'false'); }
function closeSidebar() { sidebar.classList.remove('open'); mobileScrim.hidden = true; }

function selectSession(next) {
  if (!next || next === selectedSessionId) return;
  selectedSessionId = next;
  selectionGeneration += 1;
  lastVersion = -1;
  closeMenu(); closeModelPanel(); closeFilePreview(); closeImageLightbox({restoreFocus: false});
  const loading = el('div', 'initial-loading');
  const ring = el('span', 'loading-ring');
  ring.setAttribute('aria-hidden', 'true');
  loading.append(ring, el('p', '', '正在切换 Codex Session…'));
  timeline.replaceChildren(loading);
  const url = new URL(window.location.href);
  url.searchParams.set('session', next);
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  setNotice(`正在切换到 ${shortId(next)}…`);
  refresh().catch(error => setNotice(error.message, true));
}

sessionSelect.addEventListener('change', () => selectSession(sessionSelect.value));

imageInput.addEventListener('change', () => { addImageFiles(imageInput.files); imageInput.value = ''; });
sendButton.addEventListener('click', sendCurrentMessage);
input.addEventListener('input', updateSendState);
input.addEventListener('compositionstart', () => { composing = true; });
input.addEventListener('compositionend', () => { composing = false; updateSendState(); });
input.addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.shiftKey || composing || event.isComposing || event.keyCode === 229) return;
  event.preventDefault(); sendCurrentMessage();
});
input.addEventListener('paste', event => {
  const imageFiles = Array.from(event.clipboardData?.items || [])
    .filter(item => item.kind === 'file' && allowedImageTypes.has(item.type))
    .map(item => item.getAsFile()).filter(Boolean);
  if (!imageFiles.length) return;
  event.preventDefault(); addImageFiles(imageFiles);
});

for (const eventName of ['dragenter', 'dragover']) {
  composerRegion.addEventListener(eventName, event => {
    event.preventDefault();
    if (eventName === 'dragenter') dragDepth += 1;
    composerRegion.classList.add('dragging'); composer.classList.add('drag-over');
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
  });
}
composerRegion.addEventListener('dragleave', event => {
  event.preventDefault(); dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) { composerRegion.classList.remove('dragging'); composer.classList.remove('drag-over'); }
});
composerRegion.addEventListener('drop', event => {
  event.preventDefault(); dragDepth = 0;
  composerRegion.classList.remove('dragging'); composer.classList.remove('drag-over');
  addImageFiles(event.dataTransfer?.files);
});

menuToggle.addEventListener('click', event => {
  event.stopPropagation(); closeModelPanel(); taskMenu.hidden = !taskMenu.hidden;
  menuToggle.setAttribute('aria-expanded', String(!taskMenu.hidden));
});
modelToggle.addEventListener('click', event => {
  event.stopPropagation(); closeMenu(); modelPanel.hidden = !modelPanel.hidden;
  modelToggle.setAttribute('aria-expanded', String(!modelPanel.hidden));
  if (!modelPanel.hidden) populateModelPanel();
});
modelSelect.addEventListener('change', () => {
  const entry = selectedModelEntry();
  renderEffortOptions(entry, entry?.default_reasoning_effort || '');
  renderSpeedOptions(entry, '');
});
modelApply.addEventListener('click', async () => {
  modelApply.disabled = true;
  modelApply.setAttribute('aria-busy', 'true');
  try {
    await mutate('/api/settings/model', {
      model: modelSelect.value,
      reasoning_effort: effortSelect.value,
      service_tier: speedSelect.value || null,
    });
    closeModelPanel();
    setNotice('模型设置已更新，并同步到所有页面。');
    await refresh();
  } catch (error) {
    setNotice(error.message, true);
  } finally {
    modelApply.removeAttribute('aria-busy');
    if (!modelPanel.hidden) renderModelControls(latestSnapshot || {}, latestSnapshot?.status === 'processing', Number(latestSnapshot?.queue_size || 0));
  }
});
document.addEventListener('click', event => {
  if (!taskMenu.contains(event.target) && event.target !== menuToggle) closeMenu();
  if (!modelControl.contains(event.target)) closeModelPanel();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    if (imageLightbox.open) {
      event.preventDefault();
      closeImageLightbox();
      return;
    }
    closeMenu(); closeModelPanel(); closeSidebar(); closeFilePreview();
  }
});

imageLightboxClose.addEventListener('click', () => closeImageLightbox());
imageLightbox.addEventListener('cancel', event => {
  event.preventDefault();
  closeImageLightbox();
});
imageLightbox.addEventListener('click', event => {
  if (event.target === imageLightbox || event.target === imageLightboxStage) closeImageLightbox();
});
imageLightboxImage.addEventListener('load', () => {
  imageLightboxImage.hidden = false;
  imageLightboxError.hidden = true;
});
imageLightboxImage.addEventListener('error', () => {
  imageLightboxImage.hidden = true;
  imageLightboxError.hidden = false;
});

document.getElementById('file-preview-close').addEventListener('click', closeFilePreview);
document.getElementById('file-preview-refresh').addEventListener('click', () => {
  if (currentFileReference) openFilePreview(currentFileReference);
});

document.getElementById('copy-session').addEventListener('click', async () => {
  closeMenu();
  const id = latestSnapshot?.thread_id || latestSnapshot?.thread?.id;
  if (!id) return setNotice('Session ID 尚未就绪。', true);
  try { await navigator.clipboard.writeText(id); setNotice('Session ID 已复制。'); }
  catch (_) { setNotice(`Session ID：${id}`); }
});

resyncButton.addEventListener('click', async () => {
  closeMenu(); setNotice('正在从真实 Session 重新同步…');
  try {
    const result = await mutate('/api/resync');
    setNotice(result.resynced ? '已从真实 Session 重新同步。' : '任务执行中，稍后再同步。');
    await refresh();
  } catch (error) { setNotice(error.message, true); }
});

releaseSessionButton.addEventListener('click', () => {
  closeMenu();
  changeSessionConnection(selectedSessionId, false, releaseSessionButton);
});

reconnectSessionButton.addEventListener('click', () => {
  closeMenu();
  changeSessionConnection(selectedSessionId, true, reconnectSessionButton);
});

clearQueueButton.addEventListener('click', async () => {
  const count = Number(latestSnapshot?.queue_size || 0);
  if (!count) return setNotice('排队列表为空。');
  if (!window.confirm(`确定清空 ${count} 条尚未开始的排队消息吗？`)) return;
  clearQueueButton.disabled = true;
  clearQueueButton.setAttribute('aria-busy', 'true');
  try {
    const result = await mutate('/api/queue/clear');
    setNotice(result.cleared ? `已清空 ${result.cleared} 条排队消息。` : '排队列表已经为空。');
    await refresh();
  } catch (error) {
    setNotice(error.message, true);
  } finally {
    clearQueueButton.removeAttribute('aria-busy');
    clearQueueButton.disabled = Number(latestSnapshot?.queue_size || 0) === 0;
  }
});

cancelButton.addEventListener('click', async () => {
  closeMenu();
  try {
    const result = await mutate('/api/cancel');
    setNotice(result.cancelled ? '已请求取消当前任务。' : '当前没有活动任务。');
  } catch (error) { setNotice(error.message, true); }
});

document.getElementById('sidebar-toggle').addEventListener('click', () => { sidebar.classList.add('open'); mobileScrim.hidden = false; });
document.getElementById('sidebar-close').addEventListener('click', closeSidebar);
mobileScrim.addEventListener('click', closeSidebar);
timeline.addEventListener('scroll', syncScrollToBottomButton, {passive: true});
scrollToBottomButton.addEventListener('click', scrollTimelineToBottom);

authForm.addEventListener('submit', async event => {
  event.preventDefault();
  authSubmit.disabled = true;
  authSubmit.setAttribute('aria-busy', 'true');
  authMessage.textContent = '正在验证…';
  authMessage.classList.remove('error');
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify({password: authPassword.value}),
    });
    let result = {};
    try { result = await response.json(); } catch (_) { /* use generic error */ }
    if (!response.ok) throw new Error(result.error || (response.status === 429 ? '密码尝试过多，请稍后再试' : '密码错误'));
    await startAuthenticatedApp();
  } catch (error) {
    authMessage.textContent = error.message || '无法登录';
    authMessage.classList.add('error');
    authPassword.select();
  } finally {
    authSubmit.removeAttribute('aria-busy');
    authSubmit.disabled = false;
  }
});

updateSendState();
syncScrollToBottomButton();
bootstrapAuthentication();
