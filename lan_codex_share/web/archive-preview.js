(function (root) {
  'use strict';
  function createArchivePreview(host) {
    const doc = host.document || document;
    const request = host.fetch || fetch;
    const urls = host.url || URL;
    const container = host.container;
    let state = null, controller = null, sequence = 0, objectUrls = [];
    const node = (tag, text = '', className = '') => {
      const item = doc.createElement(tag); item.textContent = text; item.className = className; return item;
    };
    function cleanup() {
      controller?.abort(); controller = null;
      objectUrls.forEach(value => urls.revokeObjectURL(value)); objectUrls = [];
    }
    function close() {
      sequence += 1; cleanup(); state = null; container.replaceChildren();
    }
    function endpoint(action, extras = {}) {
      return '/api/archives/' + action + '?' + new URLSearchParams({path: state.path, version: state.version, ...extras});
    }
    function button(text, action) {
      const item = node('button', text); item.type = 'button'; item.addEventListener('click', action); return item;
    }
    function link(text, href, name) {
      const item = node('a', text, 'archive-download'); item.href = href; item.download = name || ''; return item;
    }
    function shell(member = null) {
      const panel = node('section', '', 'archive-panel');
      const toolbar = node('div', '', 'archive-toolbar');
      toolbar.append(link('下载整个 ZIP', '/api/files/download?' + new URLSearchParams({path: state.path})));
      if (member) toolbar.append(link('下载此文件', endpoint('download', {member: member.id}), member.name));
      const crumbs = node('nav', '', 'archive-breadcrumbs'); crumbs.setAttribute('aria-label', '压缩包目录');
      crumbs.append(button('ZIP 根目录', () => list('', 0)));
      let prefix = '';
      for (const part of state.directory.split('/').filter(Boolean)) {
        prefix += part + '/'; const target = prefix;
        crumbs.append(node('span', '/'), button(part, () => list(target, 0)));
      }
      if (member) crumbs.append(node('span', '/'), node('strong', member.name));
      const body = node('div', '', 'archive-content'); body.setAttribute('aria-live', 'polite');
      panel.append(toolbar, crumbs, body); container.replaceChildren(panel);
      return body;
    }
    async function load(url, body, render) {
      cleanup(); const id = ++sequence;
      controller = new AbortController();
      body.replaceChildren(node('p', '正在读取压缩包…', 'archive-message'));
      body.setAttribute('aria-busy', 'true');
      try {
        const response = await request(url, {cache: 'no-store', signal: controller.signal});
        if (id !== sequence) return;
        if (host.onUnauthorized?.(response)) throw new Error('需要密码登录');
        if (!response.ok) {
          let error = '无法读取压缩包';
          try { error = (await response.json()).error || error; } catch (_) { /* generic error */ }
          throw new Error(error);
        }
        const type = response.headers.get('Content-Type') || '';
        const data = type.includes('application/json') ? await response.json() : await response.blob();
        if (id !== sequence) return;
        body.replaceChildren(); render(data, type, body);
      } catch (error) {
        if (id === sequence && error.name !== 'AbortError') {
          const message = node('p', error.message || '读取失败', 'archive-message archive-error');
          body.replaceChildren(message, button('重新读取 ZIP', () => open({path: state.path})));
        }
      } finally {
        if (id === sequence) body.setAttribute('aria-busy', 'false');
      }
    }
    async function list(directory, page) {
      if (!state) return;
      state.directory = directory; state.page = page;
      const body = shell();
      await load(endpoint('list', {directory, page}), body, data => {
        state.version = data.version;
        if (!data.entries.length) body.append(node('p', '此目录为空', 'archive-message'));
        const rows = node('ul', '', 'archive-entries');
        for (const entry of data.entries) {
          const row = node('li', '', 'archive-entry');
          const label = button(entry.name, () => entry.directory ? list(entry.path, 0) : member(entry));
          label.className = 'archive-entry-name';
          label.setAttribute('aria-label', (entry.directory ? '打开文件夹 ' : '预览文件 ') + entry.name);
          row.append(node('span', entry.directory ? '目录' : '文件', 'archive-entry-type'), label);
          if (!entry.directory) row.append(node('span', size(entry.size), 'archive-entry-size'),
            link('下载', endpoint('download', {member: entry.id}), entry.name));
          rows.append(row);
        }
        body.append(rows);
        const pager = node('div', '', 'archive-pager');
        const prev = button('上一页', () => list(directory, page - 1)); prev.disabled = page === 0;
        const next = button('下一页', () => list(directory, page + 1)); next.disabled = (page + 1) * 100 >= data.total;
        pager.append(prev, node('span', `第 ${page + 1} / ${Math.max(1, Math.ceil(data.total / 100))} 页 · ${data.total} 项`), next);
        body.append(pager);
      });
    }
    async function member(entry, sheet = 0) {
      if (!state) return;
      const body = shell(entry);
      await load(endpoint('preview', {member: entry.id, sheet}), body, (data, type) => {
        body.append(button('返回文件列表', () => list(state.directory, state.page)));
        if (!type.includes('application/json')) {
          if (!type.startsWith('image/') && !type.includes('application/pdf')) throw new Error('不支持的预览类型，请下载文件');
          const url = urls.createObjectURL(data); objectUrls.push(url);
          if (type.startsWith('image/')) {
            const image = node('img', '', 'file-preview-image'); image.src = url; image.alt = entry.name; body.append(image);
          } else {
            body.append(node('p', '若浏览器无法显示 PDF，请下载此文件查看。', 'archive-message'));
            const object = node('object', '', 'file-preview-pdf'); object.data = url; object.type = 'application/pdf';
            object.append(node('p', '当前浏览器无法内嵌显示 PDF。')); body.append(object);
          }
        } else {
          if (data.warning) body.append(node('p', data.warning, 'archive-message'));
          if (data.kind === 'markdown') {
            const markdown = host.renderMarkdown(data.content || ''); markdown.className = 'file-markdown'; body.append(markdown);
          } else if (data.kind === 'code') {
            body.append(node('pre', data.content || '', 'archive-text'));
          } else if (data.kind === 'spreadsheet') {
            const label = node('label', '工作表 ', 'archive-sheet-label');
            const select = node('select'); select.setAttribute('aria-label', '选择工作表');
            for (let i = 0; i < data.sheets.length; i++) {
              const option = node('option', data.sheets[i]); option.value = String(i); select.append(option);
            }
            select.value = String(data.sheet); select.disabled = !data.sheets.length;
            select.addEventListener('change', () => member(entry, Number(select.value)));
            label.append(select); body.append(label);
            if (data.truncated) body.append(node('p', '表格已截断：仅显示前 200 行、50 列，请下载查看完整内容。', 'archive-message'));
            if (!data.rows.length) body.append(node('p', '工作表为空或当前预览范围内无单元格。', 'archive-message'));
            const scroll = node('div', '', 'archive-table-scroll'); scroll.tabIndex = 0;
            scroll.setAttribute('role', 'region'); scroll.setAttribute('aria-label', '工作表预览，可横向滚动');
            const table = node('table');
            const caption = node('caption', data.sheets[data.sheet] || '工作表'); table.append(caption);
            const tbody = node('tbody');
            for (const values of data.rows.slice(0, 200)) {
              const row = node('tr'); for (const value of values.slice(0, 50)) row.append(node('td', value)); tbody.append(row);
            }
            table.append(tbody); scroll.append(table); body.append(scroll);
          } else body.append(node('p', '此文件不支持在线预览，请下载原文件。', 'archive-message'));
        }
      });
    }
    function size(bytes) {
      return bytes >= 1024 * 1024 ? (bytes / 1024 / 1024).toFixed(1) + ' MiB' : bytes >= 1024 ? (bytes / 1024).toFixed(1) + ' KiB' : bytes + ' B';
    }
    async function open(reference) {
      close(); state = {path: reference.path, version: '', directory: '', page: 0}; await list('', 0);
    }
    return {open, close};
  }
  const api = {createArchivePreview};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ArchivePreview = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
