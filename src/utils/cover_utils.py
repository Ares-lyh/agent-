"""Cover generator utilities using Pillow for Album Art creation."""
import os
import math
from typing import Optional
from PIL import Image, ImageDraw, ImageFont


def generate_cyberpunk_cover(
    title: str,
    project_id: str,
    genre: str = "Electronic / Pop",
    output_path: str = "cover.png",
    width: int = 600,
    height: int = 600,
) -> str:
    """Generate a high-contrast cyberpunk/futuristic album cover art."""
    img = Image.new("RGBA", (width, height), (10, 15, 29, 255))
    draw = ImageDraw.Draw(img)

    # 1. Background radial gradient simulation with concentric rings/rects
    center_x, center_y = width // 2, height // 2
    for r in range(width, 0, -10):
        alpha = int(255 * (1 - r / width) * 0.45)
        # Deep cyan/purple gradient tint
        red = int(10 + (r / width) * 15)
        green = int(20 + (1 - r / width) * 50)
        blue = int(45 + (1 - r / width) * 90)
        draw.ellipse(
            [center_x - r, center_y - r, center_x + r, center_y + r],
            fill=(red, green, blue, alpha),
        )

    # 2. Draw geometric cyberpunk grids and decorative lines
    line_color = (0, 240, 255, 60)
    grid_step = 40
    # Perspective ground grid
    for y in range(height // 2, height, 25):
        draw.line([(0, y), (width, y)], fill=line_color, width=1)
    for x in range(0, width + 1, grid_step):
        draw.line([(x, height // 2), (x * 1.6 - width * 0.3, height)], fill=line_color, width=1)

    # 3. Decorative glowing neon circles and accents
    accent_cyan = (0, 240, 255, 230)
    accent_purple = (168, 85, 247, 200)
    draw.ellipse([center_x - 140, center_y - 180, center_x + 140, center_y + 100], outline=accent_cyan, width=3)
    draw.ellipse([center_x - 120, center_y - 160, center_x + 120, center_y + 80], outline=accent_purple, width=1)

    # 4. Corner HUD brackets
    bracket_len = 35
    bracket_color = (0, 240, 255, 200)
    # Top-Left
    draw.line([(30, 30), (30 + bracket_len, 30)], fill=bracket_color, width=2)
    draw.line([(30, 30), (30, 30 + bracket_len)], fill=bracket_color, width=2)
    # Top-Right
    draw.line([(width - 30, 30), (width - 30 - bracket_len, 30)], fill=bracket_color, width=2)
    draw.line([(width - 30, 30), (width - 30, 30 + bracket_len)], fill=bracket_color, width=2)
    # Bottom-Left
    draw.line([(30, height - 30), (30 + bracket_len, height - 30)], fill=bracket_color, width=2)
    draw.line([(30, height - 30), (30, height - 30 - bracket_len)], fill=bracket_color, width=2)
    # Bottom-Right
    draw.line([(width - 30, height - 30), (width - 30 - bracket_len, height - 30)], fill=bracket_color, width=2)
    draw.line([(width - 30, height - 30), (width - 30, height - 30 - bracket_len)], fill=bracket_color, width=2)

    # 5. Text elements (using default bitmap or font if available)
    try:
        # Try finding standard Chinese font on Windows (msyh.ttc or simhei.ttf)
        font_paths = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        title_font = None
        sub_font = None
        tag_font = None
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    title_font = ImageFont.truetype(fp, 36)
                    sub_font = ImageFont.truetype(fp, 18)
                    tag_font = ImageFont.truetype(fp, 14)
                    break
                except Exception:
                    continue
        if not title_font:
            title_font = ImageFont.load_default()
            sub_font = ImageFont.load_default()
            tag_font = ImageFont.load_default()
    except Exception:
        title_font = ImageFont.load_default()
        sub_font = ImageFont.load_default()
        tag_font = ImageFont.load_default()

    # Draw Badge
    badge_bg = (0, 240, 255, 40)
    draw.rounded_rectangle([45, 45, 230, 75], radius=6, fill=badge_bg, outline=accent_cyan, width=1)
    draw.text((55, 52), f"MASTER TRACK // {genre[:12]}", fill=(0, 240, 255, 255), font=tag_font)

    # Draw Title & Project
    title_text = title if title else "CYBER AUDIO"
    draw.text((center_x, center_y - 20), title_text, fill=(255, 255, 255, 255), font=title_font, anchor="mm")
    draw.text((center_x, center_y + 35), f"PROJECT ID: {project_id}", fill=(160, 185, 215, 220), font=sub_font, anchor="mm")
    draw.text((center_x, height - 60), "44.1kHz / 16-BIT PCM LOSSLESS AUDIO", fill=(0, 240, 255, 180), font=tag_font, anchor="mm")

    # Save to RGB PNG
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    rgb_img = img.convert("RGB")
    rgb_img.save(output_path, "PNG")
    return output_path
