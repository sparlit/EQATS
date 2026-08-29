"""
Prop Firm Multi-Firm Calendar Feed & ICS Generator Engine.
Manages scheduled maintenance, market/crypto closures, early closes, and symbol events
across prop firms (FTMO, E8 Markets, Topstep, Blueberry Funded, FundedNext).
Generates iCalendar (.ics) feed strings for calendar sync.
"""

import time
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger("PropFirmCalendarFeed")

class PropFirmTradingEvent:
    def __init__(self, firm: str, event_type: str, summary: str, start_dt: datetime, end_dt: datetime, source_url: str = ""):
        self.firm = firm.upper()
        self.event_type = event_type.lower()
        self.summary = summary
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.source_url = source_url

    @property
    def event_key(self) -> str:
        raw = f"{self.firm}|{self.event_type}|{self.start_dt.isoformat()}|{self.end_dt.isoformat()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

class PropFirmCalendarFeedManager:
    """
    Multi-Firm Prop Calendar Manager & iCal / ICS Feed Generator.
    """
    def __init__(self):
        self.events: List[PropFirmTradingEvent] = []

    def add_event(self, firm: str, event_type: str, summary: str, start_dt: datetime, end_dt: datetime, source_url: str = "") -> str:
        evt = PropFirmTradingEvent(firm, event_type, summary, start_dt, end_dt, source_url)
        self.events.append(evt)
        return evt.event_key

    def generate_ics_feed(self, firm_filter: Optional[str] = None) -> str:
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//EQATS Prop Firm Multi-Calendar Feed//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "X-WR-CALNAME:Prop Firm Trading Calendar",
        ]

        filtered = [e for e in self.events if not firm_filter or e.firm == firm_filter.upper()]

        for e in filtered:
            start_str = e.start_dt.strftime("%Y%m%dT%H%M%SZ")
            end_str = e.end_dt.strftime("%Y%m%dT%H%M%SZ")
            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{e.event_key}@eqats.quant",
                f"DTSTAMP:{start_str}",
                f"DTSTART:{start_str}",
                f"DTEND:{end_str}",
                f"SUMMARY:[{e.firm}] {e.summary}",
                f"DESCRIPTION:Prop Firm Event ({e.event_type}). Source: {e.source_url}",
                "END:VEVENT",
            ])

        lines.append("END:VCALENDAR")
        return "\r\n".join(lines)
