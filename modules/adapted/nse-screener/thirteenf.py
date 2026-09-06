"""13F ingestion from SEC EDGAR (v10 raw material).

    python -m us.thirteenf        # → us/data/13f_positions.parquet

For each pre-registered fund: all 13F-HR filings (originals, not
amendments), the information-table XML parsed to issuer/value rows,
keyed to the FILING date. ~1,200 polite requests (<10/s per SEC rules).
"""
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).resolve().parent / "data"
UA = {"User-Agent": "research contact@deshpanda.dev"}

FUNDS = {  # frozen in PROTOCOL_V10.md
    "berkshire hathaway": None, "appaloosa": None, "baupost": None,
    "pershing square capital": None, "third point": None,
    "greenlight capital": None, "lone pine capital": None,
    "viking global": None, "tiger global management": None,
    "coatue management": None, "duquesne family office": None,
    "icahn carl": None, "valueact": None,
    "soros fund management": None, "paulson & co": None,
}


def get(url, **kw):
    time.sleep(0.15)
    r = requests.get(url, headers=UA, timeout=60, **kw)
    r.raise_for_status()
    return r


def resolve_ciks() -> dict:
    out = {}
    for name in FUNDS:
        q = name.replace(" ", "+").replace("&", "%26")
        r = get(f"https://www.sec.gov/cgi-bin/browse-edgar?company={q}"
                f"&type=13F-HR&action=getcompany&output=atom")
        m = re.search(r"CIK=(\d+)", r.text)
        if m:
            out[name] = int(m.group(1))
        else:
            print(f"  ! could not resolve {name}")
    return out


def filings_for(cik: int) -> list[dict]:
    j = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
    rec = j["filings"]["recent"]
    rows = [{"acc": a, "form": f, "filed": d}
            for a, f, d in zip(rec["accessionNumber"], rec["form"],
                               rec["filingDate"])]
    for extra in j["filings"].get("files", []):
        ej = get("https://data.sec.gov/submissions/" + extra["name"]).json()
        rows += [{"acc": a, "form": f, "filed": d}
                 for a, f, d in zip(ej["accessionNumber"], ej["form"],
                                    ej["filingDate"])]
    return [r for r in rows if r["form"] == "13F-HR"
            and r["filed"] >= "2015-01-01"]


def infotable(cik: int, acc: str) -> pd.DataFrame | None:
    folder = acc.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{folder}"
    idx = get(base + "/index.json").json()
    names = [i["name"] for i in idx["directory"]["item"]]
    cands = [n for n in names if n.lower().endswith(".xml")
             and "primary_doc" not in n.lower()]
    if not cands:
        return None
    xml = get(f"{base}/{cands[0]}").content
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    rows = []
    for it in root.iter():
        if it.tag.split("}")[-1] != "infoTable":
            continue
        d = {}
        for sub in it.iter():
            t = sub.tag.split("}")[-1]
            if t in ("nameOfIssuer", "value", "putCall") and sub.text:
                d[t] = sub.text.strip()
        if d.get("nameOfIssuer") and "putCall" not in d:
            rows.append({"issuer": d["nameOfIssuer"].upper(),
                         "value": float(d.get("value", 0) or 0)})
    if not rows:
        return None
    return (pd.DataFrame(rows).groupby("issuer", as_index=False)["value"]
            .sum())


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    ciks = resolve_ciks()
    print({k: v for k, v in ciks.items()})
    frames = []
    for name, cik in ciks.items():
        fl = filings_for(cik)
        print(f"{name}: {len(fl)} 13F-HR filings")
        for f in fl:
            try:
                t = infotable(cik, f["acc"])
            except Exception as e:
                print(f"  {f['acc']}: {e}")
                continue
            if t is None or t.empty:
                continue
            t["fund"], t["filed"] = name, f["filed"]
            frames.append(t)
    df = pd.concat(frames, ignore_index=True)
    df.to_parquet(DATA / "13f_positions.parquet", index=False)
    print(f"saved {len(df)} position rows, "
          f"{df.groupby(['fund','filed']).ngroups} filings parsed")


if __name__ == "__main__":
    main()
