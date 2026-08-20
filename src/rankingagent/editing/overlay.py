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
# title; bottom band sits flush against the bottom edge) so the burned-in
# text stays legible over busy footage. clip_processor.overlay_frame_on_clip
# blurs the video itself in these two bands; these constants are shared
# between the two so the blur and the text placement always line up.
SIDEBAR_SHIFT_DOWN = int(HEIGHT * 0.20)
TITLE_SHIFT_DOWN = int(HEIGHT * 0.156)  # a bit less than the sidebar's shift
TITLE_Y = 60 + TITLE_SHIFT_DOWN - int(HEIGHT * 0.05)
SIDEBAR_START_Y = 260 + SIDEBAR_SHIFT_DOWN
# Reduced from 480/260 (2026-08-19 user request): a full-frame source clip
# (e.g. a pre-composed dual-camera dashcam video with no dead space at the
# edges) was having meaningful content — not just empty background — hidden
# under the bands. Kept tall enough for the title text (bottom edge ~344px
# at TITLE_MAX_FONT_SIZE) and the subscribe CTA to still sit fully inside
# their respective bands with margin.
TOP_BLUR_HEIGHT = 380
BOTTOM_BLUR_HEIGHT = 170
# Anchored to the true bottom edge, not to the watermark (2026-08-19 user
# request) — previously `WATERMARK_TOP - BOTTOM_BLUR_HEIGHT` left an
# unblurred ~40px strip below the band (between it and the frame edge,
# below the watermark), which read as a rendering glitch rather than
# deliberate framing. The watermark now sits *inside* this band instead of
# just below it — see _draw_subscribe_cta for how the CTA text avoids
# colliding with it.
BOTTOM_BLUR_Y = HEIGHT - BOTTOM_BLUR_HEIGHT

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


TITLE_MAX_FONT_SIZE = 64
TITLE_MIN_FONT_SIZE = 36
TITLE_SAFE_MARGIN = 56  # each side, so the title never touches the frame edge


def _fit_title_font(
    draw: ImageDraw.ImageDraw, segments: list[tuple[str, bool]], max_width: float
) -> tuple[ImageFont.ImageFont, float]:
    """Shrink the title font from TITLE_MAX_FONT_SIZE until the full title
    fits within max_width, down to TITLE_MIN_FONT_SIZE — long titles used to
    render past the left/right frame edge at a fixed 64px."""
    size = TITLE_MAX_FONT_SIZE
    while size > TITLE_MIN_FONT_SIZE:
        font = _load_font(size)
        total_w = sum(draw.textlength(text, font=font) for text, _ in segments)
        if total_w <= max_width:
            return font, total_w
        size -= 2
    font = _load_font(TITLE_MIN_FONT_SIZE)
    total_w = sum(draw.textlength(text, font=font) for text, _ in segments)
    return font, total_w


def _draw_title_bar(draw: ImageDraw.ImageDraw, title_text: str) -> None:
    prefix = "Ranking Best "
    segments = [(prefix, False)] + _split_highlight_segments(title_text)

    max_width = WIDTH - 2 * TITLE_SAFE_MARGIN
    font, total_w = _fit_title_font(draw, segments, max_width)
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
        # rank 0 is the reserved sentinel for an extra "BONUS" clip tacked on
        # above the #1 climax (2026-08-20 user request) — every real ranked
        # clip is rank >= 1, so this never collides with normal themes.
        if clip["rank"] == 0:
            label, number_color = "BONUS", WHITE
        else:
            label, number_color = f"{clip['rank']}.", (BRAND_RED if clip["rank"] == 1 else WHITE)
        _draw_outlined_text(draw, (x_number, y), label, number_font, number_color, outline_width=5)

        if clip["reveal_index"] < revealed_count:
            reaction = (clip.get("reaction") or "").strip()
            if reaction:
                # Reserve exactly as much space as the label actually needs
                # (min 90px, the old fixed offset — fine for "1."-"5.") so a
                # wider label like "BONUS" doesn't collide with the reaction
                # text next to it.
                label_w = draw.textlength(label, font=number_font)
                reaction_x = x_number + max(90, label_w + 20)
                _draw_mixed_text(draw, (reaction_x, y + 8), reaction, reaction_font, WHITE, outline_width=4)


SUBSCRIBE_CTA_TEXT = "SUBSCRIBE to see our next video!"
SUBSCRIBE_CTA_MAX_FONT_SIZE = 44
SUBSCRIBE_CTA_MIN_FONT_SIZE = 26
# Near the top of the bottom blur band rather than vertically centered in it
# (2026-08-19 user request — centered read as too close to the bottom
# edge). The band sits flush against the true bottom edge (see
# BOTTOM_BLUR_Y), so there's slack below the text down to the frame edge.
SUBSCRIBE_CTA_Y = BOTTOM_BLUR_Y + 42
SUBSCRIBE_ICON_SIZE = 44  # width; height is 0.7x this, YouTube play-button aspect


