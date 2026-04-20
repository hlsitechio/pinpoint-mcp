# pinpoint-mcp

> MCP server for screenshot capture + intelligent visual annotation. Built for Claude Desktop, Claude Code, and any MCP-compatible client.

**Le problème** : Claude voit un écran et te dit *"clique sur le bouton en haut à droite, près de l'icône engrenage..."* en mots. Tu cherches, tu perds 30 secondes, parfois tu cliques au mauvais endroit.

**La solution** : Claude voit l'écran → trouve l'élément exact via OCR/DOM → te renvoie un screenshot annoté avec encadré rouge + flèche pointant l'endroit précis.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Claude (Desktop / Code / OpenClaw)                 │
└──────────────────────┬──────────────────────────────┘
                       │ MCP stdio
                       ▼
┌─────────────────────────────────────────────────────┐
│  pinpoint-mcp                                       │
│  ├── capture/                                       │
│  │   ├── screen.py   → mss (Windows/Linux/macOS)   │
│  │   └── web.py      → Playwright (CDP)            │
│  ├── detect/                                        │
│  │   └── ocr.py      → Tesseract                   │
│  └── render/                                        │
│      └── annotate.py → Pillow                      │
└─────────────────────────────────────────────────────┘
```

## Installation

### 1. Prérequis

- Python 3.11+
- Tesseract OCR
  - **Windows** : [installer depuis UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) (inclure French language pack)
  - **Kali/Debian** : `sudo apt install tesseract-ocr tesseract-ocr-fra`
  - **macOS** : `brew install tesseract tesseract-lang`

### 2. Installation du package

```powershell
# Windows (recommandé : utiliser uv)
uv pip install -e .
playwright install chromium
```

```bash
# Linux/macOS
pip install -e .
playwright install chromium
```

### 3. Configuration Claude Desktop

Édite `%APPDATA%\Claude\claude_desktop_config.json` (Windows) ou
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) :

```json
{
  "mcpServers": {
    "pinpoint": {
      "command": "python",
      "args": ["-m", "pinpoint.server"],
      "env": {
        "PINPOINT_WORKDIR": "C:\\Users\\Hubert\\pinpoint-output"
      }
    }
  }
}
```

Redémarre Claude Desktop. Le serveur apparaît dans la liste des MCP.

## Tools exposés

| Tool | Description |
|------|-------------|
| `pinpoint_list_monitors` | Liste les écrans disponibles |
| `pinpoint_capture_screen` | Screenshot écran complet |
| `pinpoint_capture_active_window` | Screenshot fenêtre active (Windows) |
| `pinpoint_capture_url` | Screenshot d'une page web |
| `pinpoint_find_text` | Trouve du texte par OCR |
| `pinpoint_find_web_element` | Trouve un élément DOM (sélecteurs Playwright) |
| `pinpoint_annotate` | Applique encadrés/flèches/numéros |
| `pinpoint_show_me` | **★ Workflow complet en 1 call** |

## Exemple d'utilisation avec Claude

> **Toi** : "Voici un screenshot de l'admin Shopify, montre-moi où cliquer pour approuver les scopes"

> **Claude** :
> ```
> [appelle pinpoint_show_me(target="Approve scopes",
>                           source="C:/screenshots/shopify.png")]
> ```
> Voici l'image annotée — le bouton à cliquer est encadré en rouge.

## Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `PINPOINT_WORKDIR` | `%TEMP%/pinpoint` | Dossier de sortie des PNG |
| `PINPOINT_TRANSPORT` | `stdio` | `stdio` ou `http` |
| `PINPOINT_PORT` | `8765` | Port HTTP si transport=http |

## Tests rapides

```bash
# Vérifier que Tesseract trouve "Approve scopes" dans une image
python -c "from pinpoint.detect.ocr import OCRDetector; \
           print(OCRDetector().find_text('test.png', 'Approve scopes'))"

# Lister les écrans
python -c "from pinpoint.capture.screen import ScreenCapture; \
           [print(m.label) for m in ScreenCapture().list_monitors()]"
```

## Roadmap

- [ ] OCR : support de zones de recherche (chercher uniquement dans une région)
- [ ] DOM : sélecteurs sémantiques avancés (ARIA tree introspection)
- [ ] Mode "tutoriel" : génère N images annotées pour un workflow multi-étapes
- [ ] Intégration vision Claude API en fallback quand OCR rate
- [ ] Support des fenêtres Citrix/RDP (capture spécifique au handle de fenêtre)

## Licence

MIT — fais ce que tu veux avec.

Construit par [Hubert (rainkode)](https://crowbyte.io) pour HLSI Tech.
