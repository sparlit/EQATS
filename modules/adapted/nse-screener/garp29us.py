"""v29 US cells (PROTOCOL_V29.md): Lynch-tweet GARP on PIT S&P 500.
Valuation uses RAW monthly closes (a split-adjusted price over
as-reported EPS is wrong by the cumulative future split factor);
returns use the audited engine on the adjusted deep panel.
EPS: SEC financial-statement datasets, qtrs=1, Diluted preferred,
EARLIEST filing per (cik, quarter) = first public knowledge.

    python -m us.garp29us --fetch-raw   # one-time raw monthly closes
    python -m us.garp29us               # run both US cells
"""
import json
import sys
from pathlib import Path

import pandas as pd

import config
from backtest import monthly
from us.engine_audit import load_panel, universe

DATA = Path(__file__).resolve().parent / "data"
RAW = DATA / "raw_monthly.parquet"
PE_MAX, G_MIN, PEG_MAX, TOP = 25.0, 0.15, 2.0, 40


def fetch_raw() -> None:
    import yfinance as yf
    tickers = universe()
    frames = []
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i + 50]
        df = yf.download(batch, start="2008-01-01", interval="1mo",
                         auto_adjust=False, progress=False,
                         group_by="ticker", threads=True)
        for t in batch:
            try:
                sub = df[t][["Close"]].dropna()
            except KeyError:
                continue
            sub = sub.rename(columns={"Close": "close"})
            sub["symbol"] = t
            frames.append(sub.reset_index().rename(columns={"Date": "date"}))
        print(f"  {min(i+50, len(tickers))}/{len(tickers)}", flush=True)
    pd.concat(frames, ignore_index=True).to_parquet(RAW, index=False)
    print("raw monthly closes saved")


def eps_frame() -> pd.DataFrame:
    df = pd.concat(map(pd.read_parquet,
                       sorted((config.DATA_DIR / "sec_fund")
                              .glob("*.parquet"))), ignore_index=True)
    df = df[df["qtrs"] == "1"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["ddate"] = pd.to_datetime(df["ddate"], format="%Y%m%d",
                                 errors="coerce")
    df["filed"] = pd.to_datetime(df["filed"], format="%Y%m%d",
                                 errors="coerce")
    df = df.dropna(subset=["value", "ddate", "filed"])
    df["pref"] = (df["tag"] == "EarningsPerShareDiluted").astype(int)
    df = (df.sort_values(["pref", "filed"], ascending=[False, True])
            .drop_duplicates(["cik", "ddate"], keep="first"))
    tickers = json.loads((DATA / "company_tickers.json").read_text())
    cik2tkr = {str(v["cik_str"]): v["ticker"].replace(".", "-")
               for v in tickers.values()}
    df["symbol"] = df["cik"].astype(str).str.lstrip("0").map(cik2tkr)
    df = df.dropna(subset=["symbol"]).sort_values(["symbol", "ddate"])
    rows = []
    for sym, g in df.groupby("symbol"):
        g = g.reset_index(drop=True)
        for i in range(7, len(g)):
            w8 = g.iloc[i - 7:i + 1]
            if (w8["ddate"].iloc[-1] - w8["ddate"].iloc[0]).days > 800:
                continue
            ttm, prev = w8["value"].iloc[4:].sum(), w8["value"].iloc[:4].sum()
            if ttm <= 0 or prev <= 0:
                continue
            rows.append({"symbol": sym, "avail": w8["filed"].iloc[4:].max(),
                         "ttm": ttm, "growth": ttm / prev - 1})
    return pd.DataFrame(rows).sort_values("avail")


def build_picks() -> dict:
    f = eps_frame()
    print(f"TTM records: {len(f):,} across {f['symbol'].nunique()} symbols")
    raw = pd.read_parquet(RAW)
    raw["date"] = pd.to_datetime(raw["date"], utc=True).dt.tz_localize(None)
    px = raw.pivot_table(index="date", columns="symbol", values="close")
    ttm_p = f.pivot_table(index="avail", columns="symbol", values="ttm",
                          aggfunc="last").sort_index()
    g_p = f.pivot_table(index="avail", columns="symbol", values="growth",
                        aggfunc="last").sort_index()
    picks = {}
    for t in px.index:
        if not len(ttm_p.loc[:t]):
            continue
        ttm = ttm_p.loc[:t].ffill().iloc[-1]
        gr = g_p.loc[:t].ffill().iloc[-1]
        pe = px.loc[t] / ttm
        peg = pe / (100 * gr)
        ok = ((pe > 0) & (pe < PE_MAX) & (gr > G_MIN)
              & (peg > 0) & (peg < PEG_MAX))
        picks[t.to_period("M")] = list(
            peg[ok.fillna(False)].dropna().nsmallest(TOP).index)
    return picks


def main():
    picks = build_picks()
    sizes = pd.Series({k: len(v) for k, v in picks.items()})
    print(f"qualifiers/month (pre-membership): median {sizes.median():.0f}")
    p, ctx, members = load_panel()

    def sel(t, m):
        cand = picks.get(pd.Timestamp(t).to_period("M"), [])
        mem = members.loc[t] or frozenset()
        return [s for s in cand if s in mem and s in m.index]

    for label, start, end in (("IS 2023-26 (DECISION)", "2022-01-01", None),
                              ("OOS 2010-22 (single shot)",
                               "2008-07-01", "2022-12-31")):
        print(f"\n=== {label} ===")
        idx = p["close"].index
        mask = pd.Series(True, index=idx)
        if start:
            mask &= idx >= start
        if end:
            mask &= idx <= end
        q = {k: v.loc[mask.values] for k, v in p.items()}
        c = {"bench": ctx["bench"].loc[mask.values], "stocks": ctx["stocks"]}
        monthly.report("garp_us_primary", monthly.simulate(
            q, c, regime_filter=False, select_fn=sel))
        monthly.report("garp_us_regime", monthly.simulate(
            q, c, regime_filter=True, select_fn=sel))


if __name__ == "__main__":
    if "--fetch-raw" in sys.argv:
        fetch_raw()
    else:
        main()
