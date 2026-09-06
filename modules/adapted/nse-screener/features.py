"""Point-in-time features over the whole bhavcopy panel, vectorized as
date × symbol frames. Every value at row t uses only data up to and
including t — the engine acts on them at t+1's open, so no lookahead.

Two strategies share one context (MAs, RS, ATR, liquidity, regime):
  build()    v2 — VCP breakout momentum (FAILED out-of-sample; kept for
             reproducibility)
  build_v3() v3 — delivery-accumulation footprint, spec in PROTOCOL_V3.md
"""
import numpy as np
import pandas as pd

import config
from ingest import bhavcopy, corporate_actions, deals_hist, etf_list


def _panel(start: str | None, end: str | None) -> dict:
    df = corporate_actions.adjust(bhavcopy.load_all())
    if start:
        df = df[df["date"] >= start]
    if end:
        df = df[df["date"] <= end]

    gaps = df["date"].drop_duplicates().sort_values().diff().dt.days
    if (gaps > 10).any():
        raise SystemExit(
            "Panel has a >10-day hole (backfill incomplete?). Rolling "
            "windows would span it and produce garbage. Finish the "
            "backfill, then rerun.")

    def wide(col):
        return df.pivot_table(index="date", columns="symbol", values=col)

    return {c: wide(c) for c in
            ("open", "high", "low", "close", "volume", "turnover_lacs",
             "deliv_qty")}


def _context(p: dict) -> dict:
    """Indicators and regime shared by every strategy."""
    close, high, low = p["close"], p["high"], p["low"]

    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()

    rs_raw = (0.4 * (close / close.shift(63) - 1)
              + 0.2 * (close / close.shift(126) - 1)
              + 0.2 * (close / close.shift(189) - 1)
              + 0.2 * (close / close.shift(250) - 1))
    rs_pctile = rs_raw.rank(axis=1, pct=True) * 100

    tr = np.maximum(high - low,
                    np.maximum((high - close.shift()).abs(),
                               (low - close.shift()).abs()))
    atr14 = tr.rolling(14).mean()

    liquid = (p["turnover_lacs"].rolling(20).median()
              >= config.MIN_AVG_TURNOVER_LACS)

    etfs = etf_list.symbols()
    stocks = [s for s in close.columns if s not in etfs]

    bench = close[config.BT_BENCH]
    # regime = index uptrend AND healthy breadth (stocks only). 2025 proved
    # the index alone lies: Nifty held its 200-DMA while breadth collapsed.
    breadth = ((close[stocks] > ma200[stocks]).sum(axis=1)
               / ma200[stocks].notna().sum(axis=1))
    regime = ((bench > bench.rolling(200).mean())
              & (breadth >= config.BT_BREADTH_MIN))

    return {"ma50": ma50, "ma200": ma200, "atr": atr14, "tr": tr,
            "rs_pctile": rs_pctile, "liquid": liquid, "stocks": stocks,
            "bench": bench, "regime": regime}


def _result(p, ctx, signal) -> dict:
    signal[[s for s in signal.columns if s not in ctx["stocks"]]] = False
    return {"open": p["open"], "high": p["high"], "low": p["low"],
            "close": p["close"], "ma50": ctx["ma50"], "atr": ctx["atr"],
            "rs_pctile": ctx["rs_pctile"], "signal": signal,
            "bench": ctx["bench"], "regime": ctx["regime"]}


