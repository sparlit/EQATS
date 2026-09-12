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


# This directory contains ccxt's own integration test harness, driven by
# ccxt/test/tests_init.py (see the repository CI), not by pytest.
# The test functions here are parameterized by the harness
# (exchange, skipped_properties, ...) and run against live exchange APIs,
# so collecting them with pytest fails with "fixture 'exchange' not found"
# and they would not be runnable offline in any case.
# This guard makes pytest skip the whole tree gracefully, which matters for
# downstream packagers (FreeBSD ports, Debian, nixpkgs, conda-forge) that
# reflexively run pytest over installed site-packages.
# See https://github.com/ccxt/ccxt/issues/29383
collect_ignore_glob = ["*"]
