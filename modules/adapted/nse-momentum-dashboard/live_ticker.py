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


"""
Generic live tick feed -- wraps Kite Connect's WebSocket ticker
(KiteTicker) so ANY part of this app (not intraday-specific: the
intraday engine's trigger/stop/target checks, the Intraday Dashboard's
live price display, and the Positional Dashboard/Positions & Trade
pages if/when they want push-based prices instead of a REST get_ltp()
per rerun) can react to real market ticks instead of polling a REST
endpoint. The intraday engine originally polled kite_client.get_ltp()
every POLL_SECONDS (7s), meaning every trigger/stop/target event could
be detected up to 7 seconds late; Spec.md §6.2 explicitly calls for
these to be tick-driven rather than candle- or poll-driven -- this
module is intentionally standalone (no import of intraday_* modules)
so that fix isn't locked to the intraday strategy alone.

The KiteTicker connection runs in its own background thread (connect
(threaded=True)); on_ticks() only ever writes into a lock-protected
dict, so a caller's own loop/page render never blocks on network I/O --
it just reads whatever the most recent tick left in the cache. Kite's
own client handles reconnection (reconnect=True by default).
"""

import contextlib
import datetime as dt
import threading

from kiteconnect import KiteTicker

import config

_KITE_MODES = {"ltp": "ltp", "quote": "quote", "full": "full"}


