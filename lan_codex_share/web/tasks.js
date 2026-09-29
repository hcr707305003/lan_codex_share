'use strict';
(function(root) {
  function candidateUrl(query, cursor) {
    const params = new URLSearchParams({q: query});
    if (cursor) params.set('cursor', cursor);
    return `/api/sessions/candidates?${params}`;
  }
  function newRequestId(crypto) {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  class LatestRequest {
    next() { this.cancel(); this.controller = new AbortController(); return this.controller; }
    isCurrent(controller) { return this.controller === controller && !controller.signal.aborted; }
    cancel() { this.controller?.abort(); this.controller = null; }
  }
  function mount(options) {
    const get = id => document.getElementById(id);
    const dialog = get('new-task-dialog');
    const opener = get('new-task');
    const search = get('task-search');
    const list = get('task-candidates');
    const idInput = get('task-session-id');
    const project = get('task-project');
    const submit = get('task-submit');
    const cancel = get('task-cancel');
    const message = get('task-message');
    const existing = get('task-existing-panel');
    const createPanel = get('task-create-panel');
    const modes = [...dialog.querySelectorAll('input[name="task-mode"]')];
    const candidatesGate = new LatestRequest();
    const projectsGate = new LatestRequest();
    const groups = new Map();
    let mode = 'existing', cursor = null, loading = false, busy = false, timer = null;
    let requestId = null, requestProject = null;
    const text = (tag, value, className = '') => {
      const node = document.createElement(tag); node.textContent = value; node.className = className; return node;
    };
    function say(value, error = false) {
      message.textContent = value;
      message.classList.toggle('task-error', error);
    }
    function update() {
      existing.hidden = mode !== 'existing'; createPanel.hidden = mode !== 'create';
      submit.textContent = busy ? (mode === 'create' ? '正在创建…' : '正在添加…') : mode === 'create' ? '创建并打开' : '添加到共享任务';
      submit.disabled = busy || (mode === 'existing' ? !idInput.value.trim() : !project.value);
      cancel.disabled = busy;
      for (const field of [...modes, search, idInput, project]) field.disabled = busy;
      list.setAttribute('aria-busy', String(loading));
    }
    function selectId(id) {
      if (busy) return;
      idInput.value = id;
      for (const row of list.querySelectorAll('[data-session-id]')) row.setAttribute('aria-pressed', String(row.dataset.sessionId === id));
      update();
    }
    async function loadCandidates(reset = false) {
      if (!dialog.open || mode !== 'existing' || (!reset && (loading || !cursor))) return;
      const request = candidatesGate.next();
      if (reset) cursor = null;
      loading = true; update(); say('正在读取已有会话…');
      try {
        const result = await options.request(candidateUrl(search.value.trim(), cursor), request.signal);
        if (!candidatesGate.isCurrent(request) || !dialog.open) return;
        if (reset) { list.replaceChildren(); groups.clear(); list.scrollTop = 0; }
        for (const item of result.items || []) {
          const cwd = item.cwd || '未分配项目';
          if (!groups.has(cwd)) {
            const name = cwd.split(/[\\/]/).filter(Boolean).pop() || cwd;
            const heading = text('h3', name, 'task-project-heading'); heading.title = cwd;
            const group = document.createElement('section'); group.append(heading);
            list.append(group); groups.set(cwd, group);
          }
          const row = text('button', '', 'task-candidate'); row.type = 'button';
          row.dataset.sessionId = item.id; row.setAttribute('aria-pressed', String(item.id === idInput.value.trim()));
          row.append(text('strong', item.name || '未命名会话'));
          const seconds = item.recencyAt || item.updatedAt || item.createdAt;
          const time = seconds ? new Date(seconds * 1000).toLocaleDateString() : '';
          row.append(text('span', `${item.id.slice(0, 8)}…${item.id.slice(-6)}${time ? ` · ${time}` : ''}${item.shared ? ' · 已共享' : ''}`));
          row.title = `${item.name || '未命名会话'}\n${item.id}\n${cwd}`;
          row.addEventListener('click', () => selectId(item.id));
          groups.get(cwd).append(row);
        }
        cursor = result.next_cursor;
        if (!list.children.length) list.append(text('p', '没有匹配的会话，也可以下方粘贴 Session ID。', 'task-empty'));
        if (reset) list.scrollTop = 0;
        say(cursor ? '向下滚动加载更多；选择后点击添加。' : '选择已有会话，或粘贴完整 Session ID。');
      } catch (error) {
        if (candidatesGate.isCurrent(request)) say(`${error.message}；可点击刷新重试。`, true);
      } finally {
        if (candidatesGate.isCurrent(request)) { loading = false; update(); }
      }
    }
    async function loadProjects() {
      const request = projectsGate.next();
      project.replaceChildren(); update(); say('正在读取项目…');
      try {
        const result = await options.request('/api/sessions/projects', request.signal);
        if (!projectsGate.isCurrent(request) || !dialog.open || mode !== 'create') return;
        for (const item of result.items || []) {
          const option = text('option', `${item.name} · ${item.cwd}`); option.value = item.cwd; project.append(option);
        }
        const cwd = options.current()?.cwd;
        const currentProject = (result.items || []).find(item => item.cwd === cwd || item.aliases?.includes(cwd));
        if (currentProject) project.value = currentProject.cwd;
        say(result.warning || (project.value ? '创建独立空会话，不会向当前任务发送消息。' : '没有可用的项目目录。'), !project.value);
      } catch (error) {
        if (projectsGate.isCurrent(request)) say(error.message, true);
      } finally { if (projectsGate.isCurrent(request)) update(); }
    }
    opener.addEventListener('click', () => {
      if (!options.canSubmit()) return;
      mode = 'existing'; modes[0].checked = true;
      search.value = ''; idInput.value = ''; list.replaceChildren();
      cursor = null; loading = false; dialog.showModal(); update(); search.focus(); loadCandidates(true);
    });
    for (const radio of modes) radio.addEventListener('change', () => {
      mode = radio.value; candidatesGate.cancel(); projectsGate.cancel(); loading = false;
      update(); mode === 'create' ? loadProjects() : loadCandidates(true);
    });
    search.addEventListener('input', () => {
      candidatesGate.cancel(); loading = false; cursor = null;
      clearTimeout(timer); timer = setTimeout(() => loadCandidates(true), 250);
    });
    idInput.addEventListener('input', () => selectId(idInput.value));
    project.addEventListener('change', update);
    get('task-refresh').addEventListener('click', () => { if (!busy) loadCandidates(true); });
    list.addEventListener('scroll', () => {
      if (list.scrollHeight - list.scrollTop - list.clientHeight < 90) loadCandidates();
    });
    cancel.addEventListener('click', () => dialog.close());
    dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
    dialog.addEventListener('close', () => {
      candidatesGate.cancel(); projectsGate.cancel(); clearTimeout(timer); opener.focus({preventScroll: true});
    });
    get('task-form').addEventListener('submit', async event => {
      event.preventDefault();
      if (busy || submit.disabled || !options.canSubmit()) return;
      busy = true; update(); say(mode === 'create' ? '正在创建独立会话，请稍候…' : '正在验证并保存…');
      try {
        if (mode === 'create') {
          if (!requestId || requestProject !== project.value) { requestId = newRequestId(root.crypto); requestProject = project.value; }
          const result = await options.mutate('/api/sessions/create', {project: requestProject, request_id: requestId});
          requestId = null; dialog.close(); options.onCreated(result);
        } else {
          const result = await options.mutate('/api/sessions/add', {session_id: idInput.value.trim()});
          dialog.close(); options.onAdded(result);
        }
      } catch (error) { say(error.message, true); }
      finally { busy = false; update(); }
    });
    return {isBusy: () => busy};
  }
  const api = {mount, candidateUrl, newRequestId, LatestRequest};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.LanTasks = api;
})(globalThis);
