"""Editable local model choices; entries do not guarantee upstream access."""
import json
import re
import threading
from pathlib import Path

_lock = threading.RLock()
PRESETS = [('gpt-6.1-sol', 'GPT-6.1 Sol'), ('gpt-6-astra', 'GPT-6 Astra'),
           ('gpt-6-sol', 'GPT-6 Sol'), ('gpt-6-luna', 'GPT-6 Luna'),
           ('gpt-5.6-sol', 'GPT-5.6 Sol'), ('gpt-6.1-terra', 'GPT-6.1 Terra'),
           ('gpt-5.6-terra', 'GPT-5.6 Terra'), ('gpt-5.6-luna', 'GPT-5.6 Luna'),
           ('gpt-5.5', 'GPT-5.5')]


def entry(model, name):
    return dict(id=model, model=model, display_name=name,
                description='本地模型条目，实际可用性由 Codex 服务决定', is_default=False,
                default_reasoning_effort='medium',
                supported_reasoning_efforts=[{'value': x, 'description': ''} for x in ('low', 'medium', 'high', 'xhigh', 'max', 'ultra')],
                default_service_tier=None, service_tiers=[])


class ModelCatalog:
    def __init__(self, path):
        self.path = Path(path) if path else None

    def custom(self):
        if self.path is None or not self.path.exists():
            return []
        try:
            rows = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('model'), str) or not isinstance(r.get('name'), str) for r in rows):
                raise ValueError()
            return rows
        except (ValueError, OSError) as exc:
            raise ValueError('自定义模型文件无法读取，请检查 custom_models.json') from exc

    def merge(self, server):
        with _lock:
            known = {r['model']: r for r in server}
            choices = dict(PRESETS)
            choices.update({r['model']: r['name'] for r in self.custom()})
            result = []
            for model, name in choices.items():
                item = dict(known.get(model) or entry(model, name))
                item['display_name'] = name
                result.append(item)
            result.extend(r for r in server if r['model'] not in choices)
            return result

    def add(self, model, name):
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', model.strip()):
            raise ValueError('模型 ID 须为 1～128 位字母、数字或 . _ : / -')
        model = model.strip()
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or any(ord(c) < 32 for c in name):
            raise ValueError('显示名称须为 1～100 个字符，不能包含控制字符')
        with _lock:
            if self.path is None:
                raise ValueError('自定义模型保存目录不可用')
            rows = self.custom()
            if model in dict(PRESETS) or any(r['model'] == model for r in rows):
                raise ValueError('该模型 ID 已存在')
            if len(rows) >= 100:
                raise ValueError('自定义模型最多 100 个')
            rows.append({'model': model, 'name': name.strip()})
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.path)