class LiveTicker:
    """Subscribes to a set of instrument tokens (which can grow over the
    object's lifetime via add_tokens()) and keeps the latest tick for
    each in memory.

    mode: "ltp" (last-traded-price only -- the lightest subscription,
    plenty for trigger/stop/target checks) or "quote" (adds each tick's
    own ohlc.close = previous day's close, needed to show a day-change %
    -- used by the Dashboard's own ticker, not the engine's).

    symbol_by_token: {instrument_token: "SYMBOL"} -- subscription itself
    is by token (Kite's ticker protocol has no symbol-based API); this
    mapping is kept only for get_ltp_by_symbol()/logging convenience.
    """

    def __init__(self, symbol_by_token: dict[int, str], mode: str = "ltp"):
        if mode not in _KITE_MODES:
            msg = f"mode must be one of {list(_KITE_MODES)}, got {mode!r}"
            raise ValueError(msg)
        self.mode = mode
        self.symbol_by_token = dict(symbol_by_token)
        self.token_by_symbol = {sym: tok for tok, sym in symbol_by_token.items()}
        self.tokens = list(symbol_by_token)
        self._lock = threading.Lock()
        self._ticks: dict[int, dict] = {}
        self._last_tick_at: dict[int, dt.datetime] = {}
        self._connected = threading.Event()
        self.started = False  # True once start() has been called (even if the handshake is still pending)
        self._consecutive_403s = 0  # reset on any successful connect -- see _give_up_if_auth_failure()
        self.kws = KiteTicker(config.KITE_API_KEY, config.KITE_ACCESS_TOKEN)
        self.kws.on_ticks = self._on_ticks
        self.kws.on_connect = self._on_connect
        self.kws.on_close = self._on_close
        self.kws.on_error = self._on_error
        self.kws.on_reconnect = self._on_reconnect

    def _kite_mode(self, ws):
        return {"ltp": ws.MODE_LTP, "quote": ws.MODE_QUOTE, "full": ws.MODE_FULL}[self.mode]

    def start(self, timeout: float = 15.0) -> None:
        """Connects in a background thread and blocks until the first
        on_connect callback fires (or `timeout` elapses -- callers log a
        warning and carry on rather than hanging forever, so a slow/
        failed WS handshake doesn't wedge the whole trading day/page).

        Idempotent: a second call is a no-op (returns immediately) --
        without this, a caller like _ensure_subscribed() that checks
        `.started` before calling start() on every one of several
        symbols would otherwise re-invoke connect()/re-wait the full
        `timeout` each time if `started` were never actually set."""
        if self.started:
            return
        self.started = True
        self.kws.connect(threaded=True)
        if not self._connected.wait(timeout=timeout):
            print(f"[live_ticker] WARNING: no connect callback within {timeout}s -- ticks may not be arriving yet.")

    def stop(self) -> None:
        with contextlib.suppress(Exception):
            self.kws.close()

    def add_tokens(self, symbol_by_token: dict[int, str]) -> None:
        """Subscribes additional tokens after start() -- e.g. once
        today's 2 candidates are known at 09:30, or a candidate's sector
        index is resolved. No-ops on tokens already subscribed."""
        new = {tok: sym for tok, sym in symbol_by_token.items() if tok not in self.symbol_by_token}
        if not new:
            return
        self.symbol_by_token.update(new)
        self.token_by_symbol.update({sym: tok for tok, sym in new.items()})
        self.tokens.extend(new)
        if self._connected.is_set():
            new_tokens = list(new)
            self.kws.subscribe(new_tokens)
            self.kws.set_mode(self._kite_mode(self.kws), new_tokens)

    def _on_connect(self, ws, response) -> None:
        self._consecutive_403s = 0  # a real connect proves the credential itself is fine
        ws.subscribe(self.tokens)
        ws.set_mode(self._kite_mode(ws), self.tokens)
        self._connected.set()
        print(
            f"[live_ticker] connected ({self.mode}), subscribed to {len(self.tokens)} "
            f"tokens ({', '.join(self.symbol_by_token.values())})"
        )

    def _on_close(self, ws, code, reason) -> None:
        print(f"[live_ticker] closed: {code} {reason}")

    def _on_error(self, ws, code, reason) -> None:
        print(f"[live_ticker] error: {code} {reason}")
        self._give_up_if_auth_failure(ws, reason)

    # A single real 403 fires BOTH on_error and on_close for the same
    # event -- only counted here (on_error), so this threshold means
    # roughly this many distinct rejected handshakes, not callback calls.
    _MAX_CONSECUTIVE_403S = 3

    def _give_up_if_auth_failure(self, ws, reason) -> None:
        """A genuinely bad/expired access token gets rejected with a 403
        on EVERY handshake attempt -- left to KiteTicker's own default
        retry behavior, that's an unthrottled reconnect loop (observed:
        dozens of attempts per second, indefinitely), which does nothing
        useful and burns CPU/network for as long as the process runs.

        But a single 403 can also happen with a perfectly good token --
        confirmed live 2026-09-15: the dashboard's own ticker got one
        immediately after a successful connect (likely a brief
        connection-slot contention on Kite's side), while a fresh
        LiveTicker with the SAME credentials connected cleanly moments
        later. Giving up permanently after just one 403 would have
        stopped this ticker for the rest of the process's life over a
        transient blip. Only gives up after _MAX_CONSECUTIVE_403S in a
        row with no successful connect between them (_on_connect resets
        the counter) -- a real dead credential still 403s every time and
        trips this quickly; a one-off blip lets KiteTicker's own
        reconnect (which has its own backoff) recover normally."""
        if not (reason and "403" in str(reason)):
            return
        self._consecutive_403s += 1
        if self._consecutive_403s < self._MAX_CONSECUTIVE_403S:
            print(
                f"[live_ticker] 403 Forbidden on connect ({self._consecutive_403s}/"
                f"{self._MAX_CONSECUTIVE_403S}) -- letting KiteTicker's own reconnect retry."
            )
            return
        print(
            f"[live_ticker] {self._consecutive_403s} consecutive 403s -- credentials "
            "invalid/expired, giving up (not retrying). Live prices will fall back to REST."
        )
        with contextlib.suppress(Exception):
            ws.stop_retry()

    def _on_reconnect(self, ws, attempts_count) -> None:
        print(f"[live_ticker] reconnecting (attempt {attempts_count})...")

    def _on_ticks(self, ws, ticks) -> None:
        now = dt.datetime.now()
        with self._lock:
            for t in ticks:
                token = t["instrument_token"]
                self._ticks[token] = t
                self._last_tick_at[token] = now

    def get_ltp(self, token: int) -> float | None:
        with self._lock:
            tick = self._ticks.get(token)
        return tick["last_price"] if tick else None

    def get_ltp_by_symbol(self, symbol: str) -> float | None:
        token = self.token_by_symbol.get(symbol)
        return self.get_ltp(token) if token is not None else None

    def get_change_pct(self, token: int) -> float | None:
        """Day-change % vs this tick's own ohlc.close (previous day's
        close) -- only populated in "quote"/"full" mode; always None in
        "ltp" mode (that packet has no ohlc)."""
        with self._lock:
            tick = self._ticks.get(token)
        if not tick:
            return None
        prev_close = (tick.get("ohlc") or {}).get("close")
        if not prev_close:
            return None
        return (tick["last_price"] - prev_close) / prev_close * 100

    def get_ltp_and_change(self, token: int) -> tuple[float | None, float | None]:
        with self._lock:
            tick = self._ticks.get(token)
        if not tick:
            return None, None
        last_price = tick["last_price"]
        prev_close = (tick.get("ohlc") or {}).get("close")
        change_pct = (last_price - prev_close) / prev_close * 100 if prev_close else None
        return last_price, change_pct

    def last_tick_age(self, token: int) -> float | None:
        """Seconds since the last tick for `token`, or None if none has
        arrived yet -- lets a caller fall back to a REST call if the
        feed has gone stale (e.g. mid-reconnect) instead of silently
        acting on a price that's minutes old."""
        with self._lock:
            ts = self._last_tick_at.get(token)
        return (dt.datetime.now() - ts).total_seconds() if ts else None
