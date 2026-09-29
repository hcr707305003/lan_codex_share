(function (root) {
  'use strict';
  function mount(options) {
    let session = null, project = null, signature = '', expanded = false;
    let generation = 0, controller = null, loading = false, error = '', cached = null;
    function paint() {
      options.layout(() => {
        options.root.hidden = !project?.has_notice || cached === '';
        options.toggle.setAttribute('aria-expanded', String(expanded));
        options.body.hidden = !expanded;
        options.status.hidden = !expanded || (!loading && !error);
        options.status.textContent = loading ? '正在读取公告…' : error;
        options.retry.hidden = !expanded || !error;
      });
    }
    function cancel() {
      generation++; controller?.abort(); controller = null; loading = false;
    }
    function clearBody() {
      options.layout(() => options.body.replaceChildren());
    }
    async function load() {
      if (!project?.has_notice || !expanded || loading || cached !== null || error) return;
      const token = ++generation;
      controller = new AbortController(); loading = true; paint();
      try {
        const result = await options.request(`/api/projects/profile?${new URLSearchParams({project_id: project.id})}`, controller.signal);
        if (token !== generation) return;
        cached = String(result.notice_markdown || '');
        if (!cached.trim()) { cached = ''; expanded = false; }
        options.layout(() => options.body.replaceChildren(...(cached ? [options.markdown(cached)] : [])));
      } catch (err) {
        if (token !== generation) return;
        error = err.message || '公告读取失败，请重试';
      } finally {
        if (token === generation) { loading = false; controller = null; paint(); }
      }
    }
    function update(sessionId, next) {
      const nextSignature = JSON.stringify([next?.id, next?.revision, !!next?.has_notice]);
      const changedSession = session !== sessionId;
      const changedProject = project?.id !== next?.id;
      project = next; session = sessionId;
      if (!changedSession && signature === nextSignature) return;
      signature = nextSignature;
      cancel(); cached = null; error = '';
      if (changedSession || changedProject || !project?.has_notice) expanded = false;
      clearBody(); paint(); load();
    }
    options.toggle.addEventListener('click', () => {
      if (!project?.has_notice) return;
      expanded = !expanded; paint();
      if (expanded) load();
      else cancel();
    });
    options.retry.addEventListener('click', () => { error = ''; load(); });
    options.edit.addEventListener('click', () => { if (project) options.editProject(project); });
    paint();
    return {update};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {mount};
  else root.LanNotice = {mount};
})(typeof window === 'undefined' ? globalThis : window);
