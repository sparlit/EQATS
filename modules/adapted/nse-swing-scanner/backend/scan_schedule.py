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


"""
scan_schedule.py
Single source of truth for the twice-daily scan schedule and the window
attribution / next-expected-window math.

Consumers:
  - .github/workflows/scan.yml  ("Write scan_status.json" heredoc imports this)
  - backend/scripts/watchdog_check.py (staleness decision)
  - backend/scripts/check_cron_consistency.py (CI guard vs the YAML crons)

If you change the cron expressions in .github/workflows/scan.yml, change
SCAN_WINDOWS_UTC (in settings.py) in the same commit — the CI guard fails
until both agree.
"""

from typing import List, Optional, Tuple

from settings import SCAN_WINDOWS_UTC

# Re-exported for convenience so consumers import only this module.
WINDOWS: list[tuple[int, int]] = SCAN_WINDOWS_UTC


def clock_minute_delta(a: datetime.datetime, b: datetime.datetime) -> int:
    """Circular distance in minutes between two wall-clock HH:MM values."""
    a_m = a.hour * 60 + a.minute
    b_m = b.hour * 60 + b.minute
    return min(abs(a_m - b_m), 1440 - abs(a_m - b_m))


def most_recent_window(
    now: datetime.datetime,
    windows: list[tuple[int, int]] = WINDOWS,
) -> tuple[datetime.datetime, str] | None:
    """
    The scheduled window most plausibly responsible for a scan completing at
    `now`: the closest-past candidate among today's windows plus YESTERDAY'S
    LAST window only (yesterday's earlier windows are too far back to
    plausibly be "the most recent past cron"; including them caused
    misattribution in the 00:00–first-window UTC span — fixed in 1.1.3).

    Returns (window_dt, "HH:MM") or None when no candidate is in the past
    (i.e. `now` predates every window — only possible at the very start of
    a Monday before the first window after a weekend).
    """
    today = now.date()
    cands: list[tuple[datetime.datetime, str]] = []
    for h, m in windows:
        cands.append(
            (
                datetime.datetime.combine(today, datetime.time(h, m), tzinfo=datetime.UTC),
                f"{h:02d}:{m:02d}",
            )
        )
    last_h, last_m = windows[-1]
    cands.append(
        (
            datetime.datetime.combine(
                today - datetime.timedelta(days=1),
                datetime.time(last_h, last_m),
                tzinfo=datetime.UTC,
            ),
            f"{last_h:02d}:{last_m:02d}",
        )
    )
    past = [(dt, label) for dt, label in cands if dt <= now]
    if not past:
        return None
    # Pick the past window whose HH:MM is closest to now's wall clock.
    # Handles on-time and small-drift cases correctly. For multi-hour cron
    # delays (rare), misattribution is a documented limitation: GitHub
    # Actions does not expose which cron expression fired.
    return min(past, key=lambda p: clock_minute_delta(now, p[0]))


def attribute_window(
    now: datetime.datetime,
    windows: list[tuple[int, int]] = WINDOWS,
) -> tuple[str | None, int | None]:
    """
    (scheduled_window_utc, drift_minutes) for a scan completing at `now`.
    (None, None) when no past window exists.
    """
    chosen = most_recent_window(now, windows)
    if chosen is None:
        return None, None
    dt, label = chosen
    drift = int((now - dt).total_seconds() // 60)
    return label, drift


def next_scheduled_window(
    now: datetime.datetime,
    windows: list[tuple[int, int]] = WINDOWS,
) -> datetime.datetime | None:
    """
    Next future scheduled window (Mon-Fri only — matches the cron's
    `* * 1-5` weekday constraint). The frontend uses this instead of a
    clock-time threshold so the staleness banner doesn't fire on weekends
    when no scan is expected. NSE holidays are NOT skipped (documented
    limitation — the banner tolerates them via its grace period).
    """
    base_date = now.date()
    for offset in range(7):
        cand_date = base_date + datetime.timedelta(days=offset)
        if cand_date.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            continue
        for h, m in windows:
            cand_dt = datetime.datetime.combine(
                cand_date,
                datetime.time(h, m),
                tzinfo=datetime.UTC,
            )
            if cand_dt > now:
                return cand_dt
    return None


def scheduled_cron_string(windows: list[tuple[int, int]] = WINDOWS) -> str:
    """Cron expressions as a display string, e.g. '30 3 * * 1-5, 30 10 * * 1-5'."""
    return ", ".join(f"{m} {h} * * 1-5" for h, m in windows)
