"""Generate branded news cover images: DALL-E background + Pillow text overlay.

Flow: AI image_prompt → DALL-E 3 (scene, no text) → download → Pillow overlay
(category badge, headline in Russian, gradient, source) → save PNG.

Fallback: if DALL-E fails → pure Pillow gradient card.
"""
import io
import logging
import os
import time
from pathlib import Path

import httpx
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

client = OpenAI(api_key=OPENAI_API_KEY)

# Paths
FONT_DIR = Path(__file__).parent / "fonts"
IMAGES_DIR = Path(__file__).parent / "images"
IMAGES_DIR.mkdir(exist_ok=True)
LOGO_PATH = Path(__file__).parent / "images" / "konomic-05.png"

# 1:1 for Telegram
W, H = 1080, 1080

# Brand colors
COLORS = {
    "bg_top": "#1A1A2E",
    "bg_bottom": "#16213E",
    "accent_red": "#E94560",
    "accent_gold": "#F5A623",
    "text_white": "#FFFFFF",
    "text_light": "#B8B8D0",
    "text_muted": "#6C6C8A",
    "overlay_dark": (10, 10, 30, 200),  # RGBA for bottom gradient
}

# Category → accent color + short label
CATEGORY_STYLES = {
    "🏠 Недвижимость": {"color": "#16A085", "label": "НЕДВИЖИМОСТЬ"},
    "💶 Деньги": {"color": "#F5A623", "label": "ДЕНЬГИ"},
    "🛂 Иммиграция": {"color": "#8E44AD", "label": "ИММИГРАЦИЯ"},
    "⚖️ Законы": {"color": "#E94560", "label": "ЗАКОНЫ"},
    "🛒 Быт и цены": {"color": "#3498DB", "label": "БЫТ И ЦЕНЫ"},
    # Legacy
    "Законодательство": {"color": "#E94560", "label": "ЗАКОН"},
    "Экономика": {"color": "#2ECC71", "label": "ЭКОНОМИКА"},
    "Недвижимость": {"color": "#16A085", "label": "НЕДВИЖИМОСТЬ"},
    "Экспаты и иммиграция": {"color": "#8E44AD", "label": "ИММИГРАЦИЯ"},
    "Финансы и налоги": {"color": "#F5A623", "label": "НАЛОГИ"},
    "Туризм": {"color": "#3498DB", "label": "ТУРИЗМ"},
    "Канарские острова": {"color": "#F39C12", "label": "КАНАРЫ"},
    "Новости": {"color": "#95A5A6", "label": "НОВОСТИ"},
}

# DALL-E scene hints per category (English, no text instructions)
CATEGORY_SCENES = {
    "🏠 Недвижимость": "white Mediterranean apartment building with terrace, blue sky, palm trees, golden sunlight",
    "💶 Деньги": "euro coins and calculator on bright marble table, natural daylight, clean modern office",
    "🛂 Иммиграция": "Spanish passport office, bright waiting room, documents on counter, natural light from window",
    "⚖️ Законы": "modern Spanish courthouse exterior, white stone building, blue sky, sunny day",
    "🛒 Быт и цены": "colorful Spanish market with fresh fruit and vegetables, warm natural light, vibrant",
    "🌪 Погода и стихия": "dramatic sky over Spanish coastline, storm clouds with rays of sunlight breaking through",
    "🎭 Культура и события": "vibrant Spanish festival, colorful decorations, sunny plaza, people celebrating",
    "🚨 Происшествия": "Spanish city street, police car with blue lights, daytime, urban setting",
    "🚗 Транспорт": "modern Spanish train station, bright architecture, travelers, natural light",
    "🏥 Здоровье": "modern Spanish hospital exterior, white building, blue sky, clean medical setting",
}


def _hex(color: str) -> tuple:
    c = color.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / name
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        for fb in ["/System/Library/Fonts/Helvetica.ttc",
                   "/System/Library/Fonts/SFNSText.ttf"]:
            try:
                return ImageFont.truetype(fb, size)
            except OSError:
                continue
        return ImageFont.load_default()


