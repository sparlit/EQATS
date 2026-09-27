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
Market Movement PDF Report Generator
Run from repo root: python3 market_movement/generate_market_report.py
Reads : market_movement/data/market_movement_metrics.parquet
Writes: market_movement/data/market_movement_report_{RUN_DATE}.pdf
"""

import io
import sys
from pathlib import Path

import matplotlib as mpl
import numpy as np
import pandas as pd

mpl.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except ImportError:
    sys.exit("ERROR: reportlab not installed.\nRun: pip3 install reportlab --break-system-packages")

# ── Paths ─────────────────────────────────────────
if not Path("signals").is_dir():
    sys.exit("ERROR: Run from repo root (nse-factor-engine/)")

DATA_DIR = Path("market_movement/data")
INPUT_PATH = DATA_DIR / "market_movement_metrics.parquet"
BREADTH_PATH = DATA_DIR / "breadth_metrics.parquet"
RUN_DATE = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%d%m%Y")
OUT_PATH = DATA_DIR / f"market_movement_report_{RUN_DATE}.pdf"

if not INPUT_PATH.exists():
    sys.exit(f"ERROR: {INPUT_PATH} not found. Run compute_market_metrics.py first.")

# ── Data ──────────────────────────────────────────
df = pd.read_parquet(INPUT_PATH)
as_of = pd.to_datetime(df["as_of_date"].iloc[0]).strftime("%d %b %Y")
run_date = pd.to_datetime(df["run_date"].iloc[0]).strftime("%d %b %Y")

# Load breadth (optional — report continues without it)
breadth_latest = None
if BREADTH_PATH.exists():
    breadth = pd.read_parquet(BREADTH_PATH)
    breadth_latest = breadth.sort_values("date").iloc[-1]
    print(f"Breadth data loaded: {len(breadth)} rows, latest {breadth_latest['date'].date()}")
else:
    print(f"WARNING: {BREADTH_PATH} not found — breadth section will be skipped.")


def get(symbol, col):
    row = df[df["symbol"] == symbol]
    if row.empty:
        return None
    val = row[col].iloc[0]
    return None if (isinstance(val, float) and np.isnan(val)) else val


# ── Ticker config ─────────────────────────────────
BROAD = [("^NSEI", "Nifty 50"), ("^CRSLDX", "Nifty 500")]
SECTORAL = [
    ("^NSEBANK", "Nifty Bank"),
    ("^CNXIT", "Nifty IT"),
    ("^CNXPHARMA", "Nifty Pharma"),
    ("^NSEMDCP50", "Nifty Midcap 50"),
    ("NIFTYMIDCAP150.NS", "Nifty Midcap 150"),
    ("SML100CASE.NS", "Nifty Smallcap 100"),
]

# ── Fixed phrase maps ─────────────────────────────
STAGE_LABEL = {
    "STAGE_1_ACCUMULATION": "Stage 1  Accumulation",
    "STAGE_2_ADVANCING": "Stage 2  Advancing",
    "STAGE_3_DISTRIBUTION": "Stage 3  Distribution",
    "STAGE_4_TRANSITION_BREAKDOWN": "Stage 4  Breakdown",
    "STAGE_4_DECLINING": "Stage 4  Declining",
    "TRANSITION_ZONE": "Transition Zone",
    "INSUFFICIENT_DATA": "Insufficient Data",
}
STAGE_DESC = {
    "STAGE_1_ACCUMULATION": "Range-bound, SMA slope flat. No confirmed direction.",
    "STAGE_2_ADVANCING": "Above SMA, slope rising. Confirmed uptrend.",
    "STAGE_3_DISTRIBUTION": "Whipsawing around SMA, slope flat. Topping pattern.",
    "STAGE_4_TRANSITION_BREAKDOWN": "Below support, slope negative. Breakdown underway.",
    "STAGE_4_DECLINING": "Below SMA, slope negative. Confirmed downtrend.",
    "TRANSITION_ZONE": "No confirmed stage. Structural clarity lacking.",
    "INSUFFICIENT_DATA": "Insufficient history to classify.",
}
STAGE_COLOR = {
    "STAGE_1_ACCUMULATION": colors.HexColor("#B8860B"),
    "STAGE_2_ADVANCING": colors.HexColor("#2E7D32"),
    "STAGE_3_DISTRIBUTION": colors.HexColor("#E65100"),
    "STAGE_4_TRANSITION_BREAKDOWN": colors.HexColor("#B71C1C"),
    "STAGE_4_DECLINING": colors.HexColor("#B71C1C"),
    "TRANSITION_ZONE": colors.HexColor("#37474F"),
    "INSUFFICIENT_DATA": colors.HexColor("#37474F"),
}
VIX_TIER_DESC = {
    "GOING_UP_CONFIRMED": "Systemic fear rising — confirmed spike.",
    "DEVELOPING_UPTREND": "Fear building — institutional hedging picking up.",
    "STABLE": "Fear flat — risk perception unchanged.",
    "DEVELOPING_DOWNTREND": "Fear easing — option premiums cooling.",
    "GOING_DOWN_CONFIRMED": "Fear exiting decisively — risk-off trade unwinding.",
    "INSUFFICIENT_DATA": "Insufficient data.",
}
VIX_TIER_COLOR = {
    "GOING_UP_CONFIRMED": colors.HexColor("#B71C1C"),
    "DEVELOPING_UPTREND": colors.HexColor("#E65100"),
    "STABLE": colors.HexColor("#37474F"),
    "DEVELOPING_DOWNTREND": colors.HexColor("#2E7D32"),
    "GOING_DOWN_CONFIRMED": colors.HexColor("#1B5E20"),
    "INSUFFICIENT_DATA": colors.HexColor("#37474F"),
}
COMBO_DESC = {
    "CONFIDENCE_HEALTHY_RALLY": "VIX falling, market rising — stable, climbing conditions. No immediate danger.",
    "PANIC_REAL_CRASH": "VIX spiking, market falling — fear is real. Do not catch a falling knife.",
    "FOMO_PRE_EVENT_ANXIETY": "VIX rising, market rising — overstretching. Sharp reversal possible.",
    "COMPLACENCY_BOREDOM": "VIX flat, market flat — range-bound. Big money is waiting.",
    "VIX_UP_MARKET_STABLE": "Fear rising, market holding — stress accumulating. Watch closely.",
    "VIX_STABLE_MARKET_UP": "Market rising on low fear — clean, unhedged rally.",
    "VIX_STABLE_MARKET_DOWN": "Market falling on low fear — orderly decline, not panic.",
    "VIX_DOWN_MARKET_STABLE": "Fear fading, market flat — calm returning, no breakout yet.",
    "VIX_DOWN_MARKET_DOWN": "VIX dropping as market falls — bottom may be near.",
    "INSUFFICIENT_DATA": "Insufficient data.",
}
COMBO_COLOR = {
    "CONFIDENCE_HEALTHY_RALLY": colors.HexColor("#1B5E20"),
    "PANIC_REAL_CRASH": colors.HexColor("#7F0000"),
    "FOMO_PRE_EVENT_ANXIETY": colors.HexColor("#BF360C"),
    "COMPLACENCY_BOREDOM": colors.HexColor("#37474F"),
    "VIX_UP_MARKET_STABLE": colors.HexColor("#E65100"),
    "VIX_STABLE_MARKET_UP": colors.HexColor("#2E7D32"),
    "VIX_STABLE_MARKET_DOWN": colors.HexColor("#B8860B"),
    "VIX_DOWN_MARKET_STABLE": colors.HexColor("#37474F"),
    "VIX_DOWN_MARKET_DOWN": colors.HexColor("#B8860B"),
    "INSUFFICIENT_DATA": colors.HexColor("#37474F"),
}

BREADTH_LABEL_COLOR = {
    "BROAD_BULL": colors.HexColor("#1B5E20"),
    "NARROW_BULL": colors.HexColor("#2E7D32"),
    "MIXED": colors.HexColor("#37474F"),
    "NARROW_BEAR": colors.HexColor("#B71C1C"),
    "BROAD_BEAR": colors.HexColor("#7F0000"),
}

SIGNAL_COLOR = {
    "BULLISH": colors.HexColor("#2E7D32"),
    "STRONG_BREADTH": colors.HexColor("#1B5E20"),
    "OVERBOUGHT": colors.HexColor("#B8860B"),
    "BEARISH": colors.HexColor("#B71C1C"),
    "WEAK_BREADTH": colors.HexColor("#B71C1C"),
    "OVERSOLD": colors.HexColor("#B8860B"),
    "NEUTRAL": colors.HexColor("#37474F"),
    "INSUFFICIENT_DATA": colors.HexColor("#37474F"),
}

# ── Colors ────────────────────────────────────────
BG = colors.HexColor("#0D1117")
CARD = colors.HexColor("#161B22")
BORDER = colors.HexColor("#30363D")
TEXT = colors.HexColor("#E6EDF3")
MUTED = colors.HexColor("#8B949E")
ACCENT = colors.HexColor("#58A6FF")
GREEN = colors.HexColor("#3FB950")
RED = colors.HexColor("#F85149")


# ── Styles ────────────────────────────────────────
def S(name, **kw):
    base = {"fontName": "Helvetica", "fontSize": 11, "textColor": TEXT, "leading": 15, "alignment": TA_LEFT}
    base.update(kw)
    return ParagraphStyle(name, **base)


S_TITLE = S("t", fontName="Helvetica-Bold", fontSize=20, textColor=ACCENT, leading=24)
S_SUB = S("s", fontSize=10, textColor=MUTED, leading=13)
S_SEC = S("sc", fontName="Helvetica-Bold", fontSize=11, textColor=ACCENT, leading=14)
S_NAME = S("n", fontName="Helvetica-Bold", fontSize=11, textColor=TEXT, leading=14)
S_DESC = S("d", fontSize=10, textColor=MUTED, leading=13)
S_PILL = S("pl", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white, leading=11, alignment=TA_CENTER)
S_RIGHT = S("r", fontName="Helvetica-Bold", fontSize=11, textColor=TEXT, leading=14, alignment=TA_RIGHT)
S_RMUT = S("rm", fontSize=10, textColor=MUTED, leading=13, alignment=TA_RIGHT)
S_COMBO = S("cb", fontName="Helvetica-Bold", fontSize=15, textColor=colors.white, leading=19, alignment=TA_CENTER)
S_CDSUB = S("cs", fontSize=10, textColor=colors.HexColor("#CCCCCC"), leading=13, alignment=TA_CENTER)
S_FOOT = S("ft", fontSize=8, textColor=MUTED, alignment=TA_CENTER, leading=10)


# ── Helpers ───────────────────────────────────────
def fmt_ret(v):
    if v is None:
        return "—"
    return f"{v:+.2f}%"


def fmt_prox(v):
    if v is None:
        return "—"
    if v >= 1.0:
        return "At 52W high"
    return f"{v * 100:.1f}% of 52W high"


def ret_color(v):
    if v is None:
        return MUTED
    return GREEN if v > 0 else (RED if v < 0 else MUTED)


def card_style():
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, -1), CARD),
            ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
    )


def pill(label, color):
    t = Table([[Paragraph(label, S_PILL)]], colWidths=[38 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), color),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return t


def breadth_row(label, value_str, signal_str, desc_str):
    sig_color = SIGNAL_COLOR.get(signal_str, MUTED)
    inner = Table(
        [
            [
                Paragraph(label, S("bl", fontName="Helvetica-Bold", fontSize=10, textColor=TEXT, leading=13)),
                Paragraph(
                    value_str,
                    S("bv", fontName="Helvetica-Bold", fontSize=10, textColor=TEXT, leading=13, alignment=TA_RIGHT),
                ),
                pill(signal_str.replace("_", " "), sig_color),
                Paragraph(desc_str, S_DESC),
            ]
        ],
        colWidths=[38 * mm, 28 * mm, 38 * mm, 68 * mm],
    )
    inner.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    outer = Table([[inner]], colWidths=[174 * mm])
    outer.setStyle(card_style())
    return outer


def make_breadth_chart(chart_df, y_cols, colors_list, labels, hlines=None, fill_zero=False, width_mm=174, height_mm=38):
    """
    Render a breadth trend chart as a reportlab Image (in-memory PNG).

    chart_df   : DataFrame with 'date' column + y_cols
    y_cols     : list of column names to plot
    colors_list: list of hex colour strings, one per y_col
    labels     : list of legend labels, one per y_col
    hlines     : list of (y_value, colour, linestyle) for reference lines
    fill_zero  : if True, fill area between first y_col and zero line
    """
    fig_w = width_mm / 25.4
    fig_h = height_mm / 25.4
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    # Dark background matching report
    fig.patch.set_facecolor("#0D1117")
    ax.set_facecolor("#161B22")

    dates = chart_df["date"]

    for col, col_color, label in zip(y_cols, colors_list, labels, strict=False):
        vals = chart_df[col]
        ax.plot(dates, vals, color=col_color, linewidth=0.9, label=label)
        if fill_zero:
            ax.fill_between(dates, vals, 0, where=(vals >= 0), color=col_color, alpha=0.15)
            ax.fill_between(dates, vals, 0, where=(vals < 0), color="#F85149", alpha=0.15)

    # Reference lines
    if hlines:
        for yval, hcol, hstyle in hlines:
            ax.axhline(yval, color=hcol, linewidth=0.6, linestyle=hstyle)

    # X-axis: monthly ticks, YYYY-MM labels
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax.tick_params(axis="x", colors="#8B949E", labelsize=5.5, length=2)
    ax.tick_params(axis="y", colors="#8B949E", labelsize=6, length=2)
    for spine in ax.spines.values():
        spine.set_edgecolor("#30363D")
        spine.set_linewidth(0.4)

    # Legend if multiple lines
    if len(y_cols) > 1:
        ax.legend(
            fontsize=5.5,
            loc="upper left",
            facecolor="#161B22",
            edgecolor="#30363D",
            labelcolor="#8B949E",
            framealpha=0.8,
        )

    plt.tight_layout(pad=0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)

    from reportlab.platypus import Image as RLImage

    return RLImage(buf, width=width_mm * mm, height=height_mm * mm)


def index_row(sym, name):
    state = get(sym, "weinstein_state") or "INSUFFICIENT_DATA"
    ret = get(sym, "ret_21d_pct")
    prox = get(sym, "proximity_52w_high")
    rc = ret_color(ret)

    inner = Table(
        [
            [
                pill(STAGE_LABEL.get(state, state), STAGE_COLOR.get(state, MUTED)),
                [
                    Paragraph(f"<b>{name}</b>  <font color='#8B949E'>{sym}</font>", S_NAME),
                    Paragraph(STAGE_DESC.get(state, ""), S_DESC),
                ],
                [
                    Paragraph(f"<font color='#{rc.hexval()[2:]}'>{fmt_ret(ret)}</font>", S_RIGHT),
                    Paragraph(fmt_prox(prox), S_RMUT),
                ],
            ]
        ],
        colWidths=[40 * mm, 98 * mm, 32 * mm],
    )
    inner.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ]
        )
    )
    outer = Table([[inner]], colWidths=[174 * mm])
    outer.setStyle(card_style())
    return outer


# ── Build PDF ─────────────────────────────────────
doc = SimpleDocTemplate(
    str(OUT_PATH), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=14 * mm, bottomMargin=12 * mm
)


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BG)
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas.restoreState()


def SP(n):
    return Spacer(1, n * mm)


def HR():
    return HRFlowable(width="100%", thickness=0.4, color=BORDER, spaceAfter=2)


story = []

# Header
story += [
    Paragraph("NSE Factor Engine — Market Movement", S_TITLE),
    Paragraph(f"Data as of {as_of}  ·  Generated {run_date}", S_SUB),
    SP(3),
    HR(),
    SP(2),
]

# Broad Market
story += [Paragraph("BROAD MARKET", S_SEC), SP(1.5)]
for sym, name in BROAD:
    story += [index_row(sym, name), SP(1.5)]

story += [SP(2)]

# Sectoral
story += [Paragraph("SECTORAL", S_SEC), SP(1.5)]
for sym, name in SECTORAL:
    story += [index_row(sym, name), SP(1.5)]

story += [SP(2)]

# VIX
vix_sym = "^INDIAVIX"
vix_ret = get(vix_sym, "ret_21d_pct")
vix_lvl = get(vix_sym, "close")
vix_5tier = get(vix_sym, "vix_5tier") or "INSUFFICIENT_DATA"
vc = ret_color(vix_ret)

story += [Paragraph("VOLATILITY", S_SEC), SP(1.5)]
vix_inner = Table(
    [
        [
            pill(vix_5tier.replace("_", " "), VIX_TIER_COLOR.get(vix_5tier, MUTED)),
            [
                Paragraph("<b>India VIX</b>  <font color='#8B949E'>^INDIAVIX</font>", S_NAME),
                Paragraph(VIX_TIER_DESC.get(vix_5tier, ""), S_DESC),
            ],
            [
                Paragraph(f"<font color='#{vc.hexval()[2:]}'>{fmt_ret(vix_ret)}</font>", S_RIGHT),
                Paragraph(f"Level: {vix_lvl:.2f}" if vix_lvl else "—", S_RMUT),
            ],
        ]
    ],
    colWidths=[40 * mm, 98 * mm, 32 * mm],
)
vix_inner.setStyle(
    TableStyle(
        [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ]
    )
)
vix_outer = Table([[vix_inner]], colWidths=[174 * mm])
vix_outer.setStyle(card_style())
story += [vix_outer, SP(2)]

# Regime combo card
combo = get(vix_sym, "combo_state") or "INSUFFICIENT_DATA"
mkt_3tier = get(vix_sym, "market_3tier") or "—"
mkt_ret = get(vix_sym, "market_ret_21d_pct")
combo_col = COMBO_COLOR.get(combo, MUTED)
combo_desc = COMBO_DESC.get(combo, combo)

story += [Paragraph("REGIME SIGNAL", S_SEC), SP(1.5)]

sub_row = Table(
    [
        [
            Table(
                [
                    [
                        Paragraph(
                            "VIX",
                            S("vl", fontSize=9, textColor=colors.HexColor("#AAAAAA"), leading=11, alignment=TA_CENTER),
                        ),
                        Paragraph(
                            vix_5tier.replace("_", " "),
                            S(
                                "vv",
                                fontName="Helvetica-Bold",
                                fontSize=10,
                                textColor=colors.white,
                                leading=13,
                                alignment=TA_CENTER,
                            ),
                        ),
                    ]
                ],
                colWidths=[83 * mm],
            ),
            Table(
                [
                    [
                        Paragraph(
                            "MARKET",
                            S("ml", fontSize=9, textColor=colors.HexColor("#AAAAAA"), leading=11, alignment=TA_CENTER),
                        ),
                        Paragraph(
                            f"{mkt_3tier.replace('_', ' ')}  ({fmt_ret(mkt_ret)})",
                            S(
                                "mv",
                                fontName="Helvetica-Bold",
                                fontSize=10,
                                textColor=colors.white,
                                leading=13,
                                alignment=TA_CENTER,
                            ),
                        ),
                    ]
                ],
                colWidths=[83 * mm],
            ),
        ]
    ],
    colWidths=[83 * mm, 83 * mm],
)
sub_row.setStyle(
    TableStyle(
        [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]
    )
)

combo_card = Table(
    [
        [Paragraph(combo.replace("_", " "), S_COMBO)],
        [Paragraph(combo_desc, S_CDSUB)],
        [SP(1)],
        [sub_row],
    ],
    colWidths=[172 * mm],
)
combo_card.setStyle(
    TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, -1), combo_col),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
    )
)
story += [combo_card, SP(3), HR(), SP(2)]

# ── BREADTH SECTION ───────────────────────────────
if breadth_latest is not None:
    bl = breadth_latest

    # Chart data: up to 5 years, or all available
    breadth["date"] = pd.to_datetime(breadth["date"])
    cutoff = breadth["date"].max() - pd.DateOffset(years=5)
    chart_df = breadth[breadth["date"] >= cutoff].copy()

    def _bfmt(v, fmt=".1f"):
        return "—" if pd.isna(v) else f"{v:{fmt}}"

    adv = int(bl["adv_count"])
    dec = int(bl["dec_count"])
    univ = int(bl["universe_size"])
    unch = univ - adv - dec

    story += [Paragraph("MARKET BREADTH", S_SEC), SP(1.5)]
    story += [
        Paragraph(
            f"<font color='#8B949E'>as of {pd.to_datetime(bl['date']).strftime('%d %b %Y')}  ·  "
            f"universe: {univ} stocks  ·  "
            f"advancing: {adv}  declining: {dec}  unchanged: {unch}</font>",
            S_DESC,
        ),
        SP(1.5),
    ]

    # Composite breadth banner
    b_label = str(bl["breadth_label"])
    b_score = int(bl["breadth_score"])
    b_narrative = str(bl["breadth_narrative"])
    b_color = BREADTH_LABEL_COLOR.get(b_label, MUTED)
    S_BN = S("bn", fontName="Helvetica-Bold", fontSize=13, textColor=colors.white, leading=16, alignment=TA_CENTER)
    S_BND = S("bnd", fontSize=9, textColor=colors.HexColor("#CCCCCC"), leading=12, alignment=TA_CENTER)
    S_BSC = S("bsc", fontSize=9, textColor=colors.HexColor("#AAAAAA"), leading=11, alignment=TA_CENTER)
    banner = Table(
        [
            [Paragraph(f"{b_label.replace('_', ' ')}  ({b_score:+d} / 7)", S_BN)],
            [Paragraph(b_narrative, S_BND)],
        ],
        colWidths=[172 * mm],
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), b_color),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story += [banner, SP(2)]

    ad_sig = "BULLISH" if bl["ad_line"] > 0 else ("BEARISH" if bl["ad_line"] < 0 else "NEUTRAL")
    story += [
        breadth_row(
            "A/D Line",
            _bfmt(bl["ad_line"], ".0f"),
            ad_sig,
            "Cumulative advancing minus declining. Rising = broad participation.",
        ),
        SP(1),
    ]
    story += [
        make_breadth_chart(
            chart_df, ["ad_line"], ["#58A6FF"], ["A/D Line"], hlines=[(0, "#8B949E", "--")], fill_zero=True
        ),
        SP(1.5),
    ]

    story += [
        breadth_row(
            "Adv / Dec Ratio",
            _bfmt(bl["adr"], ".3f"),
            str(bl["adr_signal"]),
            ">1.5 = strong breadth  |  <0.67 = weak breadth",
        ),
        SP(1),
    ]
    story += [
        make_breadth_chart(
            chart_df,
            ["adr"],
            ["#3FB950"],
            ["ADR"],
            hlines=[(1.5, "#3FB950", ":"), (1.0, "#8B949E", "--"), (0.67, "#F85149", ":")],
        ),
        SP(1.5),
    ]

    nh = int(bl["new_highs"])
    nl = int(bl["new_lows"])
    nh_sig = "BULLISH" if nh > nl else ("BEARISH" if nl > nh else "NEUTRAL")
    story += [
        breadth_row(
            "52W Highs / Lows",
            f"{nh} H  /  {nl} L",
            nh_sig,
            "New 52-week highs vs lows. More highs = broadening participation.",
        ),
        SP(1),
    ]
    story += [
        make_breadth_chart(
            chart_df,
            ["new_highs", "new_lows"],
            ["#3FB950", "#F85149"],
            ["New Highs", "New Lows"],
            hlines=[(0, "#8B949E", "--")],
        ),
        SP(1.5),
    ]

    story += [
        breadth_row(
            "McClellan Osc",
            _bfmt(bl["mcclellan"], ".2f"),
            str(bl["mcclellan_signal"]),
            "EMA(19) - EMA(39) of net advances. Bands: +100 overbought / -100 oversold",
        ),
        SP(1),
    ]
    story += [
        make_breadth_chart(
            chart_df,
            ["mcclellan"],
            ["#E6EDF3"],
            ["McClellan"],
            hlines=[(100, "#F85149", ":"), (0, "#8B949E", "--"), (-100, "#3FB950", ":")],
            fill_zero=True,
        ),
        SP(1.5),
    ]

    story += [
        breadth_row(
            "TRIN (Arms Index)",
            _bfmt(bl["trin"], ".3f"),
            str(bl["trin_signal"]),
            "<0.8 = advancing vol dominates (bullish)  |  >1.2 = declining vol heavy (bearish)",
        ),
        SP(1),
    ]
    story += [
        make_breadth_chart(
            chart_df,
            ["trin"],
            ["#E6A817"],
            ["TRIN"],
            hlines=[(1.2, "#F85149", ":"), (1.0, "#8B949E", "--"), (0.8, "#3FB950", ":")],
        ),
        SP(1.5),
    ]

    p50 = bl["pct_above_50sma"]
    p50_sig = "BULLISH" if (pd.notna(p50) and p50 > 60) else ("BEARISH" if (pd.notna(p50) and p50 < 40) else "NEUTRAL")
    story += [
        breadth_row(
            "% > 50-day SMA",
            f"{_bfmt(p50)}%",
            p50_sig,
            "Medium-term participation. >60% healthy  |  <40% deteriorating",
        ),
        SP(1),
    ]
    story += [
        make_breadth_chart(
            chart_df,
            ["pct_above_50sma", "pct_above_200sma"],
            ["#58A6FF", "#E6A817"],
            ["% > 50d SMA", "% > 200d SMA"],
            hlines=[(60, "#3FB950", ":"), (40, "#F85149", ":")],
        ),
        SP(1.5),
    ]

    p200 = bl["pct_above_200sma"]
    p200_sig = (
        "BULLISH"
        if (pd.notna(p200) and p200 > 60)
        else "BEARISH"
        if (pd.notna(p200) and p200 < 40)
        else "NEUTRAL"
        if pd.notna(p200)
        else "INSUFFICIENT_DATA"
    )
    story += [
        breadth_row(
            "% > 200-day SMA",
            f"{_bfmt(p200)}%" if pd.notna(p200) else "—",
            p200_sig,
            "Long-term participation. >60% = bull structure  |  <40% = bear territory",
        ),
        SP(2),
    ]
    # chart already rendered above (combined with 50-day)

    story += [HR()]

story += [
    SP(2),
    Paragraph("NSE Factor Engine  ·  Stage 8  ·  market_movement/  ·  Signal only. Not investment advice.", S_FOOT),
]

doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print(f"Saved: {OUT_PATH}")
