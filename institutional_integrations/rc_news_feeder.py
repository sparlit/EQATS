"""
RCNewsFeeder Economic Calendar & Event Blackout Engine (EQATS Institutional Adaptation)
Adapted from Sjrazaviebra/RCNewsFeeder

Provides:
- ForexFactory / FairEconomy Economic Calendar Ingestion & Parsing
- High-Impact Economic Event Filter (CPI, NFP, FOMC, Rate Decisions)
- Currency-Specific Proximity Calculator & Pre-Trade Blackout Guard
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import json


class NewsImpact(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    HOLIDAY = "Holiday"


@dataclass
class NewsEvent:
    title: str
    country: str  # e.g., "USD", "EUR", "GBP"
    date_iso: str
    impact: NewsImpact
    forecast: str = ""
    previous: str = ""


@dataclass
class NewsBlackoutCheck:
    blackout_active: bool
    currency: str
    event_title: str
    minutes_until_event: float
    impact: NewsImpact
    recommended_action: str


class RCNewsFeederEngine:
    """RCNewsFeeder Economic News Feeder & Pre-Trade Blackout Engine."""

    def __init__(
        self,
        high_impact_blackout_minutes_before: float = 15.0,
        high_impact_blackout_minutes_after: float = 15.0,
    ):
        self.high_impact_blackout_before = high_impact_blackout_minutes_before
        self.high_impact_blackout_after = high_impact_blackout_minutes_after
        self.events: List[NewsEvent] = []

    def load_events_from_json(self, json_data: List[Dict[str, Any]]) -> int:
        """Parses FairEconomy/ForexFactory JSON calendar payload into NewsEvent objects."""
        self.events.clear()
        for item in json_data:
            impact_str = item.get("impact", "Low")
            impact = NewsImpact.HIGH if impact_str == "High" else NewsImpact.MEDIUM if impact_str == "Medium" else NewsImpact.LOW

            event = NewsEvent(
                title=item.get("title", "Economic Event"),
                country=item.get("country", "USD").upper(),
                date_iso=item.get("date", ""),
                impact=impact,
                forecast=item.get("forecast", ""),
                previous=item.get("previous", ""),
            )
            self.events.append(event)
        return len(self.events)

    def check_currency_news_blackout(
        self, currency: str, current_time: datetime
    ) -> NewsBlackoutCheck:
        """Checks if a currency is within an active news blackout window."""
        curr_upper = currency.upper()

        for ev in self.events:
            if ev.country != curr_upper or ev.impact != NewsImpact.HIGH:
                continue

            try:
                # ISO Format: 2026-07-16T12:30:00-04:00 or 2026-07-16T12:30:00Z
                ev_time_str = ev.date_iso.split("+")[0].split("Z")[0]
                ev_dt = datetime.fromisoformat(ev_time_str)
            except Exception:
                continue

            diff_minutes = (ev_dt - current_time).total_seconds() / 60.0

            if -self.high_impact_blackout_after <= diff_minutes <= self.high_impact_blackout_before:
                return NewsBlackoutCheck(
                    blackout_active=True,
                    currency=curr_upper,
                    event_title=ev.title,
                    minutes_until_event=round(diff_minutes, 1),
                    impact=ev.impact,
                    recommended_action=f"FLATTEN / REJECT ENTRY: High Impact Event '{ev.title}' in {diff_minutes:.1f} mins",
                )

        return NewsBlackoutCheck(
            blackout_active=False,
            currency=curr_upper,
            event_title="None",
            minutes_until_event=999.0,
            impact=NewsImpact.LOW,
            recommended_action="PROCEED",
        )
