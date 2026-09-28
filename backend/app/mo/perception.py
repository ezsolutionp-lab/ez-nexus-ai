"""
MO NEXUS OMEGA — image analysis (classical computer vision, not object recognition).

What this does: validates an image safely, then measures it — format, size, brightness, contrast, sharpness (variance of
the Laplacian), dominant colours, whether it is blank — and reads printed text with Tesseract OCR when that binary is
installed. What it does NOT do: detect or name objects, faces or scenes; that needs a vision model MO does not bundle.
Text read from an image is untrusted and is screened for prompt-injection markers.
"""

from __future__ import annotations

import base64
import binascii
import io
import shutil
from typing import Any

from .errors import MoResult, ResultState
from .guards import injection

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
FORMATS = {"PNG", "JPEG", "GIF", "WEBP", "BMP"}


def ocr_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
        return True
    except ImportError:
        return False


def analyze(image_b64: Any, *, ocr: bool = True) -> MoResult:
    from PIL import Image, ImageStat, UnidentifiedImageError
    if not isinstance(image_b64, str) or not image_b64:
        return MoResult(ResultState.FAILED, "image_b64 is required.")
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        return MoResult(ResultState.FAILED, "image_b64 is not valid base64.")
    if len(raw) > MAX_BYTES:
        return MoResult(ResultState.FAILED, f"Images are limited to {MAX_BYTES // (1024 * 1024)} MB.")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS                          # Pillow raises on decompression bombs past 2x this
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt, size = probe.format, probe.size
            if fmt not in FORMATS:
                return MoResult(ResultState.FAILED, f"Format {fmt} is not supported (use {', '.join(sorted(FORMATS))}).")
            if size[0] * size[1] > MAX_PIXELS:
                return MoResult(ResultState.FAILED, "The image has too many pixels.")
            img = probe.convert("RGBA" if "A" in probe.getbands() else "RGB")
            img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return MoResult(ResultState.FAILED, "That is not a readable image.")
    rgb = img.convert("RGB")
    gray = rgb.convert("L")
    stat = ImageStat.Stat(gray)
    import numpy as np
    thumb = gray.copy()
    thumb.thumbnail((512, 512))
    a = np.asarray(thumb, dtype=np.float64)
    sharp = float(np.var(4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:])) if min(a.shape) >= 3 else 0.0
    palette = rgb.copy()
    palette.thumbnail((128, 128))
    quant = palette.quantize(colors=5).convert("RGB")
    counts = sorted(quant.getcolors(maxcolors=256) or [], reverse=True)
    total = sum(c for c, _ in counts) or 1
    data: dict[str, Any] = {
        "format": fmt, "width": size[0], "height": size[1], "megapixels": round(size[0] * size[1] / 1e6, 3),
        "has_alpha": img.mode == "RGBA", "brightness": round(stat.mean[0], 1), "contrast": round(stat.stddev[0], 1),
        "sharpness": round(sharp, 1), "looks_blurry": sharp < 100 and stat.stddev[0] > 5,        # common variance-of-Laplacian rule of thumb; uncalibrated
        "looks_blank": stat.stddev[0] < 2.0,
        "dominant_colors": [{"hex": "#%02x%02x%02x" % rgb_, "share": round(c / total, 3)} for c, rgb_ in counts[:5]],
        "analysis": "classical image statistics (not object recognition)",
    }
    if ocr:
        if not ocr_available():
            data["ocr"] = {"available": False, "reason": "the tesseract binary or pytesseract is not installed"}
        else:
            import pytesseract
            try:
                text = pytesseract.image_to_string(gray).strip()[:20_000]
            except Exception as exc:                            # tesseract failures are reported, never hidden
                return MoResult(ResultState.PARTIAL, f"Image measured, but OCR failed: {type(exc).__name__}", data=data)
            verdict = injection.screen(text)
            data["ocr"] = {"available": True, "text": text, "characters": len(text),
                           "injection_screen": verdict.verdict, "injection_signals": verdict.signals}
    return MoResult.ok(data, untrusted=bool(ocr and data.get("ocr", {}).get("text")))
