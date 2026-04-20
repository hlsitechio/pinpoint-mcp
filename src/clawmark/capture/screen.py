"""Capture écran cross-platform via mss (rapide, zéro dépendance native)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import mss
import mss.tools
from PIL import Image


@dataclass
class MonitorInfo:
    index: int
    left: int
    top: int
    width: int
    height: int
    is_primary: bool

    @property
    def label(self) -> str:
        primary = " (principal)" if self.is_primary else ""
        return f"Moniteur {self.index}: {self.width}×{self.height}{primary}"


class ScreenCapture:
    """Capture d'écran local avec support multi-moniteur."""

    def list_monitors(self) -> list[MonitorInfo]:
        """Liste tous les moniteurs disponibles. Index 0 = écran virtuel global,
        Index 1+ = moniteurs physiques individuels.
        """
        with mss.mss() as sct:
            monitors = []
            # mss.monitors[0] est l'écran virtuel englobant tous les écrans
            # On ne l'expose pas comme "physique" mais on le rend disponible via index 0
            for idx, mon in enumerate(sct.monitors):
                monitors.append(
                    MonitorInfo(
                        index=idx,
                        left=mon["left"],
                        top=mon["top"],
                        width=mon["width"],
                        height=mon["height"],
                        is_primary=(idx == 1),  # mss: index 1 = moniteur primaire
                    )
                )
            return monitors

    def capture_full(
        self,
        output_path: str | Path,
        monitor_index: int = 1,
    ) -> Path:
        """Capture un moniteur entier. Par défaut le moniteur principal."""
        output_path = Path(output_path)
        with mss.mss() as sct:
            if monitor_index >= len(sct.monitors):
                raise ValueError(
                    f"Moniteur {monitor_index} inexistant. "
                    f"{len(sct.monitors) - 1} moniteurs détectés (1 à {len(sct.monitors) - 1})."
                )
            mon = sct.monitors[monitor_index]
            screenshot = sct.grab(mon)
            mss.tools.to_png(screenshot.rgb, screenshot.size, output=str(output_path))
        return output_path

    def capture_region(
        self,
        output_path: str | Path,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> Path:
        """Capture une région absolue de l'écran virtuel.

        Coordonnées en pixels dans l'espace de l'écran virtuel global
        (utile pour multi-moniteur). Pour les coordonnées relatives à un
        moniteur, ajouter monitor.left/monitor.top.
        """
        output_path = Path(output_path)
        region = {"left": x, "top": y, "width": width, "height": height}
        with mss.mss() as sct:
            screenshot = sct.grab(region)
            mss.tools.to_png(screenshot.rgb, screenshot.size, output=str(output_path))
        return output_path

    def capture_active_window(self, output_path: str | Path) -> Path:
        """Capture la fenêtre active (Windows uniquement pour l'instant).

        Sur Linux/macOS: fallback sur capture du moniteur principal avec un
        message d'avertissement. Une vraie implémentation cross-platform
        nécessiterait pywin32 (Windows), AppKit (macOS), python-xlib (Linux).
        """
        import sys

        if sys.platform == "win32":
            return self._capture_active_window_windows(output_path)
        else:
            print(
                f"[warn] capture_active_window non supporté sur {sys.platform}. "
                "Fallback sur capture du moniteur principal."
            )
            return self.capture_full(output_path, monitor_index=1)

    def _capture_active_window_windows(self, output_path: str | Path) -> Path:
        """Implémentation Windows via ctypes (pas de dépendance pywin32)."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()

        rect = wintypes.RECT()
        # GetWindowRect retourne les coordonnées dans l'espace écran
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError("Impossible d'obtenir les coordonnées de la fenêtre active.")

        x, y = rect.left, rect.top
        width, height = rect.right - rect.left, rect.bottom - rect.top

        if width <= 0 or height <= 0:
            raise RuntimeError(f"Fenêtre active a des dimensions invalides: {width}x{height}")

        return self.capture_region(output_path, x, y, width, height)
