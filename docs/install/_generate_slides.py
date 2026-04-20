"""Generate terminal-style install-tutorial PNGs + annotate them."""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
OUT = ROOT

# Design tokens
W, H = 1280, 760
BG = (26, 27, 38)            # #1a1b26 - editor dark
TAB_BG = (35, 36, 48)
TITLE_BG = (16, 17, 28)
TEXT = (192, 202, 245)        # body
MUTED = (86, 95, 137)
PROMPT_PS = (159, 216, 255)   # cyan-ish
PROMPT_PATH = (99, 158, 231)  # blue
SUCCESS = (154, 235, 161)     # green
WARN = (226, 179, 119)        # orange
ERROR = (247, 118, 142)       # red
COMMAND = (255, 255, 255)
ACCENT = (187, 154, 247)      # purple
COMMENT = (86, 95, 137)


def _find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    # Try Cascadia Code / Consolas / DejaVu Sans Mono
    candidates = [
        r"C:\Windows\Fonts\CascadiaMono.ttf",
        r"C:\Windows\Fonts\CascadiaCode.ttf",
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\arial.ttf",  # fallback for title
    ]
    if bold:
        candidates.insert(0, r"C:\Windows\Fonts\CascadiaMono-Bold.ttf")
        candidates.insert(1, r"C:\Windows\Fonts\consolab.ttf")
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


FONT_MONO = _find_font(16)
FONT_MONO_BOLD = _find_font(16, bold=True)
FONT_TITLE = _find_font(14)


def make_terminal(tab_label: str, lines: list[tuple[str, str]], out_path: Path) -> Path:
    """Render terminal PNG. Lines: list of (kind, text).
    kinds: 'prompt', 'cmd', 'output', 'success', 'warn', 'error', 'comment', 'blank', 'info'
    """
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Title bar
    draw.rectangle([(0, 0), (W, 30)], fill=TITLE_BG)
    # Traffic-light-ish tab indicator
    draw.rectangle([(12, 6), (280, 28)], fill=TAB_BG, outline=(60, 64, 82))
    draw.text((22, 8), f"\u25b8 {tab_label}", fill=(200, 208, 240), font=FONT_TITLE)
    # Window controls on right
    for i, col in enumerate([(90, 95, 120), (90, 95, 120), (240, 113, 120)]):
        cx = W - 60 + i * 18
        draw.ellipse([(cx - 5, 11), (cx + 5, 21)], fill=col)

    # Body
    x0, y = 20, 50
    line_h = 22
    for kind, text in lines:
        if kind == "blank":
            y += line_h
            continue
        if kind == "prompt":
            # Split "PS C:\path>" into colors
            if text.startswith("PS ") and ">" in text:
                ps, rest = text.split(" ", 1)
                path_part, _, _ = rest.partition(">")
                draw.text((x0, y), "PS ", fill=PROMPT_PS, font=FONT_MONO_BOLD)
                draw.text((x0 + _w("PS ", FONT_MONO_BOLD), y), path_part, fill=PROMPT_PATH, font=FONT_MONO_BOLD)
                draw.text((x0 + _w("PS " + path_part, FONT_MONO_BOLD), y), ">", fill=TEXT, font=FONT_MONO_BOLD)
            else:
                draw.text((x0, y), text, fill=PROMPT_PS, font=FONT_MONO_BOLD)
        elif kind == "cmd":
            # Indent after prompt to show typed command
            draw.text((x0, y), text, fill=COMMAND, font=FONT_MONO_BOLD)
        elif kind == "prompt+cmd":
            # One-line prompt + command combined
            prompt, cmd = text.split("||", 1)
            ps, rest = prompt.split(" ", 1)
            path_part, _, _ = rest.partition(">")
            draw.text((x0, y), "PS ", fill=PROMPT_PS, font=FONT_MONO_BOLD)
            draw.text((x0 + _w("PS ", FONT_MONO_BOLD), y), path_part, fill=PROMPT_PATH, font=FONT_MONO_BOLD)
            draw.text((x0 + _w("PS " + path_part, FONT_MONO_BOLD), y), "> ", fill=TEXT, font=FONT_MONO_BOLD)
            draw.text((x0 + _w("PS " + path_part + "> ", FONT_MONO_BOLD), y), cmd, fill=COMMAND, font=FONT_MONO_BOLD)
        elif kind == "output":
            draw.text((x0, y), text, fill=TEXT, font=FONT_MONO)
        elif kind == "success":
            draw.text((x0, y), text, fill=SUCCESS, font=FONT_MONO_BOLD)
        elif kind == "warn":
            draw.text((x0, y), text, fill=WARN, font=FONT_MONO)
        elif kind == "error":
            draw.text((x0, y), text, fill=ERROR, font=FONT_MONO)
        elif kind == "comment":
            draw.text((x0, y), text, fill=COMMENT, font=FONT_MONO)
        elif kind == "info":
            draw.text((x0, y), text, fill=ACCENT, font=FONT_MONO)
        else:
            draw.text((x0, y), text, fill=TEXT, font=FONT_MONO)
        y += line_h

    img.save(out_path)
    return out_path


