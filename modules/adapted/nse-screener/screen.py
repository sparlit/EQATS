"""Daily shortlist = liquidity filter
  → Minervini trend template (all 7 conditions)
  → RS percentile >= 70
  → VCP proxy score (tightening range + volume dry-up + near base high)
  → institutional-footprint overlays (delivery spike, recent bulk/block deal)

Run:  python -m screener.screen
Out:  data/shortlist_<date>.csv, ranked by RS then VCP score.
"""
import numpy as np
import pandas as pd

import config
from ingest import bhavcopy, bulk_deals, corporate_actions, etf_list


FIELDS = ["close", "trend_ok", "rs_raw", "vcp_score", "deliv_spike",
          "pct_off_high", "avg_turnover_lacs"]


def _per_symbol(g: pd.DataFrame) -> pd.Series:
    g = g.sort_values("date")
    c = g["close"]
    if len(g) < 210:            # not enough history for a meaningful 200-DMA
        return pd.Series({f: np.nan for f in FIELDS})

    ma50, ma150, ma200 = (c.rolling(w).mean() for w in (50, 150, 200))
    last = -1
    close = c.iloc[last]
    lo52 = c.tail(250).min()
    hi52 = c.tail(250).max()

    trend = all((
        close > ma150.iloc[last],
        close > ma200.iloc[last],
        ma150.iloc[last] > ma200.iloc[last],
        len(ma200.dropna()) > 21 and ma200.iloc[last] > ma200.iloc[-21],  # rising
        ma50.iloc[last] > ma150.iloc[last],
        close > ma50.iloc[last],
        close >= config.ABOVE_LOW_PCT * lo52,
        close >= config.NEAR_HIGH_PCT * hi52,
    ))

    # RS raw score, IBD-style weighting (percentiled later across universe)
    def ret(n):
        return close / c.iloc[-n] - 1 if len(c) > n else np.nan
    rs_raw = 0.4 * ret(63) + 0.2 * ret(126) + 0.2 * ret(189) + 0.2 * ret(250)

    # --- VCP proxy over the last VCP_LOOKBACK days ---
    w = g.tail(config.VCP_LOOKBACK)
    tr = np.maximum(w["high"] - w["low"],
                    np.maximum((w["high"] - w["close"].shift()).abs(),
                               (w["low"] - w["close"].shift()).abs()))
    atr_pct = (tr / w["close"]).rolling(10).mean()
    tightening = (atr_pct.iloc[-1] < 0.75 * atr_pct.iloc[9]
                  if atr_pct.notna().sum() > 10 else False)
    vol_dryup = w["volume"].tail(10).mean() < 0.8 * w["volume"].mean()
    near_pivot = close >= 0.95 * w["high"].max()
    vcp_score = int(tightening) + int(vol_dryup) + int(near_pivot)

    # --- delivery footprint: today's delivered qty vs its 20d average ---
    dq = g["deliv_qty"].tail(21)
    deliv_spike = (dq.iloc[-1] > config.DELIVERY_SPIKE_MULT * dq.iloc[:-1].mean()
                   and close > c.iloc[-2])

    return pd.Series({
        "close": round(close, 2),
        "trend_ok": trend,
        "rs_raw": rs_raw,
        "vcp_score": vcp_score,
        "deliv_spike": bool(deliv_spike),
        "pct_off_high": round(100 * (close / hi52 - 1), 1),
        "avg_turnover_lacs": g["turnover_lacs"].tail(20).median(),
    })


def run() -> pd.DataFrame:
    df = corporate_actions.adjust(bhavcopy.load_all())
    df = df[~df["symbol"].isin(etf_list.symbols())]   # stocks only, no ETFs
    asof = df["date"].max()

    feats = (df.groupby("symbol", group_keys=False)
               .apply(_per_symbol, include_groups=False)
               .dropna(subset=["rs_raw"]))

    feats = feats[feats["avg_turnover_lacs"] >= config.MIN_AVG_TURNOVER_LACS]
    feats["rs_pctile"] = feats["rs_raw"].rank(pct=True) * 100

    short = feats[feats["trend_ok"]
                  & (feats["rs_pctile"] >= config.RS_PERCENTILE_MIN)].copy()

    deals = bulk_deals.load_all()
    if deals is not None and "symbol" in deals.columns:
        cutoff = asof - pd.Timedelta(days=config.BULK_DEAL_LOOKBACK_DAYS)
        recent = deals
        for datecol in ("date", "deal_date"):
            if datecol in deals.columns:
                recent = deals[pd.to_datetime(deals[datecol],
                                              errors="coerce", dayfirst=True) >= cutoff]
                break
        short["recent_deal"] = short.index.isin(set(recent["symbol"].str.strip()))
    else:
        short["recent_deal"] = False

    short = short.sort_values(["rs_pctile", "vcp_score"], ascending=False)
    out = config.DATA_DIR / f"shortlist_{asof.date()}.csv"
    short.drop(columns=["rs_raw", "trend_ok"]).to_csv(out)
    print(f"{len(short)} candidates → {out}")
    return short


if __name__ == "__main__":
    with pd.option_context("display.width", 160):
        print(run().head(25))
