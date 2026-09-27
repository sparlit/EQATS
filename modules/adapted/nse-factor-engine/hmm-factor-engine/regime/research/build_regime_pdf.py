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
build_regime_pdf.py
Reads regime_consolidated_<date>.json and produces a formatted PDF report.
Called automatically by regime_master.py at the end of each run.
Can also be run standalone:
    python3 build_regime_pdf.py                    # uses latest consolidated JSON
    python3 build_regime_pdf.py --date 2026-08-07  # specific date
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

REGIME_DATA = Path("/home/ec2-user/nse-factor-engine/hmm-factor-engine/regime/data")

DARK_NAVY = colors.HexColor("#0D1B2A")
MID_NAVY = colors.HexColor("#1B3A5C")
STEEL_BLUE = colors.HexColor("#2E6DA4")
LIGHT_BLUE = colors.HexColor("#EAF2FB")
ACCENT_GOLD = colors.HexColor("#C9A84C")
BULL_GREEN = colors.HexColor("#1A7A4A")
BULL_BG = colors.HexColor("#EAF7EF")
CRISIS_RED = colors.HexColor("#B03A2E")
CHOPPY_AMB = colors.HexColor("#B7770D")
LIGHT_GRAY = colors.HexColor("#F5F6F7")
MID_GRAY = colors.HexColor("#BDC3C7")
TEXT_DARK = colors.HexColor("#1A1A2E")
TEXT_MED = colors.HexColor("#34495E")
WHITE = colors.white

TIER_COLORS = {
    "CALM": (colors.HexColor("#1A5276"), colors.HexColor("#D6EAF8")),
    "NORMAL": (colors.HexColor("#1A5276"), colors.HexColor("#D6EAF8")),
    "NEUTRAL": (colors.HexColor("#2E4057"), colors.HexColor("#EAF0FB")),
    "MODERATE": (colors.HexColor("#7D6608"), colors.HexColor("#FEF9E7")),
    "SHALLOW": (colors.HexColor("#1A7A4A"), colors.HexColor("#EAF7EF")),
    "RALLY-LIKE": (colors.HexColor("#1A7A4A"), colors.HexColor("#EAF7EF")),
    "ELEVATED": (colors.HexColor("#784212"), colors.HexColor("#FDEBD0")),
    "COMPRESSED": (colors.HexColor("#784212"), colors.HexColor("#FDEBD0")),
    "ILLIQUID": (colors.HexColor("#7B241C"), colors.HexColor("#FDEDEC")),
    "SEVERE": (colors.HexColor("#7B241C"), colors.HexColor("#FDEDEC")),
    "EXTREME": (colors.HexColor("#7B241C"), colors.HexColor("#FDEDEC")),
    "CRISIS": (colors.HexColor("#7B241C"), colors.HexColor("#FDEDEC")),
}

UNIVERSE_NAMES = {
    "nifty100": "Nifty 100",
    "nifty500": "Nifty 500",
    "niftymidcap150": "Nifty Midcap 150",
    "niftysmallcap250": "Nifty Smallcap 250",
}

RISK_MEASURES = ["rv", "avg_corr", "vov", "dispersion", "drawdown", "skew"]
LIQ_MEASURES = ["amihud", "cs_spread", "turnover"]

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


def tier_colors(tier):
    key = tier.upper().strip("[]")
    for k, v in TIER_COLORS.items():
        if k in key:
            return v
    return (TEXT_MED, LIGHT_GRAY)


def load_consolidated(date_str=None):
    if date_str:
        path = REGIME_DATA / f"regime_consolidated_{date_str}.json"
        if not path.exists():
            msg = f"Consolidated JSON not found: {path}"
            raise FileNotFoundError(msg)
        return path, json.loads(path.read_text())
    files = sorted(REGIME_DATA.glob("regime_consolidated_*.json"))
    if not files:
        msg = f"No consolidated JSON found in {REGIME_DATA}"
        raise FileNotFoundError(msg)
    path = files[-1]
    return path, json.loads(path.read_text())


