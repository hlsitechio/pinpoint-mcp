"""Serveur MCP pinpoint — capture + annotation d'écrans pour Claude.

Tools exposés :
    - pinpoint_list_monitors : liste les écrans disponibles
    - pinpoint_capture_screen : screenshot écran local (Windows/Linux/macOS)
    - pinpoint_capture_url : screenshot d'une page web (Playwright)
    - pinpoint_find_text : trouve du texte dans une image (OCR)
    - pinpoint_find_web_element : trouve un élément DOM dans une URL (sélecteurs)
    - pinpoint_annotate : applique encadrés/flèches/numéros sur une image
    - pinpoint_show_me : workflow complet (capture + détection + annotation)
    - pinpoint_point_live : draw on the REAL desktop via the overlay daemon
    - pinpoint_show_me_live : capture + detect + draw on the real desktop
    - pinpoint_clear_live : wipe all live overlays
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

from pinpoint.capture.screen import ScreenCapture
from pinpoint.capture.web import WebCapture
from pinpoint.detect.ocr import OCRDetector
from pinpoint.detect.icons import IconDetector
from pinpoint.detect.elements import ElementDetector, ElementMatch
from pinpoint.render.annotate import annotate as render_annotate
from pinpoint.render.tutorial import TutorialBuilder, TutorialStep


# Dossier de travail pour les sorties (utilisateur peut overrider via env)
WORKDIR = Path(os.environ.get("PINPOINT_WORKDIR", tempfile.gettempdir())) / "pinpoint"
WORKDIR.mkdir(parents=True, exist_ok=True)


mcp = FastMCP(
    "pinpoint",
    instructions=(
        "Capture d'écran (web ou local) avec annotations visuelles intelligentes. "
        "Utilise pinpoint_show_me pour le workflow complet en un seul appel : "
        "il capture l'écran/URL, trouve l'élément demandé via OCR ou DOM, "
        "et retourne une image annotée avec encadrés rouges et flèches."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _next_output_path(prefix: str = "pinpoint", ext: str = "png") -> Path:
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
def pinpoint_list_monitors() -> str:
    """Liste tous les moniteurs/écrans disponibles avec leurs résolutions.

    Utile avant pinpoint_capture_screen pour savoir quel index utiliser
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
def pinpoint_capture_screen(
    monitor_index: int = 1,
    output_path: Optional[str] = None,
) -> str:
    """Capture un écran complet en PNG.

    Args:
        monitor_index: index du moniteur (1 = principal). Voir pinpoint_list_monitors.
        output_path: chemin de sortie optionnel. Si omis, génère un chemin temporaire.

    Returns:
        Chemin absolu du PNG créé.
    """
    capture = ScreenCapture()
    out = Path(output_path) if output_path else _next_output_path("screen")
    result = capture.capture_full(out, monitor_index=monitor_index)
    return str(result)


@mcp.tool
def pinpoint_capture_active_window(output_path: Optional[str] = None) -> str:
    """Capture la fenêtre active (Windows uniquement).

    Sur Linux/macOS, fallback sur le moniteur principal.
    """
    capture = ScreenCapture()
    out = Path(output_path) if output_path else _next_output_path("window")
    result = capture.capture_active_window(out)
    return str(result)


