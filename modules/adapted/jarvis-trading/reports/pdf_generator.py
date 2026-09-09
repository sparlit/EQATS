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


"""
Neura Capital — AXIOM Branded PDF Generator
Brand: Deep Navy + Sovereign Gold + Steel Blue
Fonts: Montserrat ExtraBold (headings) + Montserrat Light (body)
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fpdf import FPDF
from loguru import logger
from utils.timez import now_ist

# ── Brand Colours (R, G, B) ──
NAVY = (8, 13, 26)  # #080D1A — primary bg
NAVY_MID = (13, 21, 40)  # #0D1528 — alt bg
GOLD = (201, 146, 42)  # #C9922A — sovereign gold accent
BLUE = (67, 97, 238)  # #4361EE — steel blue
WHITE = (240, 244, 255)  # #F0F4FF — arctic white
GREY = (107, 122, 153)  # #6B7A99 — steel grey
GREEN = (0, 200, 120)  # profit green
RED = (220, 60, 60)  # loss red
DIVIDER = (30, 45, 75)  # subtle divider line

FONT_DIR = Path("data/fonts")
LOGO_PATH = Path("data/neura_capital_logo.png")

PAGE_W = 210  # A4 width mm
MARGIN = 14
CONTENT_W = PAGE_W - 2 * MARGIN


# ─────────────────────────────────────────────────────────────────
# BASE PDF CLASS
# ─────────────────────────────────────────────────────────────────


class NeuraCapitalPDF(FPDF):
    def __init__(self, doc_type: str = "REPORT"):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.doc_type = doc_type
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(auto=True, margin=18)
        self._load_fonts()

    def _load_fonts(self) -> None:
        try:
            self.add_font("MontserratEB", "", str(FONT_DIR / "Montserrat-ExtraBold.ttf"), uni=True)
            self.add_font("MontserratB", "", str(FONT_DIR / "Montserrat-Bold.ttf"), uni=True)
            self.add_font("MontserratR", "", str(FONT_DIR / "Montserrat-Regular.ttf"), uni=True)
            self.add_font("MontserratL", "", str(FONT_DIR / "Montserrat-Light.ttf"), uni=True)
            self._fonts_ok = True
        except Exception as exc:
            logger.warning("Montserrat fonts not loaded, using Helvetica: {}", exc)
            self._fonts_ok = False

    def _set(self, family: str, size: float) -> None:
        if self._fonts_ok:
            self.set_font(family, size=size)
        else:
            bold = family in ("MontserratEB", "MontserratB")
            self.set_font("Helvetica", style="B" if bold else "", size=size)

    # ── HEADER (called automatically on each new page) ──
    def header(self) -> None:
        # Full-page navy background — MUST run on every page (page 2+ break)
        self.set_fill_color(*NAVY)
        self.rect(0, 0, PAGE_W, 297, style="F")

        # Full-width navy header bar (slightly darker accent over the base)
        self.set_fill_color(*NAVY)
        self.rect(0, 0, PAGE_W, 22, style="F")

        # Gold left accent stripe
        self.set_fill_color(*GOLD)
        self.rect(0, 0, 3, 22, style="F")

        # Logo (if exists)
        logo_x = 6
        if LOGO_PATH.exists():
            try:
                self.image(str(LOGO_PATH), x=logo_x, y=3, h=16)
                logo_x = 42
            except Exception:
                pass

        # Firm name
        self._set("MontserratEB", 11)
        self.set_text_color(*GOLD)
        self.set_xy(logo_x, 5)
        self.cell(60, 6, "NEURA CAPITAL", ln=False)

        # Doc type tag
        self._set("MontserratL", 7)
        self.set_text_color(*GREY)
        self.set_xy(logo_x, 12)
        self.cell(60, 4, f"AXIOM — {self.doc_type}", ln=False)

        # Right: date + time
        self._set("MontserratR", 7.5)
        self.set_text_color(*GREY)
        ts = now_ist().strftime("%d %b %Y  |  %H:%M IST")
        self.set_xy(PAGE_W - MARGIN - 55, 8)
        self.cell(55, 5, ts, align="R", ln=False)

        # Bottom border line of header
        self.set_draw_color(*GOLD)
        self.set_line_width(0.4)
        self.line(0, 22, PAGE_W, 22)
        self.ln(8)

    # ── FOOTER ──
    def footer(self) -> None:
        self.set_y(-14)
        self.set_fill_color(*NAVY)
        self.rect(0, self.get_y() - 2, PAGE_W, 16, style="F")
        self.set_draw_color(*DIVIDER)
        self.set_line_width(0.3)
        self.line(MARGIN, self.get_y(), PAGE_W - MARGIN, self.get_y())
        self._set("MontserratL", 7)
        self.set_text_color(*GREY)
        self.set_x(MARGIN)
        self.cell(CONTENT_W / 2, 6, "Neura Capital  ·  Confidential  ·  For Internal Use Only", ln=False)
        self.cell(CONTENT_W / 2, 6, f"Page {self.page_no()}", align="R")

    # ── SECTION HEADER ──
    def section_header(self, title: str) -> None:
        self.ln(3)
        self.set_fill_color(*NAVY_MID)
        self.rect(MARGIN, self.get_y(), CONTENT_W, 9, style="F")
        # Gold left accent
        self.set_fill_color(*GOLD)
        self.rect(MARGIN, self.get_y(), 2.5, 9, style="F")
        self._set("MontserratB", 9)
        self.set_text_color(*WHITE)
        self.set_x(MARGIN + 6)
        self.cell(CONTENT_W - 6, 9, title.upper(), ln=True)
        self.ln(2)

    # ── KEY-VALUE ROW ──
    def kv_row(self, label: str, value: str, value_color: tuple = WHITE) -> None:
        self._set("MontserratL", 8.5)
        self.set_text_color(*GREY)
        self.set_x(MARGIN + 4)
        self.cell(55, 6, label, ln=False)
        self._set("MontserratR", 8.5)
        self.set_text_color(*value_color)
        self.cell(CONTENT_W - 59, 6, str(value), ln=True)

    # ── BODY TEXT ──
    def body_text(self, text: str, indent: int = 4) -> None:
        self._set("MontserratL", 8.5)
        self.set_text_color(*WHITE)
        self.set_x(MARGIN + indent)
        self.multi_cell(CONTENT_W - indent, 5.5, text)
        self.ln(1)

    # ── DIVIDER LINE ──
    def divider(self) -> None:
        self.ln(2)
        self.set_draw_color(*DIVIDER)
        self.set_line_width(0.25)
        self.line(MARGIN, self.get_y(), PAGE_W - MARGIN, self.get_y())
        self.ln(3)

    # ── METRIC CARD ROW (3 per row) ──
    def metric_cards(self, metrics: list[tuple[str, str, str]]) -> None:
        """Draw up to 3 metric cards per row. Each tuple: (label, value, color_hex)."""
        card_w = CONTENT_W / 3 - 2
        card_h = 16
        x_start = MARGIN
        y = self.get_y()

        for i, (label, value, colour) in enumerate(metrics[:3]):
            x = x_start + i * (card_w + 3)
            # Card bg
            self.set_fill_color(*NAVY_MID)
            self.rect(x, y, card_w, card_h, style="F")
            # Blue top border
            self.set_fill_color(*BLUE)
            self.rect(x, y, card_w, 1.2, style="F")
            # Label
            self._set("MontserratL", 6.5)
            self.set_text_color(*GREY)
            self.set_xy(x + 3, y + 2.5)
            self.cell(card_w - 3, 4, label.upper(), ln=False)
            # Value
            self._set("MontserratEB", 11)
            rgb = _hex_to_rgb(colour)
            self.set_text_color(*rgb)
            self.set_xy(x + 3, y + 7)
            self.cell(card_w - 3, 7, str(value), ln=False)

        self.ln(card_h + 4)

    # ── TABLE ──
    def table(self, headers: list[str], rows: list[list[str]], col_widths: list[float] | None = None) -> None:
        if not rows:
            self.body_text("No data available.")
            return
        n = len(headers)
        widths = col_widths or [CONTENT_W / n] * n

        # Header row
        self.set_fill_color(*NAVY_MID)
        self.rect(MARGIN, self.get_y(), CONTENT_W, 7, style="F")
        self.set_fill_color(*BLUE)
        self.rect(MARGIN, self.get_y(), CONTENT_W, 1, style="F")
        self._set("MontserratB", 7.5)
        self.set_text_color(*WHITE)
        self.set_x(MARGIN)
        for h, w in zip(headers, widths, strict=False):
            self.cell(w, 7, h.upper(), align="C", ln=False)
        self.ln(7)

        # Data rows
        for row_idx, row in enumerate(rows):
            if self.get_y() > 260:
                self.add_page()
            bg = NAVY if row_idx % 2 == 0 else NAVY_MID
            self.set_fill_color(*bg)
            self.rect(MARGIN, self.get_y(), CONTENT_W, 6, style="F")
            self._set("MontserratR", 7.5)
            self.set_text_color(*WHITE)
            self.set_x(MARGIN)
            for cell_val, w in zip(row, widths, strict=False):
                text = str(cell_val)[:20]
                # Colour P&L cells
                if text.startswith("+") or (text.startswith("₹") and "-" not in text and text != "₹0"):
                    self.set_text_color(*GREEN)
                elif text.startswith(("-", "₹-")):
                    self.set_text_color(*RED)
                else:
                    self.set_text_color(*WHITE)
                self.cell(w, 6, text, align="C", ln=False)
            self.ln(6)

        self.ln(2)


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) != 6:
        return WHITE
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ─────────────────────────────────────────────────────────────────
# REPORT GENERATORS
# ─────────────────────────────────────────────────────────────────


def generate_text_report(title: str, body: str, output_path: Path) -> Path:
    """
    Generate a branded Neura Capital PDF from a text body.
    Used for: morning briefing, task lists, ad-hoc reports.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not body or not body.strip():
        body = "[Report content unavailable. Check API configuration.]"

    pdf = NeuraCapitalPDF(doc_type=title.upper())
    pdf.add_page()  # header() paints the full-page navy background on every page

    # Report title block
    pdf.set_fill_color(*NAVY_MID)
    pdf.rect(MARGIN, pdf.get_y(), CONTENT_W, 14, style="F")
    pdf.set_fill_color(*GOLD)
    pdf.rect(MARGIN, pdf.get_y(), 2.5, 14, style="F")
    pdf._set("MontserratEB", 13)
    pdf.set_text_color(*WHITE)
    pdf.set_x(MARGIN + 7)
    pdf.cell(CONTENT_W - 7, 14, title.upper(), ln=True)
    pdf.ln(4)

    # Parse body into sections (lines starting with a number or ALL CAPS header)
    buffer: list[str] = []

    def flush_buffer() -> None:
        if buffer:
            pdf.body_text("\n".join(buffer))
            buffer.clear()

    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if buffer:
                buffer.append("")
            continue
        # Detect section headers: "1. MARKET PULSE" or "MARKET PULSE" or "## Section"
        is_header = (
            (len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in ".)")
            or (stripped.startswith("##"))
            or (stripped.isupper() and len(stripped) > 4 and len(stripped) < 50)
        )
        if is_header:
            flush_buffer()
            clean = stripped.lstrip("0123456789.)# ").strip()
            pdf.section_header(clean)
        else:
            buffer.append(stripped)

    flush_buffer()
    pdf.output(str(output_path))
    logger.info("PDF saved: {}", output_path)
    return output_path


