#!/usr/bin/env python3
"""
screen-annotate: annote une image (screenshot) avec des encadrés rouges,
flèches, numéros d'étapes et callouts pour produire des tutoriels visuels.

Usage:
    python annotate.py <image_in> <image_out> <annotations_json>

Le JSON d'annotations est une liste d'objets. Chaque objet a un "type":

    {"type": "rect",   "x": 100, "y": 50, "w": 300, "h": 200,
     "color": "red", "thickness": 4, "label": "1"}

    {"type": "arrow",  "x1": 800, "y1": 400, "x2": 1000, "y2": 450,
     "color": "red", "thickness": 5}

    {"type": "step",   "x": 150, "y": 80, "number": 1,
     "color": "red", "radius": 22}

    {"type": "text",   "x": 200, "y": 500, "content": "Cliquez ici",
     "color": "red", "bg": "white", "size": 20}

    {"type": "blur",   "x": 0, "y": 0, "w": 400, "h": 100, "radius": 15}

    {"type": "highlight", "x": 100, "y": 200, "w": 300, "h": 50,
     "color": "yellow", "opacity": 0.35}

Couleurs supportées: nom ("red", "green", "blue"...) ou hex ("#FF0000").
Coordonnées en pixels depuis le coin haut-gauche.
"""

import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Couleur par défaut — rouge vif bien visible sur dark/light UI
DEFAULT_COLOR = "#FF1744"
DEFAULT_THICKNESS = 4
DEFAULT_FONT_SIZE = 20


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Essaie plusieurs fonts communes selon l'OS; fallback sur default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_rect(draw: ImageDraw.ImageDraw, ann: dict) -> None:
    x, y = ann["x"], ann["y"]
    w, h = ann["w"], ann["h"]
    color = ann.get("color", DEFAULT_COLOR)
    thickness = ann.get("thickness", DEFAULT_THICKNESS)
    draw.rectangle([x, y, x + w, y + h], outline=color, width=thickness)

    # Label optionnel dans le coin supérieur gauche (ex: "1", "A", etc.)
    label = ann.get("label")
    if label:
        font = load_font(DEFAULT_FONT_SIZE)
        padding = 6
        bbox = draw.textbbox((0, 0), str(label), font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        bg_x, bg_y = x, y
        draw.rectangle(
            [bg_x, bg_y, bg_x + tw + padding * 2, bg_y + th + padding * 2],
            fill=color,
        )
        draw.text((bg_x + padding, bg_y + padding), str(label),
                  fill="white", font=font)


def draw_arrow(draw: ImageDraw.ImageDraw, ann: dict) -> None:
    import math
    x1, y1 = ann["x1"], ann["y1"]
    x2, y2 = ann["x2"], ann["y2"]
    color = ann.get("color", DEFAULT_COLOR)
    thickness = ann.get("thickness", DEFAULT_THICKNESS + 1)
    head_size = ann.get("head_size", 18)

    # Ligne principale
    draw.line([(x1, y1), (x2, y2)], fill=color, width=thickness)

    # Tête de flèche (triangle rempli)
    angle = math.atan2(y2 - y1, x2 - x1)
    left_angle = angle + math.radians(150)
    right_angle = angle - math.radians(150)
    left = (x2 + head_size * math.cos(left_angle),
            y2 + head_size * math.sin(left_angle))
    right = (x2 + head_size * math.cos(right_angle),
             y2 + head_size * math.sin(right_angle))
    draw.polygon([(x2, y2), left, right], fill=color)


def draw_step(draw: ImageDraw.ImageDraw, ann: dict) -> None:
    """Pastille numérotée — style tutoriel Microsoft/Apple."""
    x, y = ann["x"], ann["y"]
    number = ann["number"]
    color = ann.get("color", DEFAULT_COLOR)
    radius = ann.get("radius", 22)

    # Cercle rempli avec bordure blanche pour contraste sur tous les fonds
    draw.ellipse(
        [x - radius - 2, y - radius - 2, x + radius + 2, y + radius + 2],
        fill="white",
    )
    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill=color,
    )

    font = load_font(int(radius * 1.3))
    text = str(number)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Correction pour centrage vertical (bbox top != cap height)
    draw.text(
        (x - tw / 2 - bbox[0], y - th / 2 - bbox[1]),
        text, fill="white", font=font,
    )


