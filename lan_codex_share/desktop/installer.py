from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import tarfile
import tempfile
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile


RELEASES_URL = "https://github.com/fatedier/frp/releases"
API_URL = "https://api.github.com/repos/fatedier/frp/releases/latest"
MAX_ARCHIVE = 200 * 1024 * 1024
MAX_BINARY = 100 * 1024 * 1024


def platform_key(system=None, machine=None):
    system, machine = system or platform.system(), (machine or platform.machine()).lower()
    systems = {"Windows": "windows", "Darwin": "darwin", "Linux": "linux"}
    machines = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}
    if system not in systems or machine not in machines:
        raise ValueError("当前平台暂无自动下载支持，请打开官方下载页")
    return f"{systems[system]}_{machines[machine]}"


def validate_url(url):
    parsed = urlsplit(url)
    allowed = {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
    if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("拒绝非官方 HTTPS 下载地址")
    if parsed.hostname == "github.com" and not parsed.path.startswith('/fatedier/frp/releases/'):
        raise ValueError("拒绝非 frp 官方发行地址")


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, limit, cancel, progress):
    validate_url(url)
    for attempt in range(3):
        if cancel.is_set():
            raise ValueError("下载已取消")
        try:
            accept = 'application/vnd.github+json' if urlsplit(url).hostname == 'api.github.com' else 'application/octet-stream'
            request = Request(url, headers={"User-Agent": "lan-codex-share-desktop", "Accept": accept})
            with build_opener(OfficialRedirects()).open(request, timeout=10) as response:
                total = int(response.headers.get('Content-Length', 0))
                if total > limit:
                    raise ValueError("下载文件超过大小限制")
                output = bytearray()
                while chunk := response.read(256 * 1024):
                    if cancel.is_set():
                        raise ValueError("下载已取消")
                    output.extend(chunk)
                    if len(output) > limit:
                        raise ValueError("下载文件超过大小限制")
                    progress(f"已下载 {len(output) // 1024} KiB")
                return bytes(output)
        except HTTPError as exc:
            if exc.code in (403, 429):
                raise ValueError("GitHub 请求受限，请稍后重试或打开官方下载页") from None
            if exc.code < 500 or attempt == 2:
                raise ValueError(f"官方下载失败（HTTP {exc.code}），请使用官方下载页") from None
        except (URLError, TimeoutError, OSError):
            if attempt == 2:
                raise ValueError("官方网络连接失败，请检查网络或使用官方下载页") from None
        if cancel.wait(attempt + 1):
            raise ValueError("下载已取消")


def latest_release(cancel=None):
    payload = download(API_URL, 2 * 1024 * 1024, cancel or Event(), lambda message: None)
    release = json.loads(payload)
    if release.get('draft') or release.get('prerelease') or not isinstance(release.get('assets'), list):
        raise ValueError("未找到可安装的官方稳定发行版")
    return release


def _safe_member(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError("归档包含不安全路径")
    return path


def extract_binary(payload, extension, binary):
    found = []
    if extension == 'zip':
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for item in archive.infolist():
                path = _safe_member(item.filename)
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError("归档不允许符号链接")
                if path.name == binary:
                    if item.is_dir() or item.file_size > MAX_BINARY or (stat.S_IFMT(mode) and not stat.S_ISREG(mode)):
                        raise ValueError("二进制文件类型或大小不合法")
                    with archive.open(item) as stream:
                        found.append(stream.read(MAX_BINARY + 1))
    else:
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
            for item in archive:
                path = _safe_member(item.name)
                if item.issym() or item.islnk():
                    raise ValueError("归档不允许链接")
                if path.name == binary:
                    if not item.isfile() or item.size > MAX_BINARY:
                        raise ValueError("二进制文件类型或大小不合法")
                    with archive.extractfile(item) as stream:
                        found.append(stream.read(MAX_BINARY + 1))
    if len(found) != 1 or not found[0] or len(found[0]) > MAX_BINARY:
        raise ValueError("归档中缺少唯一有效 frpc 程序")
    return found[0]


def install_frpc(release, destination: Path, cancel: Event, progress):
    key = platform_key()
    version = str(release.get('tag_name', '')).removeprefix('v')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError("无法识别官方版本号")
    extension = 'zip' if key.startswith('windows') else 'tar.gz'
    name = f'frp_{version}_{key}.{extension}'
    assets = [asset for asset in release['assets'] if asset['name'] == name]
    if len(assets) != 1:
        raise ValueError("未找到当前平台的唯一官方安装包")
    asset = assets[0]
    digest = str(asset.get('digest') or '')
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        checksums = [a for a in release['assets'] if a['name'] in ('SHA256SUMS', 'checksums.txt', f'frp_{version}_checksums.txt', 'frp_sha256_checksums.txt')]
        digest = ''
        if len(checksums) == 1:
            content = download(checksums[0]['browser_download_url'], 1024 * 1024, cancel, progress).decode('utf-8')
            for line in content.splitlines():
                fields = line.split()
                if len(fields) == 2 and fields[1].lstrip('*') == name and re.fullmatch('[0-9a-fA-F]{64}', fields[0]):
                    digest = 'sha256:' + fields[0]
        if not digest:
            raise ValueError("官方未提供可信 SHA-256，不能自动安装，请使用官方下载页")
    payload = download(asset['browser_download_url'], MAX_ARCHIVE, cancel, progress)
    if hashlib.sha256(payload).hexdigest() != digest.split(':', 1)[1].lower():
        raise ValueError("SHA-256 校验失败，未安装")
    progress("SHA-256 已验证，正在提取程序")
    binary_name = 'frpc.exe' if key.startswith('windows') else 'frpc'
    binary = extract_binary(payload, extension, binary_name)
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.install-', dir=destination) as temporary:
        source = Path(temporary) / binary_name
        source.write_bytes(binary)
        source.chmod(0o755)
        if cancel.is_set():
            raise ValueError("下载已取消")
        target_dir = destination / version
        target = target_dir / binary_name
        if target.exists():
            if target.read_bytes() != binary:
                raise ValueError("同版本目录已有不同程序，请先手动检查，未覆盖")
            return target
        target_dir.mkdir(exist_ok=True)
        os.replace(source, target)
    return target
