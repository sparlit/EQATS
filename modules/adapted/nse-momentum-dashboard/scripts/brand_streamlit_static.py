from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""Rebrands Streamlit's own shipped index.html/favicon.png so the browser
tab title/icon are correct even BEFORE the app's JS runs (st.set_page_config
only patches document.title/favicon via JS after the React app mounts --
the raw server-rendered HTML Streamlit ships still hardcodes "Streamlit"
and its own default favicon.png). That raw HTML is what browser/OS
"create shortcut" and "add to home screen" flows read, so without this
patch those show "Streamlit" with no icon regardless of page_icon/
page_title. Also adds an apple-touch-icon (iOS) and a Web App Manifest
(Android/Chrome) -- both platforms' "Add to Home Screen" ignore the
regular favicon entirely and fall back to a plain monogram tile without
their own specific icon declaration.

This edits files INSIDE the installed streamlit package (not this repo),
so it's not covered by git and must be re-run after every `pip install`
that touches streamlit (fresh install, upgrade, or venv rebuild) --
that's exactly why this lives as a standalone idempotent script rather
than a one-off manual edit. Run with the venv's own python so the right
streamlit installation is found:
    .venv/bin/python scripts/brand_streamlit_static.py       (VPS/Linux)
    .venv\\Scripts\\python scripts\\brand_streamlit_static.py  (Windows)
"""

import json
import shutil
from pathlib import Path

import streamlit

APP_NAME = "KK Trading System"
REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_FAVICON = REPO_ROOT / "assets" / "favicon_square.png"
SOURCE_APPLE_ICON = REPO_ROOT / "assets" / "apple_touch_icon.png"
SOURCE_ICON_192 = REPO_ROOT / "assets" / "icon_192.png"
SOURCE_ICON_512 = REPO_ROOT / "assets" / "icon_512.png"

# Android's "Add to Home Screen"/"Install app" reads THIS, not favicon.png
# or apple-touch-icon -- without it Chrome falls back to a plain monogram
# tile (the "T" the user saw), regardless of what the favicon/title say.
MANIFEST = {
    "name": APP_NAME,
    "short_name": APP_NAME,
    "start_url": ".",
    "display": "standalone",
    "background_color": "#f6f5f0",
    "theme_color": "#185fa5",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}


def main() -> None:
    static_dir = Path(streamlit.__file__).resolve().parent / "static"
    index_html = static_dir / "index.html"
    favicon = static_dir / "favicon.png"
    apple_icon = static_dir / "apple-touch-icon.png"
    icon_192 = static_dir / "icon-192.png"
    icon_512 = static_dir / "icon-512.png"
    manifest_path = static_dir / "manifest.json"

    if not index_html.exists():
        raise SystemExit(f"Not found: {index_html} -- is this the right venv?")
    for src in (SOURCE_FAVICON, SOURCE_APPLE_ICON, SOURCE_ICON_192, SOURCE_ICON_512):
        if not src.exists():
            raise SystemExit(
                f"Not found: {src} -- run this from the repo root, "
                "with the assets/ icon files already generated."
            )

    html = index_html.read_text(encoding="utf-8")
    changed = False

    if "<title>Streamlit</title>" in html:
        html = html.replace("<title>Streamlit</title>", f"<title>{APP_NAME}</title>")
        changed = True
    elif f"<title>{APP_NAME}</title>" in html:
        pass  # already patched
    else:
        print(
            "WARNING: <title> tag not found in the expected form -- "
            "leaving it untouched (Streamlit's static HTML may have "
            "changed shape in this version)."
        )

    apple_meta = f'<meta name="apple-mobile-web-app-title" content="{APP_NAME}" />'
    if apple_meta not in html:
        html = html.replace("<title>", f"{apple_meta}\n    <title>", 1)
        changed = True

    # iOS's "Add to Home Screen" specifically looks for rel="apple-touch-icon"
    # (not rel="shortcut icon"/favicon.png), and Android's "Add to Home
    # Screen"/"Install app" specifically looks for a Web App Manifest's
    # icons array (not either favicon) -- without these, each platform
    # falls back to a plain monogram tile (the "T" the user saw on
    # Android) regardless of what the favicon/title say. Inserted
    # independently (not as one combined block) so re-running this after
    # only ONE of the two was added in a prior version doesn't duplicate
    # the other.
    shortcut_icon_line = '<link rel="shortcut icon" href="./favicon.png" />'
    apple_link = '<link rel="apple-touch-icon" href="./apple-touch-icon.png" />'
    manifest_link = '<link rel="manifest" href="./manifest.json" />'
    if apple_link not in html:
        html = html.replace(shortcut_icon_line, f"{shortcut_icon_line}\n    {apple_link}")
        changed = True
    if manifest_link not in html:
        html = html.replace(shortcut_icon_line, f"{shortcut_icon_line}\n    {manifest_link}")
        changed = True

    if changed:
        index_html.write_text(html, encoding="utf-8")
        print(f"Patched {index_html}")
    else:
        print(f"{index_html} already patched, nothing to do")

    shutil.copyfile(SOURCE_FAVICON, favicon)
    print(f"Replaced {favicon} with {SOURCE_FAVICON}")
    shutil.copyfile(SOURCE_APPLE_ICON, apple_icon)
    print(f"Wrote {apple_icon} from {SOURCE_APPLE_ICON}")
    shutil.copyfile(SOURCE_ICON_192, icon_192)
    shutil.copyfile(SOURCE_ICON_512, icon_512)
    print(f"Wrote {icon_192} and {icon_512}")
    manifest_path.write_text(json.dumps(MANIFEST, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
