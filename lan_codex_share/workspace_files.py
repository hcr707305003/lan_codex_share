from __future__ import annotations

from dataclasses import dataclass
import mimetypes
import os
from pathlib import Path
import threading


TEXT_EXTENSIONS = {
    ".php", ".js", ".jsx", ".ts", ".tsx", ".vue", ".py", ".java", ".go", ".rs",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".cs", ".json", ".yaml", ".yml", ".toml",
    ".xml", ".html", ".htm", ".css", ".scss", ".sass", ".less", ".sql", ".sh",
    ".ps1", ".bat", ".cmd", ".ini", ".conf", ".config", ".log", ".txt", ".csv",
}
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown"}
TEXT_FILENAMES = {".env", ".gitignore", ".gitattributes", "dockerfile", "makefile", "license"}
IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


class WorkspaceFileError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class WorkspaceFilePreview:
    path: Path
    relative_path: str
    name: str
    kind: str
    mime: str
    size: int
    content: str | None = None
    encoding_warning: bool = False

    def json_value(self) -> dict[str, object]:
        return {
            "name": self.name,
            "relativePath": self.relative_path,
            "kind": self.kind,
            "mime": self.mime,
            "size": self.size,
            "content": self.content or "",
            "encodingWarning": self.encoding_warning,
        }


class WorkspaceFileViewer:
    def __init__(
        self,
        root: str | Path,
        *,
        preview_roots: list[str | Path] | tuple[Path, ...] = (),
        max_text_bytes: int = 2 * 1024 * 1024,
        max_inline_bytes: int = 25 * 1024 * 1024,
    ):
        self.root = Path(os.path.abspath(Path(root).expanduser())).resolve()
        self._roots_lock = threading.RLock()
        roots = [self.root]
        for candidate in preview_roots:
            resolved = Path(os.path.abspath(Path(candidate).expanduser())).resolve()
            if resolved not in roots:
                roots.append(resolved)
        self._base_roots = tuple(roots)
        self.roots = self._base_roots
        self.max_text_bytes = max_text_bytes
        self.max_inline_bytes = max_inline_bytes

    def set_dynamic_roots(self, candidates: list[str | Path] | tuple[Path, ...]) -> None:
        resolved = [Path(os.path.abspath(Path(candidate).expanduser())).resolve() for candidate in candidates]
        with self._roots_lock:
            roots = list(self._base_roots)
            for candidate in resolved:
                if candidate.is_dir() and candidate not in roots:
                    roots.append(candidate)
            self.roots = tuple(roots)

    def open(self, raw_path: str) -> WorkspaceFilePreview:
        if not raw_path.strip():
            raise WorkspaceFileError(400, "文件路径不能为空")
        logical_path = Path(os.path.abspath(Path(raw_path).expanduser()))
        try:
            path = logical_path.resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise WorkspaceFileError(404, "文件不存在") from exc
        matched_root = None
        relative = None
        with self._roots_lock:
            roots = self.roots
        for root in roots:
            try:
                relative = path.relative_to(root)
                matched_root = root
                break
            except ValueError:
                continue
        if matched_root is None or relative is None:
            raise WorkspaceFileError(403, "只允许查看工作区或已授权预览目录内的文件")
        if not path.is_file():
            raise WorkspaceFileError(400, "路径不是普通文件")

        try:
            size = path.stat().st_size
        except OSError as exc:
            raise WorkspaceFileError(404, "无法读取文件") from exc
        suffix = path.suffix.lower()
        name = path.name
        relative_path = relative.as_posix()
        if matched_root != self.root:
            relative_path = f"{matched_root.name}/{relative_path}"

        if suffix in MARKDOWN_EXTENSIONS:
            return self._read_text(path, relative_path, "markdown", "text/markdown; charset=utf-8", size)
        if suffix in TEXT_EXTENSIONS or name.lower() in TEXT_FILENAMES:
            mime = mimetypes.guess_type(name)[0] or "text/plain"
            return self._read_text(path, relative_path, "code", f"{mime}; charset=utf-8", size)
        if suffix in IMAGE_MIME:
            self._check_inline_size(size)
            return WorkspaceFilePreview(path, relative_path, name, "image", IMAGE_MIME[suffix], size)
        if suffix == ".pdf":
            self._check_inline_size(size)
            return WorkspaceFilePreview(path, relative_path, name, "pdf", "application/pdf", size)
        raise WorkspaceFileError(415, "此文件类型不支持浏览器预览")

    def _read_text(self, path: Path, relative_path: str, kind: str, mime: str, size: int) -> WorkspaceFilePreview:
        if size > self.max_text_bytes:
            raise WorkspaceFileError(413, "文本文件超过 2 MiB 预览上限")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise WorkspaceFileError(404, "无法读取文件") from exc
        try:
            content = raw.decode("utf-8")
            warning = False
        except UnicodeDecodeError:
            content = raw.decode("utf-8", errors="replace")
            warning = True
        return WorkspaceFilePreview(path, relative_path, path.name, kind, mime, size, content, warning)

    def _check_inline_size(self, size: int) -> None:
        if size > self.max_inline_bytes:
            raise WorkspaceFileError(413, "图片或 PDF 超过 25 MiB 预览上限")
