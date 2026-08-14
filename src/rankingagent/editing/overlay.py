from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from rankingagent.config import ROOT_DIR

WIDTH, HEIGHT = 1080, 1920

BRAND_RED = (231, 3, 6, 255)
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)

WATERMARK_PATH = ROOT_DIR / "assets" / "brand" / "watermark.png"

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
    Emoji (Pillow renders them as plain glyphs, not full color, since it
    isn't a COLR-aware renderer here — still far better than the empty boxes
    `font` draws for codepoints it doesn't have)."""
    emoji_font = _load_emoji_font(font.size)
    x, y = xy
    for ch in text:
        if _is_emoji(ch) and emoji_font is not None:
            draw.text((x, y), ch, font=emoji_font, fill=fill, stroke_width=outline_width, stroke_fill=BLACK)
            x += emoji_font.getlength(ch)
        else:
            _draw_outlined_text(draw, (x, y), ch, font, fill, outline_width=outline_width)
            x += font.getlength(ch)


def _draw_title_bar(draw: ImageDraw.ImageDraw, theme_label: str) -> None:
    font = _load_font(64)
    prefix = "Ranking Best "
    prefix_w = draw.textlength(prefix, font=font)
    label_w = draw.textlength(theme_label, font=font)
    x = (WIDTH - (prefix_w + label_w)) / 2
    y = 60
    _draw_outlined_text(draw, (x, y), prefix, font, WHITE)
    _draw_outlined_text(draw, (x + prefix_w, y), theme_label, font, BRAND_RED)


def _draw_sidebar(draw: ImageDraw.ImageDraw, ranked_clips: list[dict], revealed_count: int) -> None:
    number_font = _load_font(54)
    reaction_font = _load_font(40)
    start_y = 260
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
    logo.thumbnail((160, 160))
    alpha = logo.split()[3].point(lambda p: int(p * 0.85))
    logo.putalpha(alpha)
    x = WIDTH - logo.width - 40
    y = HEIGHT - logo.height - 40
    canvas.alpha_composite(logo, (x, y))


def render_overlay_frame(theme_label: str, ranked_clips: list[dict], revealed_count: int) -> Image.Image:
    """Build a transparent 1080x1920 PNG frame: title bar + cumulative sidebar
    reveal state (clips with reveal_index < revealed_count show their
    reaction) + permanent watermark, meant to be composited over one video
    segment for its full duration."""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    _draw_title_bar(draw, theme_label)
    _draw_sidebar(draw, ranked_clips, revealed_count)
    _draw_watermark(canvas)
    return canvas
