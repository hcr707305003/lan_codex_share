import base64
from io import BytesIO

from PIL import Image
import pytest

from lan_codex_share.lan_store import ImageStore, ImageValidationError


def image_payload(fmt="PNG", name="sample.png", mime="image/png"):
    stream = BytesIO()
    Image.new("RGB", (2, 2), "red").save(stream, format=fmt)
    return {"name": name, "mime": mime, "data": base64.b64encode(stream.getvalue()).decode("ascii")}


def test_image_store_accepts_real_images(tmp_path):
    store = ImageStore(tmp_path / "uploads", max_bytes=1024 * 1024, max_images=4)
    saved = store.save_many([image_payload()])

    assert len(saved) == 1
    assert saved[0]["mime"] == "image/png"
    resolved, mime = store.resolve(saved[0]["id"])
    assert resolved.is_file()
    assert mime == "image/png"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "fake.png", "mime": "image/png", "data": base64.b64encode(b"not image").decode("ascii")},
        image_payload(name="../sample.png"),
        image_payload(name="sample.gif"),
        image_payload(mime="image/jpeg"),
    ],
)
def test_image_store_rejects_invalid_payload(tmp_path, payload):
    store = ImageStore(tmp_path / "uploads", max_bytes=1024 * 1024, max_images=4)
    with pytest.raises(ImageValidationError):
        store.save_many([payload])


def test_image_store_rejects_count_and_size(tmp_path):
    store = ImageStore(tmp_path / "uploads", max_bytes=5, max_images=1)
    with pytest.raises(ImageValidationError):
        store.save_many([image_payload(), image_payload()])
    with pytest.raises(ImageValidationError):
        store.save_many([image_payload()])
