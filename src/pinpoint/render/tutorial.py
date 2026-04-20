"""Mode tutoriel : génère une séquence d'images annotées numérotées
pour documenter un workflow étape par étape.

Cas d'usage typiques :
    - Documentation interne SCCM/Citrix (étapes 1..N pour technicien junior)
    - Rapports bug bounty (étapes de reproduction d'une vuln)
    - Onboarding clients Crowbyte (parcours utilisateur guidé)
    - Tutoriels publics CrowByte X/LinkedIn
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pinpoint.detect.ocr import OCRDetector, TextMatch
from pinpoint.render.annotate import annotate as render_annotate


@dataclass
class TutorialStep:
    """Une étape de tutoriel : ce qu'on cherche + comment l'annoter."""

    number: int
    target: str  # texte à trouver via OCR (ex "Approve scopes", "Login")
    caption: Optional[str] = None  # texte explicatif à afficher en callout
    annotation_style: str = "step_with_rect"  # voir _build_annotations
    color: str = "#FF1744"


@dataclass
class TutorialResult:
    """Résultat d'une étape de tutoriel."""

    step_number: int
    target: str
    found: bool
    output_path: Optional[Path] = None
    bbox: Optional[dict] = None
    error: Optional[str] = None


class TutorialBuilder:
    """Construit un tutoriel multi-images à partir d'un screenshot source."""

    def __init__(
        self,
        source_image: str | Path,
        output_dir: str | Path,
        prefix: str = "step",
        ocr_lang: str = "eng+fra",
    ):
        self.source_image = Path(source_image)
        if not self.source_image.exists():
            raise FileNotFoundError(f"Image source introuvable : {self.source_image}")

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.prefix = prefix
        self.detector = OCRDetector(lang=ocr_lang)

    def build(self, steps: list[TutorialStep]) -> list[TutorialResult]:
        """Génère N images annotées, une par étape."""
        results: list[TutorialResult] = []

        for step in steps:
            matches = self.detector.find_text(self.source_image, step.target)

            if not matches:
                results.append(
                    TutorialResult(
                        step_number=step.number,
                        target=step.target,
                        found=False,
                        error=f"Texte '{step.target}' introuvable par OCR",
                    )
                )
                continue

            # Prendre le match avec la meilleure confiance
            best = max(matches, key=lambda m: m.confidence)
            annotations = self._build_annotations(step, best)

            # Nom de sortie : prefix_01_target_summary.png
            safe_target = "".join(
                c if c.isalnum() else "_" for c in step.target.lower()
            )[:30]
            out_path = self.output_dir / f"{self.prefix}_{step.number:02d}_{safe_target}.png"

            render_annotate(str(self.source_image), str(out_path), annotations)

            results.append(
                TutorialResult(
                    step_number=step.number,
                    target=step.target,
                    found=True,
                    output_path=out_path,
                    bbox={
                        "x": best.x,
                        "y": best.y,
                        "w": best.width,
                        "h": best.height,
                        "confidence": round(best.confidence, 1),
                    },
                )
            )

        return results

    def _build_annotations(self, step: TutorialStep, match: TextMatch) -> list[dict]:
        """Construit la liste d'annotations pour une étape selon son style."""
        x, y, w, h = match.x, match.y, match.width, match.height
        pad = 8
        rect_x, rect_y = max(0, x - pad), max(0, y - pad)
        rect_w, rect_h = w + pad * 2, h + pad * 2

        annotations: list[dict] = []

        if step.annotation_style in ("step", "step_with_rect"):
            # Pastille numérotée placée à gauche de l'élément
            step_x = max(40, rect_x - 35)
            step_y = rect_y + rect_h // 2
            annotations.append({
                "type": "step",
                "x": step_x, "y": step_y,
                "number": step.number,
                "color": step.color,
                "radius": 26,
            })

        if step.annotation_style in ("rect", "step_with_rect", "rect_with_arrow"):
            annotations.append({
                "type": "rect",
                "x": rect_x, "y": rect_y, "w": rect_w, "h": rect_h,
                "color": step.color, "thickness": 5,
            })

        if step.annotation_style == "rect_with_arrow":
            arrow_x2 = rect_x - 5
            arrow_y2 = rect_y + rect_h // 2
            arrow_x1 = max(20, arrow_x2 - 130)
            annotations.append({
                "type": "arrow",
                "x1": arrow_x1, "y1": arrow_y2,
                "x2": arrow_x2, "y2": arrow_y2,
                "color": step.color, "thickness": 5,
            })

        if step.caption:
            # Callout texte placé sous l'élément, ou au-dessus si trop bas
            caption_y = rect_y + rect_h + 20
            annotations.append({
                "type": "text",
                "x": rect_x,
                "y": caption_y,
                "content": f"Étape {step.number}: {step.caption}",
                "color": step.color,
                "bg": "white",
                "size": 18,
                "padding": 10,
            })

        return annotations

    def build_combined(
        self,
        steps: list[TutorialStep],
        output_path: str | Path,
    ) -> Path:
        """Variante : génère UNE SEULE image avec toutes les étapes superposées.
        Utile pour vue d'ensemble / résumé.
        """
        all_annotations: list[dict] = []

        for step in steps:
            matches = self.detector.find_text(self.source_image, step.target)
            if not matches:
                continue
            best = max(matches, key=lambda m: m.confidence)
            all_annotations.extend(self._build_annotations(step, best))

        out = Path(output_path)
        render_annotate(str(self.source_image), str(out), all_annotations)
        return out