def make_styles():
    return {
        "cover_title": ParagraphStyle(
            "cover_title", fontName="Helvetica-Bold", fontSize=26, textColor=WHITE, leading=32, alignment=TA_LEFT
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            fontName="Helvetica",
            fontSize=12,
            textColor=colors.HexColor("#A8C6E8"),
            leading=18,
            alignment=TA_LEFT,
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta",
            fontName="Helvetica",
            fontSize=10,
            textColor=colors.HexColor("#7FB3D3"),
            leading=14,
            alignment=TA_LEFT,
        ),
        "section_header": ParagraphStyle(
            "section_header",
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=WHITE,
            leading=18,
            alignment=TA_LEFT,
            leftIndent=8,
        ),
        "sub_header": ParagraphStyle(
            "sub_header",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=STEEL_BLUE,
            leading=15,
            spaceBefore=6,
            spaceAfter=3,
        ),
        "metric_label": ParagraphStyle(
            "metric_label", fontName="Helvetica-Bold", fontSize=9, textColor=TEXT_DARK, leading=12
        ),
        "metric_value": ParagraphStyle(
            "metric_value", fontName="Helvetica", fontSize=9, textColor=TEXT_MED, leading=12
        ),
        "reading_text": ParagraphStyle(
            "reading_text", fontName="Helvetica", fontSize=8, textColor=TEXT_MED, leading=11
        ),
        "overall_text": ParagraphStyle(
            "overall_text",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=TEXT_DARK,
            leading=16,
            leftIndent=8,
            rightIndent=8,
        ),
        "tbl_header": ParagraphStyle(
            "tbl_header", fontName="Helvetica-Bold", fontSize=9, textColor=WHITE, leading=12, alignment=TA_LEFT
        ),
    }


def build_measures_table(measure_keys, measures_dict, S, col_w):
    header = [
        Paragraph("Measure", S["tbl_header"]),
        Paragraph("Tier", S["tbl_header"]),
        Paragraph("Reading", S["tbl_header"]),
    ]
    rows = [header]
    for key in measure_keys:
        if key not in measures_dict:
            continue
        m = measures_dict[key]
        tier = m.get("tier", "")
        reading = m.get("reading", "")
        tc, bg = tier_colors(tier)
        rows.append(
            [
                Paragraph(MEASURE_LABELS.get(key, key), S["metric_label"]),
                Paragraph(
                    tier.upper(),
                    ParagraphStyle(
                        f"t_{key}", fontName="Helvetica-Bold", fontSize=8, textColor=tc, leading=11, alignment=TA_CENTER
                    ),
                ),
                Paragraph(reading, S["reading_text"]),
            ]
        )
    widths = [col_w * 0.22, col_w * 0.17, col_w * 0.61]
    tbl = Table(rows, colWidths=widths)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_NAVY),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("LEFTPADDING", (0, 0), (-1, 0), 10),
        ("RIGHTPADDING", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("LEFTPADDING", (0, 1), (-1, -1), 10),
        ("RIGHTPADDING", (0, 1), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, MID_GRAY),
        ("BOX", (0, 0), (-1, -1), 0.5, MID_GRAY),
    ]
    for i, key in enumerate([k for k in measure_keys if k in measures_dict], start=1):
        tier = measures_dict[key].get("tier", "")
        _, bg = tier_colors(tier)
        row_bg = WHITE if i % 2 == 1 else LIGHT_GRAY
        style.append(("BACKGROUND", (0, i), (0, i), row_bg))
        style.append(("BACKGROUND", (1, i), (1, i), bg))
        style.append(("BACKGROUND", (2, i), (2, i), row_bg))
    tbl.setStyle(TableStyle(style))
    return tbl


