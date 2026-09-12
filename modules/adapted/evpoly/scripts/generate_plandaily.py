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


#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import math
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple
from zoneinfo import ZoneInfo

UTC = dt.UTC
ET = ZoneInfo("America/New_York")
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
ONE_HOUR_MS = 3600_000
ONE_HOUR_SEC = 3600


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    display: str
    step_pct: float
    max_pct: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate docs/plandaily.md from Binance 1h candles")
    parser.add_argument(
        "--start-close-day",
        default="2021-03-01",
        help="First ET close day (YYYY-MM-DD), default: 2021-03-01",
    )
    parser.add_argument(
        "--end-close-day",
        default=None,
        help="Last ET close day (YYYY-MM-DD). Default: latest closed ET noon day.",
    )
    parser.add_argument(
        "--output",
        default="docs/plandaily.md",
        help="Output markdown path",
    )
    parser.add_argument(
        "--start-hour",
        type=int,
        default=16,
        help="Largest checkpoint hour (T-start_hour), default 16",
    )
    parser.add_argument(
        "--end-hour",
        type=int,
        default=1,
        help="Smallest checkpoint hour (T-end_hour), default 1",
    )
    return parser.parse_args()


def default_end_close_day() -> dt.date:
    now_et = dt.datetime.now(tz=ET)
    noon_today_et = dt.datetime.combine(now_et.date(), dt.time(12, 0), ET)
    if now_et >= noon_today_et:
        return now_et.date()
    return now_et.date() - dt.timedelta(days=1)


def iter_close_days(start_day: dt.date, end_day: dt.date):
    total = (end_day - start_day).days
    for i in range(total + 1):
        yield start_day + dt.timedelta(days=i)


def fetch_klines_1h(symbol: str, start_ms: int, end_ms: int) -> list[list]:
    rows: list[list] = []
    cursor = start_ms
    while cursor < end_ms:
        params = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "interval": "1h",
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        url = f"{BINANCE_KLINES_URL}?{params}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            batch = json.loads(resp.read().decode("utf-8"))
        if not batch:
            break
        rows.extend(batch)
        last_open_ms = int(batch[-1][0])
        nxt = last_open_ms + ONE_HOUR_MS
        if nxt <= cursor:
            break
        cursor = nxt
    return rows


def fmt_pct(v: float) -> str:
    # Keep concise labels while preserving 0.25/0.5 steps.
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    if "." not in s:
        s = f"{s}.0"
    return s


def bin_labels(step: float, max_pct: float) -> list[str]:
    bins = []
    n = round(max_pct / step)
    for i in range(n):
        lo = i * step
        hi = (i + 1) * step
        bins.append(f"{fmt_pct(lo)}-{fmt_pct(hi)}%")
    return bins


def build_bins(step: float, max_pct: float) -> list[tuple[float, float]]:
    n = round(max_pct / step)
    return [(i * step, (i + 1) * step) for i in range(n)]


def pick_bin_idx(value_pct: float, bins: list[tuple[float, float]]) -> int:
    if value_pct < 0:
        return -1
    for i, (lo, hi) in enumerate(bins):
        is_last = i + 1 == len(bins)
        if value_pct >= lo and (value_pct < hi or (is_last and value_pct <= hi)):
            return i
    return -1


def et_noon_ts(day: dt.date) -> int:
    d = dt.datetime.combine(day, dt.time(12, 0), ET)
    return int(d.astimezone(UTC).timestamp())


