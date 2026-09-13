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


from v2.v3_telegram import currency, paginate_cards, percent, text, ticker


def test_html_and_ticker_are_safe_and_linked():
    assert text("A&B <test>") == "A&amp;B &lt;test&gt;"
    assert "NSE%3ARELIANCE" in ticker("reliance")
    assert "href=" not in ticker("bad symbol!")


def test_missing_and_indian_values():
    assert currency(125000) == "₹125,000.00"
    assert currency(None) == "N/A"
    assert percent(-2.5) == "-2.50%"


def test_card_pagination_never_splits_card():
    cards = ["A" * 1700, "B" * 1700, "C" * 1700]
    pages = paginate_cards("<b>HEADER</b>", cards)
    assert len(pages) == 3
    assert all(len(page) <= 3400 for page in pages)
