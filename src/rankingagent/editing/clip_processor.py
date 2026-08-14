from __future__ import annotations

import subprocess
from pathlib import Path

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
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def overlay_frame_on_clip(clip_path: Path, overlay_png: Path, output_path: Path) -> None:
    """Burn a static transparent PNG overlay onto a clip for its full duration."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_path),
        "-i", str(overlay_png),
        "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[outv]",
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