def _wrap(text: str, font, max_w: int, draw: ImageDraw.Draw) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for word in words:
        test = f"{cur} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _gradient_overlay(img: Image.Image) -> Image.Image:
    """Apply subtle gradient from bottom for text readability (covers ~40% of image)."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    h = img.size[1]
    start = int(h * 0.55)  # gradient starts at 55% from top (only bottom 45%)
    for y in range(start, h):
        t = (y - start) / (h - start)
        alpha = int(180 * t)  # 0 → 180 (was 220 — softer now)
        draw.line([(0, y), (img.size[0], y)], fill=(20, 20, 40, alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay)


def _generate_dalle_background(image_prompt: str, category: str) -> Image.Image | None:
    """Generate background image via DALL-E 3 API."""
    # Build the DALL-E prompt — scene only, NO text
    scene = CATEGORY_SCENES.get(category, "Spanish cityscape, Mediterranean architecture")

    dalle_prompt = (
        f"Create a modern editorial cover photo for a news article. "
        f"Scene: {image_prompt if image_prompt else scene}. "
        f"Style: bright, clean, modern editorial photography. "
        f"Natural warm lighting, Mediterranean sunlight, vivid but not oversaturated colors. "
        f"Shallow depth of field, minimalistic composition, premium magazine aesthetic. "
        f"NOT dark, NOT moody, NOT gloomy — light and inviting. "
        f"NO text, NO letters, NO words, NO watermarks. "
        f"Square format 1:1."
    )

    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=dalle_prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )

        image_url = response.data[0].url
        logger.info("DALL-E image generated, downloading...")

        # Download image
        with httpx.Client(timeout=30) as http:
            resp = http.get(image_url)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
            # Resize to our target
            img = img.resize((W, H), Image.LANCZOS)
            return img

    except Exception:
        logger.exception("DALL-E generation failed, will use fallback gradient")
        return None


def _gradient_background(urgent: bool = False) -> Image.Image:
    """Fallback: gradient background — light and modern."""
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    top = "#8B0000" if urgent else "#1E3A5F"
    bottom = "#1E3A5F" if urgent else "#0D253F"
    r1, g1, b1 = _hex(top)
    r2, g2, b2 = _hex(bottom)
    for y in range(H):
        t = y / H
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    return img


def generate_news_image(
    headline: str,
    category: str = "Новости",
    source: str = "",
    urgent: bool = False,
    image_prompt: str = "",
) -> str | None:
    """
    Generate a branded news cover image.

    1) Try DALL-E 3 for background scene
    2) Apply dark gradient overlay from bottom
    3) Overlay: category badge (top-left), headline (center/bottom), source, channel name
    4) Save as PNG

    Returns path to saved file, or None on error.
    """
    try:
        cat = CATEGORY_STYLES.get(category, CATEGORY_STYLES.get("Новости", {"color": "#95A5A6", "label": "НОВОСТИ"}))
        accent = cat["color"]
        label = cat["label"]

        # ── Step 1: Background ──
        bg = _generate_dalle_background(image_prompt, category)
        if bg is None:
            bg = _gradient_background(urgent)

        # ── Step 2: Dark gradient overlay ──
        img = _gradient_overlay(bg)

        # Slight blur on background for text readability
        # (only on the background, before we add text)
        # We'll work in RGBA from here
        draw = ImageDraw.Draw(img)

        # ── Urgent: red top/bottom bars ──
        if urgent:
            accent = COLORS["accent_red"]
            label = "СРОЧНО"
            draw.rectangle([0, 0, W, 6], fill=_hex(COLORS["accent_red"]))
            draw.rectangle([0, H - 6, W, H], fill=_hex(COLORS["accent_red"]))
            # Red glow at top
            for y in range(60):
                alpha = int(80 * (1 - y / 60))
                draw.line([(0, y), (W, y)], fill=(233, 69, 96, alpha))

        # ── Category badge (top-left) ──
        font_cat = _font("Montserrat-Bold.ttf", 24)
        badge_text = f"  {label}  "

        bb = draw.textbbox((0, 0), badge_text, font=font_cat)
        bw = bb[2] - bb[0] + 20
        bh = bb[3] - bb[1] + 16
        bx, by = 50, 50

        # Semi-transparent badge background
        badge_bg = Image.new("RGBA", (bw, bh), (*_hex(accent), 230))
        img.paste(badge_bg, (bx, by), badge_bg)
        draw = ImageDraw.Draw(img)  # refresh draw after paste
        draw.text((bx + 10, by + 6), badge_text,
                  font=font_cat, fill=(255, 255, 255, 255))

        # ── Logo with glow (top-right) ──
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo_h = 90
            ratio = logo_h / logo.size[1]
            logo_w = int(logo.size[0] * ratio)
            logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

            # Convert dark logo to white for dark backgrounds
            r, g, b, a = logo.split()
            white_logo = Image.merge("RGBA", (
                r.point(lambda x: 255),
                g.point(lambda x: 255),
                b.point(lambda x: 255),
                a,
            ))

            logo_x = W - logo_w - 40
            logo_y = 35

            # Soft white glow behind logo
            glow_pad = 25
            glow_size = (logo_w + glow_pad * 2, logo_h + glow_pad * 2)
            glow = Image.new("RGBA", glow_size, (0, 0, 0, 0))
            # Paste white logo into glow layer, then blur it
            glow.paste(white_logo, (glow_pad, glow_pad), white_logo)
            glow = glow.filter(ImageFilter.GaussianBlur(radius=12))
            # Make glow semi-transparent
            glow_r, glow_g, glow_b, glow_a = glow.split()
            glow_a = glow_a.point(lambda x: min(x, 80))
            glow = Image.merge("RGBA", (glow_r, glow_g, glow_b, glow_a))

            img.paste(glow, (logo_x - glow_pad, logo_y - glow_pad), glow)
            img.paste(white_logo, (logo_x, logo_y), white_logo)
            draw = ImageDraw.Draw(img)
        except Exception:
            logger.warning("Could not load logo, skipping")

        # ── Headline (bottom area, over dark gradient) ──
        font_h = _font("Montserrat-Bold.ttf", 52)
        max_tw = W - 120
        lines = _wrap(headline, font_h, max_tw, draw)

        # Max 4 lines
        if len(lines) > 4:
            lines = lines[:4]
            if len(lines[-1]) > 3:
                lines[-1] = lines[-1][:-3] + "..."

        lh = 68
        # Position headline in bottom third
        total_text_h = len(lines) * lh
        ty = H - 120 - total_text_h  # 120px from bottom for source line

        for i, line in enumerate(lines):
            x = 50
            y = ty + i * lh
            # Text shadow for readability
            draw.text((x + 2, y + 2), line,
                      font=font_h, fill=(0, 0, 0, 180))
            draw.text((x, y), line,
                      font=font_h, fill=(255, 255, 255, 255))

        # ── Source line (very bottom) ──
        font_src = _font("Montserrat-Regular.ttf", 20)
        bot_y = H - 50

        if source:
            draw.text((50, bot_y), f"Источник: {source}",
                      font=font_src, fill=(255, 255, 255, 130))

        # Accent dot (bottom-right)
        draw.ellipse([W - 70, bot_y + 3, W - 58, bot_y + 15],
                     fill=(*_hex(accent), 200))

        # ── Save ──
        # Convert RGBA to RGB for PNG/Telegram
        final = Image.new("RGB", img.size, (10, 10, 30))
        final.paste(img, mask=img.split()[3])

        safe_name = "".join(c if c.isalnum() else "_" for c in headline[:40])
        ts = int(time.time())
        path = str(IMAGES_DIR / f"{safe_name}_{ts}.png")
        final.save(path, "PNG", quality=95)
        logger.info("Generated image: %s", path)
        return path

    except Exception:
        logger.exception("Error generating news image")
        return None
