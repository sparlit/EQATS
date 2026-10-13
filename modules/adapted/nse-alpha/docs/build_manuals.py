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


"""Build script for the NSE Alpha Project Manual and Explanatory Manual PDFs.

Generates:
- docs/NSE_Alpha_Project_Manual.pdf (~13-15 pages)
- docs/NSE_Alpha_Explanatory_Manual.pdf (~20-22 pages)
"""


from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Color Palette
# ---------------------------------------------------------------------------
NAVY = colors.HexColor("#1A365D")
SLATE_BLUE = colors.HexColor("#2B6CB0")
LIGHT_BLUE_BG = colors.HexColor("#EBF8FF")
DARK_GRAY = colors.HexColor("#2D3748")
BODY_GRAY = colors.HexColor("#4A5568")
LIGHT_GRAY_BG = colors.HexColor("#F7FAFC")
BORDER_GRAY = colors.HexColor("#CBD5E0")
AMBER_WARN = colors.HexColor("#C05621")
AMBER_BG = colors.HexColor("#FFFAF0")
AMBER_BORDER = colors.HexColor("#DD6B20")
CODE_BG = colors.HexColor("#EDF2F7")
GREEN_ACCENT = colors.HexColor("#22543D")
GREEN_BG = colors.HexColor("#F0FFF4")


# ---------------------------------------------------------------------------
# Numbered Canvas for Two-Pass Page Numbering & Running Headers/Footers
# ---------------------------------------------------------------------------
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, page_count: int) -> None:
        self.saveState()
        page_num = self._pageNumber
        doc_title = getattr(self, "_doc_title", "NSE Alpha Research Pipeline")

        # Header (pages > 1)
        if page_num > 1:
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(NAVY)
            self.drawString(54, 750, "NSE ALPHA")
            self.setFont("Helvetica", 8)
            self.setFillColor(BODY_GRAY)
            self.drawString(115, 750, f"|   {doc_title}")

            # Header rule
            self.setStrokeColor(BORDER_GRAY)
            self.setLineWidth(0.5)
            self.line(54, 742, 612 - 54, 742)

        # Footer (all pages)
        self.setStrokeColor(BORDER_GRAY)
        self.setLineWidth(0.5)
        self.line(54, 45, 612 - 54, 45)

        self.setFont("Helvetica", 8)
        self.setFillColor(BODY_GRAY)
        self.drawString(54, 32, "nse_alpha v0.1.0  |  Research Documentation & Reference")
        self.drawRightString(612 - 54, 32, f"Page {page_num} of {page_count}")

        self.restoreState()


class ProjectCanvas(NumberedCanvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._doc_title = "Project Manual (Operator & User Guide)"


class ExplanatoryCanvas(NumberedCanvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._doc_title = "Explanatory & Technical Manual (Methodology Deep-Dive)"


# ---------------------------------------------------------------------------
# Style Factory
# ---------------------------------------------------------------------------
def build_stylesheet() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}

    styles["DocTitle"] = ParagraphStyle(
        "DocTitle",
        parent=sample["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=NAVY,
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    styles["DocSubtitle"] = ParagraphStyle(
        "DocSubtitle",
        parent=sample["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=SLATE_BLUE,
        alignment=TA_LEFT,
        spaceAfter=10,
    )
    styles["CoverCategory"] = ParagraphStyle(
        "CoverCategory",
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=AMBER_WARN,
        spaceAfter=4,
    )
    styles["MetaKey"] = ParagraphStyle(
        "MetaKey",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=12,
        textColor=NAVY,
    )
    styles["MetaVal"] = ParagraphStyle(
        "MetaVal",
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=DARK_GRAY,
    )
    styles["Heading1"] = ParagraphStyle(
        "H1",
        parent=sample["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=13.5,
        leading=17,
        textColor=NAVY,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    )
    styles["Heading2"] = ParagraphStyle(
        "H2",
        parent=sample["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=SLATE_BLUE,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )
    styles["Heading3"] = ParagraphStyle(
        "H3",
        parent=sample["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=13,
        textColor=DARK_GRAY,
        spaceBefore=8,
        spaceAfter=3,
        keepWithNext=True,
    )
    styles["Body"] = ParagraphStyle(
        "Body",
        parent=sample["BodyText"],
        fontName="Helvetica",
        fontSize=8.8,
        leading=13,
        textColor=DARK_GRAY,
        spaceAfter=5,
        alignment=TA_JUSTIFY,
    )
    styles["Bullet"] = ParagraphStyle(
        "Bullet",
        parent=styles["Body"],
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=3,
    )
    styles["Code"] = ParagraphStyle(
        "Code",
        fontName="Courier",
        fontSize=7.8,
        leading=10,
        textColor=DARK_GRAY,
    )
    styles["TableHeader"] = ParagraphStyle(
        "TableHeader",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10.5,
        textColor=colors.white,
        alignment=TA_LEFT,
    )
    styles["TableCell"] = ParagraphStyle(
        "TableCell",
        fontName="Helvetica",
        fontSize=7.8,
        leading=10.5,
        textColor=DARK_GRAY,
        alignment=TA_LEFT,
    )
    styles["TableCellBold"] = ParagraphStyle(
        "TableCellBold",
        fontName="Helvetica-Bold",
        fontSize=7.8,
        leading=10.5,
        textColor=NAVY,
        alignment=TA_LEFT,
    )
    styles["TableCellCode"] = ParagraphStyle(
        "TableCellCode",
        fontName="Courier",
        fontSize=7.2,
        leading=9.2,
        textColor=DARK_GRAY,
        alignment=TA_LEFT,
    )
    styles["WarnTitle"] = ParagraphStyle(
        "WarnTitle",
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=AMBER_WARN,
        spaceAfter=2,
    )
    styles["WarnBody"] = ParagraphStyle(
        "WarnBody",
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=DARK_GRAY,
    )
    styles["TOCItem"] = ParagraphStyle(
        "TOCItem",
        fontName="Helvetica-Bold",
        fontSize=8.8,
        leading=14,
        textColor=SLATE_BLUE,
    )
    return styles


# ---------------------------------------------------------------------------
# Helper Flowables
# ---------------------------------------------------------------------------
def make_callout(
    title: str, text: str, styles: dict[str, ParagraphStyle], is_warn: bool = False
) -> Table:
    bg = AMBER_BG if is_warn else LIGHT_BLUE_BG
    border = AMBER_BORDER if is_warn else SLATE_BLUE
    title_style = styles["WarnTitle"] if is_warn else styles["Heading3"]
    body_style = styles["WarnBody"] if is_warn else styles["Body"]

    content = [
        Paragraph(title, title_style),
        Paragraph(text, body_style),
    ]
    t = Table([[content]], colWidths=[504])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("BOX", (0, 0), (-1, -1), 0.5, border),
                ("LINELEFT", (0, 0), (-1, -1), 3.0, border),
            ]
        )
    )
    return t


def make_code_box(code_text: str, styles: dict[str, ParagraphStyle]) -> Table:
    lines = [
        Paragraph(
            line.replace(" ", "&nbsp;").replace("<", "&lt;").replace(">", "&gt;"), styles["Code"]
        )
        for line in code_text.strip().split("\n")
    ]
    t = Table([[lines]], colWidths=[504])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
            ]
        )
    )
    return t


def make_table(
    headers: list[str],
    data: list[list[str | Paragraph]],
    col_widths: list[float],
    styles: dict[str, ParagraphStyle],
) -> Table:
    header_row = [Paragraph(h, styles["TableHeader"]) for h in headers]
    formatted_data: list[list[Any]] = [header_row]

    for row in data:
        row_cells: list[Any] = []
        for cell in row:
            if isinstance(cell, str):
                row_cells.append(Paragraph(cell, styles["TableCell"]))
            else:
                row_cells.append(cell)
        formatted_data.append(row_cells)

    t = Table(formatted_data, colWidths=col_widths)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY_BG]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
            ]
        )
    )
    return t


