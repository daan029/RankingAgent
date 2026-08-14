from __future__ import annotations

import subprocess
from pathlib import Path

from rankingagent.editing.overlay import BOTTOM_BLUR_HEIGHT, BOTTOM_BLUR_Y, TOP_BLUR_HEIGHT

WIDTH, HEIGHT = 1080, 1920


def normalize_clip(input_path: Path, output_path: Path, duration: float = 3.5) -> None:
    """Scale+crop a raw clip to fill 1080x1920 and trim it to `duration`
    seconds, re-encoded so every segment shares identical codec params
    (required for the later stream-copy concat)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},setsar=1"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-t", str(duration),
        "-vf", vf,
        "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def overlay_frame_on_clip(clip_path: Path, overlay_png: Path, output_path: Path) -> None:
    """Blur the top band (behind the title) and bottom band (just above the
    watermark, where YouTube Shorts' own UI sits) of the clip itself, then
    burn the static transparent text/watermark PNG on top. The blur bands'
    y-coordinates come from editing.overlay so the blur and the text overlay
    always agree on where they sit."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = (
        f"[0:v]split=3[base][topsrc][botsrc];"
        f"[topsrc]crop={WIDTH}:{TOP_BLUR_HEIGHT}:0:0,gblur=sigma=20[topblur];"
        f"[botsrc]crop={WIDTH}:{BOTTOM_BLUR_HEIGHT}:0:{BOTTOM_BLUR_Y},gblur=sigma=20[botblur];"
        f"[base][topblur]overlay=0:0[step1];"
        f"[step1][botblur]overlay=0:{BOTTOM_BLUR_Y}[step2];"
        f"[step2][1:v]overlay=0:0:format=auto[outv]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_path),
        "-i", str(overlay_png),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
