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


"""Tests for the holdings Screener shareholding-pattern parser."""
from bs4 import BeautifulSoup
from holdings import _parse_shareholding_table


def _screener_table(rows):
    """Build a minimal HTML fragment mimicking Screener's shareholding table."""
    html = "<section id='shareholding'><table class='data-table'>"
    html += "<thead><tr><th></th>"
    headers = ["Mar 2024", "Jun 2024", "Sep 2024", "Dec 2024", "Mar 2025"]
    for h in headers:
        html += f"<th>{h}</th>"
    html += "</tr></thead><tbody>"
    for row in rows:
        html += "<tr>"
        for cell in row:
            html += f"<td>{cell}</td>"
        html += "</tr>"
    html += "</tbody></table></section>"
    return BeautifulSoup(html, "html.parser")


def test_parse_shareholding_basic():
    soup = _screener_table(
        [
            ["Promoters", "50.31%", "50.10%", "50.07%", "50.00%", "50.00%"],
            ["FIIs", "22.06%", "19.07%", "19.21%", "18.65%", "19.09%"],
            ["DIIs", "16.98%", "19.36%", "19.72%", "20.25%", "20.46%"],
            ["Government", "0.19%", "0.17%", "0.17%", "0.17%", "0.17%"],
            ["Public", "10.46%", "11.30%", "10.84%", "10.92%", "10.28%"],
        ]
    )
    parsed = _parse_shareholding_table(soup)
    assert parsed is not None
    assert parsed["promoters"]["latest_pct"] == 50.00
    assert parsed["fiis"]["latest_pct"] == 19.09
    assert parsed["diis"]["latest_pct"] == 20.46


def test_parse_shareholding_no_section():
    soup = BeautifulSoup("<div></div>", "html.parser")
    assert _parse_shareholding_table(soup) is None