def _fit_single_line_font(
    draw: ImageDraw.ImageDraw, text: str, max_width: float, max_size: int, min_size: int
) -> ImageFont.ImageFont:
    size = max_size
    while size > min_size:
        font = _load_font(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return _load_font(min_size)


def _draw_play_icon(draw: ImageDraw.ImageDraw, x: float, y_center: float) -> float:
    """Small red rounded-rect + white play-triangle (generic 'watch/
    subscribe' shorthand, not a reproduction of any brand's actual logo
    asset) to the left of the subscribe CTA text (2026-08-19 user request).
    Returns the x position where text should start after it."""
    w = SUBSCRIBE_ICON_SIZE
    h = w * 0.7
    top = y_center - h / 2
    draw.rounded_rectangle([x, top, x + w, top + h], radius=6, fill=BRAND_RED)
    tri = [(x + w * 0.38, top + h * 0.2), (x + w * 0.38, top + h * 0.8), (x + w * 0.74, top + h * 0.5)]
    draw.polygon(tri, fill=WHITE)
    return x + w + 12


def _draw_subscribe_cta(draw: ImageDraw.ImageDraw) -> None:
    """Ask-for-subscribe CTA, shown only once the climax (#1) clip is
    revealed — i.e. only on the final segment, when engagement peaks
    (2026-08-19 user request). Sits in the bottom blur band. Now that the
    band is anchored to the true bottom edge (see BOTTOM_BLUR_Y) it overlaps
    the watermark's reserved bottom-right corner, so the CTA is left-aligned
    and width-capped to stay clear of that corner instead of centered across
    the full width."""
    watermark_zone_w = WATERMARK_SIZE + WATERMARK_MARGIN
    icon_zone_w = SUBSCRIBE_ICON_SIZE + 12
    max_width = WIDTH - watermark_zone_w - TITLE_SAFE_MARGIN - icon_zone_w
    font = _fit_single_line_font(
        draw, SUBSCRIBE_CTA_TEXT, max_width, SUBSCRIBE_CTA_MAX_FONT_SIZE, SUBSCRIBE_CTA_MIN_FONT_SIZE
    )
    ascent, descent = font.getmetrics()
    text_x = _draw_play_icon(draw, TITLE_SAFE_MARGIN, SUBSCRIBE_CTA_Y)
    y = SUBSCRIBE_CTA_Y - (ascent + descent) / 2
    _draw_outlined_text(draw, (text_x, y), SUBSCRIBE_CTA_TEXT, font, BRAND_RED)


CLIP_CAPTION_MAX_FONT_SIZE = 40
CLIP_CAPTION_MIN_FONT_SIZE = 24


def _wrap_two_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: float) -> list[str]:
    """Greedy word-wrap into at most 2 lines — good enough for a short
    factual caption, not meant for arbitrary-length text."""
    words = text.split()
    line1 = ""
    i = 0
    while i < len(words):
        candidate = (line1 + " " + words[i]).strip()
        if draw.textlength(candidate, font=font) > max_width and line1:
            break
        line1 = candidate
        i += 1
    line2 = " ".join(words[i:])
    return [line1, line2] if line2 else [line1]


def _draw_clip_caption(draw: ImageDraw.ImageDraw, text: str) -> None:
    """Short factual caption for a specific clip's segment (e.g. "Girl meets
    surgeon who saved her life 3 years ago") — plain white, distinct from
    the brand-red subscribe CTA, since it's information rather than an ask.
    Shown only during that one clip's own segment, not cumulatively. Sits in
    the same bottom-band position as the CTA; the two never co-occur today
    (the CTA only shows on the climax segment) so no stacking logic exists
    yet — revisit if a future theme needs both on the same segment."""
    watermark_zone_w = WATERMARK_SIZE + WATERMARK_MARGIN
    max_width = WIDTH - watermark_zone_w - TITLE_SAFE_MARGIN
    font = _fit_single_line_font(draw, text, max_width, CLIP_CAPTION_MAX_FONT_SIZE, CLIP_CAPTION_MIN_FONT_SIZE)
    lines = [text]
    if draw.textlength(text, font=font) > max_width:
        lines = _wrap_two_lines(draw, text, font, max_width)

    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    total_h = line_h * len(lines)
    y = SUBSCRIBE_CTA_Y - total_h / 2
    for line in lines:
        _draw_outlined_text(draw, (TITLE_SAFE_MARGIN, y), line, font, WHITE)
        y += line_h


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


def render_overlay_frame(
    title_text: str, ranked_clips: list[dict], revealed_count: int, current_caption: str | None = None
) -> Image.Image:
    """Build a transparent 1080x1920 PNG frame: title bar (sits in the
    blurred top band) + cumulative sidebar reveal state (clips with
    reveal_index < revealed_count show their reaction, on normal
    unblurred video) + a subscribe CTA in the blurred bottom band once the
    climax (#1) clip is revealed, OR `current_caption` (a short factual
    caption for whichever clip is on screen *this* segment specifically,
    not cumulative — 2026-08-19 user request) when one is supplied for this
    segment + permanent watermark just below that band, meant to be
    composited over one video segment for its full duration."""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    _draw_title_bar(draw, title_text)
    _draw_sidebar(draw, ranked_clips, revealed_count)
    if revealed_count >= len(ranked_clips):
        _draw_subscribe_cta(draw)
    elif current_caption:
        _draw_clip_caption(draw, current_caption)
    _draw_watermark(canvas)
    return canvas
