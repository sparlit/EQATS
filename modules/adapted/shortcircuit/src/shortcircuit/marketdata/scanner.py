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


import contextlib
import logging
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from concurrent.futures import (
    TimeoutError as FutureTimeout,
)

import pandas as pd
from shortcircuit import config
from shortcircuit.broker.fyers_connect import FyersConnect
from shortcircuit.broker.rest_limiter import rest_limiter

logger = logging.getLogger(__name__)

# Long-lived pools. Deliberately NOT used as context managers: ThreadPoolExecutor
# .__exit__ calls shutdown(wait=True), which blocks on exactly the hung task the
# surrounding timeout was written to escape. See the 2026-07-29 session, where 41
# slow /history calls each stalled a scan ~80s past its own 8s cap and produced 41
# blind scan cycles.
_QUALITY_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(4, getattr(config, "SCANNER_PARALLEL_WORKERS", 3)),
    thread_name_prefix="scan-quality",
)
_HISTORY_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="scan-history")


class FyersScanner:
    def __init__(self, fyers, broker=None):
        self.fyers = fyers
        self.broker = broker
        self.symbols = {}  # Cache for symbols
        # NOTE: Do NOT use TYPO_PATCHES to suppress symbols.
        # Zero-volume symbols are handled by quality_reject_counts blacklist.
        # Both NSE:AKASH-EQ and NSE:AAKASH-EQ are separate listed entities.
        self.quality_reject_counts = {}  # Track 0-volume rejects

    def fetch_nse_symbols(self):
        """
        Downloads NSE Equity Master list and filters for EQ series.
        """
        try:
            # Fyers publishes the NSE cash symbol master as a CSV.
            url = "https://public.fyers.in/sym_details/NSE_CM.csv"

            # Columns (Official Fyers V3 Spec):
            # 0:Exch, 1:SymbolDesc, 2:SymbolDetails, 3:LotSize, 4:MinTick, 5:ISIN, 6:TradingSession, 7:LastUpdate, 8:Expiry, 9:Symbol, 10:Price, 11:ExchangeToken, 12:TickSize, 13:SymbolRoot
            # Actually, standard layout varies. We will robustly find the '-EQ' symbol and 'MinTick' (Col 4 or 12).

            df = pd.read_csv(url, header=None)

            candidates = {}  # Map Symbol -> TickSize

            # Index 9 is usually the Symbol (NSE:SBIN-EQ). Index 4 is MinTick (0.05).
            # Let's verify by iterating.

            for _index, row in df.iterrows():
                # Finding the Symbol Column (usually col 9 or 13)
                symbol = str(row.get(9, ""))  # Try Col 9 first
                if not symbol.endswith("-EQ"):
                    symbol = str(row.get(13, ""))  # Try Col 13
                if not symbol.endswith("-EQ"):
                    symbol = str(row.get(13, ""))  # Try Col 13

                if symbol.startswith("NSE:") and symbol.endswith("-EQ"):
                    # Finding Tick Size (Col 4 or 12 or 2)
                    try:
                        tick = float(row.get(4, 0.05))  # Col 4 is often MinTick
                        if tick == 0:
                            tick = 0.05
                    except:
                        tick = 0.05

                    candidates[symbol] = tick

            logger.info(f"Loaded {len(candidates)} Equity Symbols with Tick Sizes.")
            return candidates  # Returns Dict {Symbol: Tick}

        except Exception as e:
            logger.error(f"Error fetching NSE symbols: {e}")
            return []

    def _fetch_nse_symbols_sync(self):
        """
        Synchronous version of fetch_nse_symbols for Phase 44.7 startup.
        Uses requests to avoid asyncio loop locking in run_in_executor.
        """
        import requests

        try:
            url = "https://public.fyers.in/sym_details/NSE_CM.csv"
            response = requests.get(url, timeout=10)

            candidates = []
            if response.status_code == 200:
                lines = response.text.splitlines()
                for line in lines:
                    cols = line.split(",")
                    if len(cols) > 9:
                        sym = cols[9].strip()
                        if not sym.endswith("-EQ") and len(cols) > 13:
                            sym = cols[13].strip()
                        if sym.startswith("NSE:") and sym.endswith("-EQ"):
                            candidates.append(sym)

            logger.info(f"Loaded {len(candidates)} NSE EQ symbols synchronously.")
            return candidates
        except Exception as e:
            logger.error(f"Error fetching NSE symbols sync: {e}")
            return []

    def check_chart_quality(self, symbol):
        """
        Microstructure Filter: Rejects 'gappy' or 'illiquid' charts.
        Logic: Checks last 60 mins (1min candles).
        - Rejects if > 50% candles have 0 volume (truly illiquid).
        - Rejects if > 50% candles are 'Doji' (body < 0.1% of price).
        - PASSES if insufficient data (don't reject liquid stocks due to API lag).
        """
        try:
            # No local import needed anymore
            import datetime as _dt

            # Define date vars at top — needed by both 1m REST fallback and 15m fetch
            today = _dt.date.today()
            five_back = today - _dt.timedelta(days=5)

            # Local Candle Engine
            candles = None
            if getattr(config, "P82_LOCAL_CANDLES_ENABLED", False) and self.broker:
                n_bars = max(100, getattr(config, "RVOL_MIN_CANDLES", 15) + 5)
                local_data = self.broker.get_local_candles(symbol, n=n_bars)
                if local_data and len(local_data) >= getattr(config, "RVOL_MIN_CANDLES", 15):
                    candles = [
                        [c.epoch, c.open, c.high, c.low, c.close, c.volume] for c in local_data
                    ]

            if not candles:
                # Fallback to REST history
                data = {
                    "symbol": symbol,
                    "resolution": "1",
                    "date_format": "1",  # "1" = YYYY-MM-DD (Fyers v3 requirement)
                    "range_from": five_back.strftime(
                        "%Y-%m-%d"
                    ),  # 5 days back for early-morning coverage
                    "range_to": today.strftime("%Y-%m-%d"),
                    "cont_flag": "1",
                }
                rest_limiter.acquire()  # Global rate limiter — respect 10 req/sec Fyers limit
                response = self.fyers.history(data=data)
                candles = response.get("candles", [])

                if not candles:
                    # One-shot per session
                    if not hasattr(self, "_candle_debug_done"):
                        logger.info(
                            f"[CANDLE DEBUG] {symbol} → status={response.get('s')} | bars=0"
                        )
                        self._candle_debug_done = True
                    logger.warning(f"SKIP {symbol} — Insufficient candle data (0). Blocking.")
                    return False, None, None

            # One-shot per session; scaffolding, safe to remove.
            if not hasattr(self, "_candle_debug_done"):
                logger.info(f"[CANDLE DEBUG] {symbol} → bars={len(candles)}")
                self._candle_debug_done = True

            # Check Time: If < 10:00 AM, we won't have many candles (Market opens 09:15)
            # No local import needed anymore
            now_dt = _dt.datetime.now()
            is_early_morning = now_dt.hour < 10

            # RVOL validity gate — replaces is_early_morning heuristic
            # RVOL calculation requires minimum 20 candles (iloc[-20:-2])
            # Market opens 9:15 AM IST → earliest valid signal: 9:35 AM
            _mins_open = config.minutes_since_market_open()
            _rvol_valid = _mins_open >= config.RVOL_MIN_CANDLES  # 20 minutes from open

            if config.RVOL_VALIDITY_GATE_ENABLED:
                if not _rvol_valid:
                    logger.warning(
                        f"SKIP {symbol} — RVOL_VALIDITY_GATE: {_mins_open:.1f} min since open — need {config.RVOL_MIN_CANDLES} min for valid RVOL. Skip."
                    )
                    return False, None, None
                # Candle count: keep as absolute floor for API data integrity only
                min_candles = 10  # No longer varies by time — cliff-edge removed
            else:
                # Rollback to pre-PRD heuristic behavior
                min_candles = 5 if is_early_morning else 10

            if len(candles) >= min_candles:
                total = len(candles)
                zero_vol = 0

                for c in candles:
                    v = c[5]  # volume

                    if v == 0:
                        zero_vol += 1

                zero_vol_ratio = zero_vol / total

                # Threshold 1: If > 50% have zero volume, it's illiquid/choppy
                if zero_vol_ratio > 0.5:
                    reject_pct = int(zero_vol_ratio * 100)
                    logger.warning(
                        f"[SKIP] Quality Reject (Liquid): {symbol} | Zero Volume: {reject_pct}%"
                    )
                    self.quality_reject_counts[symbol] = (
                        self.quality_reject_counts.get(symbol, 0) + 1
                    )
                    return False, None, None

                # Candle body ratio: mean(body/range) over the last 10 candles,
                # which rejects choppy, wick-heavy charts.
                try:
                    recent_candles = candles[-10:]
                    ratios = []
                    for c in recent_candles:
                        o, h, l, cl = c[1], c[2], c[3], c[4]
                        candle_range = h - l
                        body = abs(cl - o)
                        if candle_range > 0:
                            ratios.append(body / candle_range)
                        else:
                            ratios.append(0)

                    avg_body_ratio = sum(ratios) / len(ratios) if ratios else 0
                    min_ratio = getattr(config, "CANDLE_BODY_RATIO_MIN", 0.25)

                    if avg_body_ratio < min_ratio:
                        logger.warning(
                            f"[SKIP] Quality Reject (Dirty): {symbol} | Avg Body Ratio: {avg_body_ratio:.2f} < {min_ratio}"
                        )
                        self.quality_reject_counts[symbol] = (
                            self.quality_reject_counts.get(symbol, 0) + 1
                        )
                        return False, None, None

                except Exception as e:
                    logger.warning(f"Error calculating body ratio for {symbol} (non-fatal): {e}")

                # Return Success AND the Dataframe (Reuse Strategy)
                cols = ["epoch", "open", "high", "low", "close", "volume"]
                df = pd.DataFrame(candles, columns=cols)
                df["datetime"] = (
                    pd.to_datetime(df["epoch"], unit="s")
                    .dt.tz_localize("UTC")
                    .dt.tz_convert("Asia/Kolkata")
                )

                # Pre-fetch 15m candles for G9 trend exhaustion
                # Add timeout protection — slow 15m fetch was causing 90s scan timeout
                df_15m = None
                try:
                    today_str = today.strftime("%Y-%m-%d")
                    five_back_str = five_back.strftime("%Y-%m-%d")
                    data_15m = {
                        "symbol": symbol,
                        "resolution": "15",
                        "date_format": "1",
                        "range_from": five_back_str,
                        "range_to": today_str,
                        "cont_flag": "1",
                    }
                    # Shared, long-lived pool — never a `with ThreadPoolExecutor`,
                    # whose __exit__ calls shutdown(wait=True) and so waits out the
                    # very call the 8s cap just abandoned. On 2026-07-29 that turned
                    # 41 slow /history calls into 41 scans over the 90s ceiling.
                    rest_limiter.acquire()
                    _f = _HISTORY_EXECUTOR.submit(self.fyers.history, data_15m)
                    try:
                        resp_15m = _f.result(timeout=8)
                        if resp_15m and resp_15m.get("s") == "ok" and resp_15m.get("candles"):
                            df_15m = pd.DataFrame(resp_15m["candles"], columns=cols)
                            df_15m["datetime"] = (
                                pd.to_datetime(df_15m["epoch"], unit="s")
                                .dt.tz_localize("UTC")
                                .dt.tz_convert("Asia/Kolkata")
                            )
                    except FutureTimeout:
                        # Abandon it; the worker is bounded by the HTTP read timeout.
                        _f.cancel()
                        logger.debug(
                            f"15m fetch timed out for {symbol} — skipping HTF (G9 fail-closed)"
                        )
                except Exception as e:
                    logger.warning(f"Failed to fetch 15m candles for {symbol}: {e}")

                return True, df, df_15m

            # Hard block 0-candle data instead of allowing
            logger.warning(f"SKIP {symbol} — Insufficient candle data ({len(candles)}). Blocking.")
            return False, None, None

        except Exception as e:
            logger.error(f"Quality Check Error {symbol}: {e}")
            return True, None, None  # PASS on error (fail-open)

    def scan_market(self):
        """
        Main Scan Logic (Phase 41.1 — Parallel fetch).
        1. Get Symbols
        2. Batch Request Quotes (50 at a time)
        3. Filter (Gain 6-18%, Vol > 100k, LTP > 5)
        4. Parallel fetch history + quality check for all candidates
        """
        # DEGRADED MODE scan banner (fires every 10 scans while WS is severely degraded)
        if hasattr(self, "broker") and self.broker.is_cache_severely_degraded():
            scan_num = self.broker.increment_degraded_scan_count()
            if scan_num % 10 == 0:
                recovery_attempts = self.broker._consecutive_reprime_failures
                logger.warning(
                    f"⚠️ SESSION DEGRADED MODE — Scan #{scan_num} running on stale REST data. "
                    f"Signal quality compromised. WS recovery attempt {recovery_attempts}/3. "
                    f"Consider restarting if this persists."
                )
        else:
            # Reset banner count when recovered
            if hasattr(self, "broker") and getattr(self.broker, "_degraded_scan_count", 0) > 0:
                self.broker.reset_degraded_scan_count()

        # Executors and concurrent.futures helpers are module-level now.

        if not self.symbols:
            self.symbols = self.fetch_nse_symbols()
            if not self.symbols:
                return []

        # Batching (Symbols is now a Dict)
        symbol_list = list(self.symbols.keys())  # EXTRACT KEYS
        pre_candidates = []  # Pass gain/volume/price filter, pending quality

        # Tiered Data Provider
        import time as _time

        scan_start_ms = _time.monotonic() * 1000

        # Increment scan counter (module-level for log correlation)
        if not hasattr(self, "_scan_counter"):
            self._scan_counter = 0
        self._scan_counter += 1
        scan_id = self._scan_counter

        data_tier = "REST_EMERGENCY"  # Will be overridden below

        if self.broker and hasattr(self.broker, "is_cache_ready") and self.broker.is_cache_ready():
            # Tier 1: Full WS Cache
            snapshot = self.broker.get_quote_cache_snapshot()
            fresh = {}
            stale_symbols = []

            for symbol in symbol_list:
                quote = snapshot.get(symbol)
                if quote is None:
                    stale_symbols.append(symbol)
                    continue
                age_s = _time.time() - quote.get("ts", 0)
                source = quote.get("source")
                if source != "ws" or age_s > config.WS_TICK_FRESHNESS_TTL_SECONDS:
                    stale_symbols.append(symbol)
                else:
                    fresh[symbol] = quote

            snap = self.broker.cache_health_snapshot()
            total = max(snap.get("total") or len(symbol_list), 1)
            fresh_pct = snap.get("fresh", 0) / total
            known_pct = (
                snap.get("fresh", 0) + snap.get("stale", 0) + snap.get("seeded", 0)
            ) / total

            if fresh_pct >= 0.85:
                # Pure Tier 1
                data_tier = "WS_CACHE"
                # Use full snapshot (fresh + stale) to avoid missing consolidated stocks
                all_quotes = snapshot

            elif known_pct >= 0.90:
                # Tier 2: HYBRID — supplement only stale/missing symbols via REST
                data_tier = "HYBRID"
                logger.warning(
                    f"[WS Cache] Tier 2 HYBRID: {len(stale_symbols)} symbols stale/missing "
                    f"(WS fresh: {snap.get('fresh')}/{snap.get('total')}, known: {known_pct:.1%}). "
                    f"Supplementing via REST."
                )
                all_quotes = dict(fresh)
                # REST supplement for stale symbols only
                batch_size = 50
                for i in range(0, len(stale_symbols), batch_size):
                    batch = stale_symbols[i : i + batch_size]
                    try:
                        logger.debug(
                            f"[Tier 2] Fetching REST quotes for batch of {len(batch)} symbols..."
                        )
                        data = {"symbols": ",".join(batch)}
                        response = self.fyers.quotes(data=data)
                        if "d" in response:
                            logger.debug(
                                f"[Tier 2] Received {len(response['d'])} quotes from REST."
                            )
                            for stock in response["d"]:
                                quote_data = stock.get("v")
                                if not isinstance(quote_data, dict):
                                    continue
                                sym = stock.get("n")
                                ltp = quote_data.get("lp", 0)
                                volume = quote_data.get("v", quote_data.get("volume", 0))
                                chp = quote_data.get("chp", 0)
                                if sym:
                                    all_quotes[sym] = {
                                        "ltp": ltp,
                                        "volume": volume,
                                        "ch_oc": chp,
                                        "oi": quote_data.get("oi", 0),
                                        "pc": quote_data.get(
                                            "pc", quote_data.get("prev_close_price", 0)
                                        ),
                                        "ts": _time.time(),
                                    }
                    except Exception as e:
                        logger.error(f"[Tier 2] REST supplement batch error: {e}")

            else:
                # Tier 3: REST EMERGENCY — cache too degraded
                data_tier = "REST_EMERGENCY"
                logger.critical(
                    f"[WS Cache] TIER 3 REST EMERGENCY: fresh={fresh_pct:.1%} "
                    f"known={known_pct:.1%} ({snap.get('fresh')}/{snap.get('total')} fresh, "
                    f"{snap.get('seeded', 0)} seeded). Full REST fallback. INVESTIGATE IMMEDIATELY."
                )
                if hasattr(self, "_bot_alert_fn") and self._bot_alert_fn:
                    with contextlib.suppress(Exception):
                        self._bot_alert_fn(
                            f"⚠️ WS CACHE FAILURE\nFresh: {snap.get('fresh')}/{snap.get('total')} ({fresh_pct:.1%})\n"
                            f"Known: {known_pct:.1%} | Seeded: {snap.get('seeded', 0)}\n"
                            "Falling back to full REST. Signals degraded."
                        )
                all_quotes = {}  # Will REST-fill below

            # Build pre_candidates from all_quotes (Tier 1 and 2)
            if data_tier in ("WS_CACHE", "HYBRID"):
                for symbol, quote in all_quotes.items():
                    ltp = quote.get("ltp", 0)
                    volume = quote.get("volume", 0)
                    gain = quote.get("ch_oc", 0)
                    oi = quote.get("oi", 0)

                    if (
                        gain >= config.SCANNER_GAIN_MIN_PCT
                        and gain <= config.SCANNER_GAIN_MAX_PCT
                        and volume >= config.SCANNER_MIN_VOLUME
                        and ltp >= config.SCANNER_MIN_LTP
                    ):
                        if self.quality_reject_counts.get(symbol, 0) >= 3:
                            logger.debug(
                                f"BLACKLIST {symbol} — Quality rejected 3x today, skipping."
                            )
                            continue

                        tick_size = self.symbols.get(symbol, 0.05)
                        pre_candidates.append(
                            {
                                "symbol": symbol,
                                "ltp": ltp,
                                "volume": volume,
                                "change": gain,
                                "tick_size": tick_size,
                                "oi": oi,
                            }
                        )

            # Elapsed for tier 1/2
            if data_tier in ("WS_CACHE", "HYBRID"):
                tier_ms = int((_time.monotonic() * 1000) - scan_start_ms)
                logger.info(
                    f"SCAN #{scan_id} | Tier: {data_tier} | "
                    f"Cache: {len(fresh)}/{len(symbol_list)} fresh | "
                    f"Scan_ms: {tier_ms} | Pre-candidates: {len(pre_candidates)}"
                )

        if data_tier == "REST_EMERGENCY" or not (
            self.broker and hasattr(self.broker, "is_cache_ready")
        ):
            # Tier 3 / No-broker fallback: original REST batch path
            if self.broker:
                # Already logged CRITICAL above; just do the REST scan
                pass
            else:
                logger.warning("[WS Cache] No broker configured — using REST batch scan")
            data_tier = "REST_EMERGENCY"

            batch_size = 50
            total_symbols = len(symbol_list)
            logger.info(f"Scanning {total_symbols} symbols in batches via REST...")

            for i in range(0, total_symbols, batch_size):
                batch = symbol_list[i : i + batch_size]
                symbols_str = ",".join(batch)

                try:
                    data = {"symbols": symbols_str}
                    response = self.fyers.quotes(data=data)

                    if "d" not in response:
                        continue

                    for stock in response["d"]:
                        quote_data = stock.get("v")
                        if not isinstance(quote_data, dict):
                            continue

                        symbol = stock.get("n")
                        ltp = quote_data.get("lp")
                        volume = quote_data.get("v", quote_data.get("volume", 0))
                        change_p = quote_data.get("chp")

                        if ltp is None or volume is None or change_p is None:
                            continue

                        if (
                            config.SCANNER_GAIN_MIN_PCT <= change_p <= config.SCANNER_GAIN_MAX_PCT
                            and volume > config.SCANNER_MIN_VOLUME
                            and ltp > config.SCANNER_MIN_LTP
                        ):
                            if self.quality_reject_counts.get(symbol, 0) >= 3:
                                logger.debug(
                                    f"BLACKLIST {symbol} — Quality rejected 3x today, skipping history fetch."
                                )
                                continue

                            tick_size = self.symbols.get(symbol, 0.05)
                            oi = quote_data.get("oi", 0)
                            pre_candidates.append(
                                {
                                    "symbol": symbol,
                                    "ltp": ltp,
                                    "volume": volume,
                                    "change": change_p,
                                    "tick_size": tick_size,
                                    "oi": oi,
                                }
                            )
                except Exception as e:
                    logger.error(f"Batch Error: {e}")

            tier_ms = int((_time.monotonic() * 1000) - scan_start_ms)
            logger.info(
                f"SCAN #{scan_id} | Tier: REST_EMERGENCY | Cache: FAILED | "
                f"Scan_ms: {tier_ms} | Pre-candidates: {len(pre_candidates)}"
            )

        # Store tier for main.py gate audit trail correlation
        self._last_data_tier = data_tier

        if not pre_candidates:
            logger.info("No pre-candidates passed filter.")
            return []

        # ETF CLUSTER DEDUPLICATION (Section 7)
        # Silver ETFs (and future: GOLD, NIFTY) often fire simultaneously.
        # Keep highest-volume member per cluster, suppress duplicates.
        if getattr(config, "ETF_CLUSTER_DEDUP_ENABLED", False):
            cluster_keywords = getattr(config, "ETF_CLUSTER_KEYWORDS", [])
            for keyword in cluster_keywords:
                keyword_upper = keyword.upper()
                cluster = [c for c in pre_candidates if keyword_upper in c["symbol"].upper()]
                if len(cluster) > 1:
                    # Sort by volume descending, keep the top one
                    cluster.sort(key=lambda x: x["volume"], reverse=True)
                    keeper = cluster[0]
                    suppressed = cluster[1:]
                    suppressed_syms = [c["symbol"] for c in suppressed]

                    # Remove suppressed from pre_candidates
                    pre_candidates = [c for c in pre_candidates if c not in suppressed]

                    logger.info(
                        f"[DEDUP] {keyword} cluster: kept {keeper['symbol']} "
                        f"(vol={keeper['volume']:,}), suppressed {len(suppressed)}: "
                        f"{', '.join(suppressed_syms)}"
                    )

        logger.info(
            f"Pre-filter: {len(pre_candidates)} candidates. Starting parallel quality check..."
        )

        # MIS leverage screen. Runs before the quality checks, which each fetch
        # history: on 2026-08-31 it dropped 10 of 22 candidates before any fetch.
        # Readings cache per symbol per session, so it costs one call per NEW
        # symbol.
        #
        # Fails OPEN by construction — an unknown reading (None) is kept, and a
        # wall-clock budget lets the remainder through unscreened. A broken or
        # slow lookup must never empty the funnel or eat main.py's 90s scan
        # timeout; that is what tore out the previous leverage gate (cd178cc).
        min_lev = getattr(config, "SCANNER_MIN_LEVERAGE", 0.0)
        if min_lev > 0 and self.broker and hasattr(self.broker, "get_symbol_leverage_sync"):
            budget_s = getattr(config, "SCANNER_LEVERAGE_BUDGET_SECONDS", 15.0)
            started = time.monotonic()
            kept, dropped, unscreened = [], [], 0
            for c in pre_candidates:
                lev = None
                if time.monotonic() - started < budget_s:
                    try:
                        lev = self.broker.get_symbol_leverage_sync(c["symbol"], c.get("ltp") or 0)
                    except Exception as e:
                        logger.warning(
                            "[LEVERAGE] lookup raised for %s: %s — allowing through", c["symbol"], e
                        )
                else:
                    unscreened += 1
                if lev is not None and lev < min_lev:
                    dropped.append(f"{c['symbol'].replace('NSE:', '').replace('-EQ', '')}({lev}x)")
                    continue
                c["leverage"] = lev
                kept.append(c)
            if dropped:
                logger.info(
                    "[LEVERAGE] dropped %d/%d below %.1fx (no intraday margin): %s",
                    len(dropped),
                    len(pre_candidates),
                    min_lev,
                    ", ".join(dropped[:12]),
                )
            if unscreened:
                logger.warning(
                    "[LEVERAGE] %.0fs budget spent — %d symbol(s) passed through unscreened",
                    budget_s,
                    unscreened,
                )
            pre_candidates = kept

        # Phase B: Parallel history + quality check
        filtered_candidates = []
        getattr(config, "SCANNER_PARALLEL_WORKERS", 3)
        candidates_map = {c["symbol"]: c for c in pre_candidates}

        def fetch_quality(symbol):
            """Fetch history + quality for a single symbol."""
            return self.check_chart_quality(symbol)

        # Shared pool, and NOT a context manager — see the 15m-fetch note above.
        # `with` here would shutdown(wait=True) on exit and block on every
        # still-running quality check, re-introducing the same unbounded stall at
        # the outer level.
        futures = {
            _QUALITY_EXECUTOR.submit(fetch_quality, c["symbol"]): c["symbol"]
            for c in pre_candidates
        }
        logger.debug(f"Submitted {len(futures)} quality check tasks to ThreadPool.")

        # Hard ceiling for the whole batch, comfortably inside main.py's 90s
        # scan timeout so a slow batch degrades to "fewer candidates" instead of
        # "no candidates at all".
        try:
            completed = as_completed(futures, timeout=45)
            for future in completed:
                symbol = futures[future]
                try:
                    is_good, df, df_15m = future.result(timeout=1)
                    if is_good:
                        c = candidates_map[symbol]
                        c["history_df"] = df
                        c["history_df_15m"] = df_15m  # Phase 51

                        # 'leverage' is set by the MIS screen above and is None
                        # when the lookup could not answer. It used to default to
                        # 1.0, which printed "Lev: 1.0x" against every candidate
                        # in the session log whether or not anything had been
                        # measured — a reading that looked alarming and meant
                        # nothing.
                        _lev = c.get("leverage")
                        leverage = f"{_lev}" if _lev is not None else "?"
                        logger.info(
                            f"[CANDIDATE] {c['symbol']} | "
                            f"Gain: {c['change']}% | "
                            f"Vol: {c['volume']:,} | "
                            f"Lev: {leverage}x | "
                            f"Tick: {c['tick_size']} | OI: {c['oi']}"
                        )
                        filtered_candidates.append(c)
                except Exception as e:
                    logger.error(f"Error in parallel quality check for {symbol}: {e}")
        except FutureTimeout:
            done = len(filtered_candidates)
            stragglers = [s for f, s in futures.items() if not f.done()]
            for f in futures:
                if not f.done():
                    f.cancel()
            logger.warning(
                "Quality-check batch hit its 45s ceiling — proceeding with %d/%d "
                "candidates. Still pending: %s",
                done,
                len(futures),
                ", ".join(stragglers[:5]) or "none",
            )

        # Sort by Change % Descending
        filtered_candidates.sort(key=lambda x: x["change"], reverse=True)
        top_gainers = filtered_candidates[:20]

        logger.info(f"Scan Complete. Found {len(filtered_candidates)} candidates.")

        return top_gainers


if __name__ == "__main__":
    # Test Scanner
    try:
        fyers_obj = FyersConnect().authenticate()
        scanner = FyersScanner(fyers_obj)
        candidates = scanner.scan_market()
        print("Candidates:", candidates)
    except Exception as e:
        print(e)
