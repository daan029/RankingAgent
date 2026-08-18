from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from google import genai

logger = logging.getLogger(__name__)

PROMPT = (
    "This is a short clip from a viral 'fails/chaos' video (a fail, an "
    "argument/confrontation, a sports mistake, or similar). Identify the "
    "full highlight window: from just before the main event/punchline "
    "starts (the fall, the impact, the confrontation peak, the mistake "
    "itself) through to when it's clearly resolved — include enough of the "
    "immediate reaction/aftermath that a viewer who only sees this window "
    "understands what happened, but exclude unrelated buildup earlier in "
    "the clip. "
    "Respond with ONLY two timestamps in MM:SS format separated by a dash, "
    "e.g. '00:12-00:19', for when that window starts and ends. No other "
    "text."
)

TIMESTAMP_RE = re.compile(r"(\d{1,2}):(\d{2})")

# Gemini's timestamp is an estimate, not frame-accurate — these buffers
# absorb a few seconds of error on either side so a slightly-early/late
# reading still keeps the actual moment inside the extracted window
# (confirmed real issue: clips regularly landed on "nothing happens" with a
# tight fixed-length cut around a single estimated instant).
LEAD_IN_SECONDS = 2.5
LEAD_OUT_SECONDS = 2.0
MIN_CLIP_DURATION = 6.0
MAX_CLIP_DURATION = 15.0
FALLBACK_SINGLE_TIMESTAMP_DURATION = 9.0


def _parse_window(text: str) -> tuple[float, float] | None:
    matches = TIMESTAMP_RE.findall(text)
    if not matches:
        return None
    timestamps = [int(m) * 60 + int(s) for m, s in matches]
    if len(timestamps) == 1:
        start = timestamps[0]
        return start, start + FALLBACK_SINGLE_TIMESTAMP_DURATION
    return timestamps[0], timestamps[1]


def find_highlight_window(
    video_path: Path, api_key: str, model: str = "gemini-3.6-flash"
) -> tuple[float, float] | None:
    """Ask Gemini for the highlight window (start, end) in a raw clip, so
    `render` can trim from the right point for however long the moment
    actually needs — not a fixed-length guess. A single stale-buildup or
    tight fixed-length cut was regularly missing the actual event (see the
    reddit-api-blocker / gate-clip case and the 2026-08-18 "nothing happens"
    feedback), so this both widens the window with lead-in/lead-out buffers
    and lets clip duration vary per clip instead of being fixed at 7s.

    Returns (start_seconds, duration_seconds), or None if the call fails or
    no timestamp could be parsed — callers should fall back to a default
    start/duration in that case, not treat None as an error.
    """
    client = genai.Client(api_key=api_key)

    uploaded = client.files.upload(file=str(video_path))
    try:
        while uploaded.state and uploaded.state.name == "PROCESSING":
            time.sleep(2)
            uploaded = client.files.get(name=uploaded.name)

        if uploaded.state and uploaded.state.name != "ACTIVE":
            logger.warning("Gemini file upload for %s ended in state %s", video_path, uploaded.state.name)
            return None

        response = client.models.generate_content(model=model, contents=[uploaded, PROMPT])
        text = (response.text or "").strip()
        logger.info("Gemini highlight response for %s: %r", video_path.name, text)

        window = _parse_window(text)
        if window is None:
            logger.warning("Could not parse a timestamp from Gemini response: %r", text)
            return None

        raw_start, raw_end = window
        start = max(0.0, raw_start - LEAD_IN_SECONDS)
        duration = (raw_end + LEAD_OUT_SECONDS) - start
        duration = max(MIN_CLIP_DURATION, min(MAX_CLIP_DURATION, duration))
        return start, duration
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