@mcp.tool
async def pinpoint_capture_url(
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
def pinpoint_find_text(
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
async def pinpoint_find_web_element(
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
def pinpoint_annotate(
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
async def pinpoint_show_me(
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
                        "Vérifie l'orthographe, ou utilise pinpoint_find_text avec "
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
def pinpoint_make_tutorial(
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




# ─────────────────────────────────────────────────────────────────────────────
# Icon detection (finds visual icons — Google G, GitHub octocat, etc.)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool
def pinpoint_fetch_favicon(
    domain: str,
    size: int = 128,
    output_path: Optional[str] = None,
) -> str:
    """Download a high-res icon for a domain via Google's favicon service.

    Args:
        domain: "google.com", "github.com", "discord.com", etc.
        size: requested px (64/128/256 all honoured by the service).
        output_path: where to save. Default: WORKDIR/<domain>_<size>.png

    Returns a JSON object with the saved path so you can feed it straight
    into pinpoint_find_icon.
    """
    import urllib.request as _ur
    dom = domain.replace("https://", "").replace("http://", "").split("/")[0]
    url = f"https://www.google.com/s2/favicons?domain={dom}&sz={size}"
    if output_path:
        out = Path(output_path)
    else:
        out = WORKDIR / f"favicon_{dom.replace('.', '_')}_{size}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _ur.urlopen(url, timeout=10) as r:
            out.write_bytes(r.read())
    except Exception as e:
        return json.dumps({"error": f"fetch failed: {e}", "url": url})
    return json.dumps({
        "domain": dom,
        "url": url,
        "saved_to": str(out),
        "size_bytes": out.stat().st_size,
    })


@mcp.tool
def pinpoint_find_icon(
    image_path: str,
    template_path: str,
    threshold: float = 0.55,
    max_matches: int = 10,
    confidence_gap: float = 0.12,
) -> str:
    """Find visual icon occurrences (template matching, not OCR).

    Uses multi-scale template matching + non-maximum suppression so one
    reference icon catches favicon-size AND bigger app-shortcut copies in
    the same screenshot. Auto-skips mask mode for opaque templates
    (~50x faster via FFT path).

    Args:
        image_path: screenshot to search in.
        template_path: reference icon PNG (e.g. a fetched favicon).
        threshold: minimum correlation score 0-1. 0.55 is permissive —
            returns everything that vaguely resembles the template so the
            gap filter can compare them.
        max_matches: cap on how many hits to return.
        confidence_gap: drop any match scoring more than this below the
            best hit. 0.12 kills typical false positives while keeping
            legitimate duplicate icons. Set to 0 to return every hit.

    Returns JSON list of bboxes with confidence + scale each match was
    found at, sorted by confidence descending.
    """
    src = _resolve_input_path(image_path)
    tpl = _resolve_input_path(template_path)

    hits = IconDetector(threshold=threshold).find(
        src, tpl, max_matches=max_matches, confidence_gap=confidence_gap,
    )
    return json.dumps([
        {
            "x": m.x, "y": m.y, "w": m.width, "h": m.height,
            "confidence": round(m.confidence, 3), "scale": m.scale,
            "center": list(m.center),
        }
        for m in hits
    ], indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# UI Automation element detection
#   "what OCR is for text, UIA is for interactive UI"
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool
def pinpoint_find_element(
    query: str,
    control_types: Optional[list[str]] = None,
    case_sensitive: bool = False,
    visible_only: bool = True,
    exact: bool = False,
    root_window_name: Optional[str] = None,
    max_matches: int = 30,
) -> str:
    """Find every UI element on the desktop whose name matches ``query``.

    Uses Windows UI Automation (the same API screen readers use). Each hit
    has a pixel-accurate bounding rectangle — feed these straight into
    pinpoint_point_live to paint red boxes on the real desktop.

    Args:
        query: substring of the element's accessible Name.
        control_types: restrict to these UIA types, e.g.
            ["ButtonControl","ImageControl","HyperlinkControl","ListItemControl"].
            None = any.
        case_sensitive: default False.
        visible_only: skip offscreen nodes (default True for the
            "point at something I can see right now" workflow).
        exact: require full Name equality instead of substring.
        root_window_name: if you know the app (e.g. "Google Chrome"),
            start the walk there - orders of magnitude faster than
            scanning the whole desktop.
        max_matches: cap on returned hits.

    Returns JSON list of {name, control_type, x, y, w, h, center,
    automation_id, class_name, is_offscreen, is_enabled, depth}.
    """
    if sys.platform != "win32":
        return json.dumps({"error": "UIA element detection is Windows-only"})

    detector = ElementDetector()
    hits = detector.find(
        query=query,
        control_types=control_types,
        case_sensitive=case_sensitive,
        visible_only=visible_only,
        exact=exact,
        root_window_name=root_window_name,
    )
    return json.dumps([
        {
            "name": m.name,
            "control_type": m.control_type,
            "x": m.x, "y": m.y, "w": m.width, "h": m.height,
            "center": list(m.center),
            "automation_id": m.automation_id,
            "class_name": m.class_name,
            "is_offscreen": m.is_offscreen,
            "is_enabled": m.is_enabled,
            "depth": m.depth,
        }
        for m in hits[:max_matches]
    ], indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Live overlay tools (drive the pinpoint-overlay daemon on the user's desktop)
# ─────────────────────────────────────────────────────────────────────────────

OVERLAY_BASE_URL = os.environ.get("PINPOINT_OVERLAY_URL", "http://127.0.0.1:8766")
_OVERLAY_HINT = (
    "Overlay daemon not reachable. Start it once with: "
    "`python -m pinpoint.overlay.daemon` (or `pinpoint-overlay`). "
    "It runs a transparent click-through window and listens on "
    f"{OVERLAY_BASE_URL}."
)


def _overlay_post(endpoint: str, payload: dict, timeout: float = 2.0) -> dict:
    """POST JSON to the local overlay daemon. Returns parsed JSON or {error}."""
    url = f"{OVERLAY_BASE_URL}{endpoint}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"error": f"overlay_unreachable: {e.reason}", "hint": _OVERLAY_HINT}
    except Exception as e:
        return {"error": f"overlay_error: {e.__class__.__name__}: {e}",
                "hint": _OVERLAY_HINT}


@mcp.tool
def pinpoint_point_live(
    x: int,
    y: int,
    w: int,
    h: int,
    ttl_ms: int = 4000,
    color: str = "#FF1744",
    label: Optional[str] = None,
) -> str:
    """Draw a red box (optional label) directly on the user's REAL desktop.

    Annotation appears on top of all windows, is click-through, and auto-fades
    after ``ttl_ms`` milliseconds. Requires the pinpoint-overlay daemon to be
    running (``python -m pinpoint.overlay.daemon``).

    Coordinates are in primary-monitor screen pixels. Use with output of
    pinpoint_find_text / pinpoint_find_web_element for "point at this on my
    real screen" workflows.
    """
    return json.dumps(_overlay_post("/point", {
        "x": int(x), "y": int(y), "w": int(w), "h": int(h),
        "ttl_ms": int(ttl_ms), "color": color, "label": label,
    }))


@mcp.tool
def pinpoint_arrow_live(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    ttl_ms: int = 4000,
    color: str = "#FF1744",
) -> str:
    """Draw a red arrow from (x1,y1) to (x2,y2) on the real desktop."""
    return json.dumps(_overlay_post("/arrow", {
        "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
        "ttl_ms": int(ttl_ms), "color": color,
    }))


@mcp.tool
def pinpoint_clear_live() -> str:
    """Wipe every active live annotation from the real desktop."""
    return json.dumps(_overlay_post("/clear", {}))


@mcp.tool
def pinpoint_show_me_live(
    target: str,
    source: str = "screen",
    monitor_index: int = 1,
    ttl_ms: int = 4500,
    color: str = "#FF1744",
    min_confidence: float = 55.0,
    draw_arrow: bool = True,
) -> str:
    """One-call live workflow: capture the screen, find ``target`` via OCR,
    and draw a red box + arrow on the user's REAL desktop (no PNG returned).

    Args:
        target: text to locate on screen (OCR match).
        source: "screen" for live capture, or a path to an existing image.
        monitor_index: 1 = primary on multi-monitor setups (see list_monitors).
        ttl_ms: how long annotations stay visible before fading.
        color: hex or CSS colour.
        min_confidence: OCR confidence floor, 0-100.
        draw_arrow: also draw an arrow pointing at the target.

    Returns JSON with the bbox that was found + the overlay daemon's ack.
    """
    if source == "screen":
        src = _next_output_path(prefix="live_src")
        ScreenCapture().capture_full(str(src), monitor_index=monitor_index)
    else:
        src = Path(source)
        if not src.exists():
            return json.dumps({"error": f"source not found: {source}"})

    matches = OCRDetector(min_confidence=min_confidence).find_text(src, target)
    if not matches:
        return json.dumps({
            "error": f"target not found on screen: {target!r}",
            "hint": "Check spelling, or lower min_confidence (try 40).",
            "capture": str(src),
        })

    best = max(matches, key=lambda m: m.confidence)
    rect_result = _overlay_post("/point", {
        "x": best.x, "y": best.y, "w": best.width, "h": best.height,
        "ttl_ms": int(ttl_ms), "color": color,
    })

    arrow_result = None
    if draw_arrow:
        # Arrow comes in from 80 px to the right of the match, points left.
        arrow_result = _overlay_post("/arrow", {
            "x1": best.x + best.width + 90,
            "y1": best.y + best.height // 2,
            "x2": best.x + best.width + 10,
            "y2": best.y + best.height // 2,
            "ttl_ms": int(ttl_ms), "color": color,
        })

    return json.dumps({
        "found": True,
        "target": target,
        "bbox": {"x": best.x, "y": best.y,
                 "w": best.width, "h": best.height,
                 "confidence": best.confidence},
        "overlay": rect_result,
        "arrow": arrow_result,
    }, indent=2)


def main():
    """Lance le serveur MCP en mode stdio (par défaut pour Claude Desktop)."""
    transport = os.environ.get("PINPOINT_TRANSPORT", "stdio")
    if transport == "http":
        port = int(os.environ.get("PINPOINT_PORT", "8765"))
        mcp.run(transport="http", port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
