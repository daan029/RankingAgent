"""
Uploads a rendered DailyWreck video to YouTube via the YouTube Data API v3.

Lessons carried over from the sibling YoutubeAgent/Trinket Tales project
(pipeline/youtube_upload.py) — see the `youtube-upload-lessons` memory entry:

- Must request the full "https://www.googleapis.com/auth/youtube" scope, not
  just "youtube.upload" — the narrower scope silently drops fields like
  containsSyntheticMedia on insert, with no error.
- videos().update() replaces the ENTIRE status object, not just the fields
  passed — update_video_status() below always reads the current status first
  and merges changes on top.
- While the Google Cloud OAuth consent screen is in "Testing" mode, the
  refresh token expires every 7 days. Since RankingAgent is meant to run
  fully unattended daily (M6), the OAuth app should be submitted for
  verification once this is wired up, or the daily run will silently start
  failing weekly.
- containsSyntheticMedia is False here by default: the clips themselves are
  real footage, only the overlay text is AI-assisted, which isn't YouTube's
  definition of synthetic/altered media.
"""
from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from rankingagent.config import ROOT_DIR, load_settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube"]
SECRETS_DIR = ROOT_DIR / "data" / "secrets"
TOKEN_PATH = SECRETS_DIR / "token.json"


def get_credentials() -> Credentials:
    settings = load_settings()
    client_secret_path = Path(settings.youtube_client_secrets_path)
    if not client_secret_path.exists():
        raise FileNotFoundError(
            f"YouTube client secrets not found at {client_secret_path} — "
            "set YOUTUBE_CLIENT_SECRETS_PATH in .env"
        )

    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str | None = None,
    contains_synthetic_media: bool = False,
    made_for_kids: bool = False,
    category_id: str = "24",  # Entertainment
    publish_at: str | None = None,
) -> str:
    settings = load_settings()
    privacy_status = privacy_status or settings.youtube_privacy_status

    # YouTube only honors `publishAt` when the video is uploaded as private —
    # it then auto-flips to public at that timestamp. Force private here
    # rather than silently ignoring an explicit publish_at with the wrong
    # privacy_status.
    if publish_at:
        privacy_status = "private"

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    status = {
        "privacyStatus": privacy_status,
        "selfDeclaredMadeForKids": made_for_kids,
        "containsSyntheticMedia": contains_synthetic_media,
        "embeddable": True,
        "publicStatsViewable": True,
        "license": "youtube",
    }
    if publish_at:
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": status,
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("Uploaded %d%%", int(status.progress() * 100))

    video_id = response["id"]

    actual_status = response.get("status", {})
    if actual_status.get("containsSyntheticMedia") is not contains_synthetic_media:
        logger.warning(
            "requested containsSyntheticMedia=%r but the API returned %r — "
            "AI-disclosure flag was NOT applied as requested, check scopes",
            contains_synthetic_media,
            actual_status.get("containsSyntheticMedia"),
        )

    logger.info("Uploaded: https://youtube.com/watch?v=%s", video_id)
    return video_id


def check_copyright_claim(video_id: str) -> dict:
    """Check a just-uploaded (still private/scheduled) video for signs of a
    live Content ID claim, so it can be caught and fixed BEFORE `publishAt`
    flips it public — see the copyright-claim-emergency-swap memory: a
    claimed video shows `contentDetails.regionRestriction.blocked` as a huge
    list (near-worldwide) while `status.privacyStatus` is still 'private'.
    There's no public API for Content ID claims directly (that's a
    partner-only Content ID API, not the Data API v3 key this project
    uses) — this region-block side effect is the best signal available to a
    regular uploader. Content ID matching isn't instant, so call this a few
    minutes after upload, not immediately.

    Returns `found=False` if `videos().list` returns zero items — itself a
    bad sign, since a fully-removed/rejected video (seen twice in practice:
    a Bensound track and a TikTok clip's background song both got the video
    taken down outright, not just region-blocked) also shows up this way."""
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    resp = youtube.videos().list(part="status,contentDetails", id=video_id).execute()
    items = resp.get("items", [])
    if not items:
        return {"found": False, "privacy_status": None, "blocked_region_count": 0, "likely_claimed": True}

    item = items[0]
    blocked = item.get("contentDetails", {}).get("regionRestriction", {}).get("blocked", [])
    return {
        "found": True,
        "privacy_status": item.get("status", {}).get("privacyStatus"),
        "blocked_region_count": len(blocked),
        # A handful of licensing-driven regional blocks can be legitimate;
        # a claim blocks essentially every country at once.
        "likely_claimed": len(blocked) > 50,
    }


def update_video_status(youtube, video_id: str, **changes) -> dict:
    """videos().update() replaces the whole status object, so read the
    current one first and merge `changes` on top — never send a partial
    status body directly."""
    current = youtube.videos().list(part="status", id=video_id).execute()
    items = current.get("items", [])
    if not items:
        raise ValueError(f"video {video_id} not found")
    status = items[0]["status"]
    status.update(changes)
    body = {"id": video_id, "status": status}
    return youtube.videos().update(part="status", body=body).execute()
