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


from app.agents.fundamental import run_fundamental_check

GOOD_INFO = {
    "sector": "Technology",
    "marketCap": 10_000_00_00_000,  # 10,000 Cr
    "debtToEquity": 50,  # 0.5x
    "returnOnEquity": 0.20,  # 20%
    "revenueGrowth": 0.15,  # 15% YoY
    "trailingPE": 25,
}


def test_approved_clean_company():
    result = run_fundamental_check("TITAN.NS", GOOD_INFO)

    assert result["approved"] is True
    assert result["block_reasons"] == []
    assert result["notes"] == "clean"


def test_blocked_micro_cap():
    info = {**GOOD_INFO, "marketCap": 2_00_00_00_000}  # 200 Cr

    result = run_fundamental_check("TITAN.NS", info)

    assert result["approved"] is False
    assert any("micro-cap" in reason for reason in result["block_reasons"])


def test_blocked_high_debt_equity():
    info = {**GOOD_INFO, "debtToEquity": 250}  # 2.5x

    result = run_fundamental_check("TITAN.NS", info)

    assert result["approved"] is False
    assert any("debt" in reason for reason in result["block_reasons"])


def test_debt_equity_skipped_for_financial_sector():
    info = {
        **GOOD_INFO,
        "sector": "Banking",
        "debtToEquity": 250,
    }  # 2.5x but in Banking sector

    result = run_fundamental_check("TITAN.NS", info)

    assert result["approved"] is True


def test_blocked_negative_roe():
    info = {**GOOD_INFO, "returnOnEquity": -0.05}  # -5%

    result = run_fundamental_check("TITAN.NS", info)

    assert result["approved"] is False
    assert any("ROE" in reason for reason in result["block_reasons"])


def test_no_data_approved_with_note():
    result = run_fundamental_check("TITAN.Ns", None)

    assert result["approved"] is True
    assert "No data" in result["notes"]


def test_flags_do_not_block():
    info = {
        **GOOD_INFO,
        "revenueGrowth": -0.15,
        "trailingPE": 120,
        "returnOnEquity": 0.03,
    }  # Flags but not disqualifying

    result = run_fundamental_check("TITAN.NS", info)

    assert result["approved"] is True
    assert "Flags:" in result["notes"]
