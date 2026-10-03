"""Generated images are kept as WebP.

gpt-image answers with 2-4 MB PNGs; a chat full of them loads slowly on a
phone. Every generated image is stored through ``routers/images.upload_image``,
which passes it here first: a large PNG is re-encoded as WebP at quality 90
(no visible difference, about a sixth of the size), keeping the alpha channel
when the picture has real transparency. Anything else -- small images, JPEG,
animations, data Pillow cannot read, or a WebP that would not be clearly
smaller -- is kept as it came. ``HALO_IMAGE_OUTPUT_WEBP=0`` turns it off.

Edits go the other way (``as_png_for_upstream``): the edit endpoint gets a PNG
as before, whatever format the stored image is in.
"""

import io
import logging
import os

from PIL import Image

log = logging.getLogger(__name__)

WEBP_QUALITY = 90
MIN_BYTES = 512 * 1024
# Keep the PNG unless the WebP saves at least this share of the bytes.
MIN_SAVING = 0.2


def _enabled() -> bool:
    return os.environ.get("HALO_IMAGE_OUTPUT_WEBP", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _has_transparency(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA"):
        return image.getchannel("A").getextrema()[0] < 255
    if image.mode == "P" and "transparency" in image.info:
        return image.convert("RGBA").getchannel("A").getextrema()[0] < 255
    return False


def compact_generated_image(data: bytes, content_type: str) -> tuple[bytes, str]:
    """``(data, content_type)`` to store for a generated image."""
    if not _enabled() or not data or len(data) < MIN_BYTES:
        return data, content_type
    if str(content_type or "").split(";")[0].strip().lower() != "image/png":
        return data, content_type
    try:
        with Image.open(io.BytesIO(data)) as image:
            if getattr(image, "is_animated", False):
                return data, content_type
            image.load()
            mode = "RGBA" if _has_transparency(image) else "RGB"
            out = io.BytesIO()
            options = {"quality": WEBP_QUALITY, "method": 4}
            if image.info.get("icc_profile"):
                options["icc_profile"] = image.info["icc_profile"]
            image.convert(mode).save(out, "WEBP", **options)
    except Exception as e:  # noqa: BLE001 -- the PNG is still a fine answer
        log.warning("generated image kept as PNG: %s", e)
        return data, content_type
    webp = out.getvalue()
    if len(webp) > len(data) * (1 - MIN_SAVING):
        return data, content_type
    log.info("generated_image_webp png_bytes=%s webp_bytes=%s", len(data), len(webp))
    return webp, "image/webp"


def as_png_for_upstream(mime: str, data: bytes) -> tuple[str, bytes]:
    """A stored WebP goes to the edit endpoint as PNG; anything else unchanged."""
    if str(mime or "").split(";")[0].strip().lower() != "image/webp":
        return mime, data
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            mode = "RGBA" if _has_transparency(image) else "RGB"
            out = io.BytesIO()
            image.convert(mode).save(out, "PNG")
            return "image/png", out.getvalue()
    except Exception as e:  # noqa: BLE001 -- let the upstream judge the WebP
        log.warning("edit input sent as WebP: %s", e)
        return mime, data
