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
Minimal, hand-rolled replacement for the previously vendored `eth-abi`,
`eth-account` and `eth-utils`/`toolz` packages.

Only the functionality actually used by ccxt is implemented:

- ``encode(types, args)``: standard Ethereum ABI (head/tail) encoding of the
  elementary types ``uintN``/``intN``/``address``/``bool``/``bytesN``/
  ``bytes``/``string`` and (nested) fixed-size/dynamic arrays thereof.
- ``hash_domain`` / ``hash_eip712_message``: EIP-712 typed structured data
  hashing, behaviour-compatible with ``eth_account.messages.encode_typed_data``.
"""

from .abi import encode
from .typed_data import (
    encode_typed_data,
    get_primary_type,
    hash_domain,
    hash_eip712_message,
)

__all__ = [
    "encode",
    "encode_typed_data",
    "get_primary_type",
    "hash_domain",
    "hash_eip712_message",
]
