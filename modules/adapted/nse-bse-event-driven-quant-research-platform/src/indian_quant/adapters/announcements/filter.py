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


from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd
from indian_quant.adapters.announcements.models import Announcement, Signal

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_INCLUDE_CATEGORIES = [
    "Award of Order / Receipt of Order",
    "Awarding of order(s)/contracts",
    "Bagging/Receiving of orders/contracts",
    "Capacity addition",
    "Commencement of commercial production/operations",
    "Analysts/Institutional Investor Meet/Con. Call Updates",
    "Press Release (Revised)",
    "New Listing",
    "Preferential issue",
    "Preferential Issue",
    "Bonus",
    "Press Release",
    "Press Release / Media Release",
    "Financial Results",
    "Board Meeting",
    "Investor Presentation",
    "Earnings Call Transcript",
    "Dividend",
    "Board Meeting Rescheduled",
]

DEFAULT_EXCLUDE_CATEGORIES = [
    "Newspaper Publication",
    "Resignation of Independent director",
    "Corrigendum",
    "Postal Ballot",
    "Change in Director(s)",
    "Change in Directorate",
    "Appointment",
    "Cessation",
    "Change in Registered Office Address",
    "Change in Auditors",
    "Retirement",
    "Change in Company Secretary/Compliance Officer",
    "Certificate under SEBI (Depositories and Participants) Regulations, 2018",
    "Appointment of Statutory Auditor/s",
    "Address Change",
    "Compliance Report",
    "Others",
    "General Updates",
    "Change in Management",
    "Structural Digital Database",
    "Resignation of Director",
    "Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate",
    "Resignation of Statutory Auditors",
    "Closure of Trading Window",
    "Clarification",
    "Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018",
]

BUY_CATEGORIES = [
    "Award of Order / Receipt of Order",
    "Awarding of order(s)/contracts",
    "Bagging/Receiving of orders/contracts",
    "Capacity addition",
    "Commencement of commercial production/operations",
]


class AnnouncementFilter:
    def __init__(
        self,
        include_categories: list[str] | None = None,
        exclude_categories: list[str] | None = None,
        lookback_minutes: int = 2,
    ):
        self.include_categories = include_categories or DEFAULT_INCLUDE_CATEGORIES
        self.exclude_categories = exclude_categories or DEFAULT_EXCLUDE_CATEGORIES
        self.lookback_minutes = lookback_minutes

    def filter_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()
        df = df[~df["Category"].isin(self.exclude_categories)]
        return df[df["Category"].isin(self.include_categories)]

    def filter_by_watchlist(self, df: pd.DataFrame, watchlist_symbols: set[str]) -> pd.DataFrame:
        if df.empty or not watchlist_symbols:
            return df
        df = df.copy()
        df["_sym"] = df["tradingsymbol"].str.strip().str.upper()
        df = df[df["_sym"].isin(watchlist_symbols)]
        return df.drop(columns=["_sym"])

    def filter_recent(
        self,
        df: pd.DataFrame,
        now_ist: datetime | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        if now_ist is None:
            now_ist = datetime.now()
        today_str = now_ist.strftime("%Y-%m-%d")
        df = df.copy()
        df["TimeDT"] = pd.to_datetime(today_str + " " + df["Time"], format="%Y-%m-%d %H:%M", errors="coerce")
        cutoff = now_ist - timedelta(minutes=self.lookback_minutes)
        recent = df[df["TimeDT"] >= cutoff]
        return recent.sort_values("TimeDT", ascending=False), df

    def filter_to_signals(
        self,
        df: pd.DataFrame,
        now_ist: datetime | None = None,
    ) -> Iterable[Signal]:
        recent, _ = self.filter_recent(df, now_ist)
        for _, row in recent.iterrows():
            yield Signal(
                symbol=str(row.get("Company", "")),
                exchange=str(row.get("Exchange", "")),
                scrip_code=str(row.get("SCRIP_CD", "")),
                category=str(row.get("Category", "")),
                announcement_type=str(row.get("Announcement Type", "")),
                strength=0.5,
                published_at=None,
                notes=f"Announcement Alpha: {row.get('Category', '')}",
            )
