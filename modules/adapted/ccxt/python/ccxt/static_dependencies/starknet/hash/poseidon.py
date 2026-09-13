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


# Ported from ts/src/static_dependencies/scure-starknet/index.ts.

from hashlib import sha256

from ..constants import FIELD_PRIME

RATE = 2
CAPACITY = 1
ROUNDS_FULL = 8
ROUNDS_PARTIAL = 83
MDS_SMALL = [
    [3, 1, 1],
    [1, -1, 1],
    [1, 1, -2],
]


def _field(value):
    return value % FIELD_PRIME


def _round_constant(name, index):
    digest = sha256((name + str(index)).encode()).digest()
    return _field(int.from_bytes(digest, "big"))


def _round_constants():
    constants = []
    rounds = ROUNDS_FULL + ROUNDS_PARTIAL
    width = RATE + CAPACITY
    for i in range(rounds):
        row = []
        for j in range(width):
            row.append(_round_constant("Hades", width * i + j))
        constants.append(row)
    return constants


ROUND_CONSTANTS = _round_constants()
MDS = [[_field(value) for value in row] for row in MDS_SMALL]


def _sbox(value):
    return pow(value, 3, FIELD_PRIME)


def _poseidon_round(values, is_full, index):
    values = [_field(value + ROUND_CONSTANTS[index][i]) for i, value in enumerate(values)]
    if is_full:
        values = [_sbox(value) for value in values]
    else:
        values[-1] = _sbox(values[-1])
    result = []
    for row in MDS:
        acc = 0
        for i, value in enumerate(values):
            acc += row[i] * value
        result.append(_field(acc))
    return result


def poseidon_hash(values):
    width = RATE + CAPACITY
    if len(values) != width:
        msg = "Poseidon: wrong values length"
        raise ValueError(msg)
    values = [_field(value) for value in values]
    round_index = 0
    half_rounds_full = ROUNDS_FULL // 2
    for _ in range(half_rounds_full):
        values = _poseidon_round(values, True, round_index)
        round_index += 1
    for _ in range(ROUNDS_PARTIAL):
        values = _poseidon_round(values, False, round_index)
        round_index += 1
    for _ in range(half_rounds_full):
        values = _poseidon_round(values, True, round_index)
        round_index += 1
    return values


def poseidon_hash_many(values):
    padded = list(values)
    padded.append(1)
    while len(padded) % RATE != 0:
        padded.append(0)
    state = [0] * (RATE + CAPACITY)
    for i in range(0, len(padded), RATE):
        for j in range(RATE):
            state[j] += padded[i + j]
        state = poseidon_hash(state)
    return state[0]
