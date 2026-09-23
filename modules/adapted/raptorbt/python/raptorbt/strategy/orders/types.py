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


"""Typed orders for the class-based order API.

Unlike the legacy intents (:class:`~raptorbt.strategy.orders.MarketOrder` /
:class:`~raptorbt.strategy.orders.ClosePosition`), these carry an explicit
side and time-in-force, may rest across bars (limit/stop kinds), and report
their lifecycle through the granular ``on_order_*`` hooks.

Sizing: pass exactly one of ``units`` (contract count) or ``size_frac``
(fraction of available capital, resolved at fill time). Omit both on a
closing-side order to close the full position. ``stop_price`` /
``target_price`` attach protective levels to the position an opening order
creates.

Semantics: market orders fill on the bar they are submitted, at the engine's
fill-price model — the same contract as ``enter()``. Resting orders begin
matching on the *next* bar; an order cannot rest into a bar that had already
closed when it was placed.
"""


from dataclasses import dataclass, field

_VALID_SIDES = ("buy", "sell")
_VALID_TIFS = ("gtc", "day", "gtd", "ioc", "fok", "at_open", "at_close")
_VALID_OFFSET_KINDS = ("price", "bps", "ticks")


@dataclass(frozen=True, kw_only=True)
class _OrderBase:
    side: str
    units: float | None = None
    size_frac: float | None = None
    tif: str = "gtc"
    expire_ns: int | None = None
    stop_price: float | None = None
    target_price: float | None = None
    reduce_only: bool = False
    tags: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in _VALID_SIDES:
            msg = f"side must be one of {_VALID_SIDES}, got {self.side!r}"
            raise ValueError(msg)
        if self.tif not in _VALID_TIFS:
            msg = f"tif must be one of {_VALID_TIFS}, got {self.tif!r}"
            raise ValueError(msg)
        if self.tif == "gtd" and self.expire_ns is None:
            msg = "tif='gtd' requires expire_ns"
            raise ValueError(msg)
        if self.tif in ("at_open", "at_close") and self.kind != "market":
            msg = "at_open/at_close apply to market orders"
            raise ValueError(msg)
        if self.units is not None and self.size_frac is not None:
            msg = "pass units or size_frac, not both"
            raise ValueError(msg)

    @property
    def kind(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True, kw_only=True)
class Market(_OrderBase):
    """Fill at the engine's fill-price model on the submission bar."""

    @property
    def kind(self) -> str:
        return "market"


@dataclass(frozen=True, kw_only=True)
class Limit(_OrderBase):
    """Rest until the market trades at or through ``price``.

    ``post_only=True`` rejects the order instead of filling if it is already
    marketable at the open of the first bar it rests into.
    """

    price: float = 0.0
    post_only: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.price <= 0.0:
            msg = "limit price must be > 0"
            raise ValueError(msg)

    @property
    def kind(self) -> str:
        return "limit"


@dataclass(frozen=True, kw_only=True)
class StopMarket(_OrderBase):
    """Become marketable once the market trades at or through ``trigger``."""

    trigger: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.trigger <= 0.0:
            msg = "stop trigger must be > 0"
            raise ValueError(msg)

    @property
    def kind(self) -> str:
        return "stop_market"


@dataclass(frozen=True, kw_only=True)
class StopLimit(_OrderBase):
    """Once ``trigger`` fires, rest as a limit at ``price`` from the next bar."""

    trigger: float = 0.0
    price: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.trigger <= 0.0 or self.price <= 0.0:
            msg = "stop_limit needs trigger > 0 and price > 0"
            raise ValueError(msg)

    @property
    def kind(self) -> str:
        return "stop_limit"


@dataclass(frozen=True, kw_only=True)
class MarketIfTouched(_OrderBase):
    """Fill once the market trades *favorably* to ``trigger`` (a buy fires
    when price falls to it) — the stop's mirror."""

    trigger: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.trigger <= 0.0:
            msg = "trigger must be > 0"
            raise ValueError(msg)

    @property
    def kind(self) -> str:
        return "market_if_touched"


