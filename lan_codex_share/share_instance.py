"""Minimal local discovery hints; records alone never authorize termination."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

import psutil


def instance_path(config_path):
    return Path(config_path).resolve().parent / 'runtime/lan/instance.json'


def _app_server(process, endpoint):
    # Only the native Codex app-server process, never shells or arbitrary descendants.
    name = Path(process.exe()).name.lower()
    return (name in ('codex', 'codex.exe') and
            list(process.cmdline())[1:] == ['app-server', '--listen', endpoint])


def write_instance(config_path, app_server, port):
    owner = psutil.Process()
    endpoint = getattr(app_server, 'endpoint', None)
    owned = []
    reused = getattr(app_server, 'reusing_existing', None)
    if reused is False and endpoint:
        for child in getattr(app_server, '_owned_processes', []):
            try:
                if (_app_server(child, endpoint) and child.is_running() and
                        owner.pid in {p.pid for p in child.parents()}):
                    owned.append({'pid': child.pid, 'created': child.create_time()})
            except psutil.Error:
                continue
    data = {'pid': owner.pid, 'created': owner.create_time(), 'config': str(Path(config_path).resolve()),
            'port': port, 'endpoint': endpoint, 'reused': reused, 'app_servers': owned}
    path = instance_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.instance-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read(config_path):
    path = instance_path(config_path)
    if path.stat().st_size > 32768:
        raise ValueError('Invalid instance record')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Invalid instance record')
    return data


def remove_instance(config_path):
    try:
        data = _read(config_path)
        owner = psutil.Process()
        if (data.get('pid') == owner.pid and data.get('created') == owner.create_time() and
                data.get('config') == str(Path(config_path).resolve())):
            instance_path(config_path).unlink(missing_ok=True)
    except (OSError, ValueError, psutil.Error):
        pass


def verified_app_servers(identity):
    unverified = '未验证关联 App Server 归属，已保留，请按需手动检查。'
    try:
        data = _read(identity.config_path)
        if (data.get('pid') != identity.pid or data.get('created') != identity.created or
                data.get('config') != str(identity.config_path)):
            return [], unverified
        if data.get('reused') is True:
            return [], '复用的 App Server 已保留。'
        endpoint = data.get('endpoint')
        if (data.get('reused') is not False or not isinstance(endpoint, str) or
                not re.fullmatch(r'ws://127\.0\.0\.1:\d{1,5}', endpoint)):
            return [], unverified
        entries = data.get('app_servers')
        if not isinstance(entries, list) or not 1 <= len(entries) <= 8:
            return [], unverified
        verified, seen = [], set()
        for entry in entries:
            if not isinstance(entry, dict) or type(entry.get('pid')) is not int:
                return [], unverified
            child = psutil.Process(entry['pid'])
            if (child.pid == identity.pid or child.pid in seen or not child.is_running() or
                    child.create_time() != entry.get('created') or child.create_time() < identity.created or
                    identity.pid not in {p.pid for p in child.parents()} or not _app_server(child, endpoint)):
                return [], unverified
            seen.add(child.pid)
            verified.append((child, (child.exe(), tuple(child.cmdline()))))
        return verified, '已处理该实例自建且身份验证通过的 App Server。'
    except (OSError, ValueError, TypeError, psutil.Error):
        return [], unverified
