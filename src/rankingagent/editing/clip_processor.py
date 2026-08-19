from __future__ import annotations

import subprocess
from pathlib import Path

from rankingagent.config import ROOT_DIR
from rankingagent.editing.overlay import BOTTOM_BLUR_HEIGHT, BOTTOM_BLUR_Y, TOP_BLUR_HEIGHT

WIDTH, HEIGHT = 1080, 1920

FALLBACK_MUSIC_PATH = ROOT_DIR / "assets" / "music" / "piano.mp3"

# Segments are cut at arbitrary points in the source audio waveform (not at
# a zero-crossing), so the raw sample jump at a concat boundary is audible
# as a "pop"/"click". A short in/out fade per segment forces the waveform to
# near-zero at both edges, which removes the click without being audible as
# an actual fade at this length.
AUDIO_EDGE_FADE_SECONDS = 0.05


def has_audio_stream(input_path: Path) -> bool:
    """Whether the clip has at least one audio stream at all — distinct from
    silence within an existing stream. Reddit clips that fail this are rare
    but real (e.g. muted/gif-sourced uploads); render falls back to
    FALLBACK_MUSIC_PATH for these (see normalize_clip)."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(input_path),
        ],
        check=True, capture_output=True, text=True,
    )
    return bool(result.stdout.strip())


def _audio_edge_fade_filter(input_path: Path, start: float, duration: float) -> str:
    """Short fade-in/fade-out afade filter string sized to the segment's
    actual output duration (source clip may be shorter than `duration` once
    `start` is applied, in which case a fade-out anchored to the requested
    `duration` would land past the end of the audio and never fire)."""
    available = max(get_duration(input_path) - start, 0.0)
    effective_duration = min(duration, available) if available > 0 else duration
    fade_out_start = max(effective_duration - AUDIO_EDGE_FADE_SECONDS, 0.0)
    return (
        f"afade=t=in:st=0:d={AUDIO_EDGE_FADE_SECONDS},"
        f"afade=t=out:st={fade_out_start}:d={AUDIO_EDGE_FADE_SECONDS}"
    )


def get_dimensions(input_path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            str(input_path),
        ],
        check=True, capture_output=True, text=True,
    )
    width_str, height_str = result.stdout.strip().split("x")
    return int(width_str), int(height_str)


# Target the midpoint of the "safe" vertical band between the two blurred
# bands (not the raw frame center — TOP_BLUR_HEIGHT and BOTTOM_BLUR_HEIGHT
# aren't equal, so those aren't the same point) when shifting the crop
# toward a detected subject position.
_SAFE_ZONE_CENTER_Y = (TOP_BLUR_HEIGHT + (HEIGHT - BOTTOM_BLUR_HEIGHT)) / 2


def _crop_filter(input_path: Path, vertical_focus: float) -> str:
    """Named-parameter crop so an omitted x still defaults to ffmpeg's own
    centered expression — only y is ever overridden here. `vertical_focus`
    (0.0=top..1.0=bottom of the *source* frame, from Gemini) shifts the crop
    window so that point lands at the safe-zone center in the 1080x1920
    output instead of the previous blind center-crop, which could put the
    subject behind the top/bottom blurred bands for an off-center source
    framing (2026-08-19 user request). Exactly 0.5 (the default used when no
    real detection is available — see editing.highlight.DEFAULT_VERTICAL_
    FOCUS) is treated as "no signal" and falls back to the original centered
    crop untouched, so renders without a real subject-position reading don't
    change behavior."""
    if vertical_focus == 0.5:
        return f"crop=w={WIDTH}:h={HEIGHT}"
    try:
        src_w, src_h = get_dimensions(input_path)
    except Exception:
        return f"crop=w={WIDTH}:h={HEIGHT}"

    scale = max(WIDTH / src_w, HEIGHT / src_h)
    scaled_h = src_h * scale
    excess_h = scaled_h - HEIGHT
    if excess_h <= 1:
        # Source is already narrow enough (or narrower) that height isn't
        # cropped at all — no room to shift, vertical_focus is moot here.
        return f"crop=w={WIDTH}:h={HEIGHT}"

    offset_y = vertical_focus * scaled_h - _SAFE_ZONE_CENTER_Y
    offset_y = max(0.0, min(excess_h, offset_y))
    return f"crop=w={WIDTH}:h={HEIGHT}:y={int(round(offset_y))}"


def normalize_clip(
    input_path: Path,
    output_path: Path,
    duration: float = 3.5,
    start: float = 0.0,
    force_music_bed: bool = False,
    vertical_focus: float = 0.5,
    manual_vf: str | None = None,
) -> None:
    """Scale+crop a raw clip to fill 1080x1920 and trim it to `duration`
    seconds starting at `start` seconds (see extract_preview_frames — the
    fail/punchline isn't always at the very start of the raw clip), re-
    encoded so every segment shares identical codec params (required for
    the later stream-copy concat). If the source clip has no audio stream at
    all, FALLBACK_MUSIC_PATH (piano.mp3) is mixed in as the segment's sole
    audio instead of leaving it silent — see ranking.scorer.select_and_rank
    for the matching rule that caps this at one clip per rendered video.
    `force_music_bed=True` (used by assembler.render_video for the opening
    segment, since viewers reliably perceive that one as silent even when it
    technically isn't — likely YouTube Shorts autoplay-mute) ducks the same
    fallback track in *underneath* the clip's own audio via amix, rather
    than replacing it, so a real-but-quiet/short audio stream still gets a
    music bed without losing the source sound. Every segment's audio gets a
    short edge fade (AUDIO_EDGE_FADE_SECONDS) so the later concat doesn't
    produce an audible click at each cut. `vertical_focus` (0.0=top..
    1.0=bottom, from Gemini via editing.highlight.find_highlight_window)
    shifts the crop toward the detected subject position instead of always
    center-cropping — see _crop_filter."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if manual_vf is not None:
        # Full manual override of the scale+crop filter chain — for a
        # one-off case _crop_filter's automatic logic can't handle, e.g. a
        # source clip whose scaled dimensions exactly match WIDTHxHEIGHT
        # (no crop slack at all) but still needs to be shifted, which
        # requires zooming in past the normal fill-scale first
        # (2026-08-19 user request).
        vf = manual_vf
    else:
        crop = _crop_filter(input_path, vertical_focus)
        vf = (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"{crop},setsar=1"
        )
    af = _audio_edge_fade_filter(input_path, start, duration)
    audio_present = has_audio_stream(input_path)

    if audio_present and not force_music_bed:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(input_path),
            "-t", str(duration),
            "-vf", vf,
            "-af", af,
            "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            str(output_path),
        ]
    elif not audio_present:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(input_path),
            "-stream_loop", "-1", "-i", str(FALLBACK_MUSIC_PATH),
            "-t", str(duration),
            "-vf", vf,
            "-af", af,
            "-r", "30",
            "-map", "0:v",
            "-map", "1:a",
            "-shortest",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        # audio_present and force_music_bed: mix the clip's real audio with
        # a quiet, looped copy of FALLBACK_MUSIC_PATH underneath it.
        music_fade_out_start = max(duration - AUDIO_EDGE_FADE_SECONDS, 0.0)
        music_af = (
            f"afade=t=in:st=0:d={AUDIO_EDGE_FADE_SECONDS},"
            f"afade=t=out:st={music_fade_out_start}:d={AUDIO_EDGE_FADE_SECONDS}"
        )
        filter_complex = (
            f"[0:a]{af}[a0];"
            f"[1:a]volume=0.45,{music_af}[a1];"
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(input_path),
            "-stream_loop", "-1", "-i", str(FALLBACK_MUSIC_PATH),
            "-t", str(duration),
            "-vf", vf,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
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