def generate_table(
    spec: SymbolSpec,
    start_close_day: dt.date,
    end_close_day: dt.date,
    checkpoint_hours: list[int],
) -> tuple[int, dict[int, dict[str, list[tuple[int, int]]]]]:
    # Pull a little extra on both ends to avoid boundary misses.
    first_open_day = start_close_day - dt.timedelta(days=1)
    fetch_start_utc = dt.datetime.combine(first_open_day, dt.time(0, 0), UTC)
    fetch_end_utc = dt.datetime.combine(end_close_day + dt.timedelta(days=1), dt.time(23, 59), UTC)

    rows = fetch_klines_1h(
        spec.symbol,
        int(fetch_start_utc.timestamp() * 1000),
        int(fetch_end_utc.timestamp() * 1000),
    )
    if not rows:
        msg = f"no kline data fetched for {spec.symbol}"
        raise RuntimeError(msg)

    # Price at exact hour boundary:
    # - open_price[t] is 1h candle open at t
    # - close_price[t] is 1h candle close at t
    open_price: dict[int, float] = {}
    close_price: dict[int, float] = {}
    for row in rows:
        open_ts = int(row[0] // 1000)
        open_price[open_ts] = float(row[1])
        close_price[open_ts + ONE_HOUR_SEC] = float(row[4])

    bins = build_bins(spec.step_pct, spec.max_pct)
    checkpoints = {
        h: {
            "Weekday": [(0, 0) for _ in bins],  # (flips, n)
            "Weekend": [(0, 0) for _ in bins],
        }
        for h in checkpoint_hours
    }

    total_windows = 0
    for close_day in iter_close_days(start_close_day, end_close_day):
        close_ts = et_noon_ts(close_day)
        open_ts = et_noon_ts(close_day - dt.timedelta(days=1))

        base = open_price.get(open_ts)
        final = close_price.get(close_ts)
        if final is None:
            final = open_price.get(close_ts)
        if base is None or final is None or base <= 0.0:
            continue

        total_windows += 1
        group = "Weekday" if close_day.weekday() < 5 else "Weekend"

        final_dir = 1 if (final - base) >= 0.0 else -1

        for h in checkpoint_hours:
            checkpoint_ts = close_ts - h * ONE_HOUR_SEC
            current = open_price.get(checkpoint_ts)
            if current is None:
                continue
            lead = (current - base) / base
            lead_pct = abs(lead) * 100.0
            # coverage rule: exclude >= max upper bound
            if lead_pct >= spec.max_pct:
                continue

            idx = pick_bin_idx(lead_pct, bins)
            if idx < 0:
                continue

            lead_dir = 1 if lead >= 0.0 else -1
            flip = 1 if final_dir != lead_dir else 0

            flips, n = checkpoints[h][group][idx]
            checkpoints[h][group][idx] = (flips + flip, n + 1)

    return total_windows, checkpoints


def render_markdown(
    specs: list[SymbolSpec],
    start_close_day: dt.date,
    end_close_day: dt.date,
    checkpoint_hours: list[int],
    tables: dict[str, tuple[int, dict[int, dict[str, list[tuple[int, int]]]]]],
) -> str:
    now_utc = dt.datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: list[str] = []
    lines.append("# 1D Crypto Bonding — Daily Reversal Analysis (Noon-to-Noon ET)")
    lines.append("")
    lines.append(f"**Generated:** {now_utc}")
    lines.append("**Source:** Binance public API (`api.binance.com/api/v3/klines`), 1h candles")
    lines.append(f"**Period:** {start_close_day.isoformat()} → {end_close_day.isoformat()}")
    lines.append("**Symbols:** " + ", ".join(spec.symbol for spec in specs))
    lines.append("**Windows:** Noon-to-noon ET (DST-corrected)")
    lines.append("**Grouping:** 2 buckets by ET close day: `Weekday` (Mon-Fri), `Weekend` (Sat-Sun)")
    lines.append(f"**Checkpoints:** T-{max(checkpoint_hours)}h through T-{min(checkpoint_hours)}h, hourly")
    lines.append(
        "**Lead bins (per symbol):** BTC uses `0.25%` steps to `5.0%`; ETH/SOL/XRP use `0.5%` steps to `10.0%`"
    )
    lines.append("**Coverage rule:** lead >= symbol max bin upper bound is excluded (no clamp)")
    lines.append("")

    for spec in specs:
        window_count, checkpoint_data = tables[spec.display]
        labels = bin_labels(spec.step_pct, spec.max_pct)

        lines.append(f"## {spec.display} — Noon-to-Noon ET ({window_count} windows)")
        lines.append("")

        for h in checkpoint_hours:
            lines.append(f"### {spec.display} — T-{h}h ({window_count} windows)")
            lines.append("")

            header = "| Window | " + " | ".join(labels) + " |"
            align = "|---|" + "---|" * len(labels)
            lines.append(header)
            lines.append(align)

            for group in ("Weekday", "Weekend"):
                cells = []
                for flips, n in checkpoint_data[h][group]:
                    if n <= 0:
                        cells.append("—")
                    else:
                        cells.append(f"{flips}/{n}")
                lines.append(f"| {group} | " + " | ".join(cells) + " |")

            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()

    start_close_day = dt.date.fromisoformat(args.start_close_day)
    end_close_day = dt.date.fromisoformat(args.end_close_day) if args.end_close_day else default_end_close_day()

    if end_close_day < start_close_day:
        msg = "end-close-day is before start-close-day"
        raise SystemExit(msg)

    if args.start_hour < args.end_hour or args.end_hour <= 0:
        msg = "checkpoint hours must satisfy start_hour >= end_hour >= 1"
        raise SystemExit(msg)

    checkpoint_hours = list(range(args.start_hour, args.end_hour - 1, -1))

    specs = [
        SymbolSpec("BTCUSDT", "BTC", 0.25, 5.0),
        SymbolSpec("ETHUSDT", "ETH", 0.5, 10.0),
        SymbolSpec("SOLUSDT", "SOL", 0.5, 10.0),
        SymbolSpec("XRPUSDT", "XRP", 0.5, 10.0),
    ]

    tables: dict[str, tuple[int, dict[int, dict[str, list[tuple[int, int]]]]]] = {}
    for spec in specs:
        print(f"[plandaily] fetching/building {spec.symbol} ...", file=sys.stderr)
        tables[spec.display] = generate_table(spec, start_close_day, end_close_day, checkpoint_hours)

    md = render_markdown(specs, start_close_day, end_close_day, checkpoint_hours, tables)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"[plandaily] wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
