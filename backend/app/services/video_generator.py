"""
EZ-NEXUS AI — In-House Video Ad Generator
Generates MP4 video ads from scripts using open-source tools only.
No third-party video APIs. No copyright issues.

Pipeline:
  1. Claude generates scenes from script
  2. Pillow renders each scene frame (background + text overlay)
  3. gTTS synthesizes AI voiceover per scene
  4. MoviePy assembles frames + audio into final MP4
"""

from __future__ import annotations
import os
import uuid
import textwrap
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Output directory ──────────────────────────────────────────────────────────
VIDEO_DIR = Path("generated_videos")
VIDEO_DIR.mkdir(exist_ok=True)

# ── Brand color palettes ──────────────────────────────────────────────────────
PALETTES = {
    "dark_blue":   {"bg": (10, 15, 40),    "accent": (56, 189, 248),  "text": (241, 245, 249)},
    "purple":      {"bg": (20, 10, 40),    "accent": (167, 139, 250), "text": (241, 245, 249)},
    "green":       {"bg": (5, 30, 20),     "accent": (34, 197, 94),   "text": (241, 245, 249)},
    "orange":      {"bg": (30, 15, 5),     "accent": (251, 146, 60),  "text": (241, 245, 249)},
    "red":         {"bg": (30, 5, 5),      "accent": (239, 68, 68),   "text": (241, 245, 249)},
    "corporate":   {"bg": (15, 23, 42),    "accent": (99, 102, 241),  "text": (241, 245, 249)},
}

W, H = 1280, 720  # 720p output


