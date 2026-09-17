from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile

import tomlkit
import yaml

from ..lan_config import load_lan_config
from .theme import normalize_theme


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("YAML 包含重复字段")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _port(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ValueError(f"{label} 必须为 1–65535 的整数")


class ConfigDocument:
    def __init__(self, path: Path, kind: str):
        self.path = Path(path).expanduser().resolve()
        self.kind = kind
        self.digest = _digest(self.path)

    def load(self) -> str:
        payload = self.path.read_bytes()
        self.digest = hashlib.sha256(payload).hexdigest()
        return payload.decode("utf-8-sig")

    def parse(self, text: str) -> dict:
        try:
            data = yaml.load(text, Loader=UniqueLoader) if self.kind == "cf" else tomlkit.parse(text)
            if not isinstance(data, dict):
                raise ValueError("配置顶层必须是字段集合")
            return data
        except Exception as exc:
            # Parser excerpts can contain passwords: never echo them in UI/logs.
            mark = getattr(exc, "problem_mark", None)
            where = f"（第 {mark.line + 1} 行）" if mark else ""
            raise ValueError(f"配置语法错误{where}，请检查格式或重复字段") from None

    def update_fields(self, text: str, updates: dict, proxy_index: int = 0, *, remove_fields=()) -> str:
        if self.kind == "cf":
            raise ValueError("Cloudflare YAML 请使用原始配置编辑")
        data = self.parse(text)
        for key in remove_fields:
            if not isinstance(key, str) or not key or '.' in key:
                raise ValueError('只能显式移除顶层配置字段')
            data.pop(key, None)
        for key, value in updates.items():
            target = data
            if key.startswith("proxies."):
                proxies = data.get("proxies", [])
                if not 0 <= proxy_index < len(proxies) or proxies[proxy_index].get("type") != "tcp":
                    raise ValueError("请先选择一个 TCP 代理")
                target = proxies[proxy_index]
                key = key.removeprefix("proxies.")
            parts = key.split(".")
            for part in parts[:-1]:
                if part not in target:
                    target[part] = tomlkit.table()
                target = target[part]
            target[parts[-1]] = value
        return tomlkit.dumps(data)

    def validate(self, text: str) -> dict:
        data = self.parse(text)
        if self.kind == "frp":
            if not isinstance(data.get("serverAddr"), str) or not data["serverAddr"].strip():
                raise ValueError("serverAddr 不能为空")
            _port(data.get("serverPort", 7000), "serverPort")
            for item in data.get("proxies", []):
                if not isinstance(item, dict):
                    raise ValueError("proxies 必须为代理表数组")
                for key in ("localPort", "remotePort"):
                    if key in item:
                        _port(item[key], key)
        elif self.kind == "cf":
            if not data.get("tunnel"):
                raise ValueError("本地 YAML 模式需要 tunnel 字段")
            if "ingress" in data and not isinstance(data["ingress"], list):
                raise ValueError("ingress 必须为数组")
        return data

    def save(self, text: str) -> None:
        self.validate(text)
        if _digest(self.path) != self.digest:
            raise ValueError("文件已被外部修改，请重新加载或另存为")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".desktop-", suffix=".toml", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            if self.kind == "lan":
                try:
                    load_lan_config(temporary)
                except Exception:
                    raise ValueError("Share 配置校验失败，请检查目录、端口、Session、权限及公网入口/密码设置") from None
            if _digest(self.path) != self.digest:
                raise ValueError("文件已被外部修改，请重新加载或另存为")
            os.replace(temporary, self.path)
            self.digest = _digest(self.path)
        finally:
            temporary.unlink(missing_ok=True)


class DesktopSettings:
    def __init__(self, lan_path: Path):
        self.path = Path(lan_path).resolve().parent / "desktop_config.toml"

    def resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (self.path.parent / path).resolve()

    def program_value(self, path: Path) -> str:
        path = Path(path).resolve()
        try:
            return path.relative_to(self.path.parent).as_posix()
        except ValueError:
            return str(path)

    def load(self) -> dict:
        defaults = {"frpc_config": "frpc.toml", "cloudflared_config": "cloudflared.yml",
                    "frpc_executable": "", "cloudflared_executable": "",
                    "cloudflared_mode": "yaml", "cloudflared_token_file": "", "theme": "graphite"}
        if self.path.exists():
            data = ConfigDocument(self.path, "desktop").parse(self.path.read_text(encoding="utf-8-sig"))
            for key in defaults:
                if key in data:
                    if key == 'theme':
                        defaults[key] = normalize_theme(data[key])
                        continue
                    if not isinstance(data[key], str):
                        raise ValueError(f"桌面设置 {key} 必须为字符串")
                    defaults[key] = data[key]
        return defaults

    def save(self, values: dict) -> None:
        doc = ConfigDocument(self.path, "desktop")
        text = doc.load() if self.path.exists() else ""
        doc.save(doc.update_fields(text, values))
