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
format_portfolio_pdf.py
Reads today's portfolio_recommendations parquet (IST date) and generates
two clean, phone-readable PDFs:

  portfolio_actions_{DDMMYYYY}.pdf    — BUY / HOLD / SELL
  portfolio_watchlist_{DDMMYYYY}.pdf  — WATCHLIST

Prints output paths to stdout (one per line) so the bot can parse and send them.
Exits 1 with message to stderr if parquet not found.

Run standalone to verify:
  python3 /home/ec2-user/nse-factor-engine/ops/format_portfolio_pdf.py
"""

import sys
from pathlib import Path

import pandas as pd

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError:
    sys.exit("ERROR: reportlab not installed. Run: pip3 install reportlab --break-system-packages")

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE = Path("/home/ec2-user/nse-factor-engine")
SIGNALS_DIR = BASE / "signals" / "stage6"
OUT_DIR = BASE / "signals" / "stage6"
COLS = [
    "symbol",
    "as_of_date",
    "rsi_14",
    "market_cap_cr",
    "adtv_63_cr",
    "mr_rank",
    "beta_12m",
    "alpha_12m",
    "portfolio_beta",
    "tier",
    "action",
    "run_date",
]

# ── Colors ─────────────────────────────────────────────────────────────────────
WHITE = colors.white
BG = colors.HexColor("#F8F9FA")
CARD = colors.white
BORDER = colors.HexColor("#DEE2E6")
TEXT = colors.HexColor("#212529")
MUTED = colors.HexColor("#6C757D")
BUY_COL = colors.HexColor("#1A7F37")
HOLD_COL = colors.HexColor("#0969DA")
SELL_COL = colors.HexColor("#CF222E")
WL_COL = colors.HexColor("#6E40C9")
ACCENT = colors.HexColor("#0969DA")

BUY_BG = colors.HexColor("#DAFBE1")
HOLD_BG = colors.HexColor("#DDF4FF")
SELL_BG = colors.HexColor("#FFEBE9")
WL_BG = colors.HexColor("#FBEFFF")


# ── Styles ─────────────────────────────────────────────────────────────────────
def S(name, **kw):
    base = {
        "fontName": "Helvetica",
        "fontSize": 10,
        "textColor": TEXT,
        "leading": 14,
        "alignment": TA_LEFT,
    }
    base.update(kw)
    return ParagraphStyle(name, **base)


S_TITLE = S("ti", fontName="Helvetica-Bold", fontSize=18, textColor=TEXT, leading=22)
S_SUB = S("su", fontSize=9, textColor=MUTED, leading=12)
S_SEC = S("sc", fontName="Helvetica-Bold", fontSize=11, leading=14)
S_SYM = S("sy", fontName="Helvetica-Bold", fontSize=11, textColor=TEXT, leading=14)
S_TIER = S("t", fontSize=8, textColor=MUTED, leading=11)
S_METRIC = S("m", fontSize=9, textColor=MUTED, leading=12, alignment=TA_RIGHT)
S_VAL = S(
    "v", fontName="Helvetica-Bold", fontSize=10, textColor=TEXT, leading=13, alignment=TA_RIGHT
)
S_FOOT = S("ft", fontSize=7, textColor=MUTED, alignment=TA_CENTER, leading=9)


# ── Helpers ────────────────────────────────────────────────────────────────────
def SP(n):
    return Spacer(1, n * mm)


def HR():
    return HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=1)


def fmt(val, suffix="", decimals=0):
    if pd.isna(val):
        return "—"
    if decimals:
        return f"{val:.{decimals}f}{suffix}"
    return f"{int(val)}{suffix}"


def section_header(label, col, bg):
    t = Table(
        [
            [
                Paragraph(
                    label,
                    S("sh", fontName="Helvetica-Bold", fontSize=11, textColor=col, leading=14),
                )
            ]
        ],
        colWidths=[170 * mm],
    )
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return t


def stock_row(row):
    rsi = fmt(row["rsi_14"], decimals=1)
    mcap_val = row["market_cap_cr"]
    if pd.notna(mcap_val):
        if mcap_val >= 100000:
            mcap = f"{mcap_val / 100000:.1f}L"
        elif mcap_val >= 1000:
            mcap = f"{mcap_val / 1000:.0f}K"
        else:
            mcap = f"{int(mcap_val)}cr"
    else:
        mcap = "—"
    adtv = fmt(row["adtv_63_cr"], suffix="cr")
    rank = fmt(row["mr_rank"])
    beta = fmt(row["beta_12m"], decimals=2)
    alpha = fmt(row["alpha_12m"], decimals=2)
    tier = str(row["tier"]).replace("_", " ")

    left = Table(
        [
            [Paragraph(row["symbol"], S_SYM)],
            [Paragraph(tier, S_TIER)],
        ],
        colWidths=[72 * mm],
    )
    left.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    def metric(label, val):
        return Paragraph(
            f"<font size='7' color='#6C757D'>{label}</font><br/><b>{val}</b>",
            S("mi", fontSize=10, textColor=TEXT, leading=13, alignment=TA_RIGHT),
        )

    right = Table(
        [
            [
                metric("Rank", rank),
                metric("Beta", beta),
                metric("Alpha", alpha),
                metric("RSI", rsi),
                metric("MCap", mcap),
                metric("ADTV", adtv),
            ]
        ],
        colWidths=[12 * mm, 13 * mm, 15 * mm, 13 * mm, 18 * mm, 18 * mm],
    )
    right.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )

    inner = Table([[left, right]], colWidths=[72 * mm, 102 * mm])
    inner.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    outer = Table([[inner]], colWidths=[174 * mm])
    outer.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD),
                ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return outer


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BG)
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas.restoreState()


def build_pdf(story, out_path):
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=14 * mm,
        bottomMargin=12 * mm,
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)


def footer(run_date, as_of):
    return [
        SP(3),
        HR(),
        Paragraph(
            f"NSE Factor Engine  ·  Stage 6  ·  Run: {run_date}  ·  As of: {as_of}  ·  Signal only. Not investment advice.",
            S_FOOT,
        ),
    ]


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    run_date_str = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%d%m%Y")
    parquet_path = SIGNALS_DIR / f"portfolio_recommendations_{run_date_str}.parquet"

    if not parquet_path.exists():
        print(
            f"ERROR: {parquet_path.name} not found. Stage 6 may not have completed.",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_parquet(parquet_path)[COLS]
    run_date = pd.to_datetime(df["run_date"].iloc[0]).strftime("%d %b %Y")
    as_of = pd.to_datetime(df["as_of_date"].iloc[0]).strftime("%d %b %Y")

    # ── PDF 1: Actions (BUY / HOLD / SELL) ────────────────────────────────────
    actions_path = OUT_DIR / f"portfolio_actions_{run_date_str}.pdf"
    story = [
        Paragraph("NSE Portfolio Actions", S_TITLE),
        Paragraph(f"Run: {run_date}  ·  As of: {as_of}", S_SUB),
        Paragraph(f"Portfolio Beta (12m): {df['portfolio_beta'].dropna().iloc[0]:.3f}", S_SUB),
        SP(3),
        HR(),
        SP(2),
    ]

    for action, label, col, bg in [
        ("BUY", "🟢 BUY", BUY_COL, BUY_BG),
        ("HOLD", "🔵 HOLD", HOLD_COL, HOLD_BG),
        ("SELL", "🔴 SELL", SELL_COL, SELL_BG),
    ]:
        subset = df[df["action"] == action].sort_values("mr_rank")
        if subset.empty:
            continue
        story += [
            section_header(f"{label}  ({len(subset)})", col, bg),
            SP(1.5),
        ]
        for _, row in subset.iterrows():
            story += [stock_row(row), SP(1.5)]
        story.append(SP(2))

    story += footer(run_date, as_of)
    build_pdf(story, actions_path)

    # ── PDF 2: Watchlist ───────────────────────────────────────────────────────
    watchlist_path = OUT_DIR / f"portfolio_watchlist_{run_date_str}.pdf"
    wl = df[df["action"] == "WATCHLIST"].sort_values("mr_rank").head(13)
    story2 = [
        Paragraph("NSE Watchlist", S_TITLE),
        Paragraph(f"Run: {run_date}  ·  As of: {as_of}", S_SUB),
        SP(3),
        HR(),
        SP(2),
        section_header(f"📋 WATCHLIST  ({len(wl)})", WL_COL, WL_BG),
        SP(1.5),
    ]
    for _, row in wl.iterrows():
        story2 += [stock_row(row), SP(1.5)]
    story2 += footer(run_date, as_of)
    build_pdf(story2, watchlist_path)

    # ── Print output paths for bot to parse ───────────────────────────────────
    print(str(actions_path))
    print(str(watchlist_path))


if __name__ == "__main__":
    main()
