from __future__ import annotations

import base64
import binascii
from io import BytesIO
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError


class ImageValidationError(ValueError):
    pass

class ImageStore:
    FORMAT_INFO = {
        "PNG": (".png", "image/png"),
        "JPEG": (".jpg", "image/jpeg"),
        "WEBP": (".webp", "image/webp"),
    }
    ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
    ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

    def __init__(self, directory: str | Path, max_bytes: int, max_images: int):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.max_images = max_images

    def save_many(self, payloads: list[dict[str, Any]]) -> list[dict[str, str]]:
        if len(payloads) > self.max_images:
            raise ImageValidationError(f"每条消息最多上传 {self.max_images} 张图片")
        saved: list[dict[str, str]] = []
        try:
            for payload in payloads:
                saved.append(self._save_one(payload))
            return saved
        except Exception:
            for record in saved:
                try:
                    Path(record["path"]).unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def _save_one(self, payload: dict[str, Any]) -> dict[str, str]:
        name = str(payload.get("name", ""))
        if not name or Path(name).name != name or "/" in name or "\\" in name:
            raise ImageValidationError("图片文件名无效")
        extension = Path(name).suffix.lower()
        if extension not in self.ALLOWED_EXTENSIONS:
            raise ImageValidationError("仅支持 PNG、JPEG 和 WebP")
        declared_mime = str(payload.get("mime", "")).lower()
        try:
            raw = base64.b64decode(str(payload.get("data", "")), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ImageValidationError("图片数据不是有效的 base64") from exc
        if not raw or len(raw) > self.max_bytes:
            raise ImageValidationError(f"单张图片不能超过 {self.max_bytes} 字节")
        try:
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > 40_000_000:
                    raise ImageValidationError("图片像素尺寸过大")
                image.verify()
                detected_format = str(image.format or "").upper()
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            raise ImageValidationError("图片内容无法解码") from exc
        if detected_format not in self.FORMAT_INFO:
            raise ImageValidationError("图片实际格式不受支持")
        canonical_extension, actual_mime = self.FORMAT_INFO[detected_format]
        accepted_extensions = {canonical_extension}
        if detected_format == "JPEG":
            accepted_extensions.add(".jpeg")
        if extension not in accepted_extensions or declared_mime != actual_mime:
            raise ImageValidationError("图片扩展名、MIME 与实际格式不一致")

        image_id = uuid4().hex
        path = (self.directory / f"{image_id}{canonical_extension}").resolve()
        if self.directory not in path.parents:
            raise ImageValidationError("图片保存路径无效")
        path.write_bytes(raw)
        return {
            "id": image_id,
            "name": name,
            "mime": actual_mime,
            "path": str(path),
        }

    def resolve(self, image_id: str) -> tuple[Path, str]:
        if not self.ID_PATTERN.fullmatch(image_id):
            raise FileNotFoundError(image_id)
        matches = list(self.directory.glob(f"{image_id}.*"))
        if len(matches) != 1 or matches[0].suffix.lower() not in self.ALLOWED_EXTENSIONS:
            raise FileNotFoundError(image_id)
        path = matches[0].resolve()
        if self.directory not in path.parents:
            raise FileNotFoundError(image_id)
        mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else f"image/{path.suffix[1:].lower()}"
        return path, mime
