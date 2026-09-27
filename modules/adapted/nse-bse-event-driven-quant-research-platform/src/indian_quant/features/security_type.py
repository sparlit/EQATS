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


"""Security type classification for Indian equities.

Classifies symbols into: EQUITY, ETF, DEBT, INDEX, SME, UNKNOWN.

ETF detection: symbol contains ETF/BEES or fund house names
DEBT detection: symbol contains GS/SEC/BOND/TBILL or starts with digits
INDEX detection: symbol starts with NIFTY/SENSEX
SME detection: segment = "SME"
EQUITY: everything else with segment = "EQ"
UNKNOWN: segment is not EQ/SME
"""


import re

# Fund house name patterns (case-insensitive)
ETF_FUND_HOUSES = [
    "ICICI",
    "HDFC",
    "SBI",
    "ADITYA",
    "MOTILAL",
    "NIPPON",
    "ABSL",
    "AXIS",
    "DSP",
    "EDELWEISS",
    "FRANKLIN",
    "HSBC",
    "IDBI",
    "IDFC",
    "IIFL",
    "INDIABULLS",
    "KOTAK",
    "L&T",
    "MIRAE",
    "QUANT",
    "SUNDARAM",
    "TATA",
    "UTI",
    "YES",
]

ETF_PATTERNS = re.compile(
    r"ETF|BEES|" + "|".join(ETF_FUND_HOUSES),
    re.IGNORECASE,
)

DEBT_PATTERNS = re.compile(
    r"^GS|^TBILL|^T-BILL|SEC\d|BOND\d|NCD\d",
    re.IGNORECASE,
)

INDEX_PATTERNS = re.compile(
    r"^NIFTY|^SENSEX|^BANKNIFTY|^FINNIFTY|^MIDCPNIFTY",
    re.IGNORECASE,
)

# Short codes starting with digits (BSE debt instruments)
DIGIT_START_PATTERN = re.compile(r"^\d{2}[A-Z]{3,5}$")


def classify_security_type(symbol: str, segment: str | None = None) -> str:
    """Classify a symbol's security type.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "ICICIPR50")
        segment: Exchange segment (e.g., "EQ", "SME", "FO")

    Returns:
        One of: EQUITY, ETF, DEBT, INDEX, SME, UNKNOWN
    """
    symbol = symbol.upper().strip()
    segment = (segment or "").upper()

    # SME segment override
    if segment == "SME":
        return "SME"

    # Index detection (check before ETF — NIFTYBEES is an ETF that tracks NIFTY)
    if INDEX_PATTERNS.match(symbol):
        return "INDEX"

    # ETF detection
    if ETF_PATTERNS.search(symbol):
        return "ETF"

    # Debt detection
    if DEBT_PATTERNS.match(symbol):
        return "DEBT"

    # Short codes starting with digits (BSE debt)
    if DIGIT_START_PATTERN.match(symbol):
        return "DEBT"

    # Default to EQUITY for EQ segment
    if segment == "EQ" or not segment:
        return "EQUITY"

    return "UNKNOWN"


def classify_all_signals(signals: list[dict]) -> list[dict]:
    """Add security_type to all signal dicts.

    Modifies signals in-place and returns them.
    """
    for s in signals:
        symbol = s.get("symbol", "")
        segment = s.get("segment", "EQ")
        s["security_type"] = classify_security_type(symbol, segment)
    return signals
