"""v41.1 (long-horizon reversal, US replication). Per PROTOCOL_V41.1.md.

Uses Ken French's CRSP-built, survivorship-clean decile portfolios —
NOT our own US price panel, which is survivor-only and therefore
disqualified for a strategy that buys multi-year losers.

    python -m us.reversal_us --fetch   # one-time
    python -m us.reversal_us
"""
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

from us.engine_audit import FRENCH, _monthly_section, load_french

FILES = ("10_Portfolios_Prior_60_13_CSV.zip",
         "6_Portfolios_ME_Prior_60_13_CSV.zip")
FF = ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{f}")
ERAS = (("1926-1984 pre-publication", "1926-01-01", "1984-12-31"),
        ("1985-1999 post-publication", "1985-01-01", "1999-12-31"),
        ("2000-2014", "2000-01-01", "2014-12-31"),
        ("2015-present", "2015-01-01", "2099-12-31"))


def fetch():
    FRENCH.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        dst = FRENCH / f
        if dst.exists():
            continue
        r = requests.get(FF.format(f=f), timeout=180,
                         headers={"User-Agent": "research contact@deshpanda.dev"})
        r.raise_for_status()
        dst.write_bytes(r.content)
        print(f"fetched {f} ({len(r.content)//1024} KB)")


def sections(zip_name):
    """French is inconsistent across files: the 10-portfolio file heads
    its value-weighted block 'Value Weight Returns -- Monthly' while the
    6-portfolio file uses 'Average Value Weighted Returns -- Monthly'.
    Same trap that bit the engine audit — try both."""
    z = zipfile.ZipFile(FRENCH / zip_name)
    txt = z.read(z.namelist()[0]).decode("latin-1")

    def grab(*variants):
        for v in variants:
            try:
                return _monthly_section(txt, v)
            except StopIteration:
                continue
        raise KeyError(f"no section among {variants} in {zip_name}")

    vw = grab("Average Value Weighted Returns -- Monthly",
              "Value Weight Returns -- Monthly")
    ew = grab("Average Equal Weighted Returns -- Monthly",
              "Equal Weight Returns -- Monthly")
    return vw, ew


def ann(r):
    r = r.dropna().astype(float)
    return 100 * ((1 + r).prod() ** (12 / len(r)) - 1) if len(r) else float("nan")


def main():
    vw10, ew10 = sections(FILES[0])
    vw6, _ = sections(FILES[1])
    _, _, mkt = load_french()
    print("decile columns:", list(vw10.columns))
    print("size-split columns:", list(vw6.columns))

    lo, hi = vw10.columns[0], vw10.columns[-1]
    print(f"\nloser leg = {lo!r}   winner leg = {hi!r}")
    print(f"\n{'era':<28} {'R1 lose-win':>12} {'R2 lose-mkt':>12}"
          f" {'(EW R1)':>10}")
    for label, a, b in ERAS:
        w = slice(a, b)
        r1 = ann(vw10.loc[w, lo]) - ann(vw10.loc[w, hi])
        r2 = ann(vw10.loc[w, lo]) - ann(mkt.loc[w])
        e1 = ann(ew10.loc[w, lo]) - ann(ew10.loc[w, hi])
        print(f"  {label:<26} {r1:+11.2f}pp {r2:+11.2f}pp {e1:+9.2f}pp")

    print("\nR3 size split (loser minus winner, value-weighted):")
    small = [c for c in vw6.columns if c.upper().startswith("SMALL")]
    big = [c for c in vw6.columns if c.upper().startswith("BIG")]
    print(f"  small cols {small} | big cols {big}")
    if len(small) >= 2 and len(big) >= 2:
        print(f"\n  {'era':<28} {'SMALL':>10} {'BIG':>10}")
        for label, a, b in ERAS:
            w = slice(a, b)
            s = ann(vw6.loc[w, small[0]]) - ann(vw6.loc[w, small[-1]])
            g = ann(vw6.loc[w, big[0]]) - ann(vw6.loc[w, big[-1]])
            print(f"  {label:<26} {s:+9.2f}pp {g:+9.2f}pp")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch()
    else:
        main()