def _lazy_imports():
    """Import heavy libs lazily to avoid slow startup."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        from gtts import gTTS
        import moviepy.editor as mpy
        return Image, ImageDraw, ImageFont, gTTS, mpy
    except ImportError as e:
        raise RuntimeError(
            f"Video generation requires extra packages. Run: "
            f"pip install moviepy gTTS Pillow\n{e}"
        )


def _get_font(size: int, bold: bool = False):
    """Try to load a system font, fall back to default."""
    from PIL import ImageFont
    font_paths = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _render_scene_image(scene: dict, palette: dict, brand_name: str, scene_idx: int, total: int) -> Any:
    """Render a single scene as a PIL Image."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), palette["bg"])
    draw = ImageDraw.Draw(img)

    # Gradient-like overlay bars
    for i in range(0, H, 2):
        alpha = int(20 * (1 - abs(i - H // 2) / (H // 2)))
        r = min(255, palette["bg"][0] + alpha)
        g = min(255, palette["bg"][1] + alpha)
        b = min(255, palette["bg"][2] + alpha)
        draw.line([(0, i), (W, i)], fill=(r, g, b))

    # Accent bar at top
    draw.rectangle([(0, 0), (W, 6)], fill=palette["accent"])
    # Accent bar at bottom
    draw.rectangle([(0, H - 6), (W, H)], fill=palette["accent"])

    # Scene number indicator dots
    dot_total = total
    dot_spacing = 20
    dot_start = (W - dot_total * dot_spacing) // 2
    for i in range(dot_total):
        color = palette["accent"] if i == scene_idx else tuple(max(0, c - 100) for c in palette["accent"])
        cx = dot_start + i * dot_spacing + 5
        draw.ellipse([(cx - 5, H - 24), (cx + 5, H - 14)], fill=color)

    # Tag/label chip at top left
    tag = scene.get("tag", f"Scene {scene_idx + 1}")
    tag_font = _get_font(18, bold=True)
    draw.rectangle([(40, 30), (40 + len(tag) * 11 + 20, 58)], fill=palette["accent"])
    draw.text((50, 34), tag.upper(), font=tag_font, fill=(10, 10, 30))

    # Brand name top right
    brand_font = _get_font(22, bold=True)
    draw.text((W - 40, 34), brand_name, font=brand_font, fill=palette["accent"], anchor="ra")

    # Headline
    headline = scene.get("headline", "")
    h_font = _get_font(58, bold=True)
    wrapped = textwrap.wrap(headline, width=26)
    y_start = H // 2 - len(wrapped) * 35 - 20
    for line in wrapped:
        bbox = draw.textbbox((0, 0), line, font=h_font)
        lw = bbox[2] - bbox[0]
        draw.text(((W - lw) // 2, y_start), line, font=h_font, fill=palette["text"])
        y_start += 70

    # Subtext
    subtext = scene.get("subtext", "")
    if subtext:
        s_font = _get_font(28)
        wrapped_sub = textwrap.wrap(subtext, width=55)
        y_sub = y_start + 20
        for line in wrapped_sub:
            bbox = draw.textbbox((0, 0), line, font=s_font)
            lw = bbox[2] - bbox[0]
            draw.text(((W - lw) // 2, y_sub), line, font=s_font, fill=tuple(int(c * 0.75) for c in palette["text"]))
            y_sub += 38

    # CTA button for last scene
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


def _make_audio(text: str, tmp_dir: Path, idx: int) -> Path:
    """Generate MP3 voiceover for a scene using gTTS."""
    from gtts import gTTS
    audio_path = tmp_dir / f"audio_{idx}.mp3"
    try:
        tts = gTTS(text=text, lang="en", slow=False)
        tts.save(str(audio_path))
    except Exception as e:
        logger.warning("gTTS failed for scene %d: %s — using silence", idx, e)
        # Write silent audio fallback using moviepy
        import moviepy.editor as mpy
        silence = mpy.AudioClip(lambda t: 0, duration=3)
        silence.write_audiofile(str(audio_path), fps=22050, logger=None)
    return audio_path


async def generate_video_ad(
    scenes: list[dict],
    brand_name: str,
    palette_name: str = "dark_blue",
    job_id: str | None = None,
) -> dict:
    """
    Main entry point. Returns dict with video_id and file path.

    scenes: list of dicts with keys:
      - tag: short label (e.g. "Hook", "Problem", "Solution", "CTA")
      - headline: main text (short, punchy)
      - subtext: supporting text
      - narration: spoken voiceover for this scene
      - duration: seconds (default 4)
      - is_cta: bool (show CTA button)
      - cta_text: CTA button text
    """
    Image, ImageDraw, ImageFont, gTTS, mpy = _lazy_imports()

    video_id = job_id or str(uuid.uuid4())[:12]
    tmp_dir = VIDEO_DIR / f"tmp_{video_id}"
    tmp_dir.mkdir(exist_ok=True)
    palette = PALETTES.get(palette_name, PALETTES["dark_blue"])

    try:
        clips = []
        for i, scene in enumerate(scenes):
            duration = float(scene.get("duration", 4))

            # 1. Render scene image
            img = _render_scene_image(scene, palette, brand_name, i, len(scenes))
            img_path = tmp_dir / f"scene_{i}.png"
            img.save(str(img_path))

            # 2. Generate voiceover
            narration = scene.get("narration", scene.get("headline", ""))
            audio_path = _make_audio(narration, tmp_dir, i)

            # 3. Create video clip from image
            img_clip = mpy.ImageClip(str(img_path))

            # Use audio duration if it fits, else use scene duration
            try:
                audio_clip = mpy.AudioFileClip(str(audio_path))
                clip_duration = max(duration, audio_clip.duration + 0.5)
                img_clip = img_clip.set_duration(clip_duration)
                audio_clip = audio_clip.set_start(0)
                final_clip = img_clip.set_audio(audio_clip)
            except Exception:
                img_clip = img_clip.set_duration(duration)
                final_clip = img_clip

            # 4. Fade in/out
            final_clip = final_clip.fadein(0.4).fadeout(0.3)
            clips.append(final_clip)

        # 5. Concatenate all scenes
        video = mpy.concatenate_videoclips(clips, method="compose")

        # 6. Write final MP4
        out_path = VIDEO_DIR / f"{video_id}.mp4"
        video.write_videofile(
            str(out_path),
            fps=24,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=str(tmp_dir / "temp_audio.m4a"),
            remove_temp=True,
            logger=None,
        )

        # Clean up tmp
        import shutil
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
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(f"Video generation failed: {e}")
