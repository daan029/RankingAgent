from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from rankingagent.config import ROOT_DIR

WIDTH, HEIGHT = 1080, 1920

BRAND_RED = (231, 3, 6, 255)
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)

WATERMARK_PATH = ROOT_DIR / "assets" / "brand" / "watermark.png"
WATERMARK_SIZE = 160
WATERMARK_MARGIN = 40
WATERMARK_TOP = HEIGHT - WATERMARK_SIZE - WATERMARK_MARGIN

# YouTube Shorts' own UI (back button, follow/like/comment/share rail,
# caption/username) covers the top and bottom of the frame, so text needs to
# sit clear of both, with blurred bands behind it (top band contains the
# title; bottom band sits just above the watermark) so the burned-in text
# stays legible over busy footage. clip_processor.overlay_frame_on_clip
# blurs the video itself in these two bands; these constants are shared
# between the two so the blur and the text placement always line up.
SIDEBAR_SHIFT_DOWN = int(HEIGHT * 0.20)
TITLE_SHIFT_DOWN = int(HEIGHT * 0.156)  # a bit less than the sidebar's shift
TITLE_Y = 60 + TITLE_SHIFT_DOWN
SIDEBAR_START_Y = 260 + SIDEBAR_SHIFT_DOWN
TOP_BLUR_HEIGHT = 480
BOTTOM_BLUR_HEIGHT = 260
BOTTOM_BLUR_Y = WATERMARK_TOP - BOTTOM_BLUR_HEIGHT

# Windows system fonts, in order of preference. This project is Windows-only
# (runs on the user's home laptop), so hardcoded paths are fine here.
FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\impact.ttf"),
    Path(r"C:\Windows\Fonts\ariblk.ttf"),
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
]
EMOJI_FONT_PATH = Path(r"C:\Windows\Fonts\seguiemj.ttf")

# Common emoji/symbol code point ranges. Impact/Arial don't have these glyphs
# and silently draw a "tofu" box, so mixed reaction text (e.g. "Ouch\ud83d\ude2c") needs the
# emoji characters routed to Segoe UI Emoji instead (see _draw_mixed_text).
_EMOJI_RANGES = [
    (0x1F300, 0x1FAFF),  # misc symbols/pictographs, emoticons, supplemental
    (0x2600, 0x27BF),  # misc symbols, dingbats
    (0x2190, 0x21FF),  # arrows (occasionally used decoratively)
    (0xFE00, 0xFE0F),  # variation selectors
]

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def _load_font(size: int) -> ImageFont.ImageFont:
    key = ("text", size)
    if key in _font_cache:
        return _font_cache[key]
    for candidate in FONT_CANDIDATES:
        if candidate.exists():
            font = ImageFont.truetype(str(candidate), size)
            _font_cache[key] = font
            return font
    return ImageFont.load_default()


def _load_emoji_font(size: int) -> ImageFont.ImageFont | None:
    key = ("emoji", size)
    if key in _font_cache:
        return _font_cache[key]
    if not EMOJI_FONT_PATH.exists():
        return None
    font = ImageFont.truetype(str(EMOJI_FONT_PATH), size)
    _font_cache[key] = font
    return font


def _draw_outlined_text(draw: ImageDraw.ImageDraw, xy, text, font, fill, outline_width: int = 4) -> None:
    draw.text(xy, text, font=font, fill=fill, stroke_width=outline_width, stroke_fill=BLACK)


def _draw_mixed_text(draw: ImageDraw.ImageDraw, xy, text, font, fill, outline_width: int = 4) -> None:
    """Like _draw_outlined_text, but routes emoji characters to Segoe UI
    Emoji with embedded_color=True for full-color (WhatsApp-style) emoji,
    keeping the black outline so they stay legible over any footage."""
    emoji_font = _load_emoji_font(font.size)
    x, y = xy
    for ch in text:
        if _is_emoji(ch) and emoji_font is not None:
            draw.text(
                (x, y), ch, font=emoji_font, embedded_color=True,
                stroke_width=outline_width, stroke_fill=BLACK,
            )
            x += emoji_font.getlength(ch)
        else:
            _draw_outlined_text(draw, (x, y), ch, font, fill, outline_width=outline_width)
            x += font.getlength(ch)


def _split_highlight_segments(title_text: str) -> list[tuple[str, bool]]:
    """Split on `*marked*` spans, e.g. "Craziest *Fails* Of The Week" ->
    [("Craziest ", False), ("Fails", True), (" Of The Week", False)].
    Only the marked word(s) render in brand red — the rest stays white,
    same as the "Ranking Best " prefix. Falls back to highlighting nothing
    (all white) if the markers are missing or unbalanced, rather than
    guessing which word matters."""
    parts = title_text.split("*")
    if len(parts) % 2 == 0:
        # odd number of '*' — unbalanced markup, don't guess
        return [(title_text, False)]
    return [(part, i % 2 == 1) for i, part in enumerate(parts) if part]


def _draw_title_bar(draw: ImageDraw.ImageDraw, title_text: str) -> None:
    font = _load_font(64)
    prefix = "Ranking Best "
    segments = [(prefix, False)] + _split_highlight_segments(title_text)

    total_w = sum(draw.textlength(text, font=font) for text, _ in segments)
    x = (WIDTH - total_w) / 2
    y = TITLE_Y
    for text, highlighted in segments:
        color = BRAND_RED if highlighted else WHITE
        _draw_outlined_text(draw, (x, y), text, font, color)
        x += draw.textlength(text, font=font)


def _draw_sidebar(draw: ImageDraw.ImageDraw, ranked_clips: list[dict], revealed_count: int) -> None:
    number_font = _load_font(54)
    reaction_font = _load_font(40)
    start_y = SIDEBAR_START_Y
    row_height = 150
    x_number = 50

    by_rank = sorted(ranked_clips, key=lambda c: c["rank"])
    for i, clip in enumerate(by_rank):
        y = start_y + i * row_height
        number_color = BRAND_RED if clip["rank"] == 1 else WHITE
        _draw_outlined_text(draw, (x_number, y), f"{clip['rank']}.", number_font, number_color, outline_width=5)

        if clip["reveal_index"] < revealed_count:
            reaction = (clip.get("reaction") or "").strip()
            if reaction:
                _draw_mixed_text(draw, (x_number + 90, y + 8), reaction, reaction_font, WHITE, outline_width=4)


def _draw_watermark(canvas: Image.Image) -> None:
    if not WATERMARK_PATH.exists():
        return
    logo = Image.open(WATERMARK_PATH).convert("RGBA")
    logo.thumbnail((WATERMARK_SIZE, WATERMARK_SIZE))
    alpha = logo.split()[3].point(lambda p: int(p * 0.85))
    logo.putalpha(alpha)
    x = WIDTH - logo.width - WATERMARK_MARGIN
    y = HEIGHT - logo.height - WATERMARK_MARGIN
    canvas.alpha_composite(logo, (x, y))


def render_overlay_frame(title_text: str, ranked_clips: list[dict], revealed_count: int) -> Image.Image:
    """Build a transparent 1080x1920 PNG frame: title bar (sits in the
    blurred top band) + cumulative sidebar reveal state (clips with
    reveal_index < revealed_count show their reaction, on normal
    unblurred video) + permanent watermark just below the blurred bottom
    band, meant to be composited over one video segment for its full
    duration."""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    _draw_title_bar(draw, title_text)
    _draw_sidebar(draw, ranked_clips, revealed_count)
    _draw_watermark(canvas)
    return canvas
