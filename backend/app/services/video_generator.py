"""
EZ-NEXUS AI — In-House Video Ad Generator
Generates MP4 video ads using Pillow + gTTS + FFmpeg (via imageio-ffmpeg).
No MoviePy dependency. No third-party video APIs.

Pipeline:
  1. Pillow renders each scene as a 1280x720 PNG frame
  2. gTTS synthesizes AI voiceover per scene
  3. FFmpeg (bundled by imageio-ffmpeg) muxes frames + audio per scene
  4. FFmpeg concatenates all scene clips into final MP4
"""

from __future__ import annotations
import os
import uuid
import textwrap
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VIDEO_DIR = Path("generated_videos")
VIDEO_DIR.mkdir(exist_ok=True)

PALETTES = {
    "dark_blue":  {"bg": (10, 15, 40),   "accent": (56, 189, 248),  "text": (241, 245, 249)},
    "purple":     {"bg": (20, 10, 40),   "accent": (167, 139, 250), "text": (241, 245, 249)},
    "green":      {"bg": (5, 30, 20),    "accent": (34, 197, 94),   "text": (241, 245, 249)},
    "orange":     {"bg": (30, 15, 5),    "accent": (251, 146, 60),  "text": (241, 245, 249)},
    "red":        {"bg": (30, 5, 5),     "accent": (239, 68, 68),   "text": (241, 245, 249)},
    "corporate":  {"bg": (15, 23, 42),   "accent": (99, 102, 241),  "text": (241, 245, 249)},
}

W, H = 1280, 720


