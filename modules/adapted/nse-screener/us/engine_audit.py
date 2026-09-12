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


"""Engine-replication audit vs the French momentum deciles.
Per PROTOCOL_USAUDIT.md — validates the monthly engine's mechanics
against the published US momentum record. Not a strategy.

    python -m us.engine_audit --fetch    # deep prices (restartable) + French
    python -m us.engine_audit            # run the audit
"""
import io
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests
from backtest import monthly
from us.momentum import member_top

DATA = Path(__file__).resolve().parent / "data"
DEEP = DATA / "prices_deep"
FRENCH = DATA / "french"
START = "1995-06-01"  # 12-1 burn-in ahead of 1997 formations
FF = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"


def universe() -> list[str]:
    m = pd.read_csv(DATA / "sp500_hist.csv")
    tickers = set()
    for row in m["tickers"]:
        tickers.update(t.strip() for t in row.split(","))
    tickers = {t.replace(".", "-") for t in tickers if t and ("." not in t or t.count(".") == 1)}
    tickers.add("SPY")
    return sorted(tickers)


def fetch_deep() -> None:
    import yfinance as yf

    DEEP.mkdir(exist_ok=True)
    tickers = universe()
    print(f"{len(tickers)} tickers ever in membership file")
    for i in range(0, len(tickers), 50):
        part = DEEP / f"batch_{i:04d}.parquet"
        if part.exists():
            continue
        batch = tickers[i : i + 50]
        df = yf.download(batch, start=START, auto_adjust=True, progress=False, group_by="ticker", threads=True)
        frames = []
        for t in batch:
            try:
                sub = df[t][["Open", "Close"]].dropna(how="all")
            except KeyError:
                continue
            if len(sub) < 50:
                continue
            sub = sub.rename(columns=str.lower)
            sub["symbol"] = t
            frames.append(sub.reset_index().rename(columns={"Date": "date"}))
        out = (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame(columns=["date", "open", "close", "symbol"])
        )
        out.to_parquet(part, index=False)
        print(
            f"  batch {i:4d}: {out['symbol'].nunique() if len(out) else 0}/{len(batch)} tickers with data", flush=True
        )
        time.sleep(1)
    print("deep fetch complete")


def fetch_french() -> None:
    FRENCH.mkdir(exist_ok=True)
    for name in ("10_Portfolios_Prior_12_2_CSV.zip", "F-F_Research_Data_Factors_CSV.zip"):
        dst = FRENCH / name
        if dst.exists():
            continue
        r = requests.get(FF + name, timeout=120, headers={"User-Agent": "research contact@deshpanda.dev"})
        r.raise_for_status()
        dst.write_bytes(r.content)
        print(f"fetched {name} ({len(r.content) // 1024} KB)")


