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
Market Context Module
Determines market regime (Trend Day vs Range Day) using Nifty/BankNifty.
Based on Murphy's principle: "Trade with the trend, not against it."
"""
import logging
import time as _time
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from shortcircuit import config
from shortcircuit.marketdata.symbols import NIFTY_50, validate_symbol

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


class MarketContext:
    """
    Analyzes broader market to determine if it's safe to take reversal trades.
    """

    # Centralised symbol handling
    NIFTY_SYMBOL = NIFTY_50

    def __init__(self, fyers, morning_high=None, morning_low=None, broker=None):
        self.fyers = fyers
        self.broker = broker  # Optional WS cache reference (Issue 1 fix)
        self.regime = "UNKNOWN"
        self.msg = "Initializing..."

        # Explicit symbol initialisation
        self.nifty_symbol = self.NIFTY_SYMBOL

        # Validate symbol
        if not validate_symbol(self.nifty_symbol):
            logger.error(f"Invalid NIFTY Symbol: {self.nifty_symbol}")
            raise ValueError(f"Invalid NIFTY Symbol: {self.nifty_symbol}")

        # Cache for today's morning range
        self._morning_high = morning_high
        self._morning_low = morning_low
        self._morning_range = (
            (morning_high - morning_low) if (morning_high and morning_low) else None
        )
        self._cache_date = None
        self.morning_range_valid = bool(
            self._morning_high
            and self._morning_low
            and self._morning_range
            and self._morning_range > 0
        )

        # Dynamic regime state
        self.last_regime = "UNKNOWN"
        self.regime_change_time = None
        self.trend_duration_minutes = 0
        self._circuit_touched_today = set()  # G3 Blacklist (Session-permanent)
        self._circuit_blacklist_date = datetime.now(IST).date()

        if self._morning_high:
            logger.info(
                f"✅ Market Context Initialized with Morning Range: {self._morning_low} - {self._morning_high}"
            )
            logger.info(f"   Index: {self.nifty_symbol}")

    @property
    def morning_high(self) -> float:
        return float(self._morning_high or 0.0)

    @property
    def morning_low(self) -> float:
        return float(self._morning_low or 0.0)

    def _fetch_morning_range_from_rest(self):
        """
        Fetch NIFTY morning range (09:15–09:45 IST) from REST 1-minute candles.
        Returns tuple(high, low). On failure, returns (0.0, 0.0).
        """
        now_ist = datetime.now(IST)
        today = now_ist.date()
        five_days_ago = today - timedelta(days=5)

        data = {
            "symbol": self.nifty_symbol,
            "resolution": "1",
            "date_format": "1",
            "range_from": five_days_ago.strftime("%Y-%m-%d"),
            "range_to": today.strftime("%Y-%m-%d"),
            "cont_flag": "1",
        }

        try:
            from shortcircuit.broker.rest_limiter import rest_limiter

            rest_limiter.acquire()
            response = self.fyers.history(data=data)
        except Exception as e:
            logger.critical(f"[MarketContext] Morning range REST fetch exception: {e}")
            return 0.0, 0.0

        candles = response.get("candles") if isinstance(response, dict) else None
        if response.get("s") != "ok" or not candles:
            logger.critical(
                "[MarketContext] Morning range REST fetch failed: status=%s code=%s",
                response.get("s"),
                response.get("code"),
            )
            return 0.0, 0.0

        morning_start = time(9, 15)
        time(9, 30)
        _IST = ZoneInfo("Asia/Kolkata")
        market_open = int(
            datetime(today.year, today.month, today.day, 9, 15, tzinfo=_IST).timestamp()
        )
        warmup_end = int(
            datetime(today.year, today.month, today.day, 9, 30, tzinfo=_IST).timestamp()
        )

        morning_candles = []
        for c in candles:
            ts_ist = datetime.fromtimestamp(c[0], tz=UTC).astimezone(IST)
            if ts_ist.date() == today and market_open <= c[0] <= warmup_end:
                morning_candles.append(c)

        if not morning_candles:
            logger.warning(
                "[MarketContext] No 09:15–09:30 candles found; falling back to all today's intraday candles."
            )
            all_today = []
            for c in candles:
                ts_ist = datetime.fromtimestamp(c[0], tz=UTC).astimezone(IST)
                if ts_ist.date() == today and ts_ist.time() >= morning_start:
                    all_today.append(c)
            if not all_today:
                return 0.0, 0.0
            morning_candles = all_today

        morning_high = max(c[2] for c in morning_candles)
        morning_low = min(c[3] for c in morning_candles)
        logger.info(
            "[MarketContext] ✅ Morning range fetched via REST: High=%s Low=%s (%s candles)",
            round(morning_high, 2),
            round(morning_low, 2),
            len(morning_candles),
        )
        return morning_high, morning_low

    def _refresh_morning_range_if_needed(self):
        """
        Daily morning range initialization.
        Always uses REST to avoid startup dependence on WS cache state.
        """
        now = _time.time()
        if not hasattr(self, "_last_range_fetch_time"):
            self._last_range_fetch_time = 0.0
        if (
            now - self._last_range_fetch_time < 600
        ):  # Increased from 300s → 600s to prevent Fyers 429 rate limits
            return
        self._last_range_fetch_time = now

        today = datetime.now(IST).date()
        if self._cache_date == today and self.morning_range_valid:
            return

        high, low = self._fetch_morning_range_from_rest()
        self._cache_date = today

        if high > 0 and low > 0 and high > low:
            self._morning_high = high
            self._morning_low = low
            self._morning_range = high - low
            self.morning_range_valid = True
            logger.info(
                "[MarketContext] ✅ Initialized | Range: %s - %s",
                round(self._morning_low, 2),
                round(self._morning_high, 2),
            )
            return

        self._morning_high = 0.0
        self._morning_low = 0.0
        self._morning_range = 0.0
        self.morning_range_valid = False
        logger.critical(
            "[MarketContext] ⚠️ Morning range unavailable — range-dependent checks are bypassed."
        )

    # G7 consolidation and caching

    def _get_index_data_cached(self, symbol=None):
        """Fetch index data.

        Primary path: Read LTP from the live WebSocket cache (zero REST calls).
        Fallback path: Fetch 5-minute candles from the REST History API if the
        broker/WS cache is unavailable.
        """
        if symbol is None:
            symbol = self.nifty_symbol

        now = _time.time()

        # Primary: Read directly from live WS cache (no REST call)
        if self.broker is not None:
            try:
                snap = self.broker.get_quote_cache_snapshot()
                entry = snap.get(symbol)
                if entry and entry.get("ltp", 0) > 0:
                    ltp = entry["ltp"]
                    # Synthesize a 1-element candle list: [epoch, o, h, l, close, vol]
                    # Consumers only use candles[-1][4] (close price)
                    synthetic_candle = [now, ltp, ltp, ltp, ltp, entry.get("volume", 0)]
                    logger.debug("[MarketContext] Index %s from WS cache: LTP=%.2f", symbol, ltp)
                    return [synthetic_candle]
            except Exception as e:
                logger.warning("[MarketContext] WS cache read failed for %s: %s", symbol, e)

        # Fallback: REST History API
        if not hasattr(self, "_index_cache"):
            self._index_cache = {}
            self._index_cache_time = {}
            self._index_last_attempt = {}
            self._index_backoff = {}

        # Cache hit?
        if symbol in self._index_cache and (now - self._index_cache_time.get(symbol, 0)) < 300:
            return self._index_cache[symbol]

        # Respect backoff window after a 429
        last_attempt = self._index_last_attempt.get(symbol, 0)
        backoff = self._index_backoff.get(symbol, 60)
        if (now - last_attempt) < backoff:
            return self._index_cache.get(symbol)
        self._index_last_attempt[symbol] = now

        today = datetime.now(IST).strftime("%Y-%m-%d")
        data = {
            "symbol": symbol,
            "resolution": "5",
            "date_format": "1",
            "range_from": today,
            "range_to": today,
            "cont_flag": "1",
        }

        try:
            from shortcircuit.broker.rest_limiter import rest_limiter

            rest_limiter.acquire()
            response = self.fyers.history(data=data)
            status = response.get("s") if isinstance(response, dict) else "INVALID"
            candles = response.get("candles") if isinstance(response, dict) else None
            if status == "ok" and candles:
                self._index_cache[symbol] = candles
                self._index_cache_time[symbol] = now
                self._index_backoff[symbol] = 60
                logger.info(
                    "[MarketContext] ✅ Index cache refreshed: %s | %d candles | latest=%s",
                    symbol,
                    len(candles),
                    candles[-1][4] if candles else "N/A",
                )
                return candles
            else:
                code = response.get("code") if isinstance(response, dict) else "N/A"
                msg = (
                    response.get("message", response.get("errmsg", ""))
                    if isinstance(response, dict)
                    else str(response)[:100]
                )
                if code == 429 or "limit" in str(msg).lower():
                    self._index_backoff[symbol] = 300
                    logger.warning(
                        "[MarketContext] ⚠️ Index 429 rate-limited: %s — backing off 300s. Using stale cache.",
                        symbol,
                    )
                else:
                    self._index_backoff[symbol] = 60
                    logger.error(
                        "[MarketContext] ❌ Index fetch failed: symbol=%s status=%s code=%s msg=%s",
                        symbol,
                        status,
                        code,
                        msg,
                    )
        except Exception as e:
            logger.error("[MarketContext] ❌ Index fetch exception: symbol=%s error=%s", symbol, e)

        stale = self._index_cache.get(symbol)
        if stale:
            logger.warning(
                "[MarketContext] Using stale index cache for %s (%d candles)", symbol, len(stale)
            )
        return stale

    def get_volume_z_score(self, df: pd.DataFrame) -> float:
        """
        Calculates the volume Z-score for the current 1m candle
        relative to the morning session mean/std.
        """
        if df is None or len(df) < 10:
            return 0.0

        # Get morning session volumes (all candles in df)
        vols = df["volume"]
        if len(vols) < 2:
            return 0.0

        mean_v = vols.mean()
        std_v = vols.std()

        if std_v == 0:
            return 0.0

        current_v = vols.iloc[-1]
        z_score = (current_v - mean_v) / std_v
        return z_score

    def is_safe_trade_window(self) -> tuple[bool, str]:
        """
        Market Regime + Time Filters.
        Returns: (allowed, reason)
        """
        now_ist = datetime.now(IST).time()

        # 1. TIME GATE: Pre-Market Noise
        if now_ist < time(9, 30):
            return False, "BLOCKED: Pre-Market Noise (before 09:30)"

        # 2. TIME GATE: EOD Cutoff
        if now_ist >= time(15, 10):
            return False, "BLOCKED: EOD Cutoff (after 15:10)"

        if getattr(config, "ENABLE_MARKET_REGIME_FILTER", True) is False:
            # FIXED: still compute and update the regime label for ML logging,
            # even though the filter is disabled as a gate.
            candles_for_label = self._get_index_data_cached(self.nifty_symbol)
            if candles_for_label and self.morning_range_valid:
                current_close = candles_for_label[-1][4]
                conf = config.MARKET_REGIME_CONFIG
                move_pct = (current_close - self._morning_high) / self._morning_high
                new_regime = "RANGE"
                if move_pct > conf["strong_trend_threshold"]:
                    new_regime = "TREND_UP"
                elif move_pct < -0.005:
                    new_regime = "TREND_DOWN"
                if new_regime != self.last_regime:
                    self.last_regime = new_regime
                    self.regime_change_time = datetime.now()
                    logger.info(
                        f"📊 REGIME UPDATE (filter disabled): {new_regime} | Move: {move_pct:.2%}"
                    )
            return True, "OK [G7]: Market Regime Filter Disabled"

        # 3. REGIME DETECTION: Nifty Trend
        candles = self._get_index_data_cached(self.nifty_symbol)
        cache_age = _time.time() - self._index_cache_time.get(self.nifty_symbol, 0)
        if not candles or cache_age > 900:
            # FIXED: fail-closed — block NEW entries when index data is unavailable/stale.
            # A false block = a few missed trades (bounded, recoverable).
            # A false allow during a hard Nifty trend = unbounded tail risk.
            # NOTE: This never force-closes existing positions.
            logger.warning(
                "[MarketContext] ⚠️ G7 FAIL-CLOSED: index data unavailable or stale (%.0fs old). Blocking new entries.",
                cache_age if candles else 0.0,
            )
            return False, "BLOCKED [G7]: Index data unavailable/stale — fail closed for new shorts"

        self._refresh_morning_range_if_needed()
        if not self.morning_range_valid:
            return False, "BLOCKED [G7]: Morning range unavailable"

        current_close = candles[-1][4]
        conf = config.MARKET_REGIME_CONFIG
        move_pct = (current_close - self._morning_high) / self._morning_high

        # Update Internal Regime State for logging
        new_regime = "RANGE"
        if move_pct > conf["strong_trend_threshold"]:
            new_regime = "TREND_UP"
        elif move_pct < -0.005:
            new_regime = "TREND_DOWN"

        if new_regime != self.last_regime:
            self.last_regime = new_regime
            self.regime_change_time = datetime.now()
            logger.info(f"📊 REGIME CHANGE: {new_regime} | Move: {move_pct:.2%}")

        # STRONG TREND (>1.5%) -> Hard Block
        if move_pct > conf["strong_trend_threshold"]:
            return False, f"BLOCKED [G7]: Strong Trend Up (+{move_pct:.2%})"

        # 4. DEFAULT: Range Day or Trend Down
        return True, "OK [G7]: Market in Range / Trend Down"

    def get_trend_label(self) -> str:
        """Returns the current regime label for ML logging."""
        return getattr(self, "last_regime", "UNKNOWN")

    # G3 circuit-hitter methods

    def mark_circuit_touched(self, symbol: str):
        """
        Mark a symbol as having touched circuit limits.
        Phase 51 [G3]: Session-permanent block.
        """
        self._refresh_circuit_blacklist_if_needed()
        self._circuit_touched_today.add(symbol)
        logger.warning(
            f"[G3] Symbol {symbol} marked as CIRCUIT HITTER. Blacklisted for remainder of session."
        )

    def is_circuit_hitter(self, symbol: str) -> bool:
        """
        Check if symbol is currently blacklisted due to circuit touch.
        Phase 51 [G3]: Session-permanent block.
        """
        self._refresh_circuit_blacklist_if_needed()
        return symbol in self._circuit_touched_today

    def _refresh_circuit_blacklist_if_needed(self):
        """Resets the circuit blacklist if a new day has started."""
        today = datetime.now(IST).date()
        if self._circuit_blacklist_date != today:
            self._circuit_touched_today.clear()
            self._circuit_blacklist_date = today
            logger.info("[G3] Daily Circuit Blacklist cleared for new session.")
