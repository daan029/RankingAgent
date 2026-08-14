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
    "single moment where the main event/punchline actually happens — the "
    "fall, the impact, the confrontation peak, the mistake itself — not the "
    "buildup before it or the aftermath after it. "
    "Respond with ONLY a timestamp in MM:SS format for when that moment "
    "begins. No other text."
)

TIMESTAMP_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _parse_timestamp(text: str) -> float | None:
    match = TIMESTAMP_RE.search(text)
    if not match:
        return None
    minutes, seconds = match.groups()
    return int(minutes) * 60 + int(seconds)


def find_highlight_timestamp(
    video_path: Path, api_key: str, model: str = "gemini-3.6-flash", lead_in: float = 1.5
) -> float | None:
    """Ask Gemini where the actual highlight/fail moment happens in a raw
    clip, so `render --clip-starts` can trim from the right point instead of
    always starting at 0 (which regularly misses the moment entirely on
    longer clips — see the reddit-api-blocker / gate-clip case).

    Returns a start time in seconds (the reported moment minus `lead_in`
    seconds so the buildup is still visible, clamped to >= 0), or None if
    the call fails or no timestamp could be parsed — callers should fall
    back to start=0 in that case, not treat None as an error.
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

        seconds = _parse_timestamp(text)
        if seconds is None:
            logger.warning("Could not parse a timestamp from Gemini response: %r", text)
            return None

        return max(0.0, seconds - lead_in)
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
