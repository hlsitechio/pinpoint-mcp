"""Icon detection via multi-scale template matching.

OCR finds TEXT, not ICONS. `IconDetector` locates visual icons (Google "G",
GitHub octocat, Discord logo, etc.) inside any screenshot. It uses OpenCV
template matching across several scales, with non-maximum suppression so
overlapping hits at adjacent scales collapse into a single clean match.

Typical usage:

    from pinpoint.detect.icons import IconDetector
    d = IconDetector()
    matches = d.find("screen.png", "google_logo.png", threshold=0.72)
    for m in matches:
        print(m.x, m.y, m.width, m.height, m.confidence, m.scale)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image


@dataclass
class IconMatch:
    """One template-matching hit. Coordinates are in source-image pixels."""
    x: int
    y: int
    width: int
    height: int
    confidence: float   # 0-1, OpenCV TM_CCOEFF_NORMED score
    scale: float        # which rescaling of the template produced the hit

    def to_rect_annotation(self, color: str = "#FF1744", thickness: int = 3) -> dict:
        return {
            "type": "rect",
            "x": self.x, "y": self.y,
            "w": self.width, "h": self.height,
            "color": color, "thickness": thickness,
        }

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


class IconDetector:
    """Multi-scale template matcher with NMS."""

    # Target sizes (in screen pixels) that UI icons typically render at.
    # Covers browser favicons (16-24), taskbar / app shortcuts (32-64),
    # hero logos (96-128), and the occasional big CTA icon (160).
    DEFAULT_TARGET_SIZES_PX: tuple[int, ...] = (20, 28, 36, 48, 64, 96, 128)

    def __init__(
        self,
        threshold: float = 0.8,
        target_sizes_px: Optional[tuple[int, ...]] = None,
        scales: Optional[tuple[float, ...]] = None,
        nms_iou: float = 0.35,
    ) -> None:
        """
        Args:
            threshold: minimum TM_CCORR_NORMED correlation (0-1) to count.
                0.8 is a clean default for masked colour matching.
            target_sizes_px: pixel sizes the template is resized to before
                matching. Overrides ``scales`` if set. Default sweeps
                20-128 px which covers almost every UI icon rendering.
            scales: alternative way to specify scaling — raw multipliers
                on the template's native size. Ignored if ``target_sizes_px``
                is set.
            nms_iou: IoU above which overlapping matches are merged.
        """
        self.threshold = threshold
        self.target_sizes_px = target_sizes_px or self.DEFAULT_TARGET_SIZES_PX
        self.scales = scales  # only used when target_sizes_px is None AND scales is set
        self.nms_iou = nms_iou

    # ── public api ────────────────────────────────────────────────────────────

    def find(
        self,
        image_path: str | Path,
        template_path: str | Path,
        max_matches: int = 20,
        confidence_gap: float = 0.12,
    ) -> list[IconMatch]:
        """Return up to ``max_matches`` hits of ``template_path`` inside
        ``image_path``, sorted by confidence descending.

        Args:
            max_matches: hard cap on returned hits.
            confidence_gap: if a match scores more than ``confidence_gap``
                below the best hit, it's treated as noise and dropped.
                Typical clean logo: best=0.91, false positives cap at
                0.77 — a gap of 0.14 kills all the noise. Set to 0 to
                disable and get every hit above threshold.

        Strategy: colour template matching (BGR) with the template's alpha
        channel as a mask when mostly-transparent; otherwise the fast FFT
        path (TM_CCOEFF_NORMED). Multi-scale sweep + NMS.
        """
        src = _load_bgr(image_path)
        tpl_bgr, tpl_mask = _load_bgr_and_mask(template_path)

        # Masked matchTemplate in OpenCV is ~10-50x slower than unmasked
        # because it falls back to a sum-of-squared-differences algorithm.
        # If the template is essentially fully opaque (>95 % of pixels),
        # the mask buys us nothing — drop it and use the fast FFT path.
        if tpl_mask is not None:
            opaque_frac = float((tpl_mask > 0).sum()) / tpl_mask.size
            if opaque_frac >= 0.95:
                tpl_mask = None

        raw: list[IconMatch] = []
        src_h, src_w = src.shape[:2]
        tpl_h, tpl_w = tpl_bgr.shape[:2]

        # Build the list of (target_w, target_h, scale) to try.
        if self.target_sizes_px:
            # Aspect-preserving: use the larger side to derive scale.
            long_side = max(tpl_w, tpl_h)
            plan = []
            for target_px in self.target_sizes_px:
                s = target_px / long_side
                th_, tw_ = int(round(tpl_h * s)), int(round(tpl_w * s))
                plan.append((tw_, th_, s))
        else:
            scales = self.scales or (0.5, 0.75, 1.0, 1.25, 1.5)
            plan = [(int(round(tpl_w * s)), int(round(tpl_h * s)), s) for s in scales]

        for tw, th, s in plan:
            if th < 8 or tw < 8 or th > src_h or tw > src_w:
                continue
            tpl_s = cv2.resize(tpl_bgr, (tw, th), interpolation=cv2.INTER_AREA)
            mask_s = None
            if tpl_mask is not None:
                mask_s = cv2.resize(tpl_mask, (tw, th), interpolation=cv2.INTER_NEAREST)

            # Fast path: no mask -> TM_CCOEFF_NORMED uses an FFT and is
            # orders of magnitude faster than masked TM_CCORR_NORMED.
            if mask_s is None:
                result = cv2.matchTemplate(src, tpl_s, cv2.TM_CCOEFF_NORMED)
            else:
                result = cv2.matchTemplate(src, tpl_s, cv2.TM_CCORR_NORMED, mask=mask_s)
            result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
            ys, xs = np.where(result >= self.threshold)
            for y, x in zip(ys, xs):
                raw.append(IconMatch(
                    x=int(x), y=int(y),
                    width=tw, height=th,
                    confidence=float(result[y, x]),
                    scale=float(s),
                ))

        # NMS across all scales.
        merged = _nms(raw, self.nms_iou)
        merged.sort(key=lambda m: m.confidence, reverse=True)

        # Gap-based noise trim: once we're more than `confidence_gap` below
        # the best hit, stop — subsequent matches are almost certainly
        # unrelated things that happen to share some colour / shape.
        if merged and confidence_gap > 0:
            top = merged[0].confidence
            cutoff = top - confidence_gap
            merged = [m for m in merged if m.confidence >= cutoff]

        return merged[:max_matches]

    # Convenience: find at most one hit (best across all scales).
    def find_best(
        self,
        image_path: str | Path,
        template_path: str | Path,
    ) -> Optional[IconMatch]:
        hits = self.find(image_path, template_path, max_matches=1)
        return hits[0] if hits else None


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_bgr(path: str | Path) -> np.ndarray:
    """Load an image as a BGR (OpenCV-native) numpy array.
    Transparent pixels are composited over mid-gray (127) so they don't
    push the correlation in any particular direction."""
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (127, 127, 127))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    arr = np.array(img)  # RGB
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _load_bgr_and_mask(path: str | Path) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """Load template as (BGR_3chan, mask_1chan or None).
    Returns an 8-bit mask where 255 = opaque template pixel, 0 = transparent.
    If the file has no alpha channel, mask is None (match the full rectangle).
    """
    img = Image.open(path)
    mask: Optional[np.ndarray] = None
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        r, g, b, a = img.split()
        rgb = Image.merge("RGB", (r, g, b))
        mask = np.array(a, dtype=np.uint8)
        # Binarise the mask: anything above 32/255 counts as opaque.
        mask = np.where(mask > 32, 255, 0).astype(np.uint8)
        arr = np.array(rgb)
    else:
        arr = np.array(img.convert("RGB"))
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return bgr, mask


def _iou(a: IconMatch, b: IconMatch) -> float:
    ax2, ay2 = a.x + a.width, a.y + a.height
    bx2, by2 = b.x + b.width, b.y + b.height
    ix = max(0, min(ax2, bx2) - max(a.x, b.x))
    iy = max(0, min(ay2, by2) - max(a.y, b.y))
    inter = ix * iy
    if inter == 0:
        return 0.0
    union = a.width * a.height + b.width * b.height - inter
    return inter / union


def _nms(boxes: list[IconMatch], iou_threshold: float) -> list[IconMatch]:
    """Greedy non-maximum suppression: sort by confidence, keep a box only if
    it doesn't overlap >iou_threshold with any already-kept higher-confidence
    box."""
    sorted_boxes = sorted(boxes, key=lambda m: m.confidence, reverse=True)
    kept: list[IconMatch] = []
    for cand in sorted_boxes:
        if all(_iou(cand, k) < iou_threshold for k in kept):
            kept.append(cand)
    return kept
