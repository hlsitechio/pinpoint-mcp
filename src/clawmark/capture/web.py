"""Capture web via Playwright avec extraction DOM (Chrome DevTools Protocol)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page


@dataclass
class ElementBBox:
    """Bounding box d'un élément DOM, en pixels écran."""

    x: int
    y: int
    width: int
    height: int
    text: Optional[str] = None
    selector: Optional[str] = None

    def to_rect_annotation(self, color: str = "#FF1744", thickness: int = 4) -> dict:
        """Convertit en annotation 'rect' pour le module render."""
        return {
            "type": "rect",
            "x": self.x,
            "y": self.y,
            "w": self.width,
            "h": self.height,
            "color": color,
            "thickness": thickness,
        }


class WebCapture:
    """Capture de pages web + résolution d'éléments via DOM."""

    def __init__(
        self,
        headless: bool = True,
        viewport_width: int = 1440,
        viewport_height: int = 900,
        device_scale_factor: float = 1.0,
    ):
        self.headless = headless
        self.viewport = {"width": viewport_width, "height": viewport_height}
        self.device_scale_factor = device_scale_factor
        self._playwright = None
        self._browser: Optional[Browser] = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _new_page(self) -> Page:
        if not self._browser:
            raise RuntimeError("WebCapture non initialisé. Utiliser comme context manager.")
        context = await self._browser.new_context(
            viewport=self.viewport,
            device_scale_factor=self.device_scale_factor,
        )
        return await context.new_page()

    async def screenshot(
        self,
        url: str,
        output_path: str | Path,
        full_page: bool = True,
        wait_until: str = "networkidle",
        timeout_ms: int = 30000,
    ) -> Path:
        """Capture une page web et retourne le chemin du PNG."""
        page = await self._new_page()
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            output_path = Path(output_path)
            await page.screenshot(path=str(output_path), full_page=full_page)
            return output_path
        finally:
            await page.context.close()

    async def screenshot_with_elements(
        self,
        url: str,
        output_path: str | Path,
        selectors: list[str],
        full_page: bool = True,
        wait_until: str = "networkidle",
        timeout_ms: int = 30000,
    ) -> tuple[Path, list[ElementBBox]]:
        """Capture une page + résout les bbox des éléments demandés.

        Selectors peuvent être :
        - CSS: 'button.primary', '#submit'
        - Text: 'text=Approve scopes' (Playwright text selector)
        - Role: 'role=button[name="Submit"]'
        - XPath: 'xpath=//button[text()="Submit"]'
        """
        page = await self._new_page()
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)

            bboxes: list[ElementBBox] = []
            for selector in selectors:
                try:
                    locator = page.locator(selector).first
                    box = await locator.bounding_box(timeout=5000)
                    if box is None:
                        continue
                    text = await locator.text_content(timeout=2000) or None
                    bboxes.append(
                        ElementBBox(
                            x=int(box["x"]),
                            y=int(box["y"]),
                            width=int(box["width"]),
                            height=int(box["height"]),
                            text=text.strip() if text else None,
                            selector=selector,
                        )
                    )
                except Exception as e:
                    # On log mais on continue pour les autres sélecteurs
                    print(f"[warn] Sélecteur '{selector}' introuvable: {e}")

            output_path = Path(output_path)
            await page.screenshot(path=str(output_path), full_page=full_page)
            return output_path, bboxes
        finally:
            await page.context.close()

    async def find_text(
        self,
        url: str,
        text_query: str,
        wait_until: str = "networkidle",
        timeout_ms: int = 30000,
    ) -> list[ElementBBox]:
        """Trouve tous les éléments contenant un texte donné. Utile pour
        'pointe le bouton qui dit Approve' sans connaître le sélecteur exact.
        """
        page = await self._new_page()
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            # Playwright text= matche partiellement et insensible à la casse par défaut
            locators = page.get_by_text(text_query, exact=False)
            count = await locators.count()

            results = []
            for i in range(count):
                loc = locators.nth(i)
                try:
                    box = await loc.bounding_box(timeout=2000)
                    if box is None:
                        continue
                    text = await loc.text_content(timeout=1000) or text_query
                    results.append(
                        ElementBBox(
                            x=int(box["x"]),
                            y=int(box["y"]),
                            width=int(box["width"]),
                            height=int(box["height"]),
                            text=text.strip(),
                            selector=f"text={text_query}",
                        )
                    )
                except Exception:
                    continue
            return results
        finally:
            await page.context.close()
