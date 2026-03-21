from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots" / "readme_banner.png"
W, H = 1280, 640

ACCENT = "#7be326"
ACCENT_BRIGHT = "#cfff8b"
TEXT = "#e7ffc8"
MUTED = "#9bcf7b"
PANEL = "#0b1209"
PANEL_2 = "#081108"


def load_font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def fit_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    ratio = max(target_w / image.width, target_h / image.height)
    resized = image.resize((int(image.width * ratio), int(image.height * ratio)))
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def framed(image: Image.Image, size: tuple[int, int], label: str, font: ImageFont.ImageFont) -> Image.Image:
    shot = fit_cover(image, size)
    canvas = Image.new("RGBA", (size[0] + 14, size[1] + 42), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (0, 0, canvas.width - 1, canvas.height - 1),
        radius=20,
        fill=PANEL_2,
        outline=ACCENT,
        width=2,
    )
    draw.text((16, 10), label, font=font, fill=ACCENT_BRIGHT)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=14, fill=255)
    canvas.paste(shot, (7, 35), mask)
    return canvas


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    max_width: int,
    font: ImageFont.ImageFont,
    fill: str,
    line_gap: int,
) -> None:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        trial = (line + " " + word).strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    x, y = xy
    for index, current in enumerate(lines):
        draw.text((x, y + index * line_gap), current, font=font, fill=fill)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    bg = Image.new("RGB", (W, H), "#050805")
    draw = ImageDraw.Draw(bg)

    for y in range(H):
        ratio = y / max(1, H - 1)
        color = (int(5 + 5 * ratio), int(8 + 16 * ratio), int(5 + 5 * ratio))
        draw.line([(0, y), (W, y)], fill=color)

    for x in range(0, W, 48):
        draw.line([(x, 0), (x, H)], fill="#0b180b", width=1)
    for y in range(0, H, 48):
        draw.line([(0, y), (W, y)], fill="#0b180b", width=1)

    title_font = load_font(
        [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"],
        48,
    )
    subtitle_font = load_font(
        [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"],
        21,
    )
    mono_font = load_font(
        [r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\cour.ttf"],
        18,
    )
    small_font = load_font(
        [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"],
        16,
    )

    icon = Image.open(ROOT / "app" / "icon.png").convert("RGBA").resize((136, 136))
    logo_card = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
    logo_draw = ImageDraw.Draw(logo_card)
    logo_draw.rounded_rectangle((0, 0, 179, 179), radius=28, fill=PANEL_2, outline=ACCENT, width=3)
    shadow = logo_card.filter(ImageFilter.GaussianBlur(12))
    bg.paste(shadow, (58, 58), shadow)
    bg.paste(logo_card, (50, 50), logo_card)
    bg.paste(icon, (72, 72), icon)

    left_x = 260
    text_width = 500
    draw.text((left_x, 84), "BrowerAI Studio Labs", font=title_font, fill=ACCENT_BRIGHT)
    draw_wrapped_text(
        draw,
        "Source-visible desktop workspace for browser automation, vision review, worker orchestration, and local AI tooling.",
        (left_x, 148),
        text_width,
        subtitle_font,
        TEXT,
        28,
    )

    pills = ["PySide6 UI", "Playwright + OCR", "Cluster Workers", "Provider Hub", "n8n Runtime", "Source-Visible"]
    px = left_x
    py = 246
    for pill in pills:
        pill_bbox = draw.textbbox((0, 0), pill, font=small_font)
        pill_w = (pill_bbox[2] - pill_bbox[0]) + 24
        if px + pill_w > left_x + text_width:
            px = left_x
            py += 42
        draw.rounded_rectangle((px, py, px + pill_w, py + 32), radius=14, fill=PANEL, outline=ACCENT, width=2)
        draw.text((px + 12, py + 6), pill, font=small_font, fill=TEXT)
        px += pill_w + 10

    train = Image.open(ROOT / "docs" / "screenshots" / "training_terminal.png").convert("RGB")
    cluster = Image.open(ROOT / "docs" / "screenshots" / "cluster_terminal.png").convert("RGB")
    settings = Image.open(ROOT / "docs" / "screenshots" / "settings_terminal.png").convert("RGB")

    train_card = framed(train, (340, 188), "Training", small_font)
    cluster_card = framed(cluster, (300, 172), "Cluster", small_font)
    settings_card = framed(settings, (220, 138), "Settings", small_font)

    bg.paste(train_card, (860, 60), train_card)
    bg.paste(cluster_card, (760, 308), cluster_card)
    bg.paste(settings_card, (1010, 356), settings_card)

    strip_y = 546
    draw.rounded_rectangle((52, strip_y, 1228, 606), radius=20, fill=PANEL, outline=ACCENT, width=2)
    features = [
        ("Graph + Training", "Visual behavior editing and runtime control"),
        ("Vision + Guide Coach", "OCR, replay diagnostics, and click calibration"),
        ("Workers + DOM Live", "Prewarmed workers and guarded checks"),
    ]
    slot_w = 1176 // len(features)
    for index, (title, desc) in enumerate(features):
        x = 72 + index * slot_w
        draw.text((x, strip_y + 12), title, font=mono_font, fill=ACCENT_BRIGHT)
        draw.text((x, strip_y + 39), desc, font=small_font, fill=MUTED)

    for inset, color in [(12, "#1f4d16"), (20, ACCENT)]:
        draw.rounded_rectangle((inset, inset, W - inset, H - inset), radius=26, outline=color, width=2)

    bg.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
