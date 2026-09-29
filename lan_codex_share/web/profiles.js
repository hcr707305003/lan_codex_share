(function (root) {
  'use strict';
  function isDirty(profile, alias, notice) {
    return alias !== profile.alias || notice !== profile.notice_markdown;
  }
  function validate(alias, notice) {
    if ([...alias].length > 100 || /[\u0000-\u001f\u007f-\u009f]/.test(alias)) return '别名最多 100 字符，不能包含换行或控制字符';
    if (new TextEncoder().encode(notice).length > 65536) return 'Markdown 公告不能超过 64 KiB';
    return '';
  }
  function mount(options) {
    let selected = null, record = null, editing = false, busy = false, generation = 0, loading = false;
    let aliasInput, noticeInput, status, revisionSeen = 0, editOnLoad = false;
    const node = (tag, text, className = '') => {
      const result = document.createElement(tag); result.textContent = text; result.className = className; return result;
    };
    const dirty = () => editing && record && isDirty(record, aliasInput.value, noticeInput.value);
    function leave() {
      if (busy) return false;
      if (dirty() && !window.confirm('项目资料尚未保存，确定放弃本次修改？')) return false;
      generation++; selected = null; record = null; editing = false; loading = false; editOnLoad = false;
      return true;
    }
    function message(text, error = false) {
      if (!status) return;
      status.textContent = text; status.className = `profile-status${error ? ' error' : ''}`;
    }
    function button(text, handler) {
      const result = node('button', text); result.type = 'button'; result.addEventListener('click', handler); return result;
    }
    function render() {
      const body = options.body; body.replaceChildren();
      const section = node('section', '', 'project-profile'); body.append(section);
      section.append(node('p', '所有访问者共用 · 不会自动发送给 AI', 'profile-hint'));
      status = node('p', '', 'profile-status'); status.setAttribute('role', 'status');
      if (!record) { section.append(status, button('重新加载', () => load())); return; }
      options.title.textContent = record.alias || record.original_name || '项目资料';
      options.path.textContent = record.cwd;
      if (!editing) {
        const bar = node('div', '', 'profile-toolbar');
        bar.append(button('编辑项目资料', () => { generation++; loading = false; editing = true; render(); aliasInput.focus(); }),
          button('重新加载', () => load())); section.append(bar);
        section.append(node('p', record.updated_at ? `更新于 ${new Date(record.updated_at).toLocaleString()}` : '尚未设置项目资料', 'profile-hint'));
        if (record.notice_markdown) {
          const markdown = options.markdown(record.notice_markdown); markdown.classList.add('profile-markdown'); section.append(markdown);
        } else section.append(node('p', '还没有公告。可以写项目用途、相关网站、测试说明和注意事项。', 'profile-empty'));
        section.append(status); return;
      }
      const aliasLabel = node('label', '项目别名'); aliasLabel.htmlFor = 'profile-alias';
      aliasInput = node('input', ''); aliasInput.id = 'profile-alias'; aliasInput.value = record.alias;
      aliasInput.placeholder = '留空使用原目录名';
      const noticeLabel = node('label', '公共公告（Markdown）'); noticeLabel.htmlFor = 'profile-notice';
      noticeInput = node('textarea', ''); noticeInput.id = 'profile-notice'; noticeInput.value = record.notice_markdown;
      noticeInput.placeholder = '# 项目简介\n\n[相关网站](https://example.com)\n\n## 注意事项\n';
      const preview = node('div', '', 'profile-markdown'); preview.hidden = true;
      const toggle = button('预览 Markdown', () => {
        preview.hidden = !preview.hidden; noticeInput.hidden = !preview.hidden;
        toggle.textContent = preview.hidden ? '预览 Markdown' : '继续编辑';
        if (!preview.hidden) preview.replaceChildren(options.markdown(noticeInput.value));
      });
      toggle.setAttribute('aria-controls', 'profile-markdown-preview'); preview.id = 'profile-markdown-preview';
      section.append(aliasLabel, aliasInput, noticeLabel, toggle, noticeInput, preview);
      const bar = node('div', '', 'profile-toolbar');
      const save = button('保存项目资料', async () => {
        if (busy) return;
        const error = validate(aliasInput.value, noticeInput.value);
        if (error) { message(error, true); return; }
        busy = true; message('正在保存…');
        for (const control of section.querySelectorAll('button,input,textarea')) control.disabled = true;
        try {
          record = await options.mutate('/api/projects/profile', {
            project_id: selected.id, alias: aliasInput.value, notice_markdown: noticeInput.value, revision: record.revision,
          });
          revisionSeen = record.revision; editing = false; render(); message('已保存，其他访问者将同步看到。'); options.changed();
        } catch (err) { message(err.message, true); }
        finally { busy = false; for (const control of section.querySelectorAll('button,input,textarea')) control.disabled = false; }
      });
      save.className = 'profile-save';
      bar.append(save, button('取消编辑', () => {
        if (dirty() && !window.confirm('确定放弃未保存的修改？')) return;
        editing = false; load();
      }), button('重新加载', () => {
        if (dirty() && !window.confirm('重新加载将放弃当前编辑，是否继续？')) return;
        editing = false; load();
      }));
      section.append(bar, status);
    }
    async function load() {
      if (!selected || busy) return;
      const token = ++generation; loading = true;
      if (!record) render();
      message('正在读取项目资料…');
      try {
        const result = await options.request(`/api/projects/profile?${new URLSearchParams({project_id: selected.id})}`);
        if (token !== generation) return;
        record = result; revisionSeen = record.revision;
        const focusEditor = editOnLoad; editing = editOnLoad; editOnLoad = false; render();
        if (focusEditor) aliasInput.focus();
      } catch (err) { if (token === generation) message(err.message, true); }
      finally { if (token === generation) loading = false; }
    }
    function open(project, edit = false) {
      if (!leave()) return false;
      selected = project; revisionSeen = project.revision || 0;
      editOnLoad = edit;
      options.show(project); load();
      return true;
    }
    function sync(projects) {
      if (!selected || busy || loading || !record) return;
      const current = (projects || []).find(p => p.id === selected.id);
      if (!current) { message('项目已不在共享列表中；当前内容保留，但无法保存。', true); return; }
      if ((current.revision || 0) === revisionSeen) return;
      revisionSeen = current.revision || 0;
      if (editing) message('其他人已更新资料。当前编辑已保留，保存前请重新加载。', true);
      else load();
    }
    window.addEventListener('beforeunload', event => {
      if (dirty() || busy) { event.preventDefault(); event.returnValue = ''; }
    });
    return {open, leave, sync};
  }
  const api = {mount, isDirty, validate};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.LanProfiles = api;
})(typeof window === 'undefined' ? globalThis : window);
