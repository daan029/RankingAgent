from __future__ import annotations

import subprocess
from pathlib import Path

from rankingagent.editing.clip_processor import normalize_clip, overlay_frame_on_clip
from rankingagent.editing.overlay import render_overlay_frame

CLIP_DURATION_SECONDS = 7.0  # fallback for clips with no detected/explicit duration


def render_video(
    title_text: str,
    ranked_clips: list[dict],
    reactions: dict[str, str],
    work_dir: Path,
    output_path: Path,
    clip_starts: dict[str, float] | None = None,
    clip_durations: dict[str, float] | None = None,
    clip_vertical_focus: dict[str, float] | None = None,
    clip_manual_vf: dict[str, str] | None = None,
    clip_captions: dict[str, str] | None = None,
    force_opening_music: bool = True,
) -> Path:
    """Build the full ranking video: normalize + overlay each clip in reveal
    order (sidebar accumulates revealed reactions as it goes, #1/climax
    always last), then concat the segments. `ranked_clips` rows must already
    carry `rank` and `reveal_index` (set by ranking.scorer.select_and_rank).
    `clip_starts` maps clip id -> trim start offset in seconds (from
    editing.clip_processor.extract_preview_frames review, or Gemini highlight
    detection); defaults to 0 for any clip not present. `clip_durations` maps
    clip id -> how long that clip's segment should run — clips vary (a quick
    impact vs. a longer confrontation), so this is no longer a single fixed
    length; falls back to CLIP_DURATION_SECONDS for any clip not present.
    `clip_vertical_focus` maps clip id -> where the main subject sits
    vertically in frame (0.0=top..1.0=bottom, from Gemini) so the crop can
    avoid hiding it behind the top/bottom blur bands; defaults to 0.5
    (centered — the previous fixed-crop behavior) for any clip not present.
    `clip_captions` maps clip id -> a short factual caption shown only
    during that clip's own segment (2026-08-19 user request), e.g. "Girl
    meets surgeon who saved her life 3 years ago" — not shown on the climax
    segment, which uses the subscribe CTA instead. `force_opening_music`
    (default True, the original behavior) can be set False per-theme when
    ducking a music bed under the opening clip's own audio feels tonally
    wrong for that theme's content (2026-08-19 — a real rescue's ambient
    sound read as undercut by a cheerful bed, unlike comedic fail content)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    clip_starts = clip_starts or {}
    clip_durations = clip_durations or {}
    clip_vertical_focus = clip_vertical_focus or {}
    clip_manual_vf = clip_manual_vf or {}
    clip_captions = clip_captions or {}

    for clip in ranked_clips:
        clip["reaction"] = reactions.get(clip["id"], "")

    ordered = sorted(ranked_clips, key=lambda c: c["reveal_index"])

    segment_paths: list[Path] = []
    for idx, clip in enumerate(ordered):
        normalized = work_dir / f"norm_{idx}.mp4"
        start = clip_starts.get(clip["id"], 0.0)
        duration = clip_durations.get(clip["id"], CLIP_DURATION_SECONDS)
        vertical_focus = clip_vertical_focus.get(clip["id"], 0.5)
        # Viewers reliably report the opening segment as silent even when it
        # technically isn't (YouTube Shorts autoplay-mute catches them before
        # they've tapped to unmute) — force a quiet music bed under clip 0
        # regardless of has_audio_stream, so the open never reads as silent.
        # Themes can opt out via force_opening_music=False.
        normalize_clip(
            Path(clip["local_path"]), normalized, duration=duration, start=start,
            force_music_bed=(idx == 0 and force_opening_music), vertical_focus=vertical_focus,
            manual_vf=clip_manual_vf.get(clip["id"]),
        )

        overlay_img = work_dir / f"overlay_{idx}.png"
        frame = render_overlay_frame(
            title_text, ranked_clips, revealed_count=idx + 1, current_caption=clip_captions.get(clip["id"])
        )
        frame.save(overlay_img)

        segment = work_dir / f"segment_{idx}.mp4"
        overlay_frame_on_clip(normalized, overlay_img, segment)
        segment_paths.append(segment)

    concat_list = work_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in segment_paths),
        encoding="utf-8",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        # Re-encode rather than stream-copy: segments are each encoded in a
        # separate ffmpeg invocation, and even with matched settings minor
        # inconsistencies (container timestamps, etc.) can produce a
        # concat-copied file some players refuse to open. Re-encoding here
        # guarantees one consistent, clean output stream.
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    return output_path
