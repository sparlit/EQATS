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


"""Wholesale Price Index, item level, monthly, from the Office of the Economic Adviser (eaindustry.nic.in), base 2011-12=100.
The workbook indx_download_1112/monthly_index_<yyyymm>.xls holds ~870 rows (all commodities down to ~700 items) with one
column per month from Apr 2012. Usage: python3 scripts/ideas/wpi.py  -> docs/ideas/wpi.json.gz
"""
import datetime
import gzip
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ist
import xlrd

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs", "ideas")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
SITE = "https://eaindustry.nic.in/"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as f:
        return f.read()


def dump_gz(obj, path):
    """Deterministic gzip (mtime=0) so an unchanged rebuild is byte-identical and git sees no churn."""
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(json.dumps(obj, separators=(",", ":")).encode())


def main():
    page = get(SITE + "download_data_1112.asp").decode("utf-8", "ignore")
    links = re.findall(r'href="(indx_download_1112/monthly_index_(\d{6})\.xls)"', page)
    if not links:
        msg = "monthly_index link not found on download_data_1112.asp"
        raise SystemExit(msg)
    link, _stamp = max(links, key=lambda t: t[1])
    raw = get(SITE + link)
    tmp = tempfile.NamedTemporaryFile(suffix=".xls", delete=False)
    tmp.write(raw)
    tmp.close()
    wb = xlrd.open_workbook(tmp.name)
    sh = wb.sheet_by_index(0)
    hdr = [str(sh.cell_value(0, j)) for j in range(sh.ncols)]
    mcols = [(j, f"{h[6:10]}-{h[4:6]}") for j, h in enumerate(hdr) if re.fullmatch(r"INDX\d{6}", h)]
    months = [m for _, m in mcols]
    items = []
    for i in range(1, sh.nrows):
        name = str(sh.cell_value(i, 0)).strip()
        code = str(sh.cell_value(i, 1)).strip()
        if not code:
            continue
        code = code.split(".")[0]
        vals = []
        for j, _ in mcols:
            v = sh.cell_value(i, j)
            vals.append(round(float(v), 1) if isinstance(v, (int, float)) and v != "" else None)
        wt = sh.cell_value(i, 2)
        items.append(
            {
                "c": code,
                "n": re.sub(r"\s+", " ", name),
                "w": round(float(wt), 5) if isinstance(wt, (int, float)) else None,
                "leaf": 0 if code.endswith("00") else 1,
                "v": vals,
            }
        )
    out = {
        "source": "Office of the Economic Adviser, DPIIT (eaindustry.nic.in) - WPI monthly index, base 2011-12=100",
        "file": link,
        "built": ist.stamp(),
        "months": months,
        "n": len(items),
        "items": items,
    }
    dump_gz(out, os.path.join(DOCS, "wpi.json.gz"))
    print("wpi:", len(items), "rows,", months[0], "..", months[-1], "from", link)
    os.unlink(tmp.name)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as e:
        # Same rule as the other builders: report the unreachable source, keep the committed file.
        msg = f"wpi: eaindustry.nic.in unreachable ({e.reason}); docs/ideas/wpi.json.gz LEFT UNCHANGED"
        raise SystemExit(msg)
