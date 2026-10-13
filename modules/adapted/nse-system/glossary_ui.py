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


"""
glossary_ui.py - a small, self-contained "explain this" index page.

WHY: every explanation lives in explain.py, but a term is only discoverable if
the owner can see it somewhere. The panels cover the terms they display; this
page covers all of them, including ones no panel currently shows (breadth,
delivery, accumulation, the veto rule...).

It is deliberately a plain server-rendered page: no build step, no framework,
nothing that can drift from explain.py.

Mount it from terminal_api with:

    from fastapi.responses import HTMLResponse
    @app.get("/glossary", response_class=HTMLResponse)
    def glossary(user: str = Depends(verify_user)):
        import glossary_ui
        return glossary_ui.render()

Everything is generated from explain.py, so adding a term there adds it here.
"""
import html as _html

import explain

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What things mean - NSE Terminal</title>
<link rel="stylesheet" href="/static/style.css?v=20">
<link rel="stylesheet" href="/static/polish.css?v=1">
<style>
  .gwrap {{ max-width: 860px; margin: 0 auto; padding: 32px 20px 64px; }}
  .gwrap h1 {{ margin: 0 0 6px; }}
  .gsub {{ color: var(--muted); margin: 0 0 28px; font-size: 14px; }}
  .gterm {{
    background: var(--surface-1); border: 1px solid var(--hairline);
    border-radius: var(--radius-lg); padding: 18px 20px; margin-bottom: 14px;
  }}
  .gterm h2 {{ margin: 0 0 8px; }}
  .gterm dl {{ margin: 0; }}
  .grow {{ display: grid; grid-template-columns: 150px 1fr; gap: 12px;
           padding: 9px 0; border-top: 1px solid var(--hairline); }}
  .grow dt {{ font-size: 11px; font-weight: 650; letter-spacing: .02em;
              text-transform: uppercase; color: var(--blue); }}
  .grow dd {{ margin: 0; font-size: 14px; line-height: 1.6; }}
  .gsight {{ background: rgba(130,183,255,.07); border-radius: 10px;
             padding: 13px 14px; margin-top: 10px; }}
  .gsight dt {{ color: var(--green); }}
  .gback {{ display: inline-block; margin-bottom: 18px; color: var(--blue);
            text-decoration: none; font-size: 13px; }}
  @media (max-width: 620px) {{ .grow {{ grid-template-columns: 1fr; gap: 3px; }} }}
</style>
</head>
<body>
<div class="gwrap">
  <a class="gback" href="/">&larr; Back to the terminal</a>
  <h1>What things mean</h1>
  <p class="gsub">Every number and label in the terminal, explained in ordinary
  words. Nothing here is a recommendation.</p>
  {body}
</div>
</body>
</html>
"""


def render() -> str:
    """The full page, built from explain.py."""
    esc = _html.escape
    parts = []
    for key in explain.all_keys():
        e = explain.EXPLAIN[key]
        rows = []
        for skey, label in explain.SECTIONS:
            value = e.get(skey)
            if not value:
                continue
            cls = ' class="grow gsight"' if skey == "sight" else ' class="grow"'
            rows.append(f"<div{cls}><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>")
        parts.append(
            f'<section class="gterm" id="{esc(key)}">'
            f"<h2>{esc(e['title'])}</h2>"
            f"<dl>{''.join(rows)}</dl>"
            f"</section>"
        )
    return PAGE.format(body="\n".join(parts))
