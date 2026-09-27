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
build_regime_html_pdf.py
Reads regime_consolidated_<date>.json, renders a PDF via template.html
(Jinja2 + headless Chromium / Playwright).

Usage:
    python3 build_regime_html_pdf.py
    python3 build_regime_html_pdf.py --date 2026-08-07
    python3 build_regime_html_pdf.py --date 2026-08-07 --out /tmp/report.pdf
"""

import argparse
import base64
import io
import json
from datetime import datetime
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from jinja2 import BaseLoader, Environment
from playwright.sync_api import sync_playwright

# ── paths ─────────────────────────────────────────────────────────────────────
REGIME_DATA = Path("/home/ec2-user/nse-factor-engine/hmm-factor-engine/regime/data")
TEMPLATE = Path(__file__).parent / "template.html"

# ── universe config ───────────────────────────────────────────────────────────
UNIVERSE_ORDER = ["nifty100", "nifty500", "niftymidcap150", "niftysmallcap250"]
UNIVERSE_NAMES = {
    "nifty100": "Nifty 100",
    "nifty500": "Nifty 500",
    "niftymidcap150": "Nifty Midcap 150",
    "niftysmallcap250": "Nifty Smallcap 250",
}

MEASURE_LABELS = {
    "rv": "Realised Volatility",
    "avg_corr": "Avg Correlation",
    "vov": "Vol of Vol",
    "dispersion": "Dispersion",
    "drawdown": "Drawdown",
    "skew": "Skew",
    "amihud": "Amihud Illiquidity",
    "cs_spread": "CS Spread",
    "turnover": "Turnover",
}

RISK_MEASURES = ["rv", "avg_corr", "vov", "dispersion", "drawdown", "skew"]
LIQ_MEASURES = ["amihud", "cs_spread", "turnover"]

CHART_SECTIONS = [
    ("Liquidity Measures", ["amihud", "cs_spread", "turnover"]),
    ("Risk — Volatility & Correlation", ["rv", "vov", "avg_corr"]),
    ("Risk — Dispersion, Drawdown & Skew", ["dispersion", "drawdown", "skew"]),
]

TIER_CLASS = {
    "CALM": "tag-neutral",
    "NORMAL": "tag-neutral",
    "NEUTRAL": "tag-neutral",
    "SHALLOW": "tag-neutral",
    "MODERATE": "tag-outline",
    "RALLY-LIKE": "tag-accent",
    "ELEVATED": "tag-outline",
    "COMPRESSED": "tag-outline",
    "ILLIQUID": "tag-accent",
    "SEVERE": "tag-accent",
    "EXTREME": "tag-accent",
    "CRISIS": "tag-accent",
    "HIGH": "tag-accent",
}

CRISIS_EVENTS = [
    ("2008-09-15", "GFC 2008"),
    ("2011-08-05", "US Debt Crisis"),
    ("2013-06-19", "Taper Tantrum"),
    ("2015-08-24", "China 2015"),
    ("2020-03-23", "COVID Crash"),
]

# ── chart theme ───────────────────────────────────────────────────────────────
BG_PAGE = "#F5F4F4"
BG_PLOT = "#FFFFFF"
COL_BAR = "#B8C4CE"
COL_1M = "#2563EB"
COL_3M = "#7C3AED"
COL_12M = "#DC2626"
COL_TEXT = "#201E1D"
COL_MUTED = "#888585"
COL_GRID = "#E5E2E2"

SHADE = {
    "calm": ("#22C55E", 0.13),
    "moderate": ("#FBBF24", 0.13),
    "elevated": ("#F97316", 0.16),
    "extreme": ("#EF4444", 0.20),
}

INVERTED_METRICS = {"turnover"}


# ── helpers ───────────────────────────────────────────────────────────────────
def fmt_date(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%Y-%b-%d")
    except Exception:
        return d


def fmt_month(m):
    try:
        return datetime.strptime(m, "%Y-%m").strftime("%b-%Y")
    except Exception:
        return m


def tier_class(tier):
    return TIER_CLASS.get((tier or "").upper(), "tag-neutral")


def get_bounds(cal_univ, metric):
    c = cal_univ.get(metric, {})
    p25 = c.get("p25", c.get("p10"))
    p75 = c.get("p75")
    p95 = c.get("p95")
    return p25, p75, p95


def find_local_max(series, date_str, window_days=30):
    try:
        ts = pd.Timestamp(date_str)
        win = series.loc[ts - pd.Timedelta(days=window_days) : ts + pd.Timedelta(days=window_days)]
        if win.empty:
            return False
        val = series.asof(ts)
        return (not pd.isna(val)) and float(val) >= float(win.quantile(0.80))
    except Exception:
        return False


# ── auto-scale tiny-valued series (e.g. amihud ~1e-10) ───────────────────────
def auto_scale(series):
    """
    Returns (scaled_series, scale_factor, raw_exp).
    Multiplies series by scale_factor so median lands in [1, 1000).
    raw_exp is the original order of magnitude (negative for tiny values).
    Chart title will say: "raw values x 1e<raw_exp>" so reader can back-convert.
    """
    median = float(series.median())
    if median == 0 or not np.isfinite(median):
        return series, 1, 0
    mag = np.log10(abs(median))
    if -3 <= mag <= 3:
        return series, 1, 0
    raw_exp = int(np.floor(mag / 3.0) * 3)  # e.g. -10 -> -12
    scale_factor = 10 ** (-raw_exp)  # multiply to bring into view
    return series * scale_factor, scale_factor, raw_exp


# ── robust axis limits (skew-aware) ──────────────────────────────────────────
def robust_ylim(vals):
    """
    Returns (ymin, ymax, n_top, n_bot, clip_pct_label).
    Clips based on skew ratio to keep chart readable:
      p99/p50 > 200  -> clip at p90
      p99/p50 >  20  -> clip at p99
      else           -> use true max
    """
    clean = vals[~np.isnan(vals)]
    if len(clean) == 0:
        return 0.0, 1.0, 0, 0, ""

    vmin = float(np.min(clean))
    vmax = float(np.max(clean))
    p01 = float(np.percentile(clean, 1.0))
    p50 = float(np.percentile(clean, 50.0))
    p90 = float(np.percentile(clean, 90.0))
    p99 = float(np.percentile(clean, 99.0))

    skew_ratio = (p99 / p50) if p50 > 0 else 0

    if skew_ratio > 200:
        ceiling = p90
        clip_pct_label = "p90"
    elif skew_ratio > 20 or vmax > p99 * 3.0:
        ceiling = p99
        clip_pct_label = "p99"
    else:
        ceiling = vmax
        clip_pct_label = ""

    ymax = ceiling * 1.15 if clip_pct_label else vmax * 1.05

    if vmin >= 0:
        ymin = 0.0
    elif p01 < 0 and abs(vmin) > abs(p01) * 3.0:
        ymin = p01 * 1.15
    else:
        ymin = vmin * 1.05

    n_top = int(np.sum(clean > ymax))
    n_bot = int(np.sum(clean < ymin))
    return ymin, ymax, n_top, n_bot, clip_pct_label


# ── single chart renderer ─────────────────────────────────────────────────────
def render_chart(metric, series, cal_univ):
    """Returns a base64-encoded PNG string for one metric."""

    # scale if needed
    series, scale_factor, raw_exp = auto_scale(series)

    # scale calibration bounds by the same factor
    if scale_factor != 1:
        cal_scaled = {k: {pk: pv * scale_factor for pk, pv in v.items()} for k, v in cal_univ.items()}
    else:
        cal_scaled = cal_univ

    fig, ax = plt.subplots(figsize=(10.0, 3.2), dpi=130)
    fig.patch.set_facecolor(BG_PAGE)
    ax.set_facecolor(BG_PLOT)

    dates = series.index
    vals = series.values

    ymin, ymax, n_top, n_bot, clip_pct_label = robust_ylim(vals)
    n_clipped = n_top + n_bot
    base = max(0.0, ymin)

    # ── percentile shading ────────────────────────────────────────────────────
    p25, p75, p95 = get_bounds(cal_scaled, metric)
    inverted = metric in INVERTED_METRICS

    if None not in (p25, p75, p95):

        def shade(lo, hi, key):
            lo = max(lo, ymin)
            hi = min(hi, ymax)
            if hi > lo:
                ax.axhspan(lo, hi, color=SHADE[key][0], alpha=SHADE[key][1], zorder=0)

        if not inverted:
            shade(ymin, p25, "calm")
            shade(p25, p75, "moderate")
            shade(p75, p95, "elevated")
            shade(p95, ymax, "extreme")
        else:
            shade(ymin, p25, "extreme")
            shade(p25, p75, "elevated")
            shade(p75, p95, "moderate")
            shade(p95, ymax, "calm")
        for pval in (p25, p75, p95):
            if ymin <= pval <= ymax:
                ax.axhline(pval, color=COL_MUTED, linewidth=0.5, linestyle="--", alpha=0.6, zorder=1)

    # ── daily bars ────────────────────────────────────────────────────────────
    in_range = (~np.isnan(vals)) & (vals >= ymin) & (vals <= ymax)
    if in_range.any():
        ax.vlines(dates[in_range], base, vals[in_range], color=COL_BAR, linewidth=0.5, alpha=0.8, zorder=2)

    # clipped top: red bars + upward triangle
    top_mask = (~np.isnan(vals)) & (vals > ymax)
    if top_mask.any():
        cap = ymax * 0.998
        ax.vlines(dates[top_mask], base, cap, color="#EF4444", linewidth=0.6, alpha=0.75, zorder=2)
        ax.scatter(
            dates[top_mask],
            np.full(int(top_mask.sum()), cap),
            marker="^",
            color="#EF4444",
            s=14,
            zorder=3,
            linewidths=0,
        )

    # clipped bottom: purple bars + downward triangle
    bot_mask = (~np.isnan(vals)) & (vals < ymin)
    if bot_mask.any():
        floor = ymin * 0.998
        ax.vlines(dates[bot_mask], floor, base, color="#7C3AED", linewidth=0.6, alpha=0.75, zorder=2)
        ax.scatter(
            dates[bot_mask],
            np.full(int(bot_mask.sum()), floor),
            marker="v",
            color="#7C3AED",
            s=14,
            zorder=3,
            linewidths=0,
        )

    # ── rolling averages ──────────────────────────────────────────────────────
    for label, window, color in [("1M", 21, COL_1M), ("3M", 63, COL_3M), ("12M", 252, COL_12M)]:
        rolled = series.rolling(window, min_periods=max(1, window // 3)).mean()
        ax.plot(
            dates,
            rolled.clip(lower=ymin, upper=ymax).values,
            color=color,
            linewidth=1.1,
            alpha=0.95,
            zorder=3,
            label=label,
        )

    # ── crisis annotations ────────────────────────────────────────────────────
    for crisis_date, crisis_label in CRISIS_EVENTS:
        ts = pd.Timestamp(crisis_date)
        if not (dates[0] <= ts <= dates[-1]):
            continue
        if find_local_max(series, crisis_date):
            val_at = float(series.asof(ts))
            plot_y = min(val_at, ymax * 0.93)
            ax.axvline(ts, color="#DC2626", linewidth=0.7, alpha=0.45, zorder=4)
            ax.text(
                ts,
                plot_y,
                f"  {crisis_label}",
                color="#DC2626",
                fontsize=5.0,
                va="bottom",
                ha="left",
                rotation=65,
                clip_on=True,
                zorder=5,
            )

    # ── stats box (raw units, scientific notation when scaled) ───────────────
    use_sci = raw_exp != 0
    inv = scale_factor if scale_factor != 1 else 1
    raw_mean = float(series.mean()) / inv
    raw_max = float(series.max()) / inv

    def fmt(v):
        return f"{v:.3e}" if use_sci else f"{v:.4f}"

    stat_lines = [f"n = {int(series.notna().sum()):,}", f"mean = {fmt(raw_mean)}"]
    if p25 is not None:
        stat_lines.append(f"p25  = {fmt(p25 / inv)}")
    if p75 is not None:
        stat_lines.append(f"p75  = {fmt(p75 / inv)}")
    if p95 is not None:
        stat_lines.append(f"p95  = {fmt(p95 / inv)}")
    stat_lines.append(f"max  = {fmt(raw_max)}")
    if n_clipped > 0:
        stat_lines.append(f"[{n_clipped} clipped]")

    ax.text(
        0.985,
        0.97,
        "\n".join(stat_lines),
        transform=ax.transAxes,
        fontsize=5.5,
        color=COL_TEXT,
        va="top",
        ha="right",
        fontfamily="monospace",
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": COL_MUTED, "alpha": 0.90},
        zorder=6,
    )

    # ── scale notice (red subtitle under title) ───────────────────────────────
    if raw_exp != 0:
        ax.text(
            0.0,
            1.02,
            f"Scaled for display \u2014 multiply y-axis by 1e{raw_exp} to recover original units",
            transform=ax.transAxes,
            fontsize=4.8,
            color="#DC2626",
            va="bottom",
            ha="left",
        )

    # ── clip notice ───────────────────────────────────────────────────────────
    if n_clipped > 0:
        raw_ceiling = (ymax / 1.15) / inv
        notice = (
            f"\u25b2 axis clipped at {clip_pct_label}={fmt(raw_ceiling)}  "
            f"(true max={fmt(raw_max)}, "
            f"{n_clipped} bar{'s' if n_clipped != 1 else ''} off-scale)"
        )
        ax.text(
            0.015, 0.03, notice, transform=ax.transAxes, fontsize=4.5, color="#DC2626", va="bottom", ha="left", zorder=6
        )

    # ── legend ────────────────────────────────────────────────────────────────
    ax.legend(
        fontsize=5.5,
        loc="upper left",
        facecolor="white",
        edgecolor=COL_MUTED,
        labelcolor=COL_TEXT,
        framealpha=0.90,
        handlelength=1.4,
        handletextpad=0.5,
        borderpad=0.4,
        labelspacing=0.3,
    )

    # ── axes ──────────────────────────────────────────────────────────────────
    ax.set_title(MEASURE_LABELS.get(metric, metric), color=COL_TEXT, fontsize=7, fontweight="bold", pad=4, loc="left")
    ax.set_xlim(dates[0], dates[-1])
    ax.set_ylim(ymin, ymax)
    ax.tick_params(axis="both", colors=COL_MUTED, labelsize=5.5, length=2.5)
    ax.xaxis.set_major_locator(mdates.YearLocator(4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.setp(ax.get_xticklabels(), color=COL_MUTED)
    plt.setp(ax.get_yticklabels(), color=COL_MUTED)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.3f}"))
    ax.grid(axis="y", color=COL_GRID, linewidth=0.4, alpha=0.8)
    for spine in ax.spines.values():
        spine.set_edgecolor(COL_GRID)
        spine.set_linewidth(0.6)

    fig.tight_layout(pad=0.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor=BG_PAGE, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


# ── per-universe chart generator ──────────────────────────────────────────────
def generate_universe_charts(univ, df, cal):
    """Returns dict: metric -> base64 PNG string."""
    cal_univ = cal.get(univ, {})
    charts = {}
    for _, metrics in CHART_SECTIONS:
        for metric in metrics:
            if metric in df.columns:
                charts[metric] = render_chart(metric, df[metric].dropna(), cal_univ)
    return charts


# ── transform ─────────────────────────────────────────────────────────────────
def transform(consolidated):
    meta = consolidated["meta"]
    hmm = consolidated["hmm"]
    univs = consolidated["universes"]

    cal_path = REGIME_DATA / "calibration.json"
    cal = json.loads(cal_path.read_text()) if cal_path.exists() else {}

    indices = []
    chart_pages = []

    for key in UNIVERSE_ORDER:
        if key not in univs:
            continue
        udata = univs[key]
        narr = udata["liquidity_risk_narrative"]
        measures = narr.get("measures", {})

        def rows(keys):
            return [
                {
                    "measure": MEASURE_LABELS.get(k, k),
                    "tier": measures[k].get("tier", ""),
                    "reading": measures[k].get("reading", ""),
                }
                for k in keys
                if k in measures
            ]

        indices.append(
            {
                "name": UNIVERSE_NAMES.get(key, key),
                "as_of": fmt_date(udata["narrative_date"]),
                "overall_assessment": narr.get("overall", ""),
                "risk_measures": rows(RISK_MEASURES),
                "liquidity_measures": rows(LIQ_MEASURES),
            }
        )

        parquet_path = REGIME_DATA / f"liquidity_risk_{key}.parquet"
        if parquet_path.exists():
            print(f"  Generating charts for {key} ...", flush=True)
            df = pd.read_parquet(parquet_path)
            charts = generate_universe_charts(key, df, cal)
            as_of = fmt_date(udata["narrative_date"])

            sections = []
            for sec_title, metrics in CHART_SECTIONS:
                sections.append(
                    {
                        "title": sec_title,
                        "charts": [
                            {
                                "metric": m,
                                "label": MEASURE_LABELS.get(m, m),
                                "b64": charts.get(m, ""),
                            }
                            for m in metrics
                        ],
                    }
                )

            chart_pages.append(
                {
                    "universe_name": UNIVERSE_NAMES.get(key, key),
                    "as_of": as_of,
                    "sections": sections,
                }
            )
        else:
            print(f"  WARNING: parquet not found for {key}, skipping charts.")

    return {
        "generated_date": fmt_date(meta["run_date"]),
        "regime": {
            "signal": hmm["regime"].upper(),
            "conviction": f"{hmm['regime_conviction'].upper()} CONVICTION",
            "month": fmt_month(hmm["as_of_month"]),
            "bull_probability": round(hmm["P_Bull"] * 100, 2),
            "choppy_probability": round(hmm["P_Choppy"] * 100, 2),
            "crisis_probability": round(hmm["P_Crisis"] * 100, 2),
            "synthesis": hmm["regime_synthesis"],
        },
        "indices": indices,
        "chart_pages": chart_pages,
    }


# ── load JSON ─────────────────────────────────────────────────────────────────
def load_consolidated(date_str=None):
    if date_str:
        path = REGIME_DATA / f"regime_consolidated_{date_str}.json"
        if not path.exists():
            msg = f"Not found: {path}"
            raise FileNotFoundError(msg)
        return json.loads(path.read_text())
    files = sorted(REGIME_DATA.glob("regime_consolidated_*.json"))
    if not files:
        msg = f"No consolidated JSON in {REGIME_DATA}"
        raise FileNotFoundError(msg)
    return json.loads(files[-1].read_text())


# ── render ────────────────────────────────────────────────────────────────────
def render(data, template_path, out_pdf):
    env = Environment(loader=BaseLoader())
    env.filters["tier_class"] = tier_class
    html = env.from_string(Path(template_path).read_text()).render(**data)

    html_path = Path(out_pdf).with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri())
        page.wait_for_load_state("networkidle")
        page.pdf(
            path=str(out_pdf),
            format="A4",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        browser.close()

    print(f"PDF  -> {out_pdf}")
    print(f"HTML -> {html_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Render regime report PDF from consolidated JSON")
    p.add_argument("--date", "-d", default=None, help="Run date YYYY-MM-DD (default: latest)")
    p.add_argument("--out", "-o", default=None, help="Output PDF path")
    p.add_argument("--template", "-t", default=str(TEMPLATE), help=f"Path to template.html (default: {TEMPLATE})")
    return p.parse_args()


def main():
    args = parse_args()
    consolidated = load_consolidated(args.date)
    run_date = consolidated["meta"]["run_date"]
    print("Transforming data and generating charts ...")
    data = transform(consolidated)
    out_pdf = Path(args.out) if args.out else REGIME_DATA / f"regime_report_design_{run_date}.pdf"
    print("Rendering PDF ...")
    render(data, args.template, out_pdf)


if __name__ == "__main__":
    main()
