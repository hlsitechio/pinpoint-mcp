"""Serveur MCP clawmark — capture + annotation d'écrans pour Claude.

Tools exposés :
    - clawmark_list_monitors : liste les écrans disponibles
    - clawmark_capture_screen : screenshot écran local (Windows/Linux/macOS)
    - clawmark_capture_url : screenshot d'une page web (Playwright)
    - clawmark_find_text : trouve du texte dans une image (OCR)
    - clawmark_find_web_element : trouve un élément DOM dans une URL (sélecteurs)
    - clawmark_annotate : applique encadrés/flèches/numéros sur une image
    - clawmark_show_me : workflow complet (capture + détection + annotation)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

from clawmark.capture.screen import ScreenCapture
from clawmark.capture.web import WebCapture
from clawmark.detect.ocr import OCRDetector
from clawmark.render.annotate import annotate as render_annotate
from clawmark.render.tutorial import TutorialBuilder, TutorialStep


# Dossier de travail pour les sorties (utilisateur peut overrider via env)
WORKDIR = Path(os.environ.get("CLAWMARK_WORKDIR", tempfile.gettempdir())) / "clawmark"
WORKDIR.mkdir(parents=True, exist_ok=True)


mcp = FastMCP(
    "clawmark",
    instructions=(
        "Capture d'écran (web ou local) avec annotations visuelles intelligentes. "
        "Utilise clawmark_show_me pour le workflow complet en un seul appel : "
        "il capture l'écran/URL, trouve l'élément demandé via OCR ou DOM, "
        "et retourne une image annotée avec encadrés rouges et flèches."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _next_output_path(prefix: str = "clawmark", ext: str = "png") -> Path:
    """Génère un chemin de sortie unique dans le dossier de travail."""
    import time
    timestamp = int(time.time() * 1000)
    return WORKDIR / f"{prefix}_{timestamp}.{ext}"


def _resolve_input_path(path_str: str) -> Path:
    """Résout un chemin d'entrée et vérifie qu'il existe."""
    p = Path(path_str).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Image introuvable : {p}")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Tools : capture
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool
def clawmark_list_monitors() -> str:
    """Liste tous les moniteurs/écrans disponibles avec leurs résolutions.

    Utile avant clawmark_capture_screen pour savoir quel index utiliser
    sur un setup multi-écran.
    """
    capture = ScreenCapture()
    monitors = capture.list_monitors()
    return json.dumps(
        [
            {
                "index": m.index,
                "label": m.label,
                "left": m.left,
                "top": m.top,
                "width": m.width,
                "height": m.height,
                "is_primary": m.is_primary,
            }
            for m in monitors
        ],
        indent=2,
    )


@mcp.tool
def clawmark_capture_screen(
    monitor_index: int = 1,
    output_path: Optional[str] = None,
) -> str:
    """Capture un écran complet en PNG.

    Args:
        monitor_index: index du moniteur (1 = principal). Voir clawmark_list_monitors.
        output_path: chemin de sortie optionnel. Si omis, génère un chemin temporaire.

    Returns:
        Chemin absolu du PNG créé.
    """
    capture = ScreenCapture()
    out = Path(output_path) if output_path else _next_output_path("screen")
    result = capture.capture_full(out, monitor_index=monitor_index)
    return str(result)


@mcp.tool
def clawmark_capture_active_window(output_path: Optional[str] = None) -> str:
    """Capture la fenêtre active (Windows uniquement).

    Sur Linux/macOS, fallback sur le moniteur principal.
    """
    capture = ScreenCapture()
    out = Path(output_path) if output_path else _next_output_path("window")
    result = capture.capture_active_window(out)
    return str(result)


@mcp.tool
async def clawmark_capture_url(
    url: str,
    output_path: Optional[str] = None,
    full_page: bool = True,
    viewport_width: int = 1440,
    viewport_height: int = 900,
) -> str:
    """Capture une page web complète via Playwright (Chromium headless).

    Args:
        url: URL à capturer (https://...)
        output_path: chemin de sortie optionnel
        full_page: si True, capture toute la page scrollable; sinon le viewport seul
        viewport_width/height: dimensions du viewport navigateur

    Returns:
        Chemin absolu du PNG créé.
    """
    out = Path(output_path) if output_path else _next_output_path("web")
    async with WebCapture(
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    ) as wc:
        result = await wc.screenshot(url, out, full_page=full_page)
    return str(result)


# ─────────────────────────────────────────────────────────────────────────────
# Tools : détection
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool
def clawmark_find_text(
    image_path: str,
    query: str,
    lang: str = "eng+fra",
    case_sensitive: bool = False,
    min_confidence: float = 60.0,
) -> str:
    """Trouve toutes les occurrences d'un texte dans une image via OCR Tesseract.

    Args:
        image_path: chemin vers le screenshot
        query: texte recherché (ex "Approve scopes", "Soumettre", "Login")
        lang: codes langue Tesseract ('eng', 'fra', 'eng+fra' pour multilingue)
        case_sensitive: matching sensible à la casse
        min_confidence: seuil de confiance Tesseract (0-100)

    Returns:
        JSON avec liste des matches : [{text, x, y, width, height, confidence}, ...]
    """
    img_path = _resolve_input_path(image_path)
    detector = OCRDetector(lang=lang, min_confidence=min_confidence)
    matches = detector.find_text(img_path, query, case_sensitive=case_sensitive)

    return json.dumps(
        [
            {
                "text": m.text,
                "x": m.x,
                "y": m.y,
                "width": m.width,
                "height": m.height,
                "confidence": round(m.confidence, 1),
                "center": list(m.center),
            }
            for m in matches
        ],
        indent=2,
    )


@mcp.tool
async def clawmark_find_web_element(
    url: str,
    selectors: list[str],
    viewport_width: int = 1440,
    viewport_height: int = 900,
) -> str:
    """Trouve les bbox exactes d'éléments DOM sur une page web (pixel-perfect).

    Args:
        url: URL à inspecter
        selectors: liste de sélecteurs Playwright. Exemples :
            - "button.primary"  (CSS)
            - "text=Approve scopes"  (texte)
            - "role=button[name='Submit']"  (rôle ARIA)
            - "#email-input"  (ID)
        viewport_width/height: dimensions navigateur

    Returns:
        JSON avec liste des bbox : [{selector, x, y, width, height, text}, ...]
    """
    async with WebCapture(
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    ) as wc:
        # Capture temporaire pour avoir le contexte (mais on ne retourne que les bbox)
        tmp_path = _next_output_path("tmp_web", "png")
        _, bboxes = await wc.screenshot_with_elements(url, tmp_path, selectors)

    return json.dumps(
        [
            {
                "selector": b.selector,
                "x": b.x,
                "y": b.y,
                "width": b.width,
                "height": b.height,
                "text": b.text,
            }
            for b in bboxes
        ],
        indent=2,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tools : annotation
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool
def clawmark_annotate(
    image_path: str,
    annotations: list[dict],
    output_path: Optional[str] = None,
) -> str:
    """Applique des annotations visuelles sur une image.

    Types d'annotations supportés :
        - {"type": "rect", "x": ..., "y": ..., "w": ..., "h": ...,
           "color": "red", "thickness": 4, "label": "1"}
        - {"type": "arrow", "x1": ..., "y1": ..., "x2": ..., "y2": ...}
        - {"type": "step", "x": ..., "y": ..., "number": 1, "radius": 22}
        - {"type": "text", "x": ..., "y": ..., "content": "Cliquez ici"}
        - {"type": "highlight", "x": ..., "y": ..., "w": ..., "h": ...,
           "color": "yellow", "opacity": 0.35}
        - {"type": "blur", "x": ..., "y": ..., "w": ..., "h": ..., "radius": 15}

    Args:
        image_path: chemin vers l'image source
        annotations: liste d'objets annotation
        output_path: chemin de sortie optionnel

    Returns:
        Chemin absolu de l'image annotée.
    """
    img_path = _resolve_input_path(image_path)
    out = Path(output_path) if output_path else _next_output_path("annotated")
    render_annotate(str(img_path), str(out), annotations)
    return str(out)


# ─────────────────────────────────────────────────────────────────────────────
# Tool killer : workflow complet en un seul call
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool
async def clawmark_show_me(
    target: str,
    source: str,
    detection_method: str = "auto",
    annotation_style: str = "rect_with_arrow",
    color: str = "#FF1744",
) -> str:
    """Workflow complet : capture + trouve l'élément + annote en une seule étape.

    C'est LE tool à utiliser pour répondre à "montre-moi où cliquer".

    Args:
        target: ce qu'on cherche (ex "Approve scopes", "Soumettre", "bouton Login")
        source: soit une URL (https://...), soit un chemin d'image, soit "screen"
                pour capturer l'écran courant
        detection_method: "auto" | "ocr" | "dom"
            - auto: DOM si URL, OCR sinon
            - ocr: force Tesseract (marche sur tout)
            - dom: force Playwright DOM (URL uniquement)
        annotation_style: "rect" | "arrow" | "rect_with_arrow" | "step"
        color: couleur des annotations (hex ou nom CSS)

    Returns:
        Chemin de l'image annotée + résumé JSON de ce qui a été trouvé.
    """
    # ─── Étape 1 : capture ───
    if source == "screen":
        capture = ScreenCapture()
        image_path = capture.capture_full(_next_output_path("screen"), monitor_index=1)
        is_url = False
    elif source.startswith(("http://", "https://")):
        async with WebCapture() as wc:
            image_path = await wc.screenshot(source, _next_output_path("web"))
        is_url = True
    else:
        image_path = _resolve_input_path(source)
        is_url = False

    # ─── Étape 2 : détection ───
    if detection_method == "auto":
        method = "dom" if is_url else "ocr"
    else:
        method = detection_method

    if method == "dom" and is_url:
        async with WebCapture() as wc:
            bboxes_raw = await wc.find_text(source, target)
        if not bboxes_raw:
            # Fallback OCR si DOM ne trouve rien
            method = "ocr"
        else:
            bbox = bboxes_raw[0]  # prendre le premier match
            element_info = {
                "method": "dom",
                "text": bbox.text,
                "selector": bbox.selector,
                "x": bbox.x,
                "y": bbox.y,
                "w": bbox.width,
                "h": bbox.height,
            }

    if method == "ocr":
        detector = OCRDetector()
        matches = detector.find_text(image_path, target)
        if not matches:
            return json.dumps(
                {
                    "error": f"Aucun élément contenant '{target}' n'a été trouvé.",
                    "image_path": str(image_path),
                    "method_tried": method,
                    "hint": (
                        "Vérifie l'orthographe, ou utilise clawmark_find_text avec "
                        "des paramètres ajustés (lang, min_confidence)."
                    ),
                },
                indent=2,
            )
        # Prendre le match avec la meilleure confiance
        best = max(matches, key=lambda m: m.confidence)
        element_info = {
            "method": "ocr",
            "text": best.text,
            "confidence": round(best.confidence, 1),
            "x": best.x,
            "y": best.y,
            "w": best.width,
            "h": best.height,
        }

    # ─── Étape 3 : construire les annotations selon le style demandé ───
    x, y, w, h = element_info["x"], element_info["y"], element_info["w"], element_info["h"]
    # Padding autour de l'élément pour ne pas coller au pixel
    pad = 8
    rect_x, rect_y = max(0, x - pad), max(0, y - pad)
    rect_w, rect_h = w + pad * 2, h + pad * 2

    annotations: list[dict] = []
    if annotation_style in ("rect", "rect_with_arrow"):
        annotations.append({
            "type": "rect",
            "x": rect_x, "y": rect_y, "w": rect_w, "h": rect_h,
            "color": color, "thickness": 5,
        })

    if annotation_style in ("arrow", "rect_with_arrow"):
        # Flèche depuis la gauche du rect, à 100px de distance
        arrow_x2 = rect_x - 5
        arrow_y2 = rect_y + rect_h // 2
        arrow_x1 = max(20, arrow_x2 - 120)
        annotations.append({
            "type": "arrow",
            "x1": arrow_x1, "y1": arrow_y2,
            "x2": arrow_x2, "y2": arrow_y2,
            "color": color, "thickness": 5,
        })

    if annotation_style == "step":
        # Pastille numérotée au coin supérieur-gauche, hors de l'élément
        annotations.append({
            "type": "step",
            "x": max(30, x - 30), "y": max(30, y - 5),
            "number": 1, "color": color, "radius": 26,
        })

    # ─── Étape 4 : annoter ───
    out_path = _next_output_path("show_me")
    render_annotate(str(image_path), str(out_path), annotations)

    return json.dumps(
        {
            "annotated_image": str(out_path),
            "source_image": str(image_path),
            "element_found": element_info,
            "annotations_applied": len(annotations),
        },
        indent=2,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tool : tutoriel multi-étapes
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool
def clawmark_make_tutorial(
    source_image: str,
    steps: list[dict],
    output_dir: Optional[str] = None,
    combined: bool = False,
) -> str:
    """Génère un tutoriel visuel multi-étapes à partir d'une image source.

    Idéal pour : doc interne SCCM/Citrix, rapports bug bounty (étapes de repro),
    onboarding clients, tutoriels publics CrowByte.

    Args:
        source_image: chemin vers le screenshot de base
        steps: liste d'étapes, chaque step est un dict :
            {
                "number": 1,
                "target": "Approve scopes",   # texte cherché par OCR
                "caption": "Cliquez ici pour valider",  # optionnel
                "annotation_style": "step_with_rect",   # rect | step | step_with_rect | rect_with_arrow
                "color": "#FF1744"  # optionnel
            }
        output_dir: dossier de sortie (défaut : workdir/tutorial_<timestamp>)
        combined: si True, génère UNE SEULE image avec toutes les étapes superposées
                  (utile pour vue d'ensemble en plus des images par étape)

    Returns:
        JSON avec chemins des images générées + statut de chaque étape.
    """
    src = _resolve_input_path(source_image)

    if output_dir:
        out_dir = Path(output_dir)
    else:
        import time
        out_dir = WORKDIR / f"tutorial_{int(time.time())}"
    out_dir.mkdir(parents=True, exist_ok=True)

    builder = TutorialBuilder(src, out_dir)

    # Convertir les dicts en TutorialStep
    tutorial_steps = [
        TutorialStep(
            number=s["number"],
            target=s["target"],
            caption=s.get("caption"),
            annotation_style=s.get("annotation_style", "step_with_rect"),
            color=s.get("color", "#FF1744"),
        )
        for s in steps
    ]

    results = builder.build(tutorial_steps)

    response = {
        "output_dir": str(out_dir),
        "steps": [
            {
                "number": r.step_number,
                "target": r.target,
                "found": r.found,
                "image": str(r.output_path) if r.output_path else None,
                "bbox": r.bbox,
                "error": r.error,
            }
            for r in results
        ],
    }

    if combined:
        combined_path = out_dir / "00_combined.png"
        builder.build_combined(tutorial_steps, combined_path)
        response["combined_image"] = str(combined_path)

    return json.dumps(response, indent=2)




def main():
    """Lance le serveur MCP en mode stdio (par défaut pour Claude Desktop)."""
    transport = os.environ.get("CLAWMARK_TRANSPORT", "stdio")
    if transport == "http":
        port = int(os.environ.get("CLAWMARK_PORT", "8765"))
        mcp.run(transport="http", port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
