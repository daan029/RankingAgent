from __future__ import annotations

import argparse
import json
import logging

from pathlib import Path

from rankingagent.pipeline import (
    discover_and_download,
    discover_from_urls,
    discover_via_rss,
    get_theme_history,
    list_candidates,
    preview_clip_frames,
    reject_clips,
    render_video_for_theme,
    select_top_clips,
    upload_rendered_video,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="rankingagent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover_parser = subparsers.add_parser(
        "discover", help="Discover and download clips for a theme from Reddit"
    )
    discover_parser.add_argument("--theme", required=True, help="Theme name from config/themes.yaml")

    discover_manual_parser = subparsers.add_parser(
        "discover-manual",
        help="Fallback while Reddit API access is pending: fetch metadata/download from a user-curated list of post URLs",
    )
    discover_manual_parser.add_argument("--theme", required=True, help="Theme name from config/themes.yaml")
    discover_manual_parser.add_argument(
        "--urls-file", required=True, help="Text file with one Reddit post URL per line"
    )

    discover_rss_parser = subparsers.add_parser(
        "discover-rss",
        help="Fully automated discovery via subreddit RSS feeds (no API approval needed, but slow/rate-limited and unfiltered for tone)",
    )
    discover_rss_parser.add_argument("--theme", required=True, help="Theme name from config/themes.yaml")

    candidates_parser = subparsers.add_parser(
        "candidates", help="List downloaded-but-unselected clips for content review; prints JSON"
    )
    candidates_parser.add_argument("--theme", required=True, help="Theme name from config/themes.yaml")

    reject_parser = subparsers.add_parser(
        "reject", help="Mark clips as rejected (excluded from select) after content review"
    )
    reject_parser.add_argument("--theme", required=True, help="Theme name from config/themes.yaml")
    reject_parser.add_argument("--clip-ids", required=True, help="Comma-separated clip ids")

    select_parser = subparsers.add_parser(
        "select", help="Rank and select the top clips for a theme; prints JSON"
    )
    select_parser.add_argument("--theme", required=True, help="Theme name from config/themes.yaml")

    preview_frames_parser = subparsers.add_parser(
        "preview-frames",
        help="Sample frames across each selected clip's full duration, to pick where the fail actually is; prints JSON",
    )
    preview_frames_parser.add_argument("--theme", required=True, help="Theme name from config/themes.yaml")
    preview_frames_parser.add_argument("--count", type=int, default=6, help="Frames per clip (default 6)")

    render_parser = subparsers.add_parser(
        "render", help="Render the final video from the currently selected clips"
    )
    render_parser.add_argument("--theme", required=True, help="Theme name from config/themes.yaml")
    render_parser.add_argument(
        "--reactions",
        required=True,
        help='JSON object mapping clip id -> short reaction text, e.g. \'{"reddit_abc123": "Aaaah\\ud83d\\udc80"}\'',
    )
    render_parser.add_argument(
        "--title-text",
        default=None,
        help='On-screen burned-in title text (after \'Ranking Best \'); wrap the word(s) to highlight in red with '
             'asterisks, e.g. "Craziest *Fails* Of The Week". Defaults to the theme\'s on_screen_label (all white).',
    )
    render_parser.add_argument(
        "--clip-starts",
        default=None,
        help='JSON object mapping clip id -> trim start offset in seconds, from reviewing `preview-frames` output, '
             'e.g. \'{"reddit_abc123": 4.5}\'. Clips not listed start at 0.',
    )

    upload_parser = subparsers.add_parser("upload", help="Upload a rendered video to YouTube")
    upload_parser.add_argument("--theme", required=True, help="Theme name from config/themes.yaml")
    upload_parser.add_argument("--video", required=True, help="Path to the rendered mp4")
    upload_parser.add_argument("--title", required=True)
    upload_parser.add_argument("--description", required=True)
    upload_parser.add_argument("--tags", default="", help="Comma-separated")
    upload_parser.add_argument(
        "--privacy", default=None, choices=["public", "unlisted", "private"],
        help="Defaults to YOUTUBE_PRIVACY_STATUS from .env (unlisted)",
    )

    history_parser = subparsers.add_parser(
        "history", help="Previously published videos for a theme; prints JSON"
    )
    history_parser.add_argument("--theme", required=True, help="Theme name from config/themes.yaml")

    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "discover":
        discover_and_download(args.theme)
    elif args.command == "discover-manual":
        urls = Path(args.urls_file).read_text(encoding="utf-8").splitlines()
        discover_from_urls(args.theme, urls)
    elif args.command == "discover-rss":
        discover_via_rss(args.theme)
    elif args.command == "candidates":
        print(json.dumps(list_candidates(args.theme), indent=2, default=str))
    elif args.command == "reject":
        clip_ids = [c.strip() for c in args.clip_ids.split(",") if c.strip()]
        reject_clips(args.theme, clip_ids)
    elif args.command == "select":
        ranked = select_top_clips(args.theme)
        print(json.dumps(ranked, indent=2, default=str))
    elif args.command == "preview-frames":
        frames = preview_clip_frames(args.theme, count=args.count)
        print(json.dumps(frames, indent=2))
    elif args.command == "render":
        reactions = json.loads(args.reactions)
        clip_starts = json.loads(args.clip_starts) if args.clip_starts else None
        output_path = render_video_for_theme(
            args.theme, reactions, title_text=args.title_text, clip_starts=clip_starts
        )
        print(str(output_path))
    elif args.command == "upload":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        video_id = upload_rendered_video(
            args.theme,
            Path(args.video),
            title=args.title,
            description=args.description,
            tags=tags,
            privacy_status=args.privacy,
        )
        print(f"https://youtube.com/watch?v={video_id}")
    elif args.command == "history":
        history = get_theme_history(args.theme)
        print(json.dumps(history, indent=2, default=str))


if __name__ == "__main__":
    main()
