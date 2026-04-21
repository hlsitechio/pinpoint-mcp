"""pinpoint overlay daemon.

A transparent, always-on-top, click-through window that paints pinpoint
annotations directly onto the user's real desktop. Designed to be driven by
the pinpoint MCP server over localhost HTTP.

Run it as:

    python -m pinpoint.overlay.daemon
    # or with the console script
    pinpoint-overlay

HTTP endpoints (POST, JSON body) on 127.0.0.1:PINPOINT_OVERLAY_PORT (default 8766):

    POST /point    {x, y, w, h, ttl_ms=4000, color="#FF1744", label=null}
    POST /arrow    {x1, y1, x2, y2, ttl_ms=4000, color="#FF1744"}
    POST /clear    {}
    GET  /health   -> {"ok": true, "platform": "win32", "screen": [w, h]}

Windows-only for now (uses WS_EX_LAYERED + WS_EX_TRANSPARENT). macOS / Linux
follow-ups go through NSPanel / X11 shape extensions.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ── Win32 constants for click-through transparent overlay ─────────────────────
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

# A "magic" colour the compositor will treat as fully transparent.
# Pick one the user is unlikely to use in real annotations.
TRANSPARENT_KEY = "#010203"

DEFAULT_PORT = int(os.environ.get("PINPOINT_OVERLAY_PORT", "8766"))
DEFAULT_HOST = os.environ.get("PINPOINT_OVERLAY_HOST", "127.0.0.1")
FRAME_MS = 16  # ~60 fps


class OverlayApp:
    """Tk canvas covering the primary monitor, driven by a thread-safe queue."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("pinpoint-overlay")
        self.root.overrideredirect(True)        # no title bar
        self.root.attributes("-topmost", True)  # stay above normal windows

        # Cover primary monitor. Multi-monitor is a follow-up: we'd spawn one
        # Toplevel per mss monitor entry and map screen-space coords to each.
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.screen_size = (sw, sh)
        self.root.geometry(f"{sw}x{sh}+0+0")

        # Make the magic background colour fully transparent.
        self.root.wm_attributes("-transparentcolor", TRANSPARENT_KEY)

        self.canvas = tk.Canvas(
            self.root,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
            width=sw,
            height=sh,
        )
        self.canvas.pack(fill="both", expand=True)

        if sys.platform == "win32":
            self._make_click_through()

        self.cmd_queue: "queue.Queue[dict]" = queue.Queue()
        self.active: dict[int, float] = {}   # canvas_item_id -> expires_at_monotonic

        self.root.after(FRAME_MS, self._pump)

    # ── click-through / no-activate on Windows ────────────────────────────────

    def _make_click_through(self) -> None:
        """OR the extended-window flags so clicks pass through to apps below."""
        # Tk hides the real HWND; the parent of the canvas HWND is the toplevel.
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        user32 = ctypes.windll.user32
        # Prefer the *W variants on 64-bit Python.
        GetWindowLong = user32.GetWindowLongW
        SetWindowLong = user32.SetWindowLongW
        GetWindowLong.restype = wintypes.LONG
        SetWindowLong.restype = wintypes.LONG

        ex = GetWindowLong(hwnd, GWL_EXSTYLE)
        ex |= (
            WS_EX_LAYERED
            | WS_EX_TRANSPARENT   # clicks pass through
            | WS_EX_TOOLWINDOW    # no taskbar / Alt-Tab entry
            | WS_EX_TOPMOST
            | WS_EX_NOACTIVATE    # never steal focus
        )
        SetWindowLong(hwnd, GWL_EXSTYLE, ex)

    # ── main pump: drain queue, draw, expire ─────────────────────────────────

    def _pump(self) -> None:
        while True:
            try:
                cmd = self.cmd_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_cmd(cmd)

        now = time.monotonic()
        expired = [cid for cid, exp in self.active.items() if exp <= now]
        for cid in expired:
            try:
                self.canvas.delete(cid)
            except tk.TclError:
                pass
            self.active.pop(cid, None)

        self.root.after(FRAME_MS, self._pump)

    def _handle_cmd(self, cmd: dict) -> None:
        op = cmd.get("op")
        if op == "point":
            self._draw_point(cmd)
        elif op == "arrow":
            self._draw_arrow(cmd)
        elif op == "clear":
            self.canvas.delete("all")
            self.active.clear()

    # ── primitives ────────────────────────────────────────────────────────────

    def _draw_point(self, cmd: dict) -> None:
        color = cmd.get("color", "#FF1744")
        ttl = float(cmd.get("ttl_ms", 4000)) / 1000.0
        x = int(cmd["x"]); y = int(cmd["y"])
        w = int(cmd["w"]); h = int(cmd["h"])
        label = cmd.get("label")

        # stroked rect, 3 px
        rect_id = self.canvas.create_rectangle(
            x, y, x + w, y + h, outline=color, width=3,
        )
        self.active[rect_id] = time.monotonic() + ttl

        if label:
            text_id = self.canvas.create_text(
                x + w + 12, y + h // 2, text=str(label), anchor="w",
                fill=color, font=("Segoe UI", 14, "bold"),
            )
            self.active[text_id] = time.monotonic() + ttl

    def _draw_arrow(self, cmd: dict) -> None:
        color = cmd.get("color", "#FF1744")
        ttl = float(cmd.get("ttl_ms", 4000)) / 1000.0
        x1 = int(cmd["x1"]); y1 = int(cmd["y1"])
        x2 = int(cmd["x2"]); y2 = int(cmd["y2"])
        arrow_id = self.canvas.create_line(
            x1, y1, x2, y2, fill=color, width=3,
            arrow=tk.LAST, arrowshape=(14, 16, 6),
        )
        self.active[arrow_id] = time.monotonic() + ttl

    def run(self) -> None:
        self.root.mainloop()


# ── HTTP front-end ────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    app: OverlayApp = None  # set by main()

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._send_json(200, {
                "ok": True,
                "platform": sys.platform,
                "screen": list(self.app.screen_size),
                "pid": os.getpid(),
                "active_items": len(self.app.active),
            })
            return
        self._send_json(404, {"error": "unknown endpoint"})

    def do_POST(self) -> None:
        data = self._read_json()
        path = self.path.rstrip("/")
        if path == "/point":
            data["op"] = "point"
        elif path == "/arrow":
            data["op"] = "arrow"
        elif path == "/clear":
            data["op"] = "clear"
        else:
            self._send_json(404, {"error": "unknown endpoint", "path": path})
            return
        self.app.cmd_queue.put(data)
        self._send_json(200, {"ok": True, "op": data["op"]})

    def log_message(self, fmt: str, *args) -> None:
        # Keep stdout clean; only log failures.
        if args and isinstance(args[0], int) and args[0] >= 400:
            sys.stderr.write("[overlay] %s - %s\n" % (self.address_string(), fmt % args))


def main() -> None:
    app = OverlayApp()
    Handler.app = app

    server = ThreadingHTTPServer((DEFAULT_HOST, DEFAULT_PORT), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    print(f"[pinpoint-overlay] listening on http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"[pinpoint-overlay] screen: {app.screen_size[0]}x{app.screen_size[1]} (primary monitor)")
    print(f"[pinpoint-overlay] Ctrl+C in this terminal to quit.")

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
