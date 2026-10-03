import io
import pathlib
import sys

from PIL import Image

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils import image_output  # noqa: E402
from open_webui.utils.image_output import (  # noqa: E402
    as_png_for_upstream,
    compact_generated_image,
)


def _noise_png(size=(900, 700), mode="RGB", alpha=None) -> bytes:
    # Random pixels: a PNG of a photo-like picture is large, like gpt-image's.
    import os

    w, h = size
    raw = os.urandom(w * h * 3)
    image = Image.frombytes("RGB", size, raw)
    if mode == "RGBA":
        image = image.convert("RGBA")
        if alpha is not None:
            image.putalpha(alpha)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _open(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_a_large_png_is_kept_as_a_much_smaller_webp():
    png = _noise_png()
    assert len(png) > image_output.MIN_BYTES
    data, mime = compact_generated_image(png, "image/png")
    assert mime == "image/webp"
    assert len(data) < len(png) * 0.8
    image = _open(data)
    assert image.format == "WEBP" and image.size == (900, 700) and image.mode == "RGB"


def test_real_transparency_survives_and_opaque_alpha_is_dropped():
    clear = Image.new("L", (900, 700), 0)
    data, mime = compact_generated_image(_noise_png(mode="RGBA", alpha=clear), "image/png")
    assert mime == "image/webp" and _open(data).mode == "RGBA"

    data, mime = compact_generated_image(_noise_png(mode="RGBA"), "image/png")
    assert mime == "image/webp" and _open(data).mode == "RGB"


def test_small_images_other_formats_and_bad_data_are_kept(monkeypatch):
    small = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(small, "PNG")
    assert compact_generated_image(small.getvalue(), "image/png") == (small.getvalue(), "image/png")

    big = _noise_png()
    assert compact_generated_image(big, "image/jpeg") == (big, "image/jpeg")
    junk = b"\x89PNG" + b"0" * image_output.MIN_BYTES
    assert compact_generated_image(junk, "image/png") == (junk, "image/png")

    monkeypatch.setenv("HALO_IMAGE_OUTPUT_WEBP", "0")
    assert compact_generated_image(big, "image/png") == (big, "image/png")


def test_a_stored_webp_goes_to_the_edit_endpoint_as_png():
    webp, _ = compact_generated_image(_noise_png(), "image/png")
    mime, data = as_png_for_upstream("image/webp", webp)
    assert mime == "image/png" and _open(data).format == "PNG"
    assert as_png_for_upstream("image/jpeg", b"x") == ("image/jpeg", b"x")
