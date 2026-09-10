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


"""Render data.json into the screener page (index.html).

Charts are hand-built inline SVG: no external libraries, so the page works
offline and inside the artifact sandbox's strict CSP.

Palette notes (validated with the dataviz validator, not eyeballed):
  * Gain/loss poles - light #116b4a / #ff6f5e passes every check
    (CVD deutan-protan worst ΔE 13.5, normal-vision 35.4). Dark #0d7a52 /
    #e8604e sits inside the dark lightness band with contrast >= 3:1, but no
    red-green pair can clear the CVD gate inside that narrow band. Polarity is
    therefore encoded THREE further ways: bar direction across the zero
    baseline, a signed value label on every bar, and rank order - plus the full
    sector table below. Colour never carries the sign alone.
  * Categorical trio for the leading sectors - slots 1-3 of the reference
    theme, which pass all-pairs in both modes.
"""

import datetime as dt
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")
OUT = os.path.join(HERE, "index.html")

SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"]


def esc(s):
    return html.escape(str(s), quote=True)


# strftime's no-pad flag is %-d on macOS/Linux but %#d on Windows, so build the
# few date strings this page needs by hand and stay portable.
def d_fmt(d, style="day_mon"):
    """Format a date without zero-padded day numbers."""
    if style == "day_mon":  # 7 Aug
        return f"{d.day} {d:%b}"
    if style == "wd_day_mon":  # Fri 7 Aug
        return f"{d:%a} {d.day} {d:%b}"
    if style == "mon_day":  # Aug 7
        return f"{d:%b} {d.day}"
    if style == "mon_day_year":  # Aug 7, 2026
        return f"{d:%b} {d.day}, {d.year}"
    raise ValueError(style)


def dt_fmt(t):
    """Timestamp like 'Sat 15 Aug 2026, 3:36 PM'."""
    hour = t.hour % 12 or 12
    return f"{t:%a} {t.day} {t:%b} {t.year}, {hour}:{t:%M} {t:%p}"


def fmt(v, dp=2, sign=True):
    if v is None:
        return "–"
    return f"{v:+.{dp}f}%" if sign else f"{v:.{dp}f}%"


def nice_span(lo, hi):
    """Symmetric axis bounds on a round step, using 2-4 divisions per arm
    so the bars fill the plot instead of huddling around zero."""
    import math

    span = max(abs(lo), abs(hi)) or 1.0
    for step in (0.1, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50):
        divs = math.ceil(span / step - 1e-9)
        if divs <= 4:
            if divs < 2:  # too coarse - a single division wastes the axis
                continue
            return -divs * step, divs * step, step
    return -span, span, span / 4


