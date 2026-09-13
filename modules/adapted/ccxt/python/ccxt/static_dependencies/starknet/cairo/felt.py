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


from typing import List

from ..constants import FIELD_PRIME

CairoData = list[int]


MAX_UINT256 = (1 << 256) - 1
MIN_UINT256 = 0


def uint256_range_check(value: int):
    if not MIN_UINT256 <= value <= MAX_UINT256:
        msg = f"Uint256 is expected to be in range [0;2**256), got: {value}."
        raise ValueError(msg)


MIN_FELT = -FIELD_PRIME // 2
MAX_FELT = FIELD_PRIME // 2


def is_in_felt_range(value: int) -> bool:
    return 0 <= value < FIELD_PRIME


def cairo_vm_range_check(value: int):
    if not is_in_felt_range(value):
        msg = f"Felt is expected to be in range [0; {FIELD_PRIME}), got: {value}."
        raise ValueError(msg)


def encode_shortstring(text: str) -> int:
    """
    A function which encodes short string value (at most 31 characters) into cairo felt (MSB as first character)

    :param text: A short string value in python
    :return: Short string value encoded into felt
    """
    if len(text) > 31:
        msg = f"Shortstring cannot be longer than 31 characters, got: {len(text)}."
        raise ValueError(msg)

    try:
        text_bytes = text.encode("ascii")
    except UnicodeEncodeError as u_err:
        msg = f"Expected an ascii string. Found: {text!r}."
        raise ValueError(msg) from u_err
    value = int.from_bytes(text_bytes, "big")

    cairo_vm_range_check(value)
    return value


def decode_shortstring(value: int) -> str:
    """
    A function which decodes a felt value to short string (at most 31 characters)

    :param value: A felt value
    :return: Decoded string which is corresponds to that felt
    """
    cairo_vm_range_check(value)
    return "".join([chr(i) for i in value.to_bytes(31, byteorder="big")]).lstrip("\x00")
