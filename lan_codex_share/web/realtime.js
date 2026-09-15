'use strict';

function patchStreamFields(original, fields, removed) {
  const result = {...original, ...fields};
  for (const key of removed || []) delete result[key];
  return result;
}

class StreamSnapshot {
  constructor() { this.sequence = 0; this.snapshot = null; }

  apply(event, data) {
    if (!Number.isSafeInteger(data.sequence) || data.sequence < 1) throw Error('实时数据序号无效');
    if (event === 'snapshot') {
      if (!data.snapshot?.thread || !Array.isArray(data.snapshot.thread.turns)) throw Error('实时快照无效');
      this.snapshot = data.snapshot;
    } else {
      if (!this.snapshot || data.base !== this.sequence || data.sequence !== this.sequence + 1) throw Error('实时数据需要重新同步');
      const turns = new Map(this.snapshot.thread.turns.map(turn => [turn.id, turn]));
      for (const change of data.turns) {
        if (change.replace) { turns.set(change.id, change.replace); continue; }
        const old = turns.get(change.id);
        if (!old) throw Error('实时对话基线缺失');
        const items = new Map((old.items || []).map(item => [item.id, item]));
        for (const item of change.items) {
          if (item.replace) items.set(item.id, item.replace);
          else {
            const prior = items.get(item.id);
            if (typeof prior?.text !== 'string' || typeof item.append !== 'string') throw Error('实时消息基线缺失');
            items.set(item.id, {...prior, text: prior.text + item.append});
          }
        }
        const turn = patchStreamFields(old, change.fields, change.removed);
        turn.items = change.order.map(id => {
          if (!items.has(id)) throw Error('实时消息缺失');
          return items.get(id);
        });
        turns.set(change.id, turn);
      }
      const thread = patchStreamFields(this.snapshot.thread, data.thread_fields, data.thread_removed);
      thread.turns = data.order.map(id => {
        if (!turns.has(id)) throw Error('实时对话缺失');
        return turns.get(id);
      });
      this.snapshot = {...patchStreamFields(this.snapshot, data.fields, data.removed), thread};
    }
    this.sequence = data.sequence;
    return this.snapshot;
  }
}

if (typeof module !== 'undefined') module.exports = {StreamSnapshot};