def build_pdf(consolidated, out_path):
    S = make_styles()
    W, _H = A4
    M = 18 * mm
    col_w = W - 2 * M
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=M,
        rightMargin=M,
        topMargin=M,
        bottomMargin=16 * mm,
        title="NSE Regime Engine Report",
        author="HMM Factor Engine",
    )
    meta = consolidated["meta"]
    hmm = consolidated["hmm"]
    univs = consolidated["universes"]
    content = []

    # Cover
    cover = Table(
        [
            [Paragraph("NSE Regime Engine", S["cover_title"])],
            [Paragraph("Weekly Liquidity, Risk &amp; Regime Report", S["cover_sub"])],
        ],
        colWidths=[col_w],
    )
    cover.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), DARK_NAVY),
                ("TOPPADDING", (0, 0), (-1, 0), 20),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                ("TOPPADDING", (0, 1), (-1, 1), 2),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 18),
                ("LEFTPADDING", (0, 0), (-1, -1), 18),
            ]
        )
    )
    content.append(cover)

    run_meta = Table(
        [
            [
                Paragraph(f"Generated Date: {fmt_date(meta['run_date'])}", S["cover_meta"]),
            ]
        ],
        colWidths=[col_w],
    )
    run_meta.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), MID_NAVY),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 18),
            ]
        )
    )
    content.append(run_meta)
    content.append(Spacer(1, 10 * mm))

    # HMM block
    hmm_hdr = Table([[Paragraph("HMM Regime", S["section_header"])]], colWidths=[col_w])
    hmm_hdr.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), STEEL_BLUE),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("ROUNDEDCORNERS", [4]),
            ]
        )
    )
    content.append(hmm_hdr)
    content.append(Spacer(1, 3 * mm))

    regime = hmm["regime"]
    conviction = hmm["regime_conviction"].upper()
    reg_color = BULL_GREEN if regime == "Bull" else CRISIS_RED if regime == "Crisis" else CHOPPY_AMB
    reg_bg = (
        BULL_BG
        if regime == "Bull"
        else colors.HexColor("#FDEDEC")
        if regime == "Crisis"
        else colors.HexColor("#FEF5E7")
    )

    left_cell = Table(
        [
            [
                Paragraph(
                    f"<b>{regime.upper()}</b>",
                    ParagraphStyle(
                        "big",
                        fontName="Helvetica-Bold",
                        fontSize=28,
                        textColor=reg_color,
                        leading=34,
                        alignment=TA_CENTER,
                    ),
                )
            ],
            [
                Paragraph(
                    f"<b>{conviction} CONVICTION</b>",
                    ParagraphStyle(
                        "conv",
                        fontName="Helvetica-Bold",
                        fontSize=9,
                        textColor=reg_color,
                        leading=13,
                        alignment=TA_CENTER,
                    ),
                )
            ],
            [
                Paragraph(
                    fmt_month(hmm["as_of_month"]),
                    ParagraphStyle(
                        "asof",
                        fontName="Helvetica",
                        fontSize=9,
                        textColor=colors.HexColor("#888888"),
                        leading=13,
                        alignment=TA_CENTER,
                    ),
                )
            ],
        ],
        colWidths=[col_w * 0.32],
    )
    left_cell.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), reg_bg),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )

    right_cell = Table(
        [
            [
                Paragraph("<b>Bull Probability</b>", S["metric_label"]),
                Paragraph(f"{hmm['P_Bull']:.2%}", S["metric_value"]),
            ],
            [
                Paragraph("<b>Choppy Probability</b>", S["metric_label"]),
                Paragraph(f"{hmm['P_Choppy']:.2%}", S["metric_value"]),
            ],
            [
                Paragraph("<b>Crisis Probability</b>", S["metric_label"]),
                Paragraph(f"{hmm['P_Crisis']:.2%}", S["metric_value"]),
            ],
        ],
        colWidths=[col_w * 0.35, col_w * 0.33],
    )
    right_cell.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, MID_GRAY),
            ]
        )
    )

    regime_row = Table([[left_cell, right_cell]], colWidths=[col_w * 0.32, col_w * 0.68])
    regime_row.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, MID_GRAY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    content.append(regime_row)
    content.append(Spacer(1, 3 * mm))

    synth = Table(
        [
            [Paragraph("<b>Regime Synthesis</b>", S["sub_header"])],
            [Paragraph(hmm["regime_synthesis"], S["overall_text"])],
        ],
        colWidths=[col_w],
    )
    synth.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), STEEL_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("BACKGROUND", (0, 1), (-1, 1), LIGHT_BLUE),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("BOX", (0, 0), (-1, -1), 1.5, STEEL_BLUE),
                ("LINEBEFORE", (0, 0), (-1, -1), 5, STEEL_BLUE),
            ]
        )
    )
    content.append(synth)
    content.append(Spacer(1, 8 * mm))

    # Per-universe
    for univ_key in ["nifty100", "nifty500", "niftymidcap150", "niftysmallcap250"]:
        if univ_key not in univs:
            continue
        udata = univs[univ_key]
        narr = udata["liquidity_risk_narrative"]
        measures = narr.get("measures", {})
        lag_note = udata.get("hmm_lag_note")
        univ_name = UNIVERSE_NAMES.get(univ_key, univ_key)
        narr_date = udata["narrative_date"]
        elems = []

        u_hdr = Table(
            [
                [
                    Paragraph(
                        univ_name,
                        ParagraphStyle(
                            "univ_name",
                            fontName="Helvetica-Bold",
                            fontSize=16,
                            textColor=WHITE,
                            leading=20,
                            alignment=TA_LEFT,
                        ),
                    )
                ],
                [
                    Paragraph(
                        f"Liquidity &amp; Risk  |  {fmt_date(narr_date)}",
                        ParagraphStyle(
                            "univ_sub",
                            fontName="Helvetica",
                            fontSize=9,
                            textColor=colors.HexColor("#A8C6E8"),
                            leading=13,
                            alignment=TA_LEFT,
                        ),
                    )
                ],
            ],
            colWidths=[col_w],
        )
        u_hdr.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), DARK_NAVY),
                    ("TOPPADDING", (0, 0), (-1, 0), 14),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                    ("TOPPADDING", (0, 1), (-1, 1), 2),
                    ("BOTTOMPADDING", (0, 1), (-1, 1), 12),
                    ("LEFTPADDING", (0, 0), (-1, -1), 16),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 16),
                    ("LINEBEFORE", (0, 0), (-1, -1), 5, ACCENT_GOLD),
                ]
            )
        )
        elems.append(u_hdr)
        elems.append(Spacer(1, 3 * mm))

        if lag_note:
            warn = Table(
                [
                    [
                        Paragraph(
                            f"&#9888; {lag_note}",
                            ParagraphStyle(
                                "warn",
                                fontName="Helvetica",
                                fontSize=8,
                                textColor=colors.HexColor("#784212"),
                                leading=11,
                            ),
                        )
                    ]
                ],
                colWidths=[col_w],
            )
            warn.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDEBD0")),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#784212")),
                    ]
                )
            )
            elems.append(warn)
            elems.append(Spacer(1, 2 * mm))

        ov = Table(
            [
                [Paragraph("<b>Overall Assessment</b>", S["sub_header"])],
                [Paragraph(narr.get("overall", ""), S["overall_text"])],
            ],
            colWidths=[col_w],
        )
        ov.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), MID_NAVY),
                    ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                    ("BACKGROUND", (0, 1), (-1, 1), LIGHT_BLUE),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ("LEFTPADDING", (0, 0), (-1, -1), 14),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                    ("BOX", (0, 0), (-1, -1), 1.5, MID_NAVY),
                    ("LINEBEFORE", (0, 0), (-1, -1), 5, STEEL_BLUE),
                ]
            )
        )
        elems.append(ov)
        elems.append(Spacer(1, 3 * mm))

        elems.append(Paragraph("Risk Measures", S["sub_header"]))
        elems.append(build_measures_table(RISK_MEASURES, measures, S, col_w))
        elems.append(Spacer(1, 3 * mm))

        elems.append(Paragraph("Liquidity Measures", S["sub_header"]))
        elems.append(build_measures_table(LIQ_MEASURES, measures, S, col_w))
        elems.append(Spacer(1, 8 * mm))

        content.append(KeepTogether(elems[:4]))
        content.extend(elems[4:])

    doc.build(content)
    print(f"PDF saved -> {out_path}")
    return out_path


def parse_args():
    p = argparse.ArgumentParser(description="Generate regime PDF from consolidated JSON")
    p.add_argument("--date", "-d", default=None, help="Run date YYYY-MM-DD (default: latest available)")
    p.add_argument("--out", "-o", default=None, help="Output PDF path (default: regime_data/regime_report_<date>.pdf)")
    return p.parse_args()


def main():
    args = parse_args()
    _json_path, consolidated = load_consolidated(args.date)
    run_date = consolidated["meta"]["run_date"]
    out_path = Path(args.out) if args.out else REGIME_DATA / f"regime_report_{run_date}.pdf"
    build_pdf(consolidated, out_path)


if __name__ == "__main__":
    main()