def draw_text(draw: ImageDraw.ImageDraw, ann: dict) -> None:
    """Callout texte avec fond opaque pour lisibilité."""
    x, y = ann["x"], ann["y"]
    content = ann["content"]
    color = ann.get("color", DEFAULT_COLOR)
    bg = ann.get("bg", "white")
    size = ann.get("size", DEFAULT_FONT_SIZE)
    padding = ann.get("padding", 8)

    font = load_font(size)
    bbox = draw.textbbox((0, 0), content, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    draw.rectangle(
        [x - padding, y - padding,
         x + tw + padding, y + th + padding],
        fill=bg, outline=color, width=2,
    )
    draw.text((x, y), content, fill=color, font=font)


def draw_blur(img: Image.Image, ann: dict) -> Image.Image:
    """Floute une zone — utile pour masquer données sensibles (tokens, emails)."""
    x, y = ann["x"], ann["y"]
    w, h = ann["w"], ann["h"]
    radius = ann.get("radius", 15)

    region = img.crop((x, y, x + w, y + h))
    blurred = region.filter(ImageFilter.GaussianBlur(radius=radius))
    img.paste(blurred, (x, y))
    return img


def draw_highlight(img: Image.Image, ann: dict) -> Image.Image:
    """Surligneur semi-transparent sur la zone."""
    x, y = ann["x"], ann["y"]
    w, h = ann["w"], ann["h"]
    color = ann.get("color", "yellow")
    opacity = ann.get("opacity", 0.35)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    # Convertir la couleur nommée vers RGBA
    from PIL import ImageColor
    rgb = ImageColor.getrgb(color)
    rgba = (*rgb, int(255 * opacity))
    overlay_draw.rectangle([x, y, x + w, y + h], fill=rgba)

    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return Image.alpha_composite(img, overlay)


def annotate(image_in: str, image_out: str, annotations: list) -> None:
    img = Image.open(image_in).convert("RGBA")

    # 1ère passe: opérations qui modifient les pixels (blur, highlight)
    for ann in annotations:
        t = ann["type"]
        if t == "blur":
            img = draw_blur(img, ann)
        elif t == "highlight":
            img = draw_highlight(img, ann)

    # 2ème passe: dessins vectoriels par-dessus
    draw = ImageDraw.Draw(img)
    for ann in annotations:
        t = ann["type"]
        if t == "rect":
            draw_rect(draw, ann)
        elif t == "arrow":
            draw_arrow(draw, ann)
        elif t == "step":
            draw_step(draw, ann)
        elif t == "text":
            draw_text(draw, ann)
        elif t in ("blur", "highlight"):
            pass  # déjà traité
        else:
            print(f"[warn] type d'annotation inconnu: {t}", file=sys.stderr)

    # Convertir en RGB si sortie JPEG
    out_path = Path(image_out)
    if out_path.suffix.lower() in (".jpg", ".jpeg"):
        img = img.convert("RGB")
    img.save(image_out)


def main():
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    image_in = sys.argv[1]
    image_out = sys.argv[2]
    annotations_arg = sys.argv[3]

    # Le 3e arg peut être soit un chemin de fichier JSON, soit du JSON inline
    # Heuristique: si ça commence par [ ou {, c'est du JSON inline
    stripped = annotations_arg.lstrip()
    if stripped.startswith(("[", "{")):
        annotations = json.loads(annotations_arg)
    elif Path(annotations_arg).exists():
        with open(annotations_arg, "r", encoding="utf-8") as f:
            annotations = json.load(f)
    else:
        # Dernier recours: essayer de parser comme JSON
        annotations = json.loads(annotations_arg)

    annotate(image_in, image_out, annotations)
    print(f"OK: {image_out}")


if __name__ == "__main__":
    main()
