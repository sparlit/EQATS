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


"""Tests for sentiment history export (archive/CSV)."""


class TestSentimentHistoryExport:
    """Tests for history_to_csv() export function."""

    def test_history_to_csv_returns_csv_string(self):
        """history_to_csv should return a valid CSV string with headers and data."""
        from persistence import history_to_csv

        data = [
            {"date": "2026-06-18", "ticker": "RELIANCE", "smartscore": "72", "avg_compound": "0.45"},
            {"date": "2026-06-19", "ticker": "RELIANCE", "smartscore": "65", "avg_compound": "0.20"},
            {"date": "2026-06-20", "ticker": "RELIANCE", "smartscore": "80", "avg_compound": "0.60"},
        ]

        csv_out = history_to_csv("RELIANCE", data)

        assert isinstance(csv_out, str)
        assert "date" in csv_out
        assert "smartscore" in csv_out
        assert "2026-06-18" in csv_out
        assert "RELIANCE" in csv_out
        lines = csv_out.strip().split("\n")
        assert len(lines) == 4  # header + 3 rows

    def test_history_to_csv_empty(self):
        """history_to_csv should return just the header for empty data."""
        from persistence import history_to_csv

        csv_out = history_to_csv("RELIANCE", [])

        assert isinstance(csv_out, str)
        assert "date" in csv_out or "ticker" in csv_out
        lines = csv_out.strip().split("\n")
        assert len(lines) == 1  # header only

    def test_history_to_csv_filters_ticker(self):
        """history_to_csv should only include rows matching the ticker, or use all if no ticker filter."""
        from persistence import history_to_csv

        data = [
            {"date": "2026-06-18", "ticker": "RELIANCE", "smartscore": "72"},
            {"date": "2026-06-19", "ticker": "HDFCBANK", "smartscore": "65"},
        ]

        csv_out = history_to_csv("RELIANCE", data)

        assert "RELIANCE" in csv_out
        assert "HDFCBANK" not in csv_out