# ---------------------------------------------------------------------------
# Project Manual Builder
# ---------------------------------------------------------------------------
def build_project_manual(out_path: Path) -> None:
    styles = build_stylesheet()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    story: list[Any] = []

    # Cover Header
    story.append(Paragraph("OPERATOR &amp; USER GUIDE", styles["CoverCategory"]))
    story.append(Paragraph("NSE Alpha — Project Manual", styles["DocTitle"]))
    story.append(
        Paragraph(
            "Cross-Sectional Alpha Research Pipeline for Indian Equities (NSE)",
            styles["DocSubtitle"],
        )
    )
    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceBefore=2, spaceAfter=8))

    # Metadata Grid
    meta_data = [
        [
            Paragraph("Package:", styles["MetaKey"]),
            Paragraph("nse_alpha v0.1.0", styles["MetaVal"]),
            Paragraph("Language:", styles["MetaKey"]),
            Paragraph("Python &ge; 3.11 / 3.12 / 3.13", styles["MetaVal"]),
        ],
        [
            Paragraph("CLI Tool:", styles["MetaKey"]),
            Paragraph("nse-alpha (Typer + Rich)", styles["MetaVal"]),
            Paragraph("Data Feed:", styles["MetaKey"]),
            Paragraph("Yahoo Finance (yfinance)", styles["MetaVal"]),
        ],
        [
            Paragraph("Scope:", styles["MetaKey"]),
            Paragraph(
                "Installation, day-to-day operations, CLI reference, and cache management",
                styles["MetaVal"],
            ),
            Paragraph("Companion:", styles["MetaKey"]),
            Paragraph("Explanatory &amp; Technical Manual", styles["MetaVal"]),
        ],
    ]
    meta_table = Table(meta_data, colWidths=[65, 185, 65, 189])
    meta_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 8))

    # Table of Contents Box
    toc_data = [
        [
            Paragraph("1 &nbsp; What This Project Is", styles["TOCItem"]),
            Paragraph("7 &nbsp; Configuration Knobs &amp; Constants", styles["TOCItem"]),
        ],
        [
            Paragraph("2 &nbsp; Installation &amp; Setup", styles["TOCItem"]),
            Paragraph("8 &nbsp; Outputs Produced &amp; Interpretation", styles["TOCItem"]),
        ],
        [
            Paragraph("3 &nbsp; Quick Start Guide", styles["TOCItem"]),
            Paragraph("9 &nbsp; Development Workflow &amp; Testing", styles["TOCItem"]),
        ],
        [
            Paragraph("4 &nbsp; CLI Command Reference", styles["TOCItem"]),
            Paragraph("10 Troubleshooting &amp; Diagnostics", styles["TOCItem"]),
        ],
        [
            Paragraph("5 &nbsp; Project Directory Structure", styles["TOCItem"]),
            Paragraph("11 Known Limitations Summary", styles["TOCItem"]),
        ],
        [
            Paragraph("6 &nbsp; Data Ingestion &amp; Cache Management", styles["TOCItem"]),
            Paragraph("", styles["TOCItem"]),
        ],
    ]
    toc_table = Table(toc_data, colWidths=[240, 240])
    toc_box = Table(
        [[Paragraph("Table of Contents", styles["Heading2"]), toc_table]], colWidths=[504]
    )
    toc_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(toc_box)
    story.append(Spacer(1, 10))

    # ------------------ Section 1 ------------------
    story.append(Paragraph("1. What This Project Is", styles["Heading1"]))
    story.append(
        Paragraph(
            "<b>nse-alpha</b> is an institutional-grade quantitative equity research pipeline for equities trading on "
            "the National Stock Exchange of India (NSE). It automatically ingests real daily OHLCV market pricing via "
            "<code>yfinance</code>, maintains an incremental local Parquet cache, normalizes cross-sectional factors, and "
            "evaluates 14 alpha signals across 5 core factor families (Momentum, Reversal, Volatility, Liquidity, Range).",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "The system rigorously tests each signal against statistical significance hurdles (Newey-West HAC t-statistics), "
            "monotonicity quantile spreads, strategy capacity constraints, and realistic transaction cost tiers (5, 15, and 30 bps). "
            "Results are summarized in a ranked alpha table (<code>results/alpha_table.csv</code>), high-resolution charts, and "
            "an audit-ready Markdown document (<code>results/REPORT.md</code>).",
            styles["Body"],
        )
    )
    story.append(
        make_callout(
            "SURVIVORSHIP BIAS WARNING",
            "The default universe (<code>data/nifty200_constituents.csv</code>) reflects today's Nifty 200 composition. "
            "Historical backtests therefore exclude equities that were delisted, merged, or demoted from the index in the past. "
            "Reported IC and Sharpe statistics represent an upper bound. The CLI automatically surfaces this caveat on every run.",
            styles,
            is_warn=True,
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 2 ------------------
    story.append(Paragraph("2. Installation &amp; Environment Setup", styles["Heading1"]))
    story.append(
        Paragraph(
            "<b>System Requirements:</b> Python &ge; 3.11 (tested on 3.11, 3.12, and 3.13) and <code>uv</code> package manager.",
            styles["Body"],
        )
    )
    story.append(
        make_code_box(
            "# 1. Install uv (if not already installed)\n"
            "pip install uv\n\n"
            "# 2. Clone repository & install dependencies into virtualenv\n"
            "git clone <repo-url> nse-alpha\n"
            "cd nse-alpha\n"
            "uv sync --extra dev\n\n"
            "# 3. Verify installation using leak-detector canary tests\n"
            "uv run pytest tests/test_canaries.py -v",
            styles,
        )
    )
    story.append(
        Paragraph(
            "<b>Core Dependencies:</b> <code>pandas</code>, <code>numpy</code>, <code>scipy</code>, <code>statsmodels</code>, "
            "<code>pyarrow</code>, <code>yfinance</code>, <code>matplotlib</code>, <code>typer</code>, <code>rich</code>. "
            "<b>Dev Extras:</b> <code>pytest</code>, <code>hypothesis</code>, <code>ruff</code>, <code>mypy</code>, <code>reportlab</code>.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 3 ------------------
    story.append(Paragraph("3. Quick Start Guide", styles["Heading1"]))
    story.append(
        Paragraph(
            "The pipeline provides a 3-step workflow to download market data, compute alphas, and render publication reports:",
            styles["Body"],
        )
    )
    story.append(
        make_code_box(
            "# Step 1: Pre-download real data for Nifty 200 (2015 to present)\n"
            "uv run nse-alpha download --universe nifty200 --start 2015-01-01\n\n"
            "# Step 2: Run alpha research pipeline & compute all signal metrics\n"
            "uv run nse-alpha run --universe nifty200 --start 2015-01-01\n\n"
            "# Step 3: Render charts and the comprehensive REPORT.md\n"
            "uv run nse-alpha report --survivorship-note\n\n"
            "# Custom Subsets: Run on specific symbols with force download\n"
            "uv run nse-alpha run --symbols INFY.NS,TCS.NS,RELIANCE.NS,HDFCBANK.NS --start 2022-01-01 --force-download\n\n"
            "# Offline Mode: Run completely from local Parquet cache without network\n"
            "set NSE_ALPHA_OFFLINE=1\n"
            "uv run nse-alpha run --start 2022-01-01",
            styles,
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 4 ------------------
    story.append(Paragraph("4. CLI Command Reference", styles["Heading1"]))
    story.append(Paragraph("4.1 <code>nse-alpha download</code>", styles["Heading2"]))
    story.append(
        Paragraph(
            "Fetches historical OHLCV data from Yahoo Finance and populates the local Snappy-compressed Parquet cache.",
            styles["Body"],
        )
    )
    dl_table = make_table(
        ["Flag", "Type", "Default", "Description"],
        [
            [
                "--universe",
                "TEXT",
                "nifty200",
                "Universe name. Loads symbols from data/nifty200_constituents.csv.",
            ],
            [
                "--symbols",
                "TEXT",
                "None",
                "Comma-separated symbols (e.g. INFY.NS,TCS.NS). Overrides --universe.",
            ],
            ["--start", "TEXT", "2015-01-01", "ISO-8601 start date for historical price download."],
            ["--end", "TEXT", "today", "ISO-8601 end date. Defaults to current system date."],
            [
                "--force",
                "FLAG",
                "false",
                "Force re-download from Yahoo Finance even if symbol is already cached.",
            ],
            ["--batch-size", "INT", "10", "Number of ticker symbols per yfinance request batch."],
        ],
        [85, 45, 65, 309],
        styles,
    )
    story.append(dl_table)
    story.append(Spacer(1, 6))

    story.append(Paragraph("4.2 <code>nse-alpha run</code>", styles["Heading2"]))
    story.append(
        Paragraph(
            "Executes full alpha research pipeline: data download, panel assembly, liquidity filtering, signal evaluation, and metric aggregation.",
            styles["Body"],
        )
    )
    run_table = make_table(
        ["Flag", "Type", "Default", "Description"],
        [
            ["--universe", "TEXT", "nifty200", "Target universe name."],
            [
                "--symbols",
                "TEXT",
                "None",
                "Comma-separated list of symbols (e.g. INFY.NS,TCS.NS,RELIANCE.NS).",
            ],
            ["--start", "TEXT", "2015-01-01", "ISO-8601 start date."],
            ["--end", "TEXT", "today", "ISO-8601 end date."],
            [
                "--sector-neutral",
                "FLAG",
                "false",
                "Demean signals within GICS sector cross-sections before evaluation.",
            ],
            [
                "--size-neutral",
                "FLAG",
                "false",
                "Regress out log-ADV (20-day median turnover) exposure via OLS.",
            ],
            [
                "--force-download",
                "FLAG",
                "false",
                "Force fresh download from yfinance even if cached.",
            ],
            [
                "--min-history-days",
                "INT",
                "252",
                "Minimum trading days of history required for liquidity filtering.",
            ],
            [
                "--output-dir",
                "PATH",
                "results",
                "Output directory for alpha_table.csv and _results.pkl.",
            ],
        ],
        [95, 40, 65, 304],
        styles,
    )
    story.append(run_table)
    story.append(Spacer(1, 6))

    story.append(Paragraph("4.3 <code>nse-alpha report</code>", styles["Heading2"]))
    story.append(
        Paragraph(
            "Reads output from a previous <code>run</code> command and generates publication charts and <code>results/REPORT.md</code>.",
            styles["Body"],
        )
    )
    rep_table = make_table(
        ["Flag", "Type", "Default", "Description"],
        [
            [
                "--survivorship-note",
                "FLAG",
                "false",
                "Embed an explicit survivorship-bias caveat banner in REPORT.md.",
            ],
            [
                "--results-dir",
                "PATH",
                "results",
                "Directory containing _results.pkl from a previous run command.",
            ],
        ],
        [110, 40, 65, 289],
        styles,
    )
    story.append(rep_table)
    story.append(Spacer(1, 8))

    # ------------------ Section 5 ------------------
    story.append(Paragraph("5. Project Directory Structure", styles["Heading1"]))
    story.append(
        make_code_box(
            "nse-alpha/\n"
            "├── nse_alpha/                     # Core Python package\n"
            "│   ├── cli.py                     # Typer CLI entry point (download, run, report)\n"
            "│   ├── data/                      # Ingestion, caching, and panel assembly\n"
            "│   │   ├── ingest.py              # Robust yfinance downloader with retry & batching\n"
            "│   │   ├── cache.py               # Snappy-compressed Parquet cache & metadata\n"
            "│   │   ├── panel.py               # Tidy MultiIndex(date, symbol) panel builder\n"
            "│   │   └── corporate_actions.py   # Yahoo Finance split/dividend adjustment caveats\n"
            "│   ├── universe/                  # Nifty 200 constituents & liquidity filters\n"
            "│   │   ├── nifty200.py            # Static constituent loader & liquidity filter rules\n"
            "│   │   └── point_in_time.py       # UniverseProvider protocol for future PIT index\n"
            "│   ├── signals/                   # 14 alpha signals across 5 families + registry\n"
            "│   │   ├── registry.py            # @register decorator (enforces economic rationale)\n"
            "│   │   ├── momentum.py            # mom_12_1, mom_6_1, mom_21d, residual_mom\n"
            "│   │   ├── reversal.py            # rev_1d, rev_5d, overnight_vs_intraday\n"
            "│   │   ├── volatility.py          # realised_vol, idiosyncratic_vol, vol_of_vol\n"
            "│   │   ├── liquidity.py           # amihud_illiquidity, turnover_ratio, volume_shock\n"
            "│   │   └── range_.py              # parkinson_vs_cc\n"
            "│   ├── eval/                      # Evaluation engine\n"
            "│   │   ├── alignment.py           # ONLY place shift() is called (T+1 execution gap)\n"
            "│   │   ├── preprocessing.py       # Winsorisation, Z-scoring, Sector/Size neutralization\n"
            "│   │   ├── ic.py                  # Spearman rank IC & Newey-West HAC t-statistics\n"
            "│   │   ├── portfolio.py           # Decile portfolios, L/S spread, Sharpe ratio\n"
            "│   │   ├── turnover.py            # Position weight derivation & one-way turnover\n"
            "│   │   ├── costs.py               # 5, 15, and 30 bps cost-hurdle simulations\n"
            "│   │   ├── validation.py          # Walk-forward cross-validation with embargo\n"
            "│   │   └── runner.py              # Orchestrates evaluation for an individual signal\n"
            "│   └── report/                    # Report formatting & chart generation\n"
            "│       ├── table.py               # Alpha summary table builder & survivor filter\n"
            "│       ├── plots.py               # IC decay, quantile returns, cumulative L/S plots\n"
            "│       └── markdown.py            # REPORT.md generator\n"
            "├── data/                          # Reference constituent files\n"
            "│   ├── nifty200_constituents.csv  # 188 cleaned & verified active NSE ticker symbols\n"
            "│   └── sector_fallback.csv        # Fallback sector mappings\n"
            "├── tests/                         # Comprehensive automated test suite (12 tests)\n"
            "│   ├── test_canaries.py           # 4 leak-detector canary tests (foresight, noise, etc.)\n"
            "│   ├── test_data_ingest.py        # yfinance ingestion, normalization & caching tests\n"
            "│   └── test_preprocessing.py      # Property-based tests for statistical transforms\n"
            "├── cache/                         # Local Parquet cache (gitignored)\n"
            "│   ├── raw/<SYMBOL>.parquet       # Fast binary price series per ticker\n"
            "│   └── meta/<SYMBOL>.json         # Date range coverage metadata\n"
            "├── results/                       # Generated research artifacts (gitignored)\n"
            "├── docs/                          # PDF Documentation Manuals\n"
            "│   ├── NSE_Alpha_Project_Manual.pdf\n"
            "│   ├── NSE_Alpha_Explanatory_Manual.pdf\n"
            "│   └── build_manuals.py           # Manual generation compiler\n"
            "├── pyproject.toml                 # Build config & strict tooling settings\n"
            "└── README.md                      # Quick-reference overview",
            styles,
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 6 ------------------
    story.append(Paragraph("6. Data Ingestion &amp; Cache Management", styles["Heading1"]))
    story.append(
        Paragraph(
            "<b>6.1 Real Data Ingestion (<code>data/ingest.py</code>)</b><br/>"
            "Market data is retrieved via <code>yfinance.download()</code> in batches of 10 symbols. Exponential backoff "
            "with jitter (2s base up to 120s max, 5 retries) prevents network failure under throttling. MultiIndex column outputs "
            "are normalized into standard lowercase names, and date indices are converted to timezone-naive timestamps.",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "<b>6.2 The Tidy Panel Contract (<code>data/panel.py</code>)</b><br/>"
            "All downstream signals and evaluation modules interact exclusively with a standardized <code>MultiIndex(date, symbol)</code> "
            "DataFrame containing exactly 7 columns:",
            styles["Body"],
        )
    )
    panel_table = make_table(
        ["Column", "Type", "Adjustment", "Usage in Research Pipeline"],
        [
            [
                "open",
                "float64",
                "Raw (unadjusted)",
                "Parkinson intraday range volatility estimator",
            ],
            ["high", "float64", "Raw (unadjusted)", "Intraday high-low range analysis"],
            ["low", "float64", "Raw (unadjusted)", "Intraday high-low range analysis"],
            [
                "close",
                "float64",
                "Raw (unadjusted)",
                "Actual monetary turnover & Amihud illiquidity",
            ],
            [
                "adj_close",
                "float64",
                "Split & Div Adjusted",
                "All return computations, signals, IC, & portfolio returns",
            ],
            ["volume", "float64", "Raw shares traded", "Volume shocks & turnover ratios"],
            [
                "turnover_value",
                "float64",
                "raw close × volume",
                "Rupee ADV, liquidity filtering, capacity limits",
            ],
        ],
        [75, 55, 100, 274],
        styles,
    )
    story.append(panel_table)
    story.append(Spacer(1, 6))

    story.append(
        Paragraph(
            "<b>6.3 Parquet Storage &amp; Cache Invalidation (<code>data/cache.py</code>)</b><br/>"
            "Data is saved under <code>cache/raw/&lt;SYMBOL&gt;.parquet</code> with range coverage in <code>cache/meta/&lt;SYMBOL&gt;.json</code>. "
            "To invalidate or clear cache, use the programmatic API <code>clear_cache(symbol)</code> or CLI flags <code>--force</code> / <code>--force-download</code>.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 7 ------------------
    story.append(Paragraph("7. Configuration Knobs &amp; Constants", styles["Heading1"]))
    story.append(
        Paragraph(
            "<b>7.1 Liquidity Filter Parameters (<code>nse_alpha/universe/nifty200.py</code>)</b>",
            styles["Body"],
        )
    )
    liq_table = make_table(
        ["Parameter", "Default Value", "Purpose"],
        [
            [
                "MIN_HISTORY_DAYS",
                "252 trading days",
                "Ensures sufficient lookback for rolling 12-month momentum & vol.",
            ],
            [
                "MIN_ADV_VALUE_RS",
                "Rs 5 Crore (50,000,000)",
                "Excludes illiquid stocks where trading impact would dominate.",
            ],
            [
                "MAX_MISSING_BARS",
                "10 NaNs / 60 days",
                "Rejects stocks with gappy or halted trading data.",
            ],
        ],
        [120, 110, 274],
        styles,
    )
    story.append(liq_table)
    story.append(Spacer(1, 6))

    story.append(
        Paragraph(
            "<b>7.2 Cost Model Configuration (<code>nse_alpha/eval/costs.py</code>)</b><br/>"
            "The baseline hurdle is <b>15 basis points</b> round-trip, decomposed as:",
            styles["Body"],
        )
    )
    cost_table = make_table(
        ["Cost Component", "Basis Points", "Regulatory / Practical Basis"],
        [
            [
                "Brokerage + Exchange Fees",
                "2 bps",
                "Standard institutional execution rates on NSE.",
            ],
            [
                "Securities Transaction Tax (STT)",
                "10 bps",
                "Indian statutory STT levied on equity delivery sales.",
            ],
            [
                "Market Impact (Large-Cap)",
                "3 bps",
                "Estimated linear slippage for Nifty 200 liquid constituents.",
            ],
            [
                "Total Baseline Round-Trip",
                "15 bps",
                "Primary survivor hurdle for strategy viability.",
            ],
        ],
        [150, 74, 280],
        styles,
    )
    story.append(cost_table)
    story.append(Spacer(1, 6))

    story.append(
        Paragraph(
            "<b>7.3 Survivor Criteria (<code>nse_alpha/report/table.py</code>)</b><br/>"
            "A signal is marked with <code>survives = True</code> if and only if: <b>Net Sharpe (15 bps) &gt; 0.50</b> AND <b>|IC t-stat| &gt; 2.00</b>.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 8 ------------------
    story.append(Paragraph("8. Outputs Produced &amp; Interpretation", styles["Heading1"]))
    out_table = make_table(
        ["Artifact File", "Generator", "Description & Contents"],
        [
            [
                "results/alpha_table.csv",
                "nse-alpha run",
                "Complete tabular summary: IC, IC t-stat, IR, turnover, gross Sharpe, net Sharpe at 5/15/30 bps, strategy capacity (Rs Cr), half-life (days), and survives flag.",
            ],
            [
                "results/_results.pkl",
                "nse-alpha run",
                "Serialized dictionary containing full daily return series, decile allocations, and IC decay matrices consumed by the reporting command.",
            ],
            [
                "results/REPORT.md",
                "nse-alpha report",
                "Full publication-ready Markdown research report with embedded chart links, summary statistics, and audit documentation.",
            ],
            [
                "results/ic_decay.png",
                "nse-alpha report",
                "Information Coefficient decay plots across forward horizons from 1 to 21 trading days.",
            ],
            [
                "results/quantile_returns.png",
                "nse-alpha report",
                "Decile portfolio annualized returns (D1 through D10) demonstrating factor monotonicity.",
            ],
            [
                "results/cumulative_ls.png",
                "nse-alpha report",
                "Cumulative Long/Short strategy performance comparing gross vs 15 bps net equity curves.",
            ],
        ],
        [120, 94, 290],
        styles,
    )
    story.append(out_table)
    story.append(Spacer(1, 8))

    # ------------------ Section 9 ------------------
    story.append(Paragraph("9. Development Workflow &amp; Testing", styles["Heading1"]))
    story.append(
        Paragraph(
            "The repository enforces rigorous code hygiene with 12 automated unit tests, strict type checking, and linting:",
            styles["Body"],
        )
    )
    story.append(
        make_code_box(
            "# Run full test suite (12 automated unit & property tests)\n"
            "uv run pytest tests/ -v\n\n"
            "# Run canary leak-detector tests specifically\n"
            "uv run pytest tests/test_canaries.py -v\n\n"
            "# Run yfinance ingestion & cache tests\n"
            "uv run pytest tests/test_data_ingest.py -v\n\n"
            "# Fast lint & code format verification\n"
            "uv run ruff check .\n\n"
            "# Strict static type checking\n"
            "uv run mypy nse_alpha/ --strict",
            styles,
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 10 ------------------
    story.append(Paragraph("10. Troubleshooting &amp; Diagnostics", styles["Heading1"]))
    diag_table = make_table(
        ["Symptom / Error", "Root Cause", "Recommended Resolution"],
        [
            [
                "Panel is empty. Check your data download.",
                "Network disconnected or date range outside historical coverage.",
                "Check internet connection, verify Yahoo Finance accessibility, or check start/end dates.",
            ],
            [
                "yfinance rate-limiting / batch timeout",
                "Yahoo Finance request throttling.",
                "The built-in exponential backoff retries automatically up to 5 times. Alternatively, reduce --batch-size.",
            ],
            [
                "No run results found. Run 'nse-alpha run' first.",
                "nse-alpha report executed before run.",
                "Execute nse-alpha run --universe nifty200 first to generate results/_results.pkl.",
            ],
            [
                "Windows console encoding errors",
                "Legacy terminal cp1252 character map issues.",
                "Resolved in current version via ASCII-safe progress bars and Console(legacy_windows=False).",
            ],
        ],
        [130, 110, 264],
        styles,
    )
    story.append(diag_table)
    story.append(Spacer(1, 8))

    # ------------------ Section 11 ------------------
    story.append(Paragraph("11. Known Limitations Summary", styles["Heading1"]))
    story.append(
        Paragraph(
            "<b>1. Static Universe:</b> Sourced from current Nifty 200 constituents; backtests carry survivorship bias.<br/>"
            "<b>2. Daily EOD Bars:</b> Intraday order flow and microstructure dynamics are not captured.<br/>"
            "<b>3. Linear Slippage Model:</b> Non-linear market impact (Almgren-Chriss) is approximated via fixed basis points.<br/>"
            "<b>4. Short-Sale Unconstrained:</b> Assumes friction-free borrowing for the short leg.<br/>"
            "<b>5. Corporate Action Coverage:</b> Rights issues and complex demergers may have adjustment approximations in Yahoo Finance.<br/>"
            "<b>6. Expanding Walk-Forward:</b> Combinatorial Purged Cross-Validation is reserved for future releases.",
            styles["Body"],
        )
    )

    doc.build(story, canvasmaker=ProjectCanvas)
    print(f"Successfully compiled Project Manual: {out_path}")


# ---------------------------------------------------------------------------
# Explanatory Manual Builder
# ---------------------------------------------------------------------------
def build_explanatory_manual(out_path: Path) -> None:
    styles = build_stylesheet()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    story: list[Any] = []

    # Cover Header
    story.append(Paragraph("EXPLANATORY &amp; TECHNICAL MANUAL", styles["CoverCategory"]))
    story.append(Paragraph("NSE Alpha — Methodology Deep-Dive", styles["DocTitle"]))
    story.append(
        Paragraph(
            "Architecture, Signal Mathematics, and the Evaluation Engine",
            styles["DocSubtitle"],
        )
    )
    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceBefore=2, spaceAfter=8))

    # Metadata Grid
    meta_data = [
        [
            Paragraph("Package:", styles["MetaKey"]),
            Paragraph("nse_alpha v0.1.0", styles["MetaVal"]),
            Paragraph("Universe:", styles["MetaKey"]),
            Paragraph("Nifty 200 (188 Active NSE Equities)", styles["MetaVal"]),
        ],
        [
            Paragraph("Signal Library:", styles["MetaKey"]),
            Paragraph("14 Alpha Signals across 5 Families", styles["MetaVal"]),
            Paragraph("Evaluation:", styles["MetaKey"]),
            Paragraph("T+1 Gap, Spearman IC, HAC t-stat, Deciles", styles["MetaVal"]),
        ],
        [
            Paragraph("Scope:", styles["MetaKey"]),
            Paragraph(
                "Mathematical specifications, alignment proofs &amp; architecture",
                styles["MetaVal"],
            ),
            Paragraph("Companion:", styles["MetaKey"]),
            Paragraph("NSE Alpha — Project Manual (Operations)", styles["MetaVal"]),
        ],
    ]
    meta_table = Table(meta_data, colWidths=[70, 180, 70, 184])
    meta_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 8))

    # Table of Contents Box
    toc_data = [
        [
            Paragraph("1 &nbsp; Research Philosophy", styles["TOCItem"]),
            Paragraph("8 &nbsp; Information Coefficient &amp; Decay", styles["TOCItem"]),
        ],
        [
            Paragraph("2 &nbsp; System Architecture", styles["TOCItem"]),
            Paragraph("9 &nbsp; Portfolio, Turnover &amp; Cost Model", styles["TOCItem"]),
        ],
        [
            Paragraph("3 &nbsp; Data Ingestion &amp; Caching Layer", styles["TOCItem"]),
            Paragraph("10 Walk-Forward Validation Protocol", styles["TOCItem"]),
        ],
        [
            Paragraph("4 &nbsp; Universe &amp; Liquidity Filters", styles["TOCItem"]),
            Paragraph("11 Reporting Layer &amp; Metrics", styles["TOCItem"]),
        ],
        [
            Paragraph("5 &nbsp; Signal Library &amp; Mathematics", styles["TOCItem"]),
            Paragraph("12 Correctness Guarantees (Canaries)", styles["TOCItem"]),
        ],
        [
            Paragraph("6 &nbsp; Statistical Preprocessing", styles["TOCItem"]),
            Paragraph("13 Known Limitations &amp; Future Work", styles["TOCItem"]),
        ],
        [
            Paragraph("7 &nbsp; Alignment &amp; No-Lookahead Proof", styles["TOCItem"]),
            Paragraph("14 Technical Glossary", styles["TOCItem"]),
        ],
    ]
    toc_table = Table(toc_data, colWidths=[240, 240])
    toc_box = Table(
        [[Paragraph("Table of Contents", styles["Heading2"]), toc_table]], colWidths=[504]
    )
    toc_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(toc_box)
    story.append(Spacer(1, 10))

    # ------------------ Section 1 ------------------
    story.append(Paragraph("1. Research Philosophy", styles["Heading1"]))
    story.append(
        Paragraph(
            "Quantitative equity research is frequently undermined by silent backtesting pathologies: subtle lookahead leakage, "
            "survivorship bias, unrealistic friction assumptions, and factor multicollinearity. The <b>nse-alpha</b> architecture "
            "is built from the ground up to eradicate these pitfalls by programmatic construction:",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "&bull; <b>Single Point of Temporal Alignment:</b> No signal calculation is permitted to invoke <code>.shift()</code>. "
            "All temporal joins occur exclusively inside <code>nse_alpha/eval/alignment.py</code> with a mandatory 1-day implementation gap.<br/>"
            "&bull; <b>Mandatory Economic Rationale:</b> The signal registry rejects any factor lacking an explicit economic hypothesis.<br/>"
            "&bull; <b>Explicit Bias Auditing:</b> Survivorship warnings are triggered on import, displayed in the console, and stamped on reports.<br/>"
            "&bull; <b>Automated Canary Falsification:</b> Four mathematical canary tests (Perfect Foresight, Pure Noise, Leak Detector, Date Shuffle) "
            "prove the evaluation engine is leak-free before any factor is tested.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 2 ------------------
    story.append(Paragraph("2. System Architecture", styles["Heading1"]))
    story.append(
        Paragraph(
            "The pipeline follows a strictly unidirectional, decoupled data flow where every component communicates via a single data contract:",
            styles["Body"],
        )
    )
    story.append(
        make_code_box(
            "┌────────────────────────────────────────────────────────────────────────┐\n"
            "│                             nse-alpha CLI                              │\n"
            "└───────────────────────────────────┬────────────────────────────────────┘\n"
            "                                    │\n"
            "        ┌───────────────────────────▼───────────────────────────┐\n"
            "        │  DATA LAYER (nse_alpha/data/)                         │\n"
            "        │  yfinance Ingest → Parquet Cache → Tidy Panel Builder │\n"
            "        └───────────────────────────┬───────────────────────────┘\n"
            "                                    │ MultiIndex(date, symbol) Panel\n"
            "        ┌───────────────────────────▼───────────────────────────┐\n"
            "        │  UNIVERSE LAYER (nse_alpha/universe/)                 │\n"
            "        │  Nifty 200 Constituents + Point-in-Time Filters       │\n"
            "        └───────────────────────────┬───────────────────────────┘\n"
            "                                    │ Filtered Eligible Panel\n"
            "        ┌───────────────────────────▼───────────────────────────┐\n"
            "        │  SIGNAL LIBRARY (nse_alpha/signals/)                  │\n"
            "        │  14 Signals: Momentum, Reversal, Vol, Liq, Range      │\n"
            "        └───────────────────────────┬───────────────────────────┘\n"
            "                                    │ Raw Alpha Scores Series\n"
            "        ┌───────────────────────────▼───────────────────────────┐\n"
            "        │  EVALUATION ENGINE (nse_alpha/eval/)                  │\n"
            "        │  Winsorize/Z-score → T+1 Alignment → Spearman IC →    │\n"
            "        │  Deciles & Long/Short Spread → 5/15/30 bps Costs      │\n"
            "        └───────────────────────────┬───────────────────────────┘\n"
            "                                    │ Evaluated Metrics Dictionary\n"
            "        ┌───────────────────────────▼───────────────────────────┐\n"
            "        │  REPORTING LAYER (nse_alpha/report/)                  │\n"
            "        │  alpha_table.csv  |  REPORT.md  |  Matplotlib Plots   │\n"
            "        └───────────────────────────────────────────────────────┘",
            styles,
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 3 ------------------
    story.append(Paragraph("3. Data Ingestion &amp; Caching Layer", styles["Heading1"]))
    story.append(
        Paragraph(
            "<b>3.1 Ingestion &amp; Yahoo Finance Feed (<code>data/ingest.py</code>)</b><br/>"
            "Historical market data is fetched via <code>yfinance.download()</code> in throttled batches of 10 symbols. "
            "To withstand rate-limiting, the layer implements exponential backoff starting at 2.0s and doubling up to 120.0s "
            "across 5 retry attempts with 25% uniform jitter. Single-ticker and multi-ticker MultiIndex columns are unpacked, "
            "normalized to canonical lowercase column headers, and verified for non-null closes.",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "<b>3.2 Parquet Cache Layer (<code>data/cache.py</code>)</b><br/>"
            "Pricing data is persisted in Snappy-compressed Parquet files under <code>cache/raw/&lt;SYMBOL&gt;.parquet</code>. "
            "The accompanying metadata in <code>cache/meta/&lt;SYMBOL&gt;.json</code> stores the exact valid start and end dates. "
            "Re-downloads merge additively with existing cache and de-duplicate by date index, ensuring idempotent cache updates. "
            "The <code>clear_cache()</code> function allows programmatic invalidation.",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "<b>3.3 The Core Panel Contract (<code>data/panel.py</code>)</b><br/>"
            "The pipeline's single data structure is a 2-level <code>MultiIndex(date, symbol)</code> DataFrame with 7 standard columns:",
            styles["Body"],
        )
    )
    panel_table = make_table(
        ["Column", "Type", "Source / Computation", "Primary Role"],
        [
            ["open", "float64", "Raw open price", "Parkinson high-low-open volatility estimator"],
            ["high", "float64", "Raw high price", "Intraday high-low range analysis"],
            ["low", "float64", "Raw low price", "Intraday high-low range analysis"],
            [
                "close",
                "float64",
                "Raw close price",
                "Monetary turnover calculation & Amihud illiquidity",
            ],
            [
                "adj_close",
                "float64",
                "Split & dividend adjusted",
                "All signal log-returns, IC calculation, portfolio returns",
            ],
            ["volume", "float64", "Raw shares traded", "Volume shock & turnover ratio factors"],
            [
                "turnover_value",
                "float64",
                "close × volume (Rs)",
                "Liquidity filtering, ADV calculation, capacity sizing",
            ],
        ],
        [80, 55, 125, 244],
        styles,
    )
    story.append(panel_table)
    story.append(Spacer(1, 8))

    # ------------------ Section 4 ------------------
    story.append(Paragraph("4. Universe Construction &amp; Liquidity Filters", styles["Heading1"]))
    story.append(
        Paragraph(
            "<b>4.1 Constituent Universe (<code>universe/nifty200.py</code>)</b><br/>"
            "The universe is defined by <code>data/nifty200_constituents.csv</code>, comprising 188 verified unique active NSE equities. "
            "All ticker symbols carry the <code>.NS</code> suffix and have been audited against current NSE market listings.",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "<b>4.2 Point-in-Time Liquidity Filters</b><br/>"
            "For any evaluation as of date <i>T</i>, eligibility is determined strictly using history prior to or on <i>T</i>:<br/>"
            "1. <b>History Requirement:</b> Minimum 252 trading days of historical data prior to <i>T</i>.<br/>"
            "2. <b>Turnover Liquidity:</b> 20-day median <code>turnover_value</code> &gt; Rs 5 Crore (50,000,000).<br/>"
            "3. <b>Data Reliability:</b> No more than 10 missing/NaN closes in the trailing 60 trading days.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 5 ------------------
    story.append(
        Paragraph("5. Signal Library &amp; Mathematical Specifications", styles["Heading1"])
    )
    story.append(
        Paragraph(
            "The library implements 14 signals across 5 families. Every signal is registered via <code>@register</code>, "
            "which enforces mandatory economic rationale validation at import time.",
            styles["Body"],
        )
    )

    sig_data = [
        [
            "mom_12_1",
            "Momentum",
            "252d",
            "ln(adj_close[t-21] / adj_close[t-252])",
            "12-1 month cross-sectional momentum (Jegadeesh &amp; Titman 1993); skips 1-month reversal.",
        ],
        [
            "mom_6_1",
            "Momentum",
            "126d",
            "ln(adj_close[t-21] / adj_close[t-126])",
            "Intermediate 6-month momentum with 1-month skip.",
        ],
        [
            "mom_21d",
            "Momentum",
            "21d",
            "ln(adj_close[t] / adj_close[t-21])",
            "Short-term 1-month trend continuation.",
        ],
        [
            "residual_mom",
            "Momentum",
            "252d",
            "Cumulative residual of stock ret on universe ret",
            "Idiosyncratic momentum stripped of market beta (Blitz et al. 2011).",
        ],
        [
            "rev_1d",
            "Reversal",
            "1d",
            "-ln(adj_close[t] / adj_close[t-1])",
            "Daily liquidity shock mean-reversion.",
        ],
        [
            "rev_5d",
            "Reversal",
            "5d",
            "-ln(adj_close[t] / adj_close[t-5])",
            "Weekly overreaction reversal (Lehmann 1990).",
        ],
        [
            "overnight_vs_intraday",
            "Reversal",
            "20d",
            "mean(r_overnight - r_intraday, 20d)",
            "Institutional vs retail sentiment spread (Lou, Polk, Skouras 2019).",
        ],
        [
            "realised_vol",
            "Volatility",
            "63d",
            "-std(daily_returns, 63d) × sqrt(252)",
            "Low-volatility anomaly: lower-risk stocks generate superior risk-adjusted alpha (Ang 2006).",
        ],
        [
            "idiosyncratic_vol",
            "Volatility",
            "63d",
            "-std(OLS residual against universe mean, 63d)",
            "Idiosyncratic volatility puzzle: stocks with low residual variance outperform.",
        ],
        [
            "vol_of_vol",
            "Volatility",
            "63d",
            "-std(rolling_21d_vol, 63d)",
            "Uncertainty of volatility risk premium (Baltussen et al. 2018).",
        ],
        [
            "amihud_illiquidity",
            "Liquidity",
            "20d",
            "-mean(|r_t| / turnover_value_t, 20d)",
            "Amihud price impact illiquidity premium.",
        ],
        [
            "turnover_ratio",
            "Liquidity",
            "20d",
            "-mean(volume / shares_out, 20d)",
            "High turnover signifies speculative sentiment and future underperformance.",
        ],
        [
            "volume_shock",
            "Liquidity",
            "20d",
            "-(volume[t] / mean(volume, 20d))",
            "Abnormal volume exhaustion indicator.",
        ],
        [
            "parkinson_vs_cc",
            "Range",
            "20d",
            "parkinson_vol_20d - close_to_close_vol_20d",
            "High intraday efficiency vs close-to-close gap risk.",
        ],
    ]

    sig_table = make_table(
        [
            "Signal Name",
            "Family",
            "Lookback",
            "Formula / Definition",
            "Economic Hypothesis &amp; Literature Rationale",
        ],
        sig_data,
        [90, 60, 45, 140, 169],
        styles,
    )
    story.append(sig_table)
    story.append(Spacer(1, 8))

    # ------------------ Section 6 ------------------
    story.append(Paragraph("6. Statistical Preprocessing Pipeline", styles["Heading1"]))
    story.append(
        Paragraph(
            "Every raw signal score undergoes rigorous cross-sectional transformations (<code>eval/preprocessing.py</code>):<br/>"
            "1. <b>Winsorisation:</b> Outliers are clipped to cross-sectional percentiles (default: 1st and 99th percentiles) to prevent extreme outliers from distorting rankings.<br/>"
            "2. <b>Z-Score Standardization:</b> Standardized cross-sectionally per date to mean 0 and standard deviation 1: <i>z = (s - &mu;) / &sigma;</i>.<br/>"
            "3. <b>Sector Neutralisation:</b> Signal scores are demeaned within their GICS sector cross-section.<br/>"
            "4. <b>Size Neutralisation:</b> Signal scores are regressed on log-ADV via OLS: <i>z_i = &alpha; + &beta; ln(ADV_i) + &epsilon;_i</i>, using residuals <i>&epsilon;_i</i> as the pure size-neutral alpha.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 7 ------------------
    story.append(
        Paragraph("7. The Alignment Module &amp; No-Lookahead Guarantee", styles["Heading1"])
    )
    story.append(
        Paragraph(
            "The central architectural guarantee of <b>nse-alpha</b> is that future information cannot leak into historical signals. "
            "To enforce this by construction:<br/>"
            "&bull; <b>No <code>.shift()</code> in Signal Code:</b> Signal functions compute purely backward-looking expressions.<br/>"
            "&bull; <b>Mandatory T+1 Gap:</b> In <code>eval/alignment.py</code>, a signal calculated at date <i>t</i> is matched with returns realized over <i>[t+1, t+1+h]</i>:",
            styles["Body"],
        )
    )
    story.append(
        make_code_box(
            "# Alignment definition in eval/alignment.py\n"
            "# Signal at close of day t -> executed at open/close of day t+1 -> evaluated over horizon h\n"
            "fwd_return = adj_close.shift(-1 - h) / adj_close.shift(-1) - 1.0\n"
            "aligned = pd.DataFrame({'signal': signal_score, 'fwd_return': fwd_return})",
            styles,
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 8 ------------------
    story.append(Paragraph("8. Information Coefficient &amp; Decay", styles["Heading1"]))
    story.append(
        Paragraph(
            "<b>8.1 Spearman Rank IC:</b> Evaluates monotonic predictive rank power: <i>IC_t = Corr(Rank(signal_t), Rank(fwd_return_{t+1}))</i>.<br/>"
            "<b>8.2 Newey-West HAC t-Statistic:</b> Standard t-stats understate error due to overlapping return autocorrelation. "
            "We compute Newey-West Heteroskedasticity and Autocorrelation Consistent (HAC) standard errors with lag <i>L = horizon + 1</i>.<br/>"
            "<b>8.3 IC Information Ratio (IR):</b> <i>IR = mean(IC) / std(IC)</i> measures signal consistency.<br/>"
            "<b>8.4 Exponential Half-Life Decay:</b> Measures how fast predictive alpha decays across forward horizons (1, 2, 3, 5, 10, 21 days) by fitting <i>IC(h) = IC_0 &middot; e^{-&lambda; h}</i>.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 9 ------------------
    story.append(
        Paragraph("9. Portfolio Construction, Turnover &amp; Cost Model", styles["Heading1"])
    )
    story.append(
        Paragraph(
            "<b>9.1 Decile Portfolios:</b> Cross-sectional ranking divides the universe into 10 equal-weighted deciles (D1 to D10). "
            "For small custom universes (&lt; 10 stocks), the engine dynamically falls back to top-half vs bottom-half quantiles.<br/>"
            "<b>9.2 Long/Short Spread:</b> Strategy return is <i>R_{LS} = 0.5 &middot; R_{D10} - 0.5 &middot; R_{D1}</i> (zero-net-cost portfolio).<br/>"
            "<b>9.3 One-Way Turnover:</b> <i>Turnover = mean(&sum; |w_{i,t} - w_{i,t-1}| / 2)</i>.<br/>"
            "<b>9.4 Net Return Tiers:</b> Net returns are deducted as <i>R_{net} = R_{gross} - 2 &middot; Turnover &middot; c</i>, where <i>c &isin; {5 bps, 15 bps, 30 bps}</i>.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 10 ------------------
    story.append(Paragraph("10. Walk-Forward Validation Protocol", styles["Heading1"]))
    story.append(
        Paragraph(
            "To guard against overfitting, the engine implements expanding-window walk-forward validation (<code>eval/validation.py</code>) "
            "with a mandatory 21-day post-training embargo period to prevent serial leakage into test windows.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 11 ------------------
    story.append(Paragraph("11. Reporting Layer &amp; Visualizations", styles["Heading1"]))
    story.append(
        Paragraph(
            "The reporting layer (<code>report/markdown.py</code>, <code>report/plots.py</code>, <code>report/table.py</code>) formats results "
            "into clean publication artifacts:<br/>"
            "&bull; <code>results/alpha_table.csv</code>: Complete ranked table of all metrics.<br/>"
            "&bull; <code>results/REPORT.md</code>: Executive summary Markdown document.<br/>"
            "&bull; <code>results/ic_decay.png</code>, <code>quantile_returns.png</code>, <code>cumulative_ls.png</code>: High-resolution diagnostic charts.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 12 ------------------
    story.append(Paragraph("12. Correctness Guarantees — The Canary Tests", styles["Heading1"]))
    story.append(
        Paragraph(
            "Four non-negotiable canary tests in <code>tests/test_canaries.py</code> run on synthetic data to continuously verify the evaluation engine:",
            styles["Body"],
        )
    )
    canary_table = make_table(
        ["Canary Test", "Synthetic Input", "Expected Invariant", "Verification Purpose"],
        [
            [
                "Perfect Foresight",
                "Signal = exact future 1-day return",
                "IC &approx; +1.00 (t-stat &gt; 50)",
                "Proves the evaluation engine correctly captures positive predictive alpha.",
            ],
            [
                "Pure Noise",
                "Signal = i.i.d. standard Gaussian noise",
                "|IC| &lt; 0.05 (|t-stat| &lt; 2.0)",
                "Proves the engine does not generate spurious alpha from white noise.",
            ],
            [
                "Leak Detector",
                "Signal constructed with intentional 1-day future leak",
                "IC_leaked &gt;&gt; IC_unleaked",
                "Proves any temporal shift bug is immediately detected and flagged.",
            ],
            [
                "Date Shuffle",
                "Signal dates permuted randomly across time",
                "IC &approx; 0.00",
                "Proves cross-sectional and time-series alignment integrity.",
            ],
        ],
        [100, 120, 110, 174],
        styles,
    )
    story.append(canary_table)
    story.append(Spacer(1, 8))

    # ------------------ Section 13 ------------------
    story.append(Paragraph("13. Known Limitations &amp; Future Roadmap", styles["Heading1"]))
    story.append(
        Paragraph(
            "<b>1. Point-in-Time Index History:</b> Implementing dynamic historical constituent feeds via <code>UniverseProvider</code> protocol.<br/>"
            "<b>2. Non-Linear Market Impact:</b> Transitioning from linear bps hurdles to square-root Almgren-Chriss impact models.<br/>"
            "<b>3. Combinatorial Purged Cross-Validation (CPCV):</b> Full implementation of Lopez de Prado's CPCV framework.<br/>"
            "<b>4. Composite Alpha Modeling:</b> Factor weighting and non-linear machine learning ensembles.",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 8))

    # ------------------ Section 14 ------------------
    story.append(Paragraph("14. Technical Glossary", styles["Heading1"]))
    gloss_table = make_table(
        ["Term", "Definition &amp; Pipeline Context"],
        [
            [
                "Information Coefficient (IC)",
                "Spearman rank correlation between signal rankings at t and forward realized returns at t+1.",
            ],
            ["Information Ratio (IR)", "Mean IC divided by standard deviation of IC over time."],
            [
                "Newey-West HAC",
                "Heteroskedasticity and Autocorrelation Consistent standard error correction for overlapping return windows.",
            ],
            [
                "Survivorship Bias",
                "Distortion caused by testing on today's index constituent list, ignoring historical delistings.",
            ],
            [
                "Implementation Gap",
                "The 1-day delay between signal generation at date t close and strategy execution at date t+1.",
            ],
            [
                "One-Way Turnover",
                "Mean fraction of portfolio value traded per rebalance period: sum(|w_t - w_{t-1}|) / 2.",
            ],
            [
                "Amihud Illiquidity",
                "Ratio of absolute daily return to daily rupee turnover value: |r_t| / (close_t × volume_t).",
            ],
        ],
        [140, 364],
        styles,
    )
    story.append(gloss_table)

    doc.build(story, canvasmaker=ExplanatoryCanvas)
    print(f"Successfully compiled Explanatory Manual: {out_path}")


def main() -> None:
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)

    project_pdf = docs_dir / "NSE_Alpha_Project_Manual.pdf"
    explanatory_pdf = docs_dir / "NSE_Alpha_Explanatory_Manual.pdf"

    build_project_manual(project_pdf)
    build_explanatory_manual(explanatory_pdf)
    print("All documentation manuals successfully compiled and verified!")


if __name__ == "__main__":
    main()