def _monthly_section(text: str, section: str) -> pd.DataFrame:
    """Parse one 'Average ... Returns -- Monthly' block of a French CSV."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if section in l)
    header = next(i for i in range(start, len(lines)) if lines[i].strip().startswith(","))
    rows = []
    for l in lines[header + 1 :]:
        parts = [p.strip() for p in l.split(",")]
        if len(parts) < 2 or not parts[0].isdigit() or len(parts[0]) != 6:
            break
        rows.append(parts)
    cols = [c.strip() for c in lines[header].split(",")]
    df = pd.DataFrame(rows, columns=cols).rename(columns={"": "ym"})
    df["date"] = pd.PeriodIndex(df["ym"], freq="M").to_timestamp("M")
    for c in df.columns:
        if c not in ("ym", "date"):
            df[c] = pd.to_numeric(df[c], errors="coerce") / 100
    return df.set_index("date").drop(columns="ym").replace(-0.9999, pd.NA)


def load_french() -> tuple[pd.Series, pd.Series, pd.Series]:
    z = zipfile.ZipFile(FRENCH / "10_Portfolios_Prior_12_2_CSV.zip")
    txt = z.read(z.namelist()[0]).decode("latin-1")
    vw = _monthly_section(txt, "Value Weight Returns -- Monthly")
    ew = _monthly_section(txt, "Average Equal Weighted Returns -- Monthly")
    z = zipfile.ZipFile(FRENCH / "F-F_Research_Data_Factors_CSV.zip")
    txt = z.read(z.namelist()[0]).decode("latin-1")
    fac = _monthly_section(txt, "This file was created")  # single table
    mkt = fac["Mkt-RF"] + fac["RF"]
    return vw["Hi PRIOR"], ew["Hi PRIOR"], mkt


def load_panel():
    px = pd.concat(map(pd.read_parquet, sorted(DEEP.glob("*.parquet"))), ignore_index=True)
    close = px.pivot_table(index="date", columns="symbol", values="close")
    open_ = px.pivot_table(index="date", columns="symbol", values="open")
    m = pd.read_csv(DATA / "sp500_hist.csv", parse_dates=["date"])
    m["set"] = m["tickers"].map(lambda s: frozenset(t.strip().replace(".", "-") for t in s.split(",")))
    members = m.set_index("date")["set"].sort_index().reindex(close.index, method="ffill")
    p = {"close": close, "open": open_, "turnover_lacs": pd.DataFrame(1e9, index=close.index, columns=close.columns)}
    ctx = {"bench": close["SPY"].ffill(), "stocks": [c for c in close.columns if c != "SPY"]}
    return p, ctx, members


def era(ours: pd.Series, mkt: pd.Series, lo: str, hi: str) -> float:
    """annualized excess (pp) of our portfolio over French market"""
    w = ours.loc[lo:hi].dropna()
    m = mkt.reindex(w.index)

    def ann(r):
        return (1 + r).prod() ** (12 / len(r)) - 1

    return 100 * (ann(w) - ann(m))


def main():
    vw10, ew10, mkt = load_french()
    p, ctx, members = load_panel()
    print(f"panel: {p['close'].shape[1]} symbols, {p['close'].index[0].date()} → {p['close'].index[-1].date()}")
    res = monthly.simulate(p, ctx, top_n=20, skip=21, cost=0.0025, regime_filter=False, select_fn=member_top(members))
    ours = res["eq"]["ret"].copy()
    # simulate() indexes each row by t1 = the month-end the return ENDS
    # at — French's convention already; just snap to calendar month-end
    ours.index = pd.to_datetime(ours.index).to_period("M").to_timestamp("M")
    ours = ours.loc["1997-01-31":].dropna()

    print("\n=== C. reference sanity (French's own file, our parsing) ===")
    for label, lo, hi in (
        ("1997-2008", "1997-01", "2008-12"),
        ("2009", "2009-01", "2009-12"),
        ("2010-2019", "2010-01", "2019-12"),
    ):
        x = era(vw10, mkt, lo, hi)
        print(f"  VW decile-10 minus market {label}: {x:+.1f} pp/yr")

    print("\n=== A. mechanical fidelity ===")
    for label, ref in (("VW", vw10), ("EW", ew10)):
        j = pd.concat([ours, ref], axis=1, join="inner").dropna()
        c = j.corr().iloc[0, 1]
        print(
            f"  corr(ours, French {label} decile-10) = {c:.3f} "
            f"over {len(j)} months  [{'PASS' if c >= 0.75 else 'fail'}]"
        )

    print("\n=== B. era replication (ours minus French market) ===")
    e1 = era(ours, mkt, "1997-01", "2008-12")
    e2 = era(ours, mkt, "2009-01", "2009-12")
    e3 = era(ours, mkt, "2010-01", "2019-12")
    print(f"  1997-2008: {e1:+.1f} pp/yr  [{'PASS' if e1 > 0 else 'FAIL'}]")
    print(f"  2009     : {e2:+.1f} pp    [{'PASS' if e2 < 0 else 'FAIL'}]")
    print(f"  2010-2019: {e3:+.1f} pp/yr  [{'PASS' if e3 < e1 else 'FAIL'} decay]")
    print("\n(levels unscored: survivor-only panel inflates them — see PROTOCOL_USAUDIT.md)")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch_french()
        fetch_deep()
    else:
        main()
