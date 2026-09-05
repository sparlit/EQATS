"""PARTLY-PAID share harvester (misnamed on purpose — see below).

CORRECTION 2026-08-19, the same day this was written: series E1/E2/E3 are
NOT rights entitlements. They are PARTLY-PAID equity shares, which arise
when a rights issue is payable in installments. The tell: TATASTEEL E1
and HATSUN E1 rows exist from 2018-12-31, before RE trading existed at
all, and HATSUN's E1 dates do not straddle its rights record date.

Rights entitlements (REs) are NOT in the equity bhavcopy in any series.
Verified by inspecting 2020-05-26, 2020-05-28 and 2020-06-01 — the middle
of Reliance's RE trading window (20 May - 3 Jun 2020): the only RELIANCE
row on each day is series EQ. Every apparent "-RE" symbol is a company
whose NAME ends in RE (APOLLOTYRE, GICRE). PROTOCOL_V39 is therefore
BLOCKED on data, not on method; untried routes are listed in STATE.

What this module DID produce, and it is genuinely novel: 7,162
partly-paid-share observations across 66 instruments, 2018-2026.
Partly-paid shares trade at a discount reflecting unpaid installments and
are studied by almost nobody — a candidate future protocol.

Design note (important): this does NOT touch config.SERIES. Changing the
main panel's series filter would silently alter the universe of all 34
prior strategies. REs get their own store.

Targeted harvest: rights issues are rare (~10-20 mainboard/yr), so
instead of re-downloading a decade of archives, we take rights-issue
record dates from the corporate-actions API and fetch only the raw
archives inside each RE trading window.

    python -m ingest.rights_re windows   # build the fetch plan
    python -m ingest.rights_re harvest   # fetch + keep E* series
"""
import io
import sys
import time
import zipfile
from datetime import timedelta

import pandas as pd

import config
from ingest import nse, renames

DIR = config.DATA_DIR / "rights_re"
OLD_URL = ("https://nsearchives.nseindia.com/content/historical/EQUITIES/"
           "{yyyy}/{mon}/cm{ddmonyyyy}bhav.csv.zip")
NEW_URL = ("https://nsearchives.nseindia.com/products/content/"
           "sec_bhavdata_full_{ddmmyyyy}.csv")
RE_SERIES = {f"E{i}" for i in range(1, 10)}      # E1..E9 = rights entitlements
CA_URL = ("https://www.nseindia.com/api/corporates-corporateActions"
          "?index=equities&from_date={frm}&to_date={to}")


def windows() -> None:
    """Rights-issue record dates → the trading days worth fetching."""
    DIR.mkdir(parents=True, exist_ok=True)
    s = nse.session()
    s.get("https://www.nseindia.com/companies-listing/"
          "corporate-filings-actions", timeout=15)
    frames = []
    for yr in range(2019, 2027):                 # RE trading began Jan-2020
        try:
            r = nse.get(CA_URL.format(frm=f"01-01-{yr}", to=f"31-12-{yr}"),
                        timeout=120)
            d = r.json()
            d = d if isinstance(d, list) else d.get("data", [])
            if d:
                frames.append(pd.DataFrame(d))
        except Exception as e:
            print(f"  {yr}: {e}", flush=True)
        time.sleep(1)
    ca = pd.concat(frames, ignore_index=True)
    ri = ca[ca["subject"].str.contains("rights", case=False, na=False)].copy()
    ri["symbol"] = renames.canonical(ri["symbol"].astype(str).str.strip())
    ri["record_date"] = pd.to_datetime(ri["exDate"], format="%d-%b-%Y",
                                       errors="coerce")
    ri = ri.dropna(subset=["record_date"]).drop_duplicates(
        ["symbol", "record_date"])
    ri.to_parquet(DIR / "issues.parquet", index=False)
    days = set()
    for d in ri["record_date"]:
        for k in range(-5, 31):                  # RE window sits after record
            dd = (d + timedelta(days=k)).date()
            if dd.weekday() < 5:
                days.add(dd)
    pd.Series(sorted(days)).to_frame("date").to_parquet(
        DIR / "fetch_plan.parquet", index=False)
    print(f"rights issues: {len(ri)} "
          f"{ri['record_date'].min().date()} → {ri['record_date'].max().date()}")
    print(f"unique trading days to fetch: {len(days)}")


def _fetch_raw(d) -> pd.DataFrame | None:
    if d >= pd.Timestamp("2020-07-01").date():
        r = nse.get(NEW_URL.format(ddmmyyyy=d.strftime("%d%m%Y")),
                    timeout=config.TIMEOUT)
        if r.status_code != 200 or len(r.content) < 500:
            return None
        df = pd.read_csv(io.BytesIO(r.content))
        df.columns = [c.strip().upper() for c in df.columns]
        df = df.rename(columns={"SERIES": "SERIES", "OPEN_PRICE": "OPEN",
                                "CLOSE_PRICE": "CLOSE", "HIGH_PRICE": "HIGH",
                                "LOW_PRICE": "LOW",
                                "TTL_TRD_QNTY": "TOTTRDQTY"})
    else:
        r = nse.get(OLD_URL.format(yyyy=d.strftime("%Y"),
                                   mon=d.strftime("%b").upper(),
                                   ddmonyyyy=d.strftime("%d%b%Y").upper()),
                    timeout=config.TIMEOUT)
        if r.status_code != 200:
            return None
        df = pd.read_csv(io.BytesIO(r.content), compression="zip")
    df["SERIES"] = df["SERIES"].astype(str).str.strip()
    sub = df[df["SERIES"].isin(RE_SERIES)]
    if sub.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "symbol": sub["SYMBOL"].astype(str).str.strip(),
        "series": sub["SERIES"],
        "date": pd.to_datetime(d),
        "open": pd.to_numeric(sub["OPEN"], errors="coerce"),
        "high": pd.to_numeric(sub["HIGH"], errors="coerce"),
        "low": pd.to_numeric(sub["LOW"], errors="coerce"),
        "close": pd.to_numeric(sub["CLOSE"], errors="coerce"),
        "qty": pd.to_numeric(sub["TOTTRDQTY"], errors="coerce"),
    })


def harvest() -> None:
    plan = pd.read_parquet(DIR / "fetch_plan.parquet")["date"]
    done_file = DIR / "re_trades.parquet"
    done = pd.read_parquet(done_file) if done_file.exists() else pd.DataFrame()
    have = set(done["date"].dt.date) if len(done) else set()
    rows, n = [], 0
    for d in plan:
        d = d.date() if hasattr(d, "date") else d
        if d in have:
            continue
        try:
            sub = _fetch_raw(d)
        except Exception:
            sub = None
        if sub is not None and len(sub):
            rows.append(sub)
        n += 1
        if n % 100 == 0:
            if rows:
                done = pd.concat([done] + rows, ignore_index=True)
                done.to_parquet(done_file, index=False)
                rows = []
            print(f"  {n} days fetched, {len(done)} RE rows stored", flush=True)
        time.sleep(0.45)
    if rows:
        done = pd.concat([done] + rows, ignore_index=True)
    if len(done):
        done.to_parquet(done_file, index=False)
        print(f"RE harvest done: {len(done)} rows, "
              f"{done['symbol'].nunique()} instruments")
    else:
        print("RE harvest done: nothing stored")


if __name__ == "__main__":
    {"windows": windows, "harvest": harvest}[sys.argv[1]]()
