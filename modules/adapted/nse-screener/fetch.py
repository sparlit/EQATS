"""Download daily OHLCV for every S&P 500 member since 2017 (point-in-time
list) + SPY, via yfinance.

    python us/fetch.py        # → us/data/prices.parquet, coverage report
"""
from pathlib import Path

import pandas as pd
import yfinance as yf

DATA = Path(__file__).resolve().parent / "data"
START = "2016-06-01"          # 200-DMA warmup ahead of 2017 events


def universe() -> tuple[set[str], pd.DataFrame]:
    m = pd.read_csv(DATA / "sp500_hist.csv", parse_dates=["date"])
    m = m[m["date"] >= "2017-01-01"]
    tickers = set()
    for row in m["tickers"]:
        tickers.update(t.strip() for t in row.split(","))
    tickers = {t.replace(".", "-") for t in tickers if t and "." not in t
               or t.count(".") == 1}                     # BRK.B → BRK-B
    return tickers, m


def main() -> None:
    tickers, _ = universe()
    tickers.add("SPY")
    tickers = sorted(tickers)
    print(f"{len(tickers)} tickers (point-in-time members 2017+, + SPY)")

    frames, got = [], 0
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i + 50]
        df = yf.download(batch, start=START, auto_adjust=True,
                         progress=False, group_by="ticker", threads=True)
        for t in batch:
            try:
                sub = df[t][["Open", "Close", "Volume"]].dropna(how="all")
            except KeyError:
                continue
            if len(sub) < 50:
                continue
            sub = sub.rename(columns=str.lower)
            sub["symbol"] = t
            frames.append(sub.reset_index().rename(columns={"Date": "date"}))
            got += 1
        print(f"  {min(i+50, len(tickers))}/{len(tickers)} requested, "
              f"{got} with data")

    out = pd.concat(frames, ignore_index=True)
    out.to_parquet(DATA / "prices.parquet", index=False)
    print(f"saved {got}/{len(tickers)} tickers "
          f"({100*got/len(tickers):.0f}% coverage) → us/data/prices.parquet")


if __name__ == "__main__":
    main()
