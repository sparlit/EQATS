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


###############################################################################
# Copyright 2019 StarkWare Industries Ltd.                                    #
#                                                                             #
# Licensed under the Apache License, Version 2.0 (the "License").             #
# You may not use this file except in compliance with the License.            #
# You may obtain a copy of the License at                                     #
#                                                                             #
# https://www.starkware.co/open-source-license/                               #
#                                                                             #
# Unless required by applicable law or agreed to in writing,                  #
# software distributed under the License is distributed on an "AS IS" BASIS,  #
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.    #
# See the License for the specific language governing permissions             #
# and limitations under the License.                                          #
###############################################################################


from typing import Tuple

# A type that represents a point (x,y) on an elliptic curve.
ECPoint = tuple[int, int]


def igcdex(a: int, b: int) -> tuple[int, int, int]:
    """
    Extended Euclidean algorithm: returns x, y, g such that g = x*a + y*b = gcd(a, b).
    """
    if (not a) and (not b):
        return (0, 1, 0)
    if not a:
        return (0, b // abs(b), abs(b))
    if not b:
        return (a // abs(a), 0, abs(a))
    x_sign = 1
    y_sign = 1
    if a < 0:
        a, x_sign = -a, -1
    if b < 0:
        b, y_sign = -b, -1
    x, r = 1, 0
    y, s = 0, 1
    while b:
        q, c = divmod(a, b)
        a, b = b, c
        x, r = r, x - q * r
        y, s = s, y - q * s
    return (x * x_sign, y * y_sign, a)


def div_mod(n: int, m: int, p: int) -> int:
    """
    Finds a nonnegative integer 0 <= x < p such that (m * x) % p == n
    """
    a, _b, c = igcdex(m, p)
    assert c == 1
    return (n * a) % p


def div_ceil(x, y):
    assert isinstance(x, int)
    assert isinstance(y, int)
    return -((-x) // y)


def ec_add(point1: ECPoint, point2: ECPoint, p: int) -> ECPoint:
    """
    Gets two points on an elliptic curve mod p and returns their sum.
    Assumes the points are given in affine form (x, y) and have different x coordinates.
    """
    assert (point1[0] - point2[0]) % p != 0
    m = div_mod(point1[1] - point2[1], point1[0] - point2[0], p)
    x = (m * m - point1[0] - point2[0]) % p
    y = (m * (point1[0] - x) - point1[1]) % p
    return x, y


def ec_neg(point: ECPoint, p: int) -> ECPoint:
    """
    Given a point (x,y) return (x, -y)
    """
    x, y = point
    return (x, (-y) % p)


def ec_double(point: ECPoint, alpha: int, p: int) -> ECPoint:
    """
    Doubles a point on an elliptic curve with the equation y^2 = x^3 + alpha*x + beta mod p.
    Assumes the point is given in affine form (x, y) and has y != 0.
    """
    assert point[1] % p != 0
    m = div_mod(3 * point[0] * point[0] + alpha, 2 * point[1], p)
    x = (m * m - 2 * point[0]) % p
    y = (m * (point[0] - x) - point[1]) % p
    return x, y


def ec_mult(m: int, point: ECPoint, alpha: int, p: int) -> ECPoint:
    """
    Multiplies by m a point on the elliptic curve with equation y^2 = x^3 + alpha*x + beta mod p.
    Assumes the point is given in affine form (x, y) and that 0 < m < order(point).
    """
    if m == 1:
        return point
    if m % 2 == 0:
        return ec_mult(m // 2, ec_double(point, alpha, p), alpha, p)
    return ec_add(ec_mult(m - 1, point, alpha, p), point, p)