def _w(text: str, font) -> int:
    l, t, r, b = font.getbbox(text)
    return r - l


def make_json_viewer(title: str, json_text: str, out_path: Path) -> Path:
    """Render a VSCode-style JSON viewer PNG."""
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Title bar
    draw.rectangle([(0, 0), (W, 30)], fill=TITLE_BG)
    draw.rectangle([(12, 6), (480, 28)], fill=TAB_BG, outline=(60, 64, 82))
    draw.text((22, 8), f"\u25b8 {title}", fill=(200, 208, 240), font=FONT_TITLE)

    # Line number gutter
    gutter_w = 60
    draw.rectangle([(0, 30), (gutter_w, H)], fill=(22, 23, 34))

    # Render JSON with simple syntax colors
    lines = json_text.split("\n")
    y = 50
    for i, line in enumerate(lines, start=1):
        # line number
        ln_text = f"{i:>3}"
        draw.text((12, y), ln_text, fill=MUTED, font=FONT_MONO)
        # content with simple tokenizing
        x = gutter_w + 12
        _draw_json_line(draw, line, x, y)
        y += 22

    img.save(out_path)
    return out_path


def _draw_json_line(draw: ImageDraw.ImageDraw, line: str, x: int, y: int):
    """Draw a JSON line with naive token coloring."""
    i = 0
    cursor = x
    in_string = False
    token_start = 0
    buf = ""

    def flush(color):
        nonlocal cursor, buf
        if buf:
            draw.text((cursor, y), buf, fill=color, font=FONT_MONO)
            cursor += _w(buf, FONT_MONO)
            buf = ""

    while i < len(line):
        c = line[i]
        if c == '"':
            flush(TEXT)
            # read string to next unescaped quote
            j = i + 1
            while j < len(line) and line[j] != '"':
                if line[j] == "\\" and j + 1 < len(line):
                    j += 2
                else:
                    j += 1
            s = line[i:j + 1]
            # string after colon? → value (orange); else key (cyan)
            tail = line[j + 1:].lstrip()
            is_key = tail.startswith(":")
            color = PROMPT_PS if is_key else WARN
            draw.text((cursor, y), s, fill=color, font=FONT_MONO)
            cursor += _w(s, FONT_MONO)
            i = j + 1
        elif c in "{}[]":
            flush(TEXT)
            draw.text((cursor, y), c, fill=ACCENT, font=FONT_MONO)
            cursor += _w(c, FONT_MONO)
            i += 1
        elif c == ":":
            flush(TEXT)
            draw.text((cursor, y), c, fill=TEXT, font=FONT_MONO)
            cursor += _w(c, FONT_MONO)
            i += 1
        elif c == ",":
            flush(TEXT)
            draw.text((cursor, y), c, fill=MUTED, font=FONT_MONO)
            cursor += _w(c, FONT_MONO)
            i += 1
        else:
            buf += c
            i += 1
    flush(TEXT)


# ──────────────────────────────────────────────────────────────────────────────
# Annotation overlay (pinpoint-style: red rect + arrow)
# ──────────────────────────────────────────────────────────────────────────────