@dataclass(frozen=True, kw_only=True)
class LimitIfTouched(_OrderBase):
    """Favorable touch at ``trigger``, then rest as a limit at ``price``."""

    trigger: float = 0.0
    price: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.trigger <= 0.0 or self.price <= 0.0:
            msg = "limit_if_touched needs trigger > 0 and price > 0"
            raise ValueError(msg)

    @property
    def kind(self) -> str:
        return "limit_if_touched"


@dataclass(frozen=True, kw_only=True)
class MarketToLimit(_OrderBase):
    """Fill at the next bar's open (identical to an at-the-open market until
    partial fills exist)."""

    @property
    def kind(self) -> str:
        return "market_to_limit"


@dataclass(frozen=True, kw_only=True)
class TrailingStopMarket(_OrderBase):
    """Stop whose trigger trails the running favorable extreme by
    ``offset`` — ``offset_kind`` is ``"price"``, ``"bps"``, or ``"ticks"``
    (ticks need an instrument with a ``price_increment``)."""

    offset: float = 0.0
    offset_kind: str = "price"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.offset <= 0.0:
            msg = "offset must be > 0"
            raise ValueError(msg)
        if self.offset_kind not in _VALID_OFFSET_KINDS:
            msg = f"offset_kind must be one of {_VALID_OFFSET_KINDS}"
            raise ValueError(msg)

    @property
    def kind(self) -> str:
        return "trailing_stop_market"


@dataclass(frozen=True, kw_only=True)
class TrailingStopLimit(_OrderBase):
    """Trailing stop that rests as a limit ``limit_offset`` through the
    trigger once it fires (bounded slippage)."""

    offset: float = 0.0
    offset_kind: str = "price"
    limit_offset: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.offset <= 0.0:
            msg = "offset must be > 0"
            raise ValueError(msg)
        if self.offset_kind not in _VALID_OFFSET_KINDS:
            msg = f"offset_kind must be one of {_VALID_OFFSET_KINDS}"
            raise ValueError(msg)
        if self.limit_offset < 0.0:
            msg = "limit_offset must be >= 0"
            raise ValueError(msg)

    @property
    def kind(self) -> str:
        return "trailing_stop_limit"


@dataclass(frozen=True, kw_only=True)
class Twap(_OrderBase):
    """Slice an order into equal parts released at a fixed interval.

    A TWAP is a schedule, not an order: it releases ``slices`` ordinary
    orders spaced ``every`` nanoseconds apart, the first immediately. Each
    slice reports its own fill, with a client id of ``"<parent>#<n>"``.

    ``every`` is a duration rather than a bar count because a bar index
    means different things in bar and tick sessions — "every 1 bar" would
    silently become "every 1 print" on a tick feed. Pass ``every_bars``
    with ``bar_ns`` if you would rather think in bars.

    Only explicit ``units`` can be sliced. ``size_frac`` resolves against
    equity at fill time, so each slice would size against a different
    account.

    Cancelling a schedule stops the remaining slices; it does not unwind
    the ones that already traded.
    """

    slices: int = 2
    every: int = 0
    every_bars: int | None = None
    bar_ns: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.slices < 1:
            msg = "slices must be >= 1"
            raise ValueError(msg)
        if self.units is None:
            msg = "Twap needs explicit units; size_frac cannot be sliced"
            raise ValueError(msg)
        if self.every_bars is not None:
            if self.bar_ns is None:
                msg = "every_bars needs bar_ns to convert to a duration"
                raise ValueError(msg)
            if self.every:
                msg = "pass every or every_bars, not both"
                raise ValueError(msg)
        elif self.every <= 0:
            msg = "every must be > 0 nanoseconds"
            raise ValueError(msg)

    @property
    def kind(self) -> str:
        return "market"

    @property
    def interval_ns(self) -> int:
        """Resolved slice interval in nanoseconds."""
        if self.every_bars is not None:
            return self.every_bars * int(self.bar_ns)
        return self.every
