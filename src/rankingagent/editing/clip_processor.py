from __future__ import annotations

import subprocess
from pathlib import Path

from rankingagent.editing.overlay import BOTTOM_BLUR_HEIGHT, BOTTOM_BLUR_Y, TOP_BLUR_HEIGHT

WIDTH, HEIGHT = 1080, 1920


def normalize_clip(input_path: Path, output_path: Path, duration: float = 3.5, start: float = 0.0) -> None:
    """Scale+crop a raw clip to fill 1080x1920 and trim it to `duration`
    seconds starting at `start` seconds (see extract_preview_frames — the
    fail/punchline isn't always at the very start of the raw clip), re-
    encoded so every segment shares identical codec params (required for
    the later stream-copy concat)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},setsar=1"
    )
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
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


def get_duration(input_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path),
        ],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def extract_preview_frames(input_path: Path, out_dir: Path, count: int = 6) -> list[dict]:
    """Sample `count` evenly-spaced frames across the clip's full duration,
    so a reviewer (the daily agent or a human) can see which part of the
    clip actually has the fail/punchline in it before picking a trim start
    — the moment often isn't at the very beginning of the raw clip."""
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = get_duration(input_path)

    frames = []
    for i in range(count):
        # skip the very first/last instants — often blank/transition frames
        t = duration * (i + 0.5) / count
        frame_path = out_dir / f"frame_{i}_{t:.1f}s.png"
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(t),
                "-i", str(input_path),
                "-frames:v", "1", "-q:v", "3",
                str(frame_path),
            ],
            check=True, capture_output=True,
        )
        frames.append({"time": round(t, 1), "path": str(frame_path)})

    return frames


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