# --------------------------------------------------------------------------
# Chart 1 - diverging horizontal bars, one row per sector
# --------------------------------------------------------------------------
def sector_chart(sectors):
    rows = len(sectors)
    row_h, gap = 26, 6
    m_l, m_r, m_t, m_b = 190, 28, 16, 44
    plot_w = 660
    plot_h = rows * row_h
    w, h = m_l + plot_w + m_r, m_t + plot_h + m_b

    vals = [s["week"] for s in sectors]
    lo, hi, step = nice_span(min(vals), max(vals))
    zero = m_l + plot_w / 2

    def x(v):
        return zero + (v / hi) * (plot_w / 2)

    out = [
        (
            f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="Weekly return by sector, sorted best to worst">'
        )
    ]

    # gridlines + ticks
    t = lo
    while t <= hi + 1e-9:
        gx = x(t)
        cls = "axis-zero" if abs(t) < 1e-9 else "gridline"
        out.append(f'<line class="{cls}" x1="{gx:.1f}" y1="{m_t}" x2="{gx:.1f}" y2="{m_t + plot_h}"/>')
        out.append(f'<text class="tick" x="{gx:.1f}" y="{m_t + plot_h + 18}" text-anchor="middle">{t:g}</text>')
        t += step
    out.append(
        f'<text class="axis-title" x="{zero:.1f}" y="{h - 6}" text-anchor="middle">'
        f"Weekly return (%) — sector median</text>"
    )

    for i, s in enumerate(sectors):
        y = m_t + i * row_h + gap / 2
        bh = row_h - gap
        v = s["week"]
        pos = v >= 0
        x0, x1 = (zero, x(v)) if pos else (x(v), zero)
        bw = max(abs(x1 - x0), 1.5)
        # 2px surface gap so a bar never touches the zero rule
        if pos:
            bx, r = x0 + 1, "0 4 4 0"
        else:
            bx, r = x0, "4 0 0 4"
        fill = "var(--gain)" if pos else "var(--loss)"
        label = f"{v:+.2f}%"
        tip = f"{s['sector']}: {label} this week · {s['advancers']}/{s['count']} advancing · 1M {fmt(s['month'])}"
        out.append(
            f'<g class="bar-g"><title>{esc(tip)}</title>'
            f'<rect class="bar" x="{bx:.1f}" y="{y:.1f}" width="{max(bw - 1, 1):.1f}" height="{bh}" '
            f'rx="4" fill="{fill}" style="--r:{r}"/>'
            f'<rect class="hit" x="{m_l}" y="{y - gap / 2:.1f}" width="{plot_w}" height="{row_h}"/>'
            f"</g>"
        )
        # sector name (left gutter)
        out.append(
            f'<text class="row-label" x="{m_l - 10}" y="{y + bh / 2 + 4:.1f}" text-anchor="end">'
            f"{esc(s['sector'])}</text>"
        )
        # Signed value label - the secondary encoding that carries polarity.
        # Long bars take the label inside so it can never collide with the
        # sector name in the left gutter; short bars take it outside.
        ty = y + bh / 2 + 4
        lw = 7 * len(label)  # generous width estimate for the label text
        overflows = (x1 + 7 + lw > m_l + plot_w) if pos else (x0 - 7 - lw < m_l)
        if overflows and bw > lw + 16:
            lx = (x1 - 8) if pos else (x0 + 8)
            anchor = "end" if pos else "start"
            cls = "val val-in-gain" if pos else "val val-in-loss"
        else:
            lx = (x1 + 7) if pos else (x0 - 7)
            anchor = "start" if pos else "end"
            cls = "val"
        out.append(f'<text class="{cls}" x="{lx:.1f}" y="{ty:.1f}" text-anchor="{anchor}">{label}</text>')

    out.append("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Chart 2 - grouped vertical bars, best stocks from the leading sectors
# --------------------------------------------------------------------------
def leaders_chart(sectors, per=5, groups=3):
    lead = sectors[:groups]
    bars = []
    for gi, s in enumerate(lead):
        for st in s["stocks"][:per]:
            bars.append((gi, s["sector"], st))
    if not bars:
        return ""

    n = len(bars)
    bar_w, bar_gap, grp_gap = 42, 10, 34
    m_l, m_r, m_t, m_b = 56, 20, 22, 92
    plot_w = n * bar_w + (n - 1) * bar_gap + (groups - 1) * grp_gap
    plot_h = 300
    w, h = m_l + plot_w + m_r, m_t + plot_h + m_b

    import math

    vals = [b[2]["week"] for b in bars]
    # Round tick step, with headroom above the tallest bar for its label.
    raw_hi = max([*vals, 0]) * 1.08
    raw_lo = min([*vals, 0])
    step = 1.0
    for cand in (0.5, 1, 2, 2.5, 5, 10, 20):
        if (raw_hi - min(raw_lo, 0)) / cand <= 6:
            step = cand
            break
    hi = math.ceil(raw_hi / step) * step
    lo = math.floor(min(raw_lo, 0) / step) * step
    rng = (hi - lo) or 1
    ticks = round(rng / step)

    def y(v):
        return m_t + plot_h - ((v - lo) / rng) * plot_h

    out = [
        (
            f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="Best performing stocks in the top three sectors this week">'
        )
    ]
    for i in range(ticks + 1):
        v = lo + rng * i / ticks
        gy = y(v)
        cls = "axis-zero" if abs(v) < 1e-9 else "gridline"
        out.append(f'<line class="{cls}" x1="{m_l}" y1="{gy:.1f}" x2="{m_l + plot_w}" y2="{gy:.1f}"/>')
        out.append(f'<text class="tick" x="{m_l - 9}" y="{gy + 4:.1f}" text-anchor="end">{v:.1f}</text>')
    out.append(
        f'<text class="axis-title" transform="rotate(-90 16 {m_t + plot_h / 2:.1f})" '
        f'x="16" y="{m_t + plot_h / 2:.1f}" text-anchor="middle">Weekly return (%)</text>'
    )

    cx = m_l
    prev_g = 0
    for gi, sector, st in bars:
        if gi != prev_g:
            cx += grp_gap
            prev_g = gi
        v = st["week"]
        y0, y1 = (y(v), y(0)) if v >= 0 else (y(0), y(v))
        bh = max(y1 - y0, 1.5)
        tip = f"{st['root']} · {st['name']} · {sector} · {v:+.2f}% this week · ₹{st['last']:,.2f}"
        out.append(
            f'<g class="bar-g"><title>{esc(tip)}</title>'
            f'<rect class="bar" x="{cx:.1f}" y="{y0:.1f}" width="{bar_w}" height="{bh:.1f}" '
            f'rx="4" fill="{SERIES[gi]}"/>'
            f'<rect class="hit" x="{cx - bar_gap / 2:.1f}" y="{m_t}" width="{bar_w + bar_gap}" height="{plot_h}"/>'
            f"</g>"
        )
        out.append(f'<text class="val" x="{cx + bar_w / 2:.1f}" y="{y0 - 7:.1f}" text-anchor="middle">{v:+.1f}%</text>')
        out.append(
            f'<text class="cat" x="{cx + bar_w / 2:.1f}" y="{m_t + plot_h + 16:.1f}" '
            f'text-anchor="end" transform="rotate(-45 {cx + bar_w / 2:.1f} {m_t + plot_h + 16:.1f})">'
            f"{esc(st['root'])}</text>"
        )
        cx += bar_w + bar_gap

    out.append("</svg>")

    legend = (
        '<div class="legend">'
        + "".join(
            f'<span class="lg"><i style="background:{SERIES[i]}"></i>{esc(s["sector"])} <b>{fmt(s["week"])}</b></span>'
            for i, s in enumerate(lead)
        )
        + "</div>"
    )
    return legend + "\n".join(out)


# --------------------------------------------------------------------------
def stock_row(st, sector=None, quarter=True):
    cls = "up" if st["week"] >= 0 else "down"
    sec = f'<td class="dim">{esc(sector)}</td>' if sector else ""
    q = f"<td class='num hide-s'>{fmt(st.get('quarter'))}</td>" if quarter else ""
    return (
        f"<tr><td><b>{esc(st['root'])}</b><span class='sub'>{esc(st['name'])}</span></td>"
        f"{sec}"
        f"<td class='num'>{st['last']:,.2f}</td>"
        f"<td class='num {cls}'>{fmt(st['week'])}</td>"
        f"<td class='num'>{fmt(st.get('month'))}</td>"
        f"{q}</tr>"
    )


def build_html(d):
    sectors = d["sectors"]
    ws = dt.date.fromisoformat(d["week_start"])
    we = dt.date.fromisoformat(d["week_end"])
    if ws.month == we.month:
        week_label = f"{d_fmt(ws, 'mon_day')}–{we.day}, {we.year}"
    else:
        week_label = f"{d_fmt(ws, 'mon_day')} – {d_fmt(we, 'mon_day_year')}"
    gen = dt.datetime.fromisoformat(d["generated_at"])
    next_run = d_fmt((gen + dt.timedelta(days=7)).date(), "wd_day_mon")
    base = dt.date.fromisoformat(d["baseline"])
    base_label = d_fmt(base, "wd_day_mon")
    status = "completed trading week" if d.get("week_complete", True) else "week so far — still in progress"

    # Index daily bars are published later than stock bars, so a benchmark can
    # still be a session behind the universe. Say so on the tile rather than
    # letting a Thursday number sit silently under a Mon-Fri headline.
    def tile(b):
        lag = ""
        if b.get("week_end") and b["week_end"] != d["week_end"]:
            lag = (
                f'<div class="tile-lag" title="This index has not published '
                f'{d["week_end"]} yet, so its figure covers a shorter week.">'
                f"to {d_fmt(dt.date.fromisoformat(b['week_end']))} only</div>"
            )
        return (
            f'<div class="tile"><div class="tile-k">{esc(b["label"])}</div>'
            f'<div class="tile-v {"up" if b["week"] >= 0 else "down"}">{fmt(b["week"])}</div>'
            f'<div class="tile-s">{b["last"]:,.0f} · 1M {fmt(b["month"])}</div>{lag}</div>'
        )

    tiles = "".join(tile(b) for b in d["benchmarks"])

    sec_rows = "".join(
        f'<tr><td class="rank">{i + 1}</td><td><b>{esc(s["sector"])}</b></td>'
        f'<td class="num {"up" if s["week"] >= 0 else "down"}">{fmt(s["week"])}</td>'
        f'<td class="num">{fmt(s["month"])}</td>'
        f'<td class="num hide-s">{fmt(s["quarter"])}</td>'
        f'<td class="num"><span class="breadth"><span class="breadth-f" '
        f'style="width:{s["breadth"]:.0f}%"></span></span>'
        f'<span class="bl">{s["advancers"]}/{s["count"]}</span></td>'
        f'<td><b>{esc(s["best"])}</b> <span class="up">{fmt(s["best_week"], 1)}</span></td>'
        f'<td class="hide-s"><b>{esc(s["worst"])}</b> '
        f'<span class="down">{fmt(s["worst_week"], 1)}</span></td></tr>'
        for i, s in enumerate(sectors)
    )

    details = "".join(
        f'<details class="sec"{" open" if i < 3 else ""}>'
        f'<summary><span class="sm-rank">{i + 1}</span>'
        f'<span class="sm-name">{esc(s["sector"])}</span>'
        f'<span class="sm-val {"up" if s["week"] >= 0 else "down"}">{fmt(s["week"])}</span>'
        f'<span class="sm-b">{s["advancers"]}/{s["count"]} advancing</span></summary>'
        f'<div class="tw"><table><thead><tr><th>Stock</th><th class="num">Close ₹</th>'
        f'<th class="num">1W</th><th class="num">1M</th><th class="num hide-s">3M</th></tr></thead>'
        f"<tbody>{''.join(stock_row(st) for st in s['stocks'][:5])}</tbody></table></div>"
        f"</details>"
        for i, s in enumerate(sectors)
    )

    gain_rows = "".join(stock_row(g, d["sector_of"].get(g["root"], "–"), quarter=False) for g in d["gainers"])
    lose_rows = "".join(stock_row(g, d["sector_of"].get(g["root"], "–"), quarter=False) for g in d["losers"])

    top3 = ", ".join(s["sector"] for s in sectors[:3])
    lead = sectors[0]
    lag = sectors[-1]

    return f"""<meta charset="utf-8">
<title>Indian Market Weekly Sector Screener</title>
<style>
:root {{
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10);
  --gain:#116b4a; --loss:#ff6f5e;
  --gain-ink:#0f6b48; --loss-ink:#c23b2c;
  --series-1:#2a78d6; --series-2:#eb6834; --series-3:#1baf7a;
  --rule:#ece9e2;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
    --gain:#0d7a52; --loss:#e8604e;
    --gain-ink:#2fae77; --loss-ink:#f08272;
    --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
    --rule:#232321;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
  --gain:#0d7a52; --loss:#e8604e;
  --gain-ink:#2fae77; --loss-ink:#f08272;
  --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
  --rule:#232321;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--page); color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.5;
}}
.wrap {{ max-width:1120px; margin:0 auto; padding:34px 20px 72px; display:flex;
         flex-direction:column; gap:18px; }}
header {{ border-bottom:2px solid var(--axis); padding-bottom:16px; }}
h1 {{ font-size:26px; line-height:1.15; margin:0 0 6px; letter-spacing:-.021em;
      text-wrap:balance; font-weight:660; }}
.sub-h {{ color:var(--ink-2); margin:0; font-size:14.5px; }}
.stamp {{ color:var(--muted); font-size:12.5px; margin:10px 0 0; }}
.stamp b {{ color:var(--ink-2); font-weight:600; }}
h2 {{ font-size:15.5px; margin:0 0 5px; letter-spacing:-.005em; color:var(--ink);
      font-weight:650; text-wrap:balance; }}
.note {{ color:var(--muted); font-size:13px; margin:0 0 16px; max-width:74ch; }}
section {{
  background:var(--surface); border:1px solid var(--rule); border-radius:6px;
  padding:18px 20px 20px;
}}
/* 1px grid gap over a rule-coloured ground draws the dividers, so they stay
   correct however the tiles wrap. */
.tiles {{ display:grid; grid-template-columns:repeat(5,1fr); gap:1px;
          background:var(--rule); border:1px solid var(--rule);
          border-radius:6px; overflow:hidden; }}
.tile {{ padding:13px 16px; background:var(--surface); }}
@media (max-width:900px) {{ .tiles {{ grid-template-columns:repeat(2,1fr); }} }}
@media (max-width:430px) {{ .tiles {{ grid-template-columns:1fr; }} }}
.tile-k {{ font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); }}
.tile-v {{ font-size:23px; font-weight:650; margin-top:3px; letter-spacing:-.02em; }}
.tile-s {{ font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }}
.tile-lag {{ font-size:11px; color:var(--loss-ink); margin-top:3px; }}
.up {{ color:var(--gain-ink); }}
.down {{ color:var(--loss-ink); }}
.scroll {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
svg.chart {{ display:block; width:100%; min-width:560px; height:auto; overflow:visible; }}
.gridline {{ stroke:var(--grid); stroke-width:1; }}
.axis-zero {{ stroke:var(--axis); stroke-width:1.5; }}
.tick {{ fill:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; }}
.axis-title {{ fill:var(--muted); font-size:12px; }}
.row-label {{ fill:var(--ink-2); font-size:12.5px; }}
.cat {{ fill:var(--ink-2); font-size:11.5px; }}
.val {{ fill:var(--ink); font-size:11.5px; font-weight:600; font-variant-numeric:tabular-nums; }}
/* Labels sitting on a bar fill: white on the deep green, near-black on the
   coral - both clear 4.4:1 or better against their own fill in either mode. */
.val-in-gain {{ fill:#ffffff; }}
.val-in-loss {{ fill:#180d09; }}
.bar {{ transition:opacity .12s; }}
.hit {{ fill:transparent; }}
.bar-g:hover .bar {{ opacity:.72; }}
.legend {{ display:flex; flex-wrap:wrap; gap:16px; margin:0 0 14px; font-size:13px; color:var(--ink-2); }}
.lg {{ display:inline-flex; align-items:center; gap:7px; }}
.lg i {{ width:11px; height:11px; border-radius:3px; display:inline-block; }}
.lg b {{ color:var(--ink); font-variant-numeric:tabular-nums; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th {{
  text-align:left; font-size:11px; letter-spacing:.05em; text-transform:uppercase;
  color:var(--muted); font-weight:600; padding:0 10px 8px; border-bottom:1px solid var(--border);
  white-space:nowrap;
}}
td {{ padding:9px 10px; border-bottom:1px solid var(--border); vertical-align:middle; }}
tr:last-child td {{ border-bottom:none; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
th.num {{ text-align:right; }}
.rank {{ color:var(--muted); width:26px; font-variant-numeric:tabular-nums; }}
.sub {{ display:block; font-size:11.5px; color:var(--muted); font-weight:400;
        max-width:230px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.dim {{ color:var(--ink-2); font-size:13px; }}
.movers {{ font-size:13.5px; }}
.movers td, .movers th {{ padding-left:7px; padding-right:7px; }}
.movers .sub {{ max-width:150px; }}
.movers .dim {{ font-size:12px; max-width:96px; }}
.breadth {{
  display:inline-block; width:56px; height:6px; border-radius:3px;
  background:var(--grid); overflow:hidden; vertical-align:middle; margin-right:8px;
}}
.breadth-f {{ display:block; height:100%; background:var(--gain); }}
.bl {{ font-size:12px; color:var(--muted); }}
.sec {{ border:1px solid var(--rule); border-radius:5px; margin-bottom:7px; background:var(--surface); }}
.sec summary:focus-visible {{ outline:2px solid var(--series-1); outline-offset:-2px; border-radius:4px; }}
@media (prefers-reduced-motion: reduce) {{
  * {{ transition:none !important; animation:none !important; }}
}}
.sec summary {{
  display:flex; align-items:center; gap:11px; padding:11px 14px;
  cursor:pointer; list-style:none; font-size:14px;
}}
.sec summary::-webkit-details-marker {{ display:none; }}
.sec summary::after {{ content:"▾"; margin-left:auto; color:var(--muted); font-size:12px; }}
.sec[open] summary::after {{ content:"▴"; }}
.sm-rank {{
  min-width:21px; height:21px; border-radius:6px; background:var(--grid); color:var(--ink-2);
  display:inline-grid; place-items:center; font-size:11.5px; font-weight:600;
}}
.sm-name {{ font-weight:600; }}
.sm-val {{ font-variant-numeric:tabular-nums; font-weight:600; }}
.sm-b {{ color:var(--muted); font-size:12.5px; }}
.tw {{ padding:0 14px 12px; overflow-x:auto; }}
.cols {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
/* Grid items default to min-width:auto, which lets a wide table push the
   column past the viewport instead of scrolling inside its own container. */
.cols > div {{ min-width:0; }}
footer {{ color:var(--muted); font-size:12.5px; line-height:1.65; margin-top:8px; }}
footer b {{ color:var(--ink-2); }}
@media (max-width:760px) {{
  .wrap {{ padding:22px 14px 56px; }}
  h1 {{ font-size:22px; }}
  .cols {{ grid-template-columns:1fr; }}
  .hide-s {{ display:none; }}
  .sub {{ max-width:130px; }}
}}
</style>

<div class="wrap">
<header>
  <h1>Indian Market Weekly Sector Screener</h1>
  <p class="sub-h">NSE &amp; BSE listed stocks · week of <b>{week_label}</b>
     — {d["sessions"]} sessions, {status}</p>
  <p class="stamp">All weekly returns are measured from the <b>{base_label}</b> close
     (the previous week's last session) to the <b>{d_fmt(we, "wd_day_mon")}</b> close ·
     refreshed <b>{dt_fmt(gen)}</b> ·
     next automatic refresh <b>{next_run}</b> ·
     {d["universe_size"]} stocks across {len(sectors)} sectors</p>
</header>

<div class="tiles">{tiles}</div>

<section>
  <h2>Sector performance</h2>
  <p class="note">Median weekly return of each sector's constituents, best to worst.
     <b>{esc(lead["sector"])}</b> led at {fmt(lead["week"])};
     <b>{esc(lag["sector"])}</b> lagged at {fmt(lag["week"])}.</p>
  <div class="scroll">{sector_chart(sectors)}</div>
</section>

<section>
  <h2>Top performers: best stocks from the {len(sectors[:3])} leading sectors</h2>
  <p class="note">Five strongest constituents in each of {esc(top3)}.</p>
  <div class="scroll">{leaders_chart(sectors)}</div>
</section>

<section>
  <h2>Full sector table</h2>
  <p class="note">Breadth is the share of constituents that closed the week higher — a wide
     bar means the move was broad, not one stock carrying the sector.</p>
  <div class="scroll"><table>
    <thead><tr><th></th><th>Sector</th><th class="num">1W</th><th class="num">1M</th>
    <th class="num hide-s">3M</th><th class="num">Breadth</th><th>Best</th>
    <th class="hide-s">Worst</th></tr></thead>
    <tbody>{sec_rows}</tbody>
  </table></div>
</section>

<section>
  <h2>Best shares by sector</h2>
  <p class="note">Top five stocks in each sector this week. Tap a sector to expand.</p>
  {details}
</section>

<section>
  <h2>Weekly movers across the whole universe</h2>
  <div class="cols">
    <div>
      <p class="note"><b>Top 15 gainers</b></p>
      <div class="scroll"><table class="movers"><thead><tr><th>Stock</th><th>Sector</th>
      <th class="num">Close ₹</th><th class="num">1W</th><th class="num">1M</th>
      </tr></thead><tbody>{gain_rows}</tbody></table></div>
    </div>
    <div>
      <p class="note"><b>Top 15 losers</b></p>
      <div class="scroll"><table class="movers"><thead><tr><th>Stock</th><th>Sector</th>
      <th class="num">Close ₹</th><th class="num">1W</th><th class="num">1M</th>
      </tr></thead><tbody>{lose_rows}</tbody></table></div>
    </div>
  </div>
</section>

<section>
  <h2>Method &amp; caveats</h2>
  <footer>
    <b>Window.</b> The week shown is the ISO week containing the most recent available
    close — <b>{week_label}</b>, {d["sessions"]} trading sessions, {status}. Every weekly
    return compares the <b>{d_fmt(we)}</b> close with the <b>{base_label}</b>
    close, which is the last session of the preceding week. 1M and 3M look back 22 and 64
    trading sessions. If you open this page mid-week, the figures still describe that same
    window until the next refresh — they do not drift.<br>
    <b>Sector return.</b> The <b>median</b> of the sector's constituents — equal-weighted, so
    one index heavyweight cannot define the sector, and robust to a single outlier.
    Breadth is reported beside it because a median cannot tell a broad move from a narrow one.<br>
    <b>Universe.</b> {d["universe_size"]} liquid NSE-listed stocks grouped into {len(sectors)}
    sectors following the NSE sectoral/thematic index families. Sectors overlap where the
    market does (PSU banks are also banks). Prices come from the NSE listing, falling back to
    the BSE listing when NSE data is unavailable; index levels cover both exchanges
    (Nifty 50, Sensex, Nifty 500, Midcap 50, Smallcap 250). Yahoo's own NSE sectoral index
    series are not used — several publish erratically.<br>
    <b>Colour.</b> Gain/loss colours are validated for colour-vision deficiency, but no
    red-green pair fully clears the gate in dark mode: polarity is also carried by bar
    direction, a signed label on every bar, rank order, and the tables above.<br>
    <b>Data.</b> Yahoo Finance daily closes, unadjusted for corporate actions — a stock that
    went ex-dividend, split or bonus during the week will show a distorted return.
    Not investment advice.
  </footer>
</section>
</div>
"""


if __name__ == "__main__":
    # encoding is explicit everywhere: Python defaults to the locale encoding on
    # Windows (cp1252), which cannot represent the rupee sign or the arrows.
    with open(DATA, encoding="utf-8") as fh:
        data = json.load(fh)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(build_html(data))
    print(f"wrote {OUT}")
