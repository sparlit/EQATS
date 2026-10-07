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


import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

BASE_URL = "https://www.bseindia.com/"
API_URL = "https://api.bseindia.com/BseIndiaAPI/api"

_VALID_GROUPS = (
    "A",
    "B",
    "E",
    "F",
    "FC",
    "GC",
    "I",
    "IF",
    "IP",
    "M",
    "MS",
    "MT",
    "P",
    "R",
    "T",
    "TS",
    "W",
    "X",
    "XD",
    "XT",
    "Y",
    "Z",
    "ZP",
    "ZY",
)


class _Throttle:
    """Minimal throttle fallback when mthrottle is unavailable."""

    def __init__(self, *args, **kwargs):
        pass

    def check(self, *args, **kwargs):
        pass


try:
    from mthrottle import Throttle

    _THROTTLE = Throttle({"default": {"rps": 8}, "lookup": {"rps": 15}}, 15)
except ImportError:
    _THROTTLE = _Throttle()


class BSEAnnouncementClient:
    def __init__(self, download_folder: str | Path = "./Bse_Nse_announcement_downloads"):
        self._client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/138.0",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.5",
                "Origin": BASE_URL,
                "Referer": BASE_URL,
                "Connection": "keep-alive",
            },
            timeout=10.0,
        )
        self.download_dir = Path(download_folder)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _req(self, url: str, params: dict | None = None) -> Any:
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _lookup(self, scrip: str) -> str:
        _THROTTLE.check("lookup")
        url = f"{API_URL}/PeerSmartSearch/w"
        resp = self._req(url, {"Type": "SS", "text": scrip})
        return str(resp).replace("&nbsp;", " ")

    def get_scrip_code(self, scripname: str) -> str:
        regex = rf"<\w+>{scripname.upper()}<\/\w+>\s+\w+\s+(\d{{6}})"
        response = self._lookup(scripname)
        match = re.search(regex, response)
        if match:
            return match.group(1)
        raise ValueError(f"Could not find scrip code for {scripname}")

    def announcements(
        self,
        page_no: int = 1,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        segment: str = "equity",
        scripcode: str | None = None,
        category: str = "-1",
        subcategory: str = "-1",
    ) -> dict[str, list[dict]]:
        _type = "C" if segment == "equity" else ("D" if segment == "debt" else "M")
        if from_date is None:
            from_date = datetime.now()
        if to_date is None:
            to_date = datetime.now()
        if from_date > to_date:
            raise ValueError("'from_date' cannot be greater than 'to_date'")
        url = f"{API_URL}/AnnSubCategoryGetData/w"
        fmt = "%Y%m%d"
        params = {
            "pageno": page_no,
            "strCat": category,
            "subcategory": subcategory,
            "strPrevDate": from_date.strftime(fmt),
            "strToDate": to_date.strftime(fmt),
            "strSearch": "P",
            "strscrip": scripcode,
            "strType": _type,
        }
        _THROTTLE.check()
        return self._req(url, params)

    def fetch_all_announcements(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        segment: str = "equity",
        output_path: str | Path | None = None,
    ) -> list[dict]:
        if from_date is None:
            from_date = datetime.now()
        if to_date is None:
            to_date = datetime.now()
        all_ann: list[dict] = []
        page_count = 1
        total_count = 1000
        while True:
            res = self.announcements(
                page_no=page_count, from_date=from_date, to_date=to_date, segment=segment
            )
            if page_count == 1:
                total_count = res.get("Table1", [{}])[0].get("ROWCNT", 0)
            page_count += 1
            all_ann.extend(res.get("Table", []))
            if len(all_ann) >= total_count:
                break
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(all_ann, f, indent=2)
        return all_ann

    def announcements_to_dataframe(
        self,
        announcements: list[dict],
    ) -> pd.DataFrame:
        df = pd.DataFrame(announcements)
        if df.empty:
            return df
        df["Company"] = df.get("SLONGNAME", "")
        df["Time"] = pd.to_datetime(df.get("DT_TM", ""), errors="coerce").dt.strftime("%H:%M")
        df["SCRIP_CD"] = df.get("SCODE", "")
        df["Category"] = df.get("SUBCATNAME", "")
        df["Exchange"] = "BSE"
        df["Announcement Type"] = df.get("ATTACHMENTNAME", "")
        df["Linked Text"] = df["Announcement Type"].apply(
            lambda x: (
                f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{x}"
                if pd.notna(x) and x
                else ""
            )
        )
        return df[
            [
                "Company",
                "Time",
                "SCRIP_CD",
                "Category",
                "Exchange",
                "Announcement Type",
                "Linked Text",
            ]
        ]

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
