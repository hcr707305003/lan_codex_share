'use strict';

function reconcileHistoryNodes(parent, nodes) {
  const keep = new Set(nodes);
  for (const child of Array.from(parent.children)) if (!keep.has(child)) child.remove();
  let next = parent.firstElementChild;
  for (const node of nodes) {
    if (node === next) next = next.nextElementSibling;
    else parent.insertBefore(node, next);
  }
}

class HistoryTimeline {
  constructor({root, renderTurn, fetchPage, onError}) {
    Object.assign(this, {root, renderTurn, fetchPage, onError});
    this.generation = 0;
    this.reset();
    this.root.addEventListener('scroll', () => {
      if (this.root.scrollTop <= 80 && !this.failed) this.loadEarlier();
    }, {passive: true});
  }

  reset() {
    this.generation += 1;
    this.controller?.abort();
    for (const entry of this.entries?.values() || []) entry.node.dispose?.();
    this.entries = new Map();
    this.epoch = null;
    this.latest = null;
    this.before = null;
    this.loading = false;
    this.failed = false;
    this.root.replaceChildren();
    this.controls = document.createElement('div');
    this.controls.className = 'history-controls';
    this.more = document.createElement('button');
    this.more.type = 'button';
    this.more.addEventListener('click', () => this.loadEarlier());
    this.recent = document.createElement('button');
    this.recent.type = 'button';
    this.recent.textContent = '回到最近 20 轮';
    this.recent.addEventListener('click', () => this.showRecent());
    this.label = document.createElement('span');
    this.label.setAttribute('role', 'status');
    this.controls.append(this.more, this.recent, this.label);
    this.root.append(this.controls);
  }

  anchor() {
    const top = this.root.getBoundingClientRect().top;
    for (const entry of this.entries.values()) {
      const rect = entry.node.getBoundingClientRect();
      if (rect.bottom > top && rect.top < top + this.root.clientHeight) return {id: entry.turn.id, top: rect.top};
    }
    return null;
  }

  restore(anchor) {
    const node = anchor && this.entries.get(anchor.id)?.node;
    if (node) this.root.scrollTop += node.getBoundingClientRect().top - anchor.top;
  }

  update(snapshot) {
    const turns = snapshot.thread?.turns || [];
    const page = snapshot.history || {epoch: snapshot.thread_id || 'empty', start: 0, end: turns.length, total: turns.length, before: null};
    const newest = Math.max(-1, ...Array.from(this.entries.values(), entry => entry.index));
    if (this.epoch !== page.epoch || (newest >= 0 && page.start > newest + 1)) this.reset();
    this.epoch = page.epoch;
    this.latest = snapshot;
    const first = !this.entries.size;
    const atBottom = this.root.scrollHeight - this.root.scrollTop - this.root.clientHeight < 120;
    const anchor = !first && !atBottom ? this.anchor() : null;
    this.merge(turns, page);
    // Bound automatic growth during days-long streams; manually loaded history
    // remains available while the reader is away from the live tail.
    if (atBottom && this.entries.size > 100) {
      const cutoff = page.end - 100;
      for (const [id, entry] of this.entries) if (entry.index < cutoff) this.remove(id);
    }
    this.draw();
    if (first || atBottom) this.root.scrollTop = this.root.scrollHeight;
    else this.restore(anchor);
  }

  remove(id) {
    this.entries.get(id)?.node.dispose?.();
    this.entries.get(id)?.node.remove();
    this.entries.delete(id);
  }

  merge(turns, page) {
    turns.forEach((turn, offset) => {
      const old = this.entries.get(turn.id);
      const revision = turn.history_revision ?? JSON.stringify(turn);
      const node = old?.revision === revision ? old.node : this.renderTurn(turn, old?.node);
      this.entries.set(turn.id, {turn, revision, node, index: page.start + offset});
    });
  }

  draw() {
    const entries = Array.from(this.entries.values()).sort((a, b) => a.index - b.index);
    const start = entries[0]?.index || 0;
    this.before = start ? `${this.epoch}:${start}` : null;
    this.more.hidden = !this.before || !this.failed;
    this.more.disabled = this.loading;
    this.more.textContent = '重试加载历史';
    this.more.setAttribute('aria-busy', String(this.loading));
    this.recent.hidden = entries.length <= 20;
    const count = entries.length ? `已加载 ${entries.length} / ${this.latest?.history?.total ?? entries.length} 轮` : '这个 Session 还没有消息。';
    this.label.textContent = this.loading ? `正在加载更早消息… · ${count}`
      : this.failed ? `历史加载失败 · ${count}`
      : this.before ? `上滑加载更早消息 · ${count}` : count;
    this.controls.setAttribute('aria-busy', String(this.loading));
    reconcileHistoryNodes(this.root, [this.controls, ...entries.map(entry => entry.node)]);
  }

  async loadEarlier() {
    if (!this.before || this.loading) return;
    const loadingAnchor = this.anchor();
    this.loading = true;
    this.failed = false;
    const generation = this.generation;
    const epoch = this.epoch;
    this.controller = new AbortController();
    this.draw();
    this.restore(loadingAnchor);
    try {
      const snapshot = await this.fetchPage(this.before, this.controller.signal);
      if (generation !== this.generation || epoch !== snapshot.history?.epoch) return;
      const anchor = this.anchor();
      this.merge(snapshot.thread.turns, snapshot.history);
      this.draw();
      this.restore(anchor);
    } catch (error) {
      if (generation === this.generation && error.name !== 'AbortError') {
        this.failed = true;
        this.onError(error);
      }
    } finally {
      if (generation === this.generation) {
        const anchor = this.anchor();
        this.loading = false;
        this.draw();
        this.restore(anchor);
      }
    }
  }

  showRecent() {
    if (!this.latest) return;
    const snapshot = this.latest;
    this.reset();
    this.update(snapshot);
    this.root.scrollTop = this.root.scrollHeight;
  }
}

if (typeof module !== 'undefined') module.exports = {HistoryTimeline, reconcileHistoryNodes};