def overlay_annotation(img_path: Path, rect: tuple[int, int, int, int],
                        arrow_from: tuple[int, int], arrow_to: tuple[int, int],
                        color: tuple[int, int, int] = (255, 23, 68)) -> None:
    """Draw a pinpoint-style red rect + arrow on an already-saved image."""
    img = Image.open(img_path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    x, y, w, h = rect
    # rectangle (3 px stroke)
    for off in range(3):
        draw.rectangle([(x - off, y - off), (x + w + off, y + h + off)], outline=color)
    # arrow line
    draw.line([arrow_from, arrow_to], fill=color, width=3)
    # arrow head
    _draw_arrow_head(draw, arrow_from, arrow_to, color)
    img.convert("RGB").save(img_path)


def _draw_arrow_head(draw, p1, p2, color):
    import math
    angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    head_len = 12
    head_w = 7
    x2, y2 = p2
    hx1 = x2 - head_len * math.cos(angle) + head_w * math.sin(angle)
    hy1 = y2 - head_len * math.sin(angle) - head_w * math.cos(angle)
    hx2 = x2 - head_len * math.cos(angle) - head_w * math.sin(angle)
    hy2 = y2 - head_len * math.sin(angle) + head_w * math.cos(angle)
    draw.polygon([(x2, y2), (hx1, hy1), (hx2, hy2)], fill=color)


# ──────────────────────────────────────────────────────────────────────────────
# Slides (username-redacted: uses "YOU" instead of the author's login)
# Slide 01 = Tesseract prereq (web capture, annotated externally)
# Slide 02 = GitHub repo page (web capture, annotated externally)
# Slides 03-07 generated below + annotated via overlay_annotation().
# ──────────────────────────────────────────────────────────────────────────────

# Slide 03: Clone
slide_clone = OUT / "slide_03_clone.png"
make_terminal(
    "Windows PowerShell",
    [
        ("comment", "# 1 - Clone the repo, then move into the checkout"),
        ("prompt+cmd", r"PS C:\Users\YOU\pinpoint-install-demo>||git clone https://github.com/hlsitechio/pinpoint-mcp.git"),
        ("output",  "Cloning into 'pinpoint-mcp'..."),
        ("output",  "remote: Enumerating objects: 35, done."),
        ("output",  "remote: Counting objects: 100% (35/35), done."),
        ("output",  "remote: Compressing objects: 100% (28/28), done."),
        ("output",  "remote: Total 35 (delta 6), reused 29 (delta 3)"),
        ("output",  "Receiving objects: 100% (35/35), 12.34 KiB | 2.00 MiB/s, done."),
        ("success", "Resolving deltas: 100% (6/6), done."),
        ("blank", ""),
        ("prompt+cmd", r"PS C:\Users\YOU\pinpoint-install-demo>||cd pinpoint-mcp"),
        ("prompt+cmd", r"PS C:\Users\YOU\pinpoint-install-demo\pinpoint-mcp>||"),
    ],
    slide_clone,
)
# Dual annotation: both commands matter (clone + cd into checkout)
overlay_annotation(slide_clone,
                   rect=(368, 67, 514, 26),
                   arrow_from=(945, 80), arrow_to=(889, 80))
overlay_annotation(slide_clone,
                   rect=(368, 265, 148, 26),
                   arrow_from=(580, 278), arrow_to=(523, 278))

# Slide 04: pip install
slide_pip = OUT / "slide_04_pip.png"
make_terminal(
    "Windows PowerShell",
    [
        ("comment", "# 2 - Install the Python package (editable mode)"),
        ("prompt+cmd", r"PS C:\Users\YOU\...\pinpoint-mcp>||pip install -e ."),
        ("output",  "Obtaining file:///C:/Users/YOU/pinpoint-install-demo/pinpoint-mcp"),
        ("output",  "  Installing build dependencies ... done"),
        ("output",  "  Checking if build backend supports build_editable ... done"),
        ("output",  "  Getting requirements to build editable ... done"),
        ("output",  "  Preparing editable metadata (pyproject.toml) ... done"),
        ("output",  "Collecting fastmcp>=2.0.0"),
        ("output",  "Collecting Pillow>=10.0.0"),
        ("output",  "Collecting mss>=9.0.1"),
        ("output",  "Collecting playwright>=1.40.0"),
        ("output",  "Collecting pytesseract>=0.3.10"),
        ("output",  "Collecting pydantic>=2.0.0"),
        ("output",  "Building wheels for collected packages: pinpoint-mcp"),
        ("output",  "  Building editable for pinpoint-mcp (pyproject.toml) ... done"),
        ("output",  "  Created wheel for pinpoint-mcp"),
        ("output",  "Successfully built pinpoint-mcp"),
        ("output",  "Installing collected packages: pinpoint-mcp"),
        ("success", "Successfully installed pinpoint-mcp-0.1.0"),
    ],
    slide_pip,
)
overlay_annotation(slide_pip,
                   rect=(16, 442, 385, 25),
                   arrow_from=(460, 455), arrow_to=(405, 455))

# Slide 05: Playwright install
slide_pw = OUT / "slide_05_playwright.png"
make_terminal(
    "Windows PowerShell",
    [
        ("comment", "# 3 - Install the Playwright Chromium browser (~170 MB)"),
        ("prompt+cmd", r"PS C:\Users\YOU\...\pinpoint-mcp>||playwright install chromium"),
        ("output", "Downloading Chromium 131.0.6778.33 (playwright build v1148) from"),
        ("output", "  https://cdn.playwright.dev/builds/chromium/1148/chromium-win64.zip"),
        ("info",   "    167.2 Mb [====================] 100%  0.0s"),
        ("output", "Chromium 131.0.6778.33 (playwright build v1148) downloaded to"),
        ("output", "  C:\\Users\\YOU\\AppData\\Local\\ms-playwright\\chromium-1148"),
        ("output", "Downloading FFMPEG playwright build v1011 from"),
        ("output", "  https://cdn.playwright.dev/builds/ffmpeg/1011/ffmpeg-win64.zip"),
        ("info",   "    2.3 Mb [====================] 100%  0.0s"),
        ("success","FFMPEG playwright build v1011 downloaded."),
        ("blank", ""),
        ("success","\u2713  Chromium + ffmpeg ready for pinpoint_capture_url"),
    ],
    slide_pw,
)
overlay_annotation(slide_pw,
                   rect=(16, 310, 470, 26),
                   arrow_from=(555, 322), arrow_to=(490, 322))

# Slide 06: Config file
slide_cfg = OUT / "slide_06_config.png"
make_json_viewer(
    "claude_desktop_config.json",
    '''{
  "mcpServers": {
    "pinpoint": {
      "command": "C:\\\\Python314\\\\python.exe",
      "args": ["-m", "pinpoint.server"],
      "env": {
        "PINPOINT_WORKDIR": "C:\\\\Users\\\\YOU\\\\pinpoint-output",
        "TESSDATA_PREFIX": "C:\\\\Users\\\\YOU\\\\.pinpoint\\\\tessdata",
        "PATH": "C:\\\\Program Files\\\\Tesseract-OCR;C:\\\\Python314"
      }
    }
  }
}''',
    slide_cfg,
)
overlay_annotation(slide_cfg,
                   rect=(105, 92, 555, 175),
                   arrow_from=(730, 180), arrow_to=(665, 180))

# Slide 07: Verify — simulate a pinpoint_list_monitors MCP call
slide_verify = OUT / "slide_07_verify.png"
make_terminal(
    "Claude Desktop - MCP call",
    [
        ("comment", "# 4 - Restart Claude Desktop, then ask it to call pinpoint"),
        ("info",    "\u25b8 pinpoint_list_monitors"),
        ("blank", ""),
        ("output",  "["),
        ("output",  "  {"),
        ("output",  '    "index": 0,'),
        ("output",  '    "label": "Monitor 0: 2560x1440",'),
        ("output",  '    "width": 2560,'),
        ("output",  '    "height": 1440,'),
        ("output",  '    "is_primary": false'),
        ("output",  "  },"),
        ("output",  "  {"),
        ("output",  '    "index": 1,'),
        ("output",  '    "label": "Monitor 1: 2560x1440 (primary)",'),
        ("output",  '    "width": 2560,'),
        ("output",  '    "height": 1440,'),
        ("output",  '    "is_primary": true'),
        ("output",  "  }"),
        ("output",  "]"),
        ("blank", ""),
        ("success", "\u2713  pinpoint MCP connected. All 9 tools ready."),
    ],
    slide_verify,
)
overlay_annotation(slide_verify,
                   rect=(16, 486, 450, 25),
                   arrow_from=(530, 498), arrow_to=(470, 498))

print("generated 5 terminal/code slides with dogfood annotations + username redacted")
