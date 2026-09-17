/* Page-local notifications. Never infer completion from connection or queue state. */
const TASK_TERMINAL_STATUSES = new Map([
  ['completed', 'completed'], ['failed', 'failed'], ['interrupted', 'interrupted'],
  ['cancelled', 'interrupted'], ['canceled', 'interrupted'],
]);

class TaskCompletionTracker {
  constructor() { this.reset(); }
  reset() { this.session = ''; this.seen = new Map(); }
  update(snapshot) {
    const session = String(snapshot.selected_session_id || snapshot.thread_id || snapshot.thread?.id || '');
    const turns = snapshot.thread?.turns;
    if (!session || !Array.isArray(turns)) return [];
    const baseline = session !== this.session;
    if (baseline) { this.reset(); this.session = session; }
    const notices = [];
    for (const turn of turns) {
      if (!turn.id) continue;
      const id = String(turn.id);
      const status = TASK_TERMINAL_STATUSES.get(turn.status);
      // Terminal markers are sticky even if a stale update reports inProgress later.
      if (status && !baseline && this.seen.get(id) !== true) {
        notices.push({id, session, status, name: String(snapshot.thread.name || 'Codex Session'),
          completedAt: turn.completedAt ?? null});
      }
      this.seen.set(id, this.seen.get(id) === true || Boolean(status));
    }
    return notices;
  }
}

class TaskNotifications {
  constructor(container) {
    this.container = container;
    this.tracker = new TaskCompletionTracker();
    this.enabled = false;
    this.reset();
  }
  setEnabled(value) {
    const enabled = value === true;
    if (enabled === this.enabled) return;
    this.enabled = enabled;
    this.reset();
  }
  reset() {
    this.tracker.reset();
    this.container.replaceChildren();
    this.container.hidden = true;
  }
  update(snapshot) {
    if (!this.enabled) return;
    const previous = this.tracker.session;
    const notices = this.tracker.update(snapshot);
    if (previous !== this.tracker.session) {
      this.container.replaceChildren();
      this.container.hidden = true;
    }
    for (const notice of notices) this.append(notice);
  }
  append(notice) {
    const node = (tag, className, text) => {
      const value = document.createElement(tag);
      value.className = className;
      if (text !== undefined) value.textContent = text;
      return value;
    };
    const labels = {completed:'任务已完成', failed:'任务失败', interrupted:'任务已中断'};
    const card = node('article', `task-notification ${notice.status}`);
    const title = node('strong', 'task-notification-title', labels[notice.status]);
    const name = node('div', 'task-notification-name', notice.name);
    let value = notice.completedAt;
    if (typeof value === 'number' && value < 1e12) value *= 1000;
    let date = value == null ? new Date() : new Date(value);
    if (Number.isNaN(date.getTime())) date = new Date();
    const time = node('time', 'task-notification-time', date.toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit', second:'2-digit'}));
    time.dateTime = date.toISOString();
    const close = node('button', 'task-notification-close', '×');
    close.type = 'button';
    close.setAttribute('aria-label', `关闭${labels[notice.status]}提示`);
    close.title = '关闭提示';
    close.addEventListener('click', () => {
      card.remove();
      this.container.hidden = this.container.children.length === 0;
    });
    card.append(title, name, time, close);
    this.container.hidden = false;
    this.container.append(card);
    this.container.scrollTop = this.container.scrollHeight;
  }
}

if (typeof module !== 'undefined') module.exports = {TaskCompletionTracker, TaskNotifications};
