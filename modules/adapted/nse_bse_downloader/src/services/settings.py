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


"""Validated effective settings with explicit precedence."""


from typing import Any

from ..utils.user_preferences import UserPreferences


class SettingsService:
    """Resolve built-ins, config defaults, then persisted user overrides."""

    def __init__(self, config, preferences: UserPreferences | None = None):
        self.config = config
        self.preferences = preferences or UserPreferences(config)

    def download_options(self) -> dict[str, Any]:
        return self.preferences.get_download_options()

    def get_download_option(self, name: str, default: Any = None) -> Any:
        return self.download_options().get(name, default)

    def append_options(self) -> dict[str, bool]:
        return self.preferences.get_append_options()

    def auto_check_updates(self) -> bool:
        return self.preferences.get_auto_check_updates()

    def skipped_update_version(self) -> str:
        return self.preferences.get_skipped_update_version()
