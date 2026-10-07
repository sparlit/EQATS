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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from indian_quant.adapters.announcements.filter import AnnouncementFilter
from indian_quant.adapters.announcements.models import Signal


@dataclass
class ScanResult:
    date_str: str
    total_announcements: int
    filtered_announcements: int
    signals: list[Signal] = field(default_factory=list)


class AnnouncementScanner:
    """Reads BSE announcement JSON files from disk, filters for alpha signals,
    and optionally restricts to a watchlist of stock symbols."""

    def __init__(
        self,
        data_dir: str | Path = "./Bse_Nse_announcement_downloads",
        instrument_master: str | Path = "data/upstox_master.csv.gz",
        watchlist: set[str] | None = None,
    ):
        self._data_dir = Path(data_dir)
        self._instrument_master = Path(instrument_master)
        self._watchlist = watchlist or set()
        self._filter = AnnouncementFilter()
        self._instrument_cache: dict[str, dict] | None = None

    def scan(self, date_str: str | None = None, now_ist: datetime | None = None) -> ScanResult:
        if now_ist is None:
            now_ist = datetime.now()
        if date_str is None:
            date_str = now_ist.strftime("%Y-%m-%d")

        ann_file = self._data_dir / date_str / "Bse_announcements_*.json"
        rel = ann_file.relative_to(self._data_dir)
        matches = sorted(self._data_dir.glob(str(rel)))
        if not matches:
            return ScanResult(
                date_str=date_str, total_announcements=0, filtered_announcements=0, signals=[]
            )

        all_ann: list[dict] = []
        for fpath in matches:
            with open(fpath) as f:
                data = json.load(f)
            if isinstance(data, list):
                all_ann.extend(data)

        total = len(all_ann)
        df = self._to_dataframe(all_ann)
        df = self._add_tradingsymbols(df)
        df = self._filter.filter_dataframe(df)
        recent_df, _ = self._filter.filter_recent(df, now_ist)

        if self._watchlist:
            recent_df = self._filter.filter_by_watchlist(recent_df, self._watchlist)

        signals = list(self._filter.filter_to_signals(recent_df, now_ist))
        return ScanResult(
            date_str=date_str,
            total_announcements=total,
            filtered_announcements=len(recent_df),
            signals=signals,
        )

    @staticmethod
    def _to_dataframe(announcements: list[dict]) -> pd.DataFrame:
        df = pd.DataFrame(announcements)
        if df.empty:
            return df
        df["Company"] = df.get("SLONGNAME", "")
        df["Time"] = pd.to_datetime(df.get("DT_TM", ""), errors="coerce").dt.strftime("%H:%M")
        df["SCRIP_CD"] = df.get("SCODE", "")
        df["Category"] = df.get("SUBCATNAME", "")
        df["Exchange"] = "BSE"
        df["Announcement Type"] = df.get("ATTACHMENTNAME", "")
        return df[["Company", "Time", "SCRIP_CD", "Category", "Exchange", "Announcement Type"]]

    def _add_tradingsymbols(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        master = self._load_instruments()
        name_to_sym = {}
        for _, row in master.iterrows():
            ts = str(row.get("tradingsymbol", "")).strip().upper()
            name = (
                str(row.get("name", "")).strip().upper().rstrip(".").replace(" LTD", " LTD").strip()
            )
            if ts and ts not in name_to_sym:
                name_to_sym[name] = ts
        # Normalize company names for matching
        df["_norm"] = df["Company"].str.strip().str.upper().str.rstrip(".")
        df["tradingsymbol"] = df["_norm"].map(name_to_sym).fillna("")
        df = df.drop(columns=["_norm"])
        return df

    def find_instrument(self, symbol: str, exchange: str) -> dict | None:
        master = self._load_instruments()
        sym_upper = symbol.strip().upper()
        for _, row in master.iterrows():
            if (
                str(row.get("tradingsymbol", "")).strip().upper() == sym_upper
                or str(row.get("name", "")).strip().upper() == sym_upper
            ) and exchange == str(row.get("exchange", "")).strip():
                return row.to_dict()
        return None

    def _load_instruments(self) -> pd.DataFrame:
        if self._instrument_cache is not None:
            return self._instrument_cache
        self._instrument_cache = pd.read_csv(self._instrument_master)
        return self._instrument_cache
