"""UI-Automation-based element detection.

What OCR is for text, UIA is for interactive UI: every Windows app (and any
web content inside a browser) publishes its buttons, links, icons, list items
etc. through the accessibility tree. Each node has a Name, ControlType, and a
pixel-accurate bounding rectangle — no template, no OCR, no cv2, just a tree
walk on the live desktop.

Typical usage:

    from pinpoint.detect.elements import ElementDetector
    d = ElementDetector()
    matches = d.find("DeepSeek", visible_only=True)
    for m in matches:
        print(m.name, m.control_type, m.x, m.y, m.width, m.height)

Windows only (uiautomation module wraps the Win32 UIA COM API). macOS
equivalent would wrap AXUIElement; Linux would use AT-SPI.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class ElementMatch:
    """One hit in the UI tree. Coordinates are in virtual-screen pixels."""
    name: str
    control_type: str   # "ButtonControl", "TextControl", "ImageControl", ...
    x: int
    y: int
    width: int
    height: int
    depth: int          # how deep in the tree (0 = direct window child)
    automation_id: str = ""
    class_name: str = ""
    is_offscreen: bool = False
    is_enabled: bool = True

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def to_rect_annotation(self, color: str = "#FF1744", thickness: int = 3) -> dict:
        return {
            "type": "rect",
            "x": self.x, "y": self.y,
            "w": self.width, "h": self.height,
            "color": color, "thickness": thickness,
        }


class ElementDetector:
    """Walks the UIA tree depth-first, stopping early at ``max_depth`` and
    ``max_nodes``. Sub-second on typical desktops if you skip offscreen nodes.
    """

    def __init__(
        self,
        max_depth: int = 14,
        max_nodes: int = 8000,
        timeout_s: float = 4.0,
    ) -> None:
        """
        Args:
            max_depth: tree depth cap. 14 covers even deeply-nested web pages
                wrapped inside a browser tab.
            max_nodes: hard ceiling on how many nodes to visit per call. Stops
                runaway walks on pathological apps.
            timeout_s: wall-clock budget. Returns whatever was found when hit.
        """
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.timeout_s = timeout_s

    # ── public api ────────────────────────────────────────────────────────────

    def find(
        self,
        query: str,
        control_types: Optional[Iterable[str]] = None,
        case_sensitive: bool = False,
        visible_only: bool = True,
        exact: bool = False,
        root_window_name: Optional[str] = None,
    ) -> list[ElementMatch]:
        """Return every UI element whose Name matches ``query``.

        Args:
            query: substring (or exact name) to look for.
            control_types: restrict to these UIA control types, e.g.
                ("ButtonControl", "ImageControl", "HyperlinkControl").
                None = any.
            case_sensitive: default False for friendlier matching.
            visible_only: skip ``IsOffscreen`` nodes. True for "point me at
                something on my screen right now" workflows.
            exact: if True, require full Name equality instead of substring.
            root_window_name: if set, start the walk at the window with this
                title (speeds up enormously when you know which app).
        """
        if sys.platform != "win32":
            raise RuntimeError("ElementDetector currently supports Windows only")

        import uiautomation as auto   # late import: heavy COM init

        needle = query if case_sensitive else query.lower()
        wanted_types = set(control_types or [])

        deadline = time.monotonic() + self.timeout_s
        matches: list[ElementMatch] = []
        visited = 0

        if root_window_name:
            root = auto.WindowControl(searchDepth=1, Name=root_window_name)
            if not root.Exists(0.5):
                return []
            roots = [root]
        else:
            # All top-level windows on the desktop.
            desktop = auto.GetRootControl()
            roots = desktop.GetChildren()

        def pred(name: str) -> bool:
            if exact:
                return (name == query) if case_sensitive else (name.lower() == needle)
            return needle in (name if case_sensitive else name.lower())

        # Iterative DFS so we can cap depth / nodes without recursion overhead.
        stack: list[tuple[object, int]] = [(c, 0) for c in roots]

        while stack and visited < self.max_nodes and time.monotonic() < deadline:
            node, depth = stack.pop()
            visited += 1

            try:
                # Cheap properties first — if they fail we skip the subtree.
                name = node.Name or ""
                ctrl_type = node.ControlTypeName or ""
                rect = node.BoundingRectangle
            except Exception:
                continue

            if visible_only:
                try:
                    if node.IsOffscreen:
                        continue
                except Exception:
                    pass

            # Collapse zero-size rects (some invisible wrappers).
            w = rect.width() if hasattr(rect, "width") else (rect.right - rect.left)
            h = rect.height() if hasattr(rect, "height") else (rect.bottom - rect.top)
            x = rect.left
            y = rect.top

            if w > 0 and h > 0 and name and pred(name):
                if not wanted_types or ctrl_type in wanted_types:
                    try:
                        auto_id = node.AutomationId or ""
                    except Exception:
                        auto_id = ""
                    try:
                        cls = node.ClassName or ""
                    except Exception:
                        cls = ""
                    try:
                        is_off = bool(node.IsOffscreen)
                    except Exception:
                        is_off = False
                    try:
                        is_en = bool(node.IsEnabled)
                    except Exception:
                        is_en = True
                    matches.append(ElementMatch(
                        name=name, control_type=ctrl_type,
                        x=int(x), y=int(y), width=int(w), height=int(h),
                        depth=depth, automation_id=auto_id, class_name=cls,
                        is_offscreen=is_off, is_enabled=is_en,
                    ))

            if depth < self.max_depth:
                try:
                    for child in reversed(node.GetChildren() or []):
                        stack.append((child, depth + 1))
                except Exception:
                    continue

        return matches
