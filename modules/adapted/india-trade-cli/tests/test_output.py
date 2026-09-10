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


"""Tests for engine/output.py — flag parsing, markup stripping, filenames."""

from engine.output import _strip_rich_markup, parse_output_flags


class TestParseOutputFlags:
    def test_pdf_flag(self):
        args, pdf, explain, explain_save = parse_output_flags(["RELIANCE", "--pdf"])
        assert args == ["RELIANCE"]
        assert pdf is True
        assert explain is False
        assert explain_save is False

    def test_explain_flag(self):
        args, pdf, explain, _explain_save = parse_output_flags(["RELIANCE", "--explain"])
        assert args == ["RELIANCE"]
        assert pdf is False
        assert explain is True

    def test_explain_save_enables_both(self):
        args, pdf, explain, explain_save = parse_output_flags(["SYM", "--explain-save"])
        assert args == ["SYM"]
        assert pdf is True
        assert explain is True
        assert explain_save is True

    def test_no_flags(self):
        args, pdf, explain, _explain_save = parse_output_flags(["RELIANCE"])
        assert args == ["RELIANCE"]
        assert pdf is False
        assert explain is False

    def test_multiple_flags(self):
        args, pdf, explain, _ = parse_output_flags(["SYM", "--pdf", "--explain"])
        assert args == ["SYM"]
        assert pdf is True
        assert explain is True

    def test_empty_args(self):
        args, pdf, _explain, _ = parse_output_flags([])
        assert args == []
        assert pdf is False


class TestStripRichMarkup:
    def test_bold(self):
        assert _strip_rich_markup("[bold]hello[/bold]") == "hello"

    def test_color(self):
        assert _strip_rich_markup("[red]error[/red]") == "error"

    def test_nested(self):
        result = _strip_rich_markup("[bold cyan]title[/bold cyan] text")
        assert "title" in result
        assert "text" in result
        assert "[" not in result

    def test_plain_text_unchanged(self):
        assert _strip_rich_markup("plain text") == "plain text"
