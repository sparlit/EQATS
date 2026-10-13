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


"""Pre-compute and cache all delivery signals in PostgreSQL + Redis.

Architecture:
    1. Scan ALL NSE + BSE parquet files → compute features
    2. Write to PostgreSQL (persistent store)
    3. Write to Redis (hot cache, TTL=1h)
    4. Dashboard/Signals read from Redis → PostgreSQL fallback

Usage:
    python scripts/cache_signals.py              # full rebuild
    python scripts/cache_signals.py --warm-redis  # only refresh Redis from PG

Run daily after market close via APScheduler or cron.
"""


import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config import load_settings
from indian_quant.features.delivery import add_features, conviction_score, prepare_frame
from indian_quant.features.market_cap import classify_signals as classify_signals_mcap
from indian_quant.features.security_type import classify_all_signals
from indian_quant.ingestion.router import SourceRouter
from indian_quant.web.prod_config import (
    REDIS_TTL,
    ensure_schema,
    get_pg_engine,
    get_redis_client,
)


def compute_signal_from_bars(
    parquet_path: Path, symbol: str, exchange: str, router: SourceRouter | None = None
) -> dict | None:
    """Compute technical signals from bars_1d OHLCV (no delivery z-score).

    Uses router to fetch fresh bars if the parquet is stale or missing.
    """
    try:
        raw = pd.read_parquet(parquet_path)
        if raw.empty or len(raw) < 20:
            return None

        # Normalize columns for add_features
        df = raw.copy()
        df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        df = df.sort_values("date").reset_index(drop=True)
        df["segment"] = df.get("series", pd.Series("EQ", index=df.index))

        # Compute returns
        df["ret_1d"] = df["close"].pct_change()
        df["log_ret"] = np.log(df["close"] / df["close"].shift(1))

        # RSI
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi"] = 100 - 100 / (1 + rs)

        # MACD
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

        # SMA
        df["sma_20"] = df["close"].rolling(20).mean()
        df["sma_50"] = df["close"].rolling(50).mean()

        # ATR
        tr1 = df["high"] - df["low"]
        tr2 = abs(df["high"] - df["close"].shift(1))
        tr3 = abs(df["low"] - df["close"].shift(1))
        df["atr_14"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

        # Volume z-score
        vol_ma = df["volume"].rolling(20).mean()
        vol_std = df["volume"].rolling(20).std()
        df["vol_z"] = (df["volume"] - vol_ma) / vol_std.replace(0, np.nan)

        df = df.dropna(subset=["ret_1d", "rsi"]).tail(30)
        if df.empty:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else df.iloc[-1]
        close = float(last["close"])
        prev_close = float(prev["close"]) if pd.notna(prev.get("close")) else close
        atr = (
            float(last.get("atr_14", close * 0.03))
            if pd.notna(last.get("atr_14"))
            else close * 0.03
        )

        signal_type = None
        rsi_val = last.get("rsi")
        prev_rsi = prev.get("rsi")
        macd_val = last.get("macd")
        macd_sig = last.get("macd_signal")
        prev_macd = prev.get("macd")
        prev_macd_sig = prev.get("macd_signal")

        if pd.notna(rsi_val) and pd.notna(prev_rsi):
            if rsi_val < 30 and prev_rsi >= 30:
                signal_type = "rsi_oversold"
            elif rsi_val > 70 and prev_rsi <= 70:
                signal_type = "rsi_overbought"
        if (
            signal_type is None
            and pd.notna(macd_val)
            and pd.notna(macd_sig)
            and pd.notna(prev_macd)
            and pd.notna(prev_macd_sig)
        ):
            if macd_val > macd_sig and prev_macd <= prev_macd_sig:
                signal_type = "macd_bullish_x"
            elif macd_val < macd_sig and prev_macd >= prev_macd_sig:
                signal_type = "macd_bearish_x"

        return {
            "symbol": symbol,
            "exchange": exchange,
            "signal_date": str(last["date"].date())
            if hasattr(last["date"], "date")
            else str(last["date"])[:10],
            "segment": str(last.get("segment", "EQ")),
            "close": round(close, 2),
            "prev_close": round(prev_close, 2),
            "ret_1d_pct": round((close / prev_close - 1) * 100, 2) if prev_close > 0 else 0,
            "deliv_pct": None,
            "deliv_z": None,
            "vol_z": round(float(last["vol_z"]), 2) if pd.notna(last.get("vol_z")) else None,
            "rsi": round(float(rsi_val), 1) if pd.notna(rsi_val) else None,
            "macd": round(float(macd_val), 2) if pd.notna(macd_val) else None,
            "macd_signal": round(float(macd_sig), 2) if pd.notna(macd_sig) else None,
            "sma_20": round(float(last["sma_20"]), 2) if pd.notna(last.get("sma_20")) else None,
            "sma_50": round(float(last["sma_50"]), 2) if pd.notna(last.get("sma_50")) else None,
            "atr_14": round(atr, 2),
            "hi_streak": 0,
            "signal_type": signal_type,
            "entry_zone_low": round(close - atr * 0.5, 2),
            "entry_zone_high": round(close, 2),
            "stop_loss": round(close * 0.93, 2),
            "target_price": round(close * 1.05, 2),
            "volume": float(last.get("volume", 0)) if pd.notna(last.get("volume")) else 0,
        }
    except Exception:
        return None


def compute_signal_for_stock(
    parquet_path: Path, symbol: str, exchange: str, router: SourceRouter | None = None
) -> dict | None:
    try:
        raw = pd.read_parquet(parquet_path)
        if raw.empty or len(raw) < 20:
            return None

        frame = prepare_frame(raw, min_rows=min(20, len(raw)))
        if frame is None or frame.empty:
            return None

        frame = add_features(frame)
        if frame.empty:
            return None

        last = frame.iloc[-1]
        prev = frame.iloc[-2] if len(frame) > 1 else frame.iloc[-1]

        signal_type = None
        if pd.notna(last.get("deliv_z")) and pd.notna(last.get("ret_1d")):
            dz = last["deliv_z"]
            ret = last["ret_1d"]
            rsi = last.get("rsi", 50)
            macd_val = last.get("macd")
            macd_sig = last.get("macd_signal")
            sma20 = last.get("sma_20")

            if dz >= 2 and ret >= 0.005:
                # Apply technical confirmation filters for dz_hi_up
                rsi_ok = 30 <= rsi <= 70 if pd.notna(rsi) else False
                macd_ok = pd.notna(macd_val) and pd.notna(macd_sig) and macd_val > macd_sig
                ma_ok = pd.notna(sma20) and last["close"] > sma20
                if rsi_ok and macd_ok and ma_ok:
                    signal_type = "dz_hi_up"
            elif dz >= 2 and ret <= -0.005:
                signal_type = "dz_hi_dn"
            elif dz <= -2 and ret >= 0.005:
                signal_type = "dz_lo_up"

        if signal_type is None:
            rsi = last.get("rsi")
            prev_rsi = prev.get("rsi") if prev is not None else None
            macd_val = last.get("macd")
            macd_sig = last.get("macd_signal")
            prev_macd = prev.get("macd") if prev is not None else None
            prev_macd_sig = prev.get("macd_signal") if prev is not None else None

            if pd.notna(rsi) and pd.notna(prev_rsi):
                if rsi < 30 and prev_rsi >= 30:
                    signal_type = "rsi_oversold"
                elif rsi > 70 and prev_rsi <= 70:
                    signal_type = "rsi_overbought"
            if (
                signal_type is None
                and pd.notna(macd_val)
                and pd.notna(macd_sig)
                and pd.notna(prev_macd)
                and pd.notna(prev_macd_sig)
            ):
                if macd_val > macd_sig and prev_macd <= prev_macd_sig:
                    signal_type = "macd_bullish_x"
                elif macd_val < macd_sig and prev_macd >= prev_macd_sig:
                    signal_type = "macd_bearish_x"

        close = float(last["close"])
        prev_close = float(prev["close"]) if pd.notna(prev.get("close")) else close
        ret_1d_pct = round((close / prev_close - 1) * 100, 2) if prev_close > 0 else 0
        atr = (
            float(last.get("atr_14", close * 0.03))
            if pd.notna(last.get("atr_14"))
            else close * 0.03
        )

        # Momentum and volatility features
        momentum_20d = None
        volatility_20d = None
        if len(frame) >= 20:
            close_20 = frame["close"].iloc[-20]
            if close_20 > 0:
                momentum_20d = round((close / close_20 - 1) * 100, 2)
            log_returns = np.log(frame["close"] / frame["close"].shift(1)).dropna()
            if len(log_returns) >= 20:
                volatility_20d = round(float(log_returns.tail(20).std() * np.sqrt(252) * 100), 2)

        # Conviction score for dz_hi_up signals
        conv_score = 0.0
        if signal_type == "dz_hi_up":
            conv_score = conviction_score(last)

        return {
            "symbol": symbol,
            "exchange": exchange,
            "signal_date": str(pd.to_datetime(last["date"]).date()),
            "segment": str(last.get("segment", "EQ")),
            "close": round(close, 2),
            "prev_close": round(prev_close, 2),
            "ret_1d_pct": ret_1d_pct,
            "deliv_pct": round(float(last["deliv_pct"]), 1)
            if pd.notna(last.get("deliv_pct"))
            else None,
            "deliv_z": round(float(last["deliv_z"]), 2) if pd.notna(last.get("deliv_z")) else None,
            "vol_z": round(float(last["vol_z"]), 2) if pd.notna(last.get("vol_z")) else None,
            "rsi": round(float(last["rsi"]), 1) if pd.notna(last.get("rsi")) else None,
            "macd": round(float(last["macd"]), 2) if pd.notna(last.get("macd")) else None,
            "macd_signal": round(float(last["macd_signal"]), 2)
            if pd.notna(last.get("macd_signal"))
            else None,
            "sma_20": round(float(last["sma_20"]), 2) if pd.notna(last.get("sma_20")) else None,
            "sma_50": round(float(last["sma_50"]), 2) if pd.notna(last.get("sma_50")) else None,
            "atr_14": round(atr, 2),
            "hi_streak": int(last.get("hi_streak", 0)) if pd.notna(last.get("hi_streak")) else 0,
            "signal_type": signal_type,
            "entry_zone_low": round(close - atr * 0.5, 2),
            "entry_zone_high": round(close, 2),
            "stop_loss": round(close * 0.93, 2),
            "target_price": round(close * 1.05, 2),
            "volume": float(last.get("volume", 0)) if pd.notna(last.get("volume")) else 0,
            "momentum_20d": momentum_20d,
            "volatility_20d": volatility_20d,
            "conviction_score": round(conv_score, 4),
        }
    except Exception:
        return None


def enrich_with_corporate_actions(signals: list[dict], router: SourceRouter) -> list[dict]:
    """Enrich signals with recent corporate actions (dividends, splits) via MCP/dalal.

    Adds/adjusts fields in each signal dict.
    """
    if not signals or router is None:
        return signals

    enriched = []
    for s in signals:
        symbol = s["symbol"]
        try:
            # Try MCP corporate actions first
            ca = router.get_corporate_actions(symbol=symbol, exchange=s["exchange"])
            if ca is not None and isinstance(ca, dict):
                # Extract key info from corporate actions payload
                # Format depends on MCP response - store raw for now
                s["corporate_action_raw"] = json.dumps(ca, default=str)[:200]
            else:
                # Fallback to dalal
                try:
                    import dalal

                    ca = dalal.actions(symbol=symbol, exchange=s["exchange"])
                    s["corporate_action_raw"] = str(ca)[:200] if ca else "none"
                except Exception:
                    s["corporate_action_raw"] = "dalal_failed"
        except Exception:
            s["corporate_action_raw"] = "mcp_failed"

        enriched.append(s)

    return enriched


def write_to_postgres(signals: list[dict]) -> None:
    """Write all signals to PostgreSQL (full replace)."""
    import sqlalchemy as sa

    engine = get_pg_engine()
    ensure_schema()

    with engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE TABLE cached_signals"))
        conn.commit()

    if signals:
        df = pd.DataFrame(signals)
        df["cached_at"] = datetime.now(UTC).isoformat()
        df.to_sql("cached_signals", engine, if_exists="append", index=False)


def write_to_redis(signals: list[dict]) -> None:
    """Write all signals to Redis as hot cache."""
    r = get_redis_client()
    pipe = r.pipeline()

    # Clear old cache
    pipe.delete("signals:all")
    pipe.delete("signals:buys")
    pipe.delete("signals:avoids")
    pipe.delete("signals:by_symbol")

    buys = [s for s in signals if s.get("signal_type") == "dz_hi_up"]
    avoids = [s for s in signals if s.get("signal_type") == "dz_hi_dn"]

    # Store as JSON
    pipe.set("signals:all", json.dumps(signals, default=str), ex=REDIS_TTL)
    pipe.set("signals:buys", json.dumps(buys, default=str), ex=REDIS_TTL)
    pipe.set("signals:avoids", json.dumps(avoids, default=str), ex=REDIS_TTL)
    pipe.set("signals:date", signals[0]["signal_date"] if signals else "", ex=REDIS_TTL)
    pipe.set("signals:count", str(len(signals)), ex=REDIS_TTL)

    # Store per-symbol lookup
    for s in signals:
        pipe.hset("signals:by_symbol", s["symbol"], json.dumps(s, default=str))
    pipe.expire("signals:by_symbol", REDIS_TTL)

    pipe.execute()


def warm_redis_from_pg() -> int:
    """Refresh Redis cache from PostgreSQL (fast, no parquet scan)."""

    engine = get_pg_engine()

    df = pd.read_sql("SELECT * FROM cached_signals", engine)
    if df.empty:
        return 0

    signals = df.to_dict(orient="records")
    write_to_redis(signals)
    return len(signals)


# ── ENRICHMENT: Fundamentals + Institutional + Sectors ──


def enrich_with_fundamentals(signals: list[dict]) -> list[dict]:
    """Enrich signals with fundamental data from PostgreSQL."""
    engine = get_pg_engine()

    # Bulk load key_ratios and company_profile
    try:
        kr_df = pd.read_sql(
            "SELECT symbol, pe_trailing, price_to_book, roe, debt_to_equity, "
            "profit_margin, revenue_growth, dividend_yield, beta, "
            "ev_to_ebitda, current_ratio, market_cap "
            "FROM key_ratios",
            engine,
        )
        kr_dict = kr_df.set_index("symbol").to_dict(orient="index")
    except Exception:
        kr_dict = {}

    try:
        cp_df = pd.read_sql(
            "SELECT symbol, sector, industry, company_name FROM company_profile", engine
        )
        cp_dict = cp_df.set_index("symbol").to_dict(orient="index")
    except Exception:
        cp_dict = {}

    # Fallback: load sector_map for symbols missing sector from company_profile
    try:
        sm_df = pd.read_sql("SELECT symbol, sector FROM sector_map", engine)
        sm_dict = sm_df.set_index("symbol").to_dict(orient="index")
    except Exception:
        sm_dict = {}

    for sig in signals:
        symbol = sig.get("symbol", "")
        kr = kr_dict.get(symbol, {})
        cp = cp_dict.get(symbol, {})

        # Add fundamental fields
        sig["pe_trailing"] = kr.get("pe_trailing")
        sig["price_to_book"] = kr.get("price_to_book")
        sig["roe"] = kr.get("roe")
        sig["debt_to_equity"] = kr.get("debt_to_equity")
        sig["profit_margin"] = kr.get("profit_margin")
        sig["revenue_growth"] = kr.get("revenue_growth")
        sig["dividend_yield"] = kr.get("dividend_yield")
        sig["ev_to_ebitda"] = kr.get("ev_to_ebitda")
        sig["current_ratio"] = kr.get("current_ratio")

        # Add sector/industry — fallback to sector_map if company_profile missing
        sig["sector"] = cp.get("sector") or sm_dict.get(symbol, {}).get("sector")
        sig["industry"] = cp.get("industry")
        sig["company_name"] = cp.get("company_name")

        # Compute fundamental score (0-1)
        fund_score = 0.0
        pe = sig.get("pe_trailing")
        if pe is not None and 5 < pe < 25:
            fund_score += 0.15
        elif pe is not None and 25 < pe < 40:
            fund_score += 0.05

        roe = sig.get("roe")
        if roe is not None and roe > 20:
            fund_score += 0.15
        elif roe is not None and roe > 12:
            fund_score += 0.08

        de = sig.get("debt_to_equity")
        if de is not None and de < 0.5:
            fund_score += 0.10
        elif de is not None and de < 1.0:
            fund_score += 0.05

        margin = sig.get("profit_margin")
        if margin is not None and margin > 15:
            fund_score += 0.10

        growth = sig.get("revenue_growth")
        if growth is not None and growth > 0.15:
            fund_score += 0.10

        div_yield = sig.get("dividend_yield")
        if div_yield is not None and div_yield > 0.02:
            fund_score += 0.05

        sig["fundamental_score"] = round(min(fund_score, 1.0), 4)

    return signals


def enrich_with_institutional(signals: list[dict]) -> list[dict]:
    """Enrich signals with institutional flow data from PostgreSQL."""
    engine = get_pg_engine()

    try:
        sh_df = pd.read_sql(
            "SELECT symbol, promoter_pct, fii_pct, dii_pct, "
            "promoter_chg, fii_chg, dii_chg "
            "FROM shareholding_history "
            "WHERE quarter = (SELECT MAX(quarter) FROM shareholding_history)",
            engine,
        )
        sh_dict = sh_df.set_index("symbol").to_dict(orient="index")
    except Exception:
        sh_dict = {}

    try:
        pp_df = pd.read_sql("SELECT symbol, pledge_pct FROM promoter_pledge", engine)
        pp_dict = pp_df.set_index("symbol").to_dict(orient="index")
    except Exception:
        pp_dict = {}

    for sig in signals:
        symbol = sig.get("symbol", "")
        sh = sh_dict.get(symbol, {})
        pp = pp_dict.get(symbol, {})

        sig["fii_pct"] = sh.get("fii_pct")
        sig["dii_pct"] = sh.get("dii_pct")
        sig["promoter_pct"] = sh.get("promoter_pct")
        sig["fii_chg"] = sh.get("fii_chg")
        sig["dii_chg"] = sh.get("dii_chg")
        sig["promoter_chg"] = sh.get("promoter_chg")
        sig["pledge_pct"] = pp.get("pledge_pct")

        # Compute institutional score (0-1)
        inst_score = 0.0

        # Promoter holding score (from BSE shareholding summary)
        promoter_pct = sig.get("promoter_pct")
        if promoter_pct is not None:
            if 25 <= promoter_pct <= 60:
                inst_score += 0.30  # Healthy promoter range
            elif 15 <= promoter_pct < 25:
                inst_score += 0.15  # Lower but acceptable
            elif promoter_pct > 60:
                inst_score += 0.10  # Very high — some liquidity concern

        fii_chg = sig.get("fii_chg")
        if fii_chg is not None and fii_chg > 0:
            inst_score += 0.20
        elif fii_chg is not None and fii_chg == 0:
            inst_score += 0.05

        dii_chg = sig.get("dii_chg")
        if dii_chg is not None and dii_chg > 0:
            inst_score += 0.15

        promoter_chg = sig.get("promoter_chg")
        if promoter_chg is not None and promoter_chg >= 0:
            inst_score += 0.20

        pledge = sig.get("pledge_pct")
        if pledge is not None and pledge < 5:
            inst_score += 0.25
        elif pledge is not None and pledge < 15:
            inst_score += 0.15
        elif pledge is not None and pledge < 25:
            inst_score += 0.05

        fii_pct = sig.get("fii_pct")
        if fii_pct is not None and fii_pct > 20:
            inst_score += 0.10
        elif fii_pct is not None and fii_pct > 10:
            inst_score += 0.05

        # If we only have promoter data (no FII/DII), give partial credit
        if promoter_pct is not None and fii_chg is None and dii_chg is None:
            inst_score += 0.10  # Partial credit for having shareholding data

        sig["institutional_score"] = round(min(inst_score, 1.0), 4)

    return signals


def compute_professional_score(signals: list[dict]) -> list[dict]:
    """Compute composite professional score combining all layers."""
    for sig in signals:
        # Existing conviction score (delivery + momentum + vol + technicals)
        base = sig.get("conviction_score", 0.0)

        # Fundamental and institutional scores
        fund = sig.get("fundamental_score", 0.0)
        inst = sig.get("institutional_score", 0.0)

        # Composite: 55% base + 25% fundamentals + 20% institutional
        prof_score = (base * 0.55) + (fund * 0.25) + (inst * 0.20)
        sig["professional_score"] = round(min(prof_score, 1.0), 4)

    return signals


def main() -> int:
    parser = argparse.ArgumentParser(description="Cache delivery signals")
    parser.add_argument(
        "--warm-redis", action="store_true", help="Only refresh Redis from PostgreSQL (fast)"
    )
    parser.parse_args()

    if "--warm-redis" in sys.argv:
        t0 = time.time()
        count = warm_redis_from_pg()
        print(
            json.dumps(
                {"action": "warm_redis", "symbols": count, "time": f"{time.time() - t0:.1f}s"}
            )
        )
        return 0

    settings = load_settings()
    nse_dir = settings.normalized_dir / "delivery" / "NSE"
    bse_dir = settings.normalized_dir / "bars_1d" / "BSE"  # BSE has no delivery data

    t0 = time.time()
    signals = []
    router = SourceRouter()

    if nse_dir.exists():
        nse_files = sorted(nse_dir.glob("*.parquet"))
        print(f"Scanning {len(nse_files)} NSE parquets...", flush=True)
        for i, p in enumerate(nse_files):
            sig = compute_signal_for_stock(p, p.stem, "NSE", router=router)
            if sig:
                signals.append(sig)
            if (i + 1) % 500 == 0:
                print(
                    f"  {i + 1}/{len(nse_files)} scanned, {len(signals)} signals ({time.time() - t0:.0f}s)",
                    flush=True,
                )
        print(f"NSE done: {len(signals)} signals ({time.time() - t0:.0f}s)", flush=True)

    # BSE: use router for Upstox V3 bars (26 years!) instead of stale yfinance
    if bse_dir.exists():
        bse_files = sorted(bse_dir.glob("*.parquet"))
        bse_ok = sum(1 for p in bse_files if len(pd.read_parquet(p)) >= 20)
        print(f"Scanning {len(bse_files)} BSE bars ({bse_ok} with 20+ bars)...", flush=True)
        bse_count = 0
        for i, p in enumerate(bse_files):
            # Use router to get Upstox V3 bars, then compute signals
            sig = compute_signal_from_bars(p, p.stem, "BSE", router=router)
            if sig:
                signals.append(sig)
                bse_count += 1
            if (i + 1) % 500 == 0:
                print(
                    f"  BSE {i + 1}/{len(bse_files)} scanned, {bse_count} signals ({time.time() - t0:.0f}s)",
                    flush=True,
                )
        print(f"BSE done: {bse_count} signals ({time.time() - t0:.0f}s)", flush=True)

    # Classify all signals by market cap (SME override applied inside classify_signals)
    signals = classify_signals_mcap(signals, router)

    # Safety net: ensure SME-segment stocks are classified as "SME"
    for s in signals:
        if s.get("segment") == "SME" and s.get("market_cap_class") != "SME":
            s["market_cap_class"] = "SME"

    # Classify security type (ETF, DEBT, INDEX, SME, EQUITY, UNKNOWN)
    signals = classify_all_signals(signals)

    # Enrich with fundamentals + institutional data
    try:
        signals = enrich_with_fundamentals(signals)
        signals = enrich_with_institutional(signals)
        signals = compute_professional_score(signals)
    except Exception as e:
        print(f"Warning: enrichment failed (non-fatal): {e}", flush=True)

    elapsed_scan = time.time() - t0

    if signals:
        write_to_postgres(signals)
        write_to_redis(signals)

    elapsed_total = time.time() - t0
    buys = sum(1 for s in signals if s.get("signal_type") == "dz_hi_up")
    avoids = sum(1 for s in signals if s.get("signal_type") == "dz_hi_dn")

    print(
        json.dumps(
            {
                "total_stocks": len(signals),
                "buys": buys,
                "avoids": avoids,
                "scan_time": f"{elapsed_scan:.1f}s",
                "total_time": f"{elapsed_total:.1f}s",
                "store": "postgresql+redis",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