def _get_ffmpeg() -> str:
    """Return path to FFmpeg binary — prefer imageio-ffmpeg bundle, fall back to system."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    for candidate in ("ffmpeg", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if shutil.which(candidate) or os.path.exists(candidate):
            return candidate
    raise RuntimeError("FFmpeg not found. Install imageio-ffmpeg: pip install imageio-ffmpeg")


def _get_font(size: int, bold: bool = False):
    from PIL import ImageFont
    candidates = [
        ("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ("/System/Library/Fonts/Helvetica.ttc"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _render_scene(scene: dict, palette: dict, brand_name: str, idx: int, total: int) -> Any:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), palette["bg"])
    draw = ImageDraw.Draw(img)

    # Soft gradient overlay
    for i in range(0, H, 2):
        alpha = int(20 * (1 - abs(i - H // 2) / (H // 2)))
        r = min(255, palette["bg"][0] + alpha)
        g = min(255, palette["bg"][1] + alpha)
        b = min(255, palette["bg"][2] + alpha)
        draw.line([(0, i), (W, i)], fill=(r, g, b))

    # Accent bars
    draw.rectangle([(0, 0), (W, 6)], fill=palette["accent"])
    draw.rectangle([(0, H - 6), (W, H)], fill=palette["accent"])

    # Scene dots
    dot_spacing = 20
    dot_start = (W - total * dot_spacing) // 2
    for i in range(total):
        color = palette["accent"] if i == idx else tuple(max(0, c - 100) for c in palette["accent"])
        cx = dot_start + i * dot_spacing + 5
        draw.ellipse([(cx - 5, H - 24), (cx + 5, H - 14)], fill=color)

    # Tag chip
    tag = scene.get("tag", f"Scene {idx + 1}")
    tag_font = _get_font(18, bold=True)
    draw.rectangle([(40, 30), (40 + len(tag) * 11 + 20, 58)], fill=palette["accent"])
    draw.text((50, 34), tag.upper(), font=tag_font, fill=(10, 10, 30))

    # Brand name
    brand_font = _get_font(22, bold=True)
    draw.text((W - 40, 34), brand_name, font=brand_font, fill=palette["accent"], anchor="ra")

    # Headline
    headline = scene.get("headline", "")
    h_font = _get_font(58, bold=True)
    wrapped = textwrap.wrap(headline, width=26)
    y = H // 2 - len(wrapped) * 35 - 20
    for line in wrapped:
        bbox = draw.textbbox((0, 0), line, font=h_font)
        lw = bbox[2] - bbox[0]
        draw.text(((W - lw) // 2, y), line, font=h_font, fill=palette["text"])
        y += 70

    # Subtext
    subtext = scene.get("subtext", "")
    if subtext:
        s_font = _get_font(28)
        wrapped_sub = textwrap.wrap(subtext, width=55)
        y_sub = y + 20
        for line in wrapped_sub:
            bbox = draw.textbbox((0, 0), line, font=s_font)
            lw = bbox[2] - bbox[0]
            draw.text(((W - lw) // 2, y_sub), line, font=s_font,
                      fill=tuple(int(c * 0.75) for c in palette["text"]))
            y_sub += 38

    # CTA button on last scene
    if scene.get("is_cta"):
        cta = scene.get("cta_text", "Learn More")
        btn_font = _get_font(26, bold=True)
        bbox = draw.textbbox((0, 0), cta, font=btn_font)
        bw = bbox[2] - bbox[0] + 60
        bx = (W - bw) // 2
        by = H - 120
        draw.rounded_rectangle([(bx, by), (bx + bw, by + 50)], radius=25, fill=palette["accent"])
        draw.text((bx + 30, by + 12), cta, font=btn_font, fill=(10, 10, 30))

    return img


def _make_audio(text: str, path: Path) -> bool:
    """Generate MP3 voiceover. Returns True on success."""
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang="en", slow=False)
        tts.save(str(path))
        return path.exists() and path.stat().st_size > 0
    except Exception as e:
        logger.warning("gTTS failed: %s", e)
        return False


def _ffmpeg_scene(ffmpeg: str, img_path: Path, audio_path: Path | None, duration: float, out_path: Path):
    """Create a single scene MP4 from a still image + optional audio."""
    cmd: list[str]
    if audio_path and audio_path.exists() and audio_path.stat().st_size > 0:
        cmd = [
            ffmpeg, "-y",
            "-loop", "1", "-i", str(img_path),
            "-i", str(audio_path),
            "-c:v", "libx264", "-tune", "stillimage", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            "-vf", "scale=1280:720",
            str(out_path),
        ]
    else:
        cmd = [
            ffmpeg, "-y",
            "-loop", "1", "-i", str(img_path),
            "-c:v", "libx264", "-tune", "stillimage", "-preset", "ultrafast",
            "-t", str(duration),
            "-vf", "scale=1280:720",
            "-an",
            str(out_path),
        ]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg scene failed: {result.stderr.decode()[:500]}")


def _ffmpeg_concat(ffmpeg: str, scene_paths: list[Path], out_path: Path):
    """Concatenate scene MP4s into final video."""
    concat_file = out_path.parent / "concat.txt"
    with open(concat_file, "w") as f:
        for p in scene_paths:
            f.write(f"file '{p.resolve()}'\n")
    cmd = [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    concat_file.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg concat failed: {result.stderr.decode()[:500]}")


def generate_video_ad(
    scenes: list[dict],
    brand_name: str,
    palette_name: str = "dark_blue",
    job_id: str | None = None,
) -> dict:
    """
    Synchronous entry point. Call from async via asyncio.to_thread().

    scenes: list of dicts — tag, headline, subtext, narration, duration, is_cta, cta_text
    Returns: {video_id, file_path, file_name, scenes, status}
    """
    ffmpeg = _get_ffmpeg()
    video_id = job_id or str(uuid.uuid4())[:12]
    tmp_dir = VIDEO_DIR / f"tmp_{video_id}"
    tmp_dir.mkdir(exist_ok=True)
    palette = PALETTES.get(palette_name, PALETTES["dark_blue"])

    try:
        scene_videos: list[Path] = []

        for i, scene in enumerate(scenes):
            duration = float(scene.get("duration", 4))

            # 1. Render frame
            img = _render_scene(scene, palette, brand_name, i, len(scenes))
            img_path = tmp_dir / f"scene_{i}.png"
            img.save(str(img_path))

            # 2. Voiceover
            audio_path = tmp_dir / f"audio_{i}.mp3"
            narration = scene.get("narration", scene.get("headline", ""))
            has_audio = _make_audio(narration, audio_path)

            # 3. Encode scene clip
            scene_out = tmp_dir / f"scene_{i}.mp4"
            _ffmpeg_scene(
                ffmpeg, img_path,
                audio_path if has_audio else None,
                duration, scene_out
            )
            scene_videos.append(scene_out)

        # 4. Concatenate
        out_path = VIDEO_DIR / f"{video_id}.mp4"
        _ffmpeg_concat(ffmpeg, scene_videos, out_path)

        shutil.rmtree(tmp_dir, ignore_errors=True)
        return {
            "video_id": video_id,
            "file_path": str(out_path),
            "file_name": f"{video_id}.mp4",
            "scenes": len(scenes),
            "status": "ready",
        }

    except Exception as e:
        logger.error("Video generation failed: %s", e)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(f"Video generation failed: {e}")