def build(start: str | None = None, end: str | None = None) -> dict:
    """v2: trend template + VCP contraction + volume breakout."""
    p = _panel(start, end)
    ctx = _context(p)
    close, high, vol = p["close"], p["high"], p["volume"]
    ma50, ma200 = ctx["ma50"], ctx["ma200"]
    ma150 = close.rolling(150).mean()
    lo52 = close.rolling(250, min_periods=210).min()
    hi52 = close.rolling(250, min_periods=210).max()

    trend = ((close > ma150) & (close > ma200) & (ma150 > ma200)
             & (ma200 > ma200.shift(21))          # 200-DMA rising ~1 month
             & (ma50 > ma150) & (close > ma50)
             & (close >= config.ABOVE_LOW_PCT * lo52)
             & (close >= config.NEAR_HIGH_PCT * hi52))

    atr_pct = (ctx["tr"] / close).rolling(10).mean()
    tightening = atr_pct < 0.75 * atr_pct.shift(config.VCP_LOOKBACK - 10)
    vol_dryup = (vol.rolling(10).mean()
                 < 0.8 * vol.rolling(config.VCP_LOOKBACK).mean())
    contraction = (tightening.fillna(False).astype(int)
                   + vol_dryup.fillna(False).astype(int))

    pivot = high.rolling(config.VCP_LOOKBACK).max().shift(1)
    breakout = (close > pivot) & (close.shift(1) <= pivot.shift(1))
    vol_confirm = vol > config.BT_VOL_BREAKOUT * vol.rolling(20).mean().shift(1)

    signal = (trend.fillna(False) & ctx["liquid"].fillna(False)
              & (ctx["rs_pctile"] >= config.RS_PERCENTILE_MIN)
              & (contraction >= config.BT_MIN_CONTRACTION)
              & breakout.fillna(False) & vol_confirm.fillna(False))
    return _result(p, ctx, signal)


def build_v3(start: str | None = None, end: str | None = None,
             spike_mult: float | None = None, cluster: int | None = None,
             rs_floor: float | None = None, window: int | None = None) -> dict:
    """v3: delivery-accumulation clusters. Spec frozen in PROTOCOL_V3.md."""
    spike_mult = spike_mult or config.V3_SPIKE_MULT
    cluster = cluster or config.V3_CLUSTER
    rs_floor = rs_floor or config.V3_RS_FLOOR
    window = window or config.V3_WINDOW

    p = _panel(start, end)
    ctx = _context(p)
    close, dq = p["close"], p["deliv_qty"]

    med = dq.rolling(60, min_periods=40).median().shift(1)
    acc_day = (dq > spike_mult * med) & (close > close.shift(1))
    in_cluster = acc_day.rolling(window).sum() >= cluster
    # fill_value=False keeps bool dtype — .fillna(False) would go object,
    # where ~True == -2 (truthy) silently disables the freshness filter
    fresh = in_cluster & ~in_cluster.shift(1, fill_value=False)

    signal = (fresh & ctx["liquid"].fillna(False)
              & (close > ctx["ma200"])
              & (ctx["rs_pctile"] >= rs_floor))
    return _result(p, ctx, signal)


def build_v5(start: str | None = None, end: str | None = None,
             sticky_re: str = config.V5_STICKY_RE,
             min_vol_share: float = 0.0, rs_floor: float = 0.0,
             bulk_only: bool = False) -> dict:
    """v5: sticky-institution bulk/block buy events. PROTOCOL_V5.md."""
    p = _panel(start, end)
    ctx = _context(p)
    close = p["close"]

    d = deals_hist.load_all()
    if bulk_only:
        d = d[d["kind"] == "bulk"]
    d = d[d["client_name"].str.upper()
           .str.contains(sticky_re, na=False, regex=True)].copy()
    d["net"] = d["qty"].where(d["buy_sell"].str.upper().str.startswith("B"),
                              -d["qty"])
    net = (d.groupby(["date", "symbol"])["net"].sum()
             .unstack().reindex(index=close.index, columns=close.columns))
    event = net > 0
    if min_vol_share > 0:
        event = event & (net >= min_vol_share * p["volume"])

    signal = (event.fillna(False) & ctx["liquid"].fillna(False)
              & (close > ctx["ma200"]))
    if rs_floor > 0:
        signal &= ctx["rs_pctile"] >= rs_floor
    return _result(p, ctx, signal)