def generate_trade_journal_pdf(trades: pd.DataFrame, output_path: Path) -> Path:
    """Generate a branded trade journal PDF with summary metrics and trade table."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = NeuraCapitalPDF(doc_type="TRADE JOURNAL")
    pdf.add_page()  # header() paints the full-page navy background on every page

    # Title
    pdf._set("MontserratEB", 14)
    pdf.set_text_color(*GOLD)
    pdf.set_x(MARGIN)
    pdf.cell(CONTENT_W, 10, "TRADE JOURNAL REPORT", ln=True, align="C")
    pdf.ln(2)

    if trades.empty:
        pdf.body_text("No trades recorded yet.")
        pdf.output(str(output_path))
        return output_path

    # ── Summary Metrics ──
    trades = trades.copy()
    trades["pnl"] = pd.to_numeric(trades.get("pnl", 0), errors="coerce").fillna(0)
    total = len(trades)
    wins = int((trades["pnl"] > 0).sum())
    win_rate = wins / total * 100 if total else 0
    total_pnl = trades["pnl"].sum()
    avg_pnl = trades["pnl"].mean() if total else 0

    pnl_color = "#00C878" if total_pnl >= 0 else "#DC3C3C"
    pdf.metric_cards(
        [
            ("Total Trades", str(total), "#4361EE"),
            ("Win Rate", f"{win_rate:.1f}%", "#C9922A"),
            ("Total P&L", f"₹{total_pnl:,.0f}", pnl_color),
        ]
    )
    pdf.metric_cards(
        [
            ("Wins", str(wins), "#00C878"),
            ("Losses", str(total - wins), "#DC3C3C"),
            ("Avg P&L", f"₹{avg_pnl:,.0f}", "#F0F4FF"),
        ]
    )

    # ── P&L by Setup Type ──
    if "setup_type" in trades.columns:
        pdf.section_header("Performance by Setup Type")
        by_setup = trades.groupby("setup_type")["pnl"].agg(["count", "sum", "mean"]).reset_index()
        rows = [
            [
                row["setup_type"],
                str(int(row["count"])),
                f"₹{row['sum']:,.0f}",
                f"₹{row['mean']:,.0f}",
            ]
            for _, row in by_setup.iterrows()
        ]
        pdf.table(
            headers=["Setup Type", "Trades", "Total P&L", "Avg P&L"],
            rows=rows,
            col_widths=[65, 30, 45, 42],
        )

    # ── Recent Trades Table ──
    pdf.section_header(f"Recent Trades (Last {min(20, len(trades))})")
    display = trades.tail(20).copy()
    display["pnl_fmt"] = display["pnl"].apply(lambda x: f"+₹{x:,.0f}" if x >= 0 else f"-₹{abs(x):,.0f}")
    rows = []
    for _, r in display.iterrows():
        rows.append(
            [
                str(r.get("symbol", ""))[:12],
                str(r.get("setup_type", ""))[:14],
                str(r.get("entry_price", ""))[:8],
                str(r.get("exit_price", ""))[:8],
                str(r.get("quantity", ""))[:6],
                r["pnl_fmt"],
                str(r.get("created_at", ""))[:10],
            ]
        )
    pdf.table(
        headers=["Symbol", "Setup", "Entry", "Exit", "Qty", "P&L", "Date"],
        rows=rows,
        col_widths=[30, 35, 25, 25, 18, 30, 24],
    )

    pdf.output(str(output_path))
    logger.info("Trade journal PDF saved: {}", output_path)
    return output_path


def generate_screener_pdf(
    results: pd.DataFrame,
    commentary: str,
    output_path: Path,
    regime: str = "UNKNOWN",
) -> Path:
    """Generate a branded screener results PDF."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = NeuraCapitalPDF(doc_type="SCREENER REPORT")
    pdf.add_page()  # header() paints the full-page navy background on every page

    pdf._set("MontserratEB", 14)
    pdf.set_text_color(*GOLD)
    pdf.set_x(MARGIN)
    pdf.cell(CONTENT_W, 10, "STOCK SCREENER REPORT", ln=True, align="C")
    pdf._set("MontserratL", 8)
    pdf.set_text_color(*GREY)
    pdf.set_x(MARGIN)
    pdf.cell(
        CONTENT_W,
        6,
        f"Run: {now_ist().strftime('%d %b %Y  %H:%M IST')}  ·  Regime: {regime}  ·  Universe: NSE 200",
        ln=True,
        align="C",
    )
    pdf.ln(3)

    if results.empty:
        pdf.body_text("Screener returned no candidates matching filters.")
        pdf.output(str(output_path))
        return output_path

    grade_a = (
        results[results.get("grade", pd.Series()) == "A"]
        if "grade" in results.columns
        else results[results["score"] >= 75]
    )
    grade_b = (
        results[results.get("grade", pd.Series()) == "B"]
        if "grade" in results.columns
        else results[(results["score"] >= 55) & (results["score"] < 75)]
    )

    pdf.metric_cards(
        [
            ("Total Candidates", str(len(results)), "#4361EE"),
            ("Grade A", str(len(grade_a)), "#00C878"),
            ("Grade B", str(len(grade_b)), "#C9922A"),
        ]
    )

    # Top candidates table
    pdf.section_header("Top Candidates — Grade A & B")
    top = results.head(15)
    rows = []
    for _, r in top.iterrows():
        score = r.get("score", 0)
        grade = r.get("grade", "C")
        rows.append(
            [
                str(r.get("symbol", ""))[:12],
                str(grade),
                f"{score:.0f}",
                f"{r.get('close', 0):,.1f}",
                f"{r.get('rsi', 0):.1f}",
                f"{r.get('adx', 0):.1f}",
                r.get("notes", "")[:30],
            ]
        )
    pdf.table(
        headers=["Symbol", "Grade", "Score", "Price", "RSI", "ADX", "Notes"],
        rows=rows,
        col_widths=[28, 16, 16, 22, 16, 16, 68],
    )

    # AI Commentary
    if commentary:
        pdf.section_header("AXIOM Analyst Commentary")
        for line in commentary.splitlines():
            if line.strip():
                pdf.body_text(line.strip())

    pdf.output(str(output_path))
    logger.info("Screener PDF saved: {}", output_path)
    return output_path
