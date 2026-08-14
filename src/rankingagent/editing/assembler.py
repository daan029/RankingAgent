from __future__ import annotations

import subprocess
from pathlib import Path

from rankingagent.editing.clip_processor import normalize_clip, overlay_frame_on_clip
from rankingagent.editing.overlay import render_overlay_frame

CLIP_DURATION_SECONDS = 3.5


def render_video(
    theme_label: str,
    ranked_clips: list[dict],
    reactions: dict[str, str],
    work_dir: Path,
    output_path: Path,
) -> Path:
    """Build the full ranking video: normalize + overlay each clip in reveal
    order (sidebar accumulates revealed reactions as it goes, #1/climax
    always last), then concat the segments. `ranked_clips` rows must already
    carry `rank` and `reveal_index` (set by ranking.scorer.select_and_rank)."""
    work_dir.mkdir(parents=True, exist_ok=True)

    for clip in ranked_clips:
        clip["reaction"] = reactions.get(clip["id"], "")

    ordered = sorted(ranked_clips, key=lambda c: c["reveal_index"])

    segment_paths: list[Path] = []
    for idx, clip in enumerate(ordered):
        normalized = work_dir / f"norm_{idx}.mp4"
        normalize_clip(Path(clip["local_path"]), normalized, duration=CLIP_DURATION_SECONDS)

        overlay_img = work_dir / f"overlay_{idx}.png"
        frame = render_overlay_frame(theme_label, ranked_clips, revealed_count=idx + 1)
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
