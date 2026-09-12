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


#!/usr/bin/env python3
"""
Backtest EVcurve D1 gap threshold selection from 2021-03-01 onward.

This script simulates d1_ev trades using:
  - docs/plandaily.md tables (p_flip, n, bins, checkpoints)
  - Binance 1h candles (base/current/final direction)
  - Calibrated synthetic Polymarket implied flip probability from local
    evcurve 1d logs (events.jsonl*)

Modeling choices (defaults):
  - conservative synthetic ask = market_prob + spread_buffer + impact_buffer
  - min cell sample gate n >= 150
  - gap grid search in [0.02, 0.20] step 0.01
  - per-trade stake = 500 USD
"""


import argparse
import datetime as dt
import glob
import itertools
import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

UTC = dt.UTC
ET = ZoneInfo("America/New_York")
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
ONE_HOUR_SEC = 3600
ONE_HOUR_MS = 3_600_000

SYMBOLS = ("BTC", "ETH", "SOL", "XRP")
BINANCE_SYMBOL = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "XRP": "XRPUSDT",
}


@dataclass(frozen=True)
class PlanDailyCell:
    flips: int
    n: int


@dataclass(frozen=True)
class LeadBinRange:
    low_pct: float
    high_pct: float


@dataclass(frozen=True)
class LookupResult:
    flips: int
    n: int
    p_flip: float
    p_hold: float
    lead_bin_idx: int
    tau_low_sec: int
    tau_high_sec: int


@dataclass(frozen=True)
class Opportunity:
    symbol: str
    close_day: dt.date
    ts_ms: int
    tau_sec: int
    group_key: str
    hold_side: str
    buy_side: str
    lead_bin_idx: int
    n: int
    flips: int
    p_flip: float
    p_hold: float
    p_flip_market: float
    gap_abs: float
    ask: float
    max_buy: float
    final_dir: str

    @property
    def win(self) -> bool:
        return self.buy_side == self.final_dir


@dataclass
class ThresholdMetrics:
    symbol: str
    gap: float
    trades: int
    wins: int
    losses: int
    win_rate: float
    pnl_usd: float
    avg_ask: float
    avg_gap: float
    avg_n: float
    max_drawdown_usd: float
    profit_factor: float
    expectancy_usd: float


class PlanDailyTablesPy:
    def __init__(self) -> None:
        self.cells: dict[tuple[str, str, int, int], PlanDailyCell] = {}
        self.bin_ranges: dict[str, list[LeadBinRange]] = {}
        self.checkpoints_by_symbol: dict[str, list[int]] = defaultdict(list)

    @staticmethod
    def _normalize_symbol(raw: str) -> str | None:
        s = raw.strip().upper()
        if s in ("BTC", "BTCUSDT"):
            return "BTC"
        if s in ("ETH", "ETHUSDT"):
            return "ETH"
        if s in ("SOL", "SOLUSDT", "SOLANA"):
            return "SOL"
        if s in ("XRP", "XRPUSDT"):
            return "XRP"
        return None

    @staticmethod
    def _canonical_group(raw: str) -> str | None:
        s = raw.strip().lower()
        if s.startswith("weekday"):
            return "weekday"
        if s.startswith("weekend"):
            return "weekend"
        return None

    @staticmethod
    def _tau_label_to_sec(raw: str) -> int | None:
        compact = raw.strip().lower().replace(" ", "")
        marker = compact.find("t-")
        if marker < 0:
            return None
        rest = compact[marker + 2 :]
        digits_chars: list[str] = []
        for ch in rest:
            if ch.isdigit():
                digits_chars.append(ch)
            else:
                break
        digits = "".join(digits_chars)
        if not digits:
            return None
        val = int(digits)
        if "h" in rest:
            return val * 3600
        if "m" in rest:
            return val * 60
        return val

    @staticmethod
    def _parse_bin(raw: str) -> LeadBinRange | None:
        cleaned = raw.strip().rstrip("%").replace(",", "").replace(" ", "")
        if "-" not in cleaned:
            return None
        a, b = cleaned.split("-", 1)
        try:
            low = float(a)
            high = float(b)
        except ValueError:
            return None
        if not math.isfinite(low) or not math.isfinite(high) or high < low:
            return None
        return LeadBinRange(low, high)

    @staticmethod
    def _parse_flips_n(raw: str) -> PlanDailyCell | None:
        v = raw.strip().strip("`").replace(",", "").replace(" ", "")
        if not v or v in ("—", "-") or "/" not in v:
            return None
        left, right = v.split("/", 1)
        try:
            flips = int(left)
            n = int(right)
        except ValueError:
            return None
        if n <= 0:
            return None
        return PlanDailyCell(flips=flips, n=n)

    @staticmethod
    def _split_cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    @classmethod
    def load(cls, path: Path) -> PlanDailyTablesPy:
        text = path.read_text(encoding="utf-8")
        out = cls()
        lines = text.splitlines()
        i = 0
        context_symbol: str | None = None
        context_tau_sec: int | None = None

        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("### ") and " — " in line:
                left, right = line[4:].split(" — ", 1)
                context_symbol = cls._normalize_symbol(left)
                context_tau_sec = cls._tau_label_to_sec(right)
                i += 1
                continue

            if (
                context_symbol is not None
                and context_tau_sec is not None
                and line.startswith("|")
                and i + 1 < len(lines)
                and lines[i + 1].strip().startswith("|")
            ):
                headers = cls._split_cells(lines[i].strip())
                i += 2
                rows: list[list[str]] = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    rows.append(cls._split_cells(lines[i].strip()))
                    i += 1

                if headers and headers[0].lower() == "window":
                    bins = [cls._parse_bin(h) for h in headers[1:]]
                    if any(b is not None for b in bins):
                        out.bin_ranges[context_symbol] = [b for b in bins if b is not None]
                    out.checkpoints_by_symbol[context_symbol].append(context_tau_sec)

                    for row in rows:
                        if len(row) < 2:
                            continue
                        group = cls._canonical_group(row[0])
                        if group is None:
                            continue
                        for idx, cell_raw in enumerate(row[1:]):
                            cell = cls._parse_flips_n(cell_raw)
                            if cell is None:
                                continue
                            out.cells[(context_symbol, group, context_tau_sec, idx)] = cell
                context_symbol = None
                context_tau_sec = None
                continue

            i += 1

        for sym in list(out.checkpoints_by_symbol.keys()):
            unique = sorted(set(out.checkpoints_by_symbol[sym]))
            out.checkpoints_by_symbol[sym] = unique

        if not out.cells:
            msg = f"no plandaily cells parsed from {path}"
            raise RuntimeError(msg)
        return out

    def checkpoints_for_symbol(self, symbol: str) -> list[int]:
        return list(self.checkpoints_by_symbol.get(symbol, []))

    def bin_index_for_lead(self, symbol: str, lead_pct: float) -> int | None:
        bins = self.bin_ranges.get(symbol)
        if not bins:
            return None
        lead = max(0.0, lead_pct)
        for idx, r in enumerate(bins):
            is_last = idx + 1 == len(bins)
            if lead >= r.low_pct and (lead < r.high_pct or (is_last and lead <= r.high_pct)):
                return idx
        return None

    def lookup(
        self,
        symbol: str,
        group_key: str,
        tau_sec: int,
        lead_pct: float,
    ) -> LookupResult | None:
        bin_idx = self.bin_index_for_lead(symbol, lead_pct)
        if bin_idx is None:
            return None
        checkpoints = self.checkpoints_for_symbol(symbol)
        if not checkpoints:
            return None
        tau_low, tau_high, w_high = interpolation_bounds(checkpoints, max(0, tau_sec))
        low = self.cells.get((symbol, group_key, tau_low, bin_idx))
        high = self.cells.get((symbol, group_key, tau_high, bin_idx))
        if low is None and high is None:
            return None

        if low is not None and high is not None and tau_low != tau_high:
            p_a = low.flips / low.n
            p_b = high.flips / high.n
            p = p_a + (p_b - p_a) * w_high
            n_interp = round(low.n + (high.n - low.n) * w_high)
            n = max(1, n_interp)
            flips = round(p * n)
            p_flip = min(1.0, max(0.0, p))
            return LookupResult(
                flips=flips,
                n=n,
                p_flip=p_flip,
                p_hold=min(1.0, max(0.0, 1.0 - p_flip)),
                lead_bin_idx=bin_idx,
                tau_low_sec=tau_low,
                tau_high_sec=tau_high,
            )

        cell = low if low is not None else high
        assert cell is not None
        p_flip = min(1.0, max(0.0, cell.flips / cell.n))
        return LookupResult(
            flips=cell.flips,
            n=cell.n,
            p_flip=p_flip,
            p_hold=min(1.0, max(0.0, 1.0 - p_flip)),
            lead_bin_idx=bin_idx,
            tau_low_sec=tau_low,
            tau_high_sec=tau_high,
        )


def interpolation_bounds(checkpoints: Sequence[int], tau_sec: int) -> tuple[int, int, float]:
    if not checkpoints:
        return tau_sec, tau_sec, 0.0
    sorted_cp = sorted(checkpoints)
    tau = max(0, tau_sec)
    if tau <= sorted_cp[0]:
        return sorted_cp[0], sorted_cp[0], 0.0
    if tau >= sorted_cp[-1]:
        return sorted_cp[-1], sorted_cp[-1], 0.0
    for low, high in itertools.pairwise(sorted_cp):
        if low <= tau <= high:
            if high == low:
                return low, high, 0.0
            w = (tau - low) / (high - low)
            return low, high, min(1.0, max(0.0, w))
    return sorted_cp[-1], sorted_cp[-1], 0.0


def parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def default_end_close_day() -> dt.date:
    now_et = dt.datetime.now(tz=ET)
    noon_today = dt.datetime.combine(now_et.date(), dt.time(12, 0), ET)
    return now_et.date() if now_et >= noon_today else (now_et.date() - dt.timedelta(days=1))


def et_noon_ts(day: dt.date) -> int:
    return int(dt.datetime.combine(day, dt.time(12, 0), ET).astimezone(UTC).timestamp())


def group_key_for_close_day(close_day: dt.date) -> str:
    return "weekday" if close_day.weekday() < 5 else "weekend"


def clamp01(v: float) -> float:
    return min(0.99, max(0.01, v))


def fetch_klines_1h(symbol: str, start_ms: int, end_ms: int) -> list[list]:
    rows: list[list] = []
    cursor = start_ms
    retries = 0
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
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                batch = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            retries += 1
            if retries > 6:
                msg = f"failed to fetch {symbol} klines at cursor={cursor}: {exc}"
                raise RuntimeError(msg) from exc
            sleep_s = min(8.0, 0.5 * (2 ** (retries - 1)))
            time.sleep(sleep_s)
            continue

        retries = 0
        if not batch:
            break
        rows.extend(batch)
        last_open_ms = int(batch[-1][0])
        nxt = last_open_ms + ONE_HOUR_MS
        if nxt <= cursor:
            break
        cursor = nxt
        # Mild pacing to reduce chance of public API throttling.
        time.sleep(0.02)
    return rows


def load_symbol_prices(
    symbol: str, start_close_day: dt.date, end_close_day: dt.date
) -> tuple[dict[int, float], dict[int, float]]:
    first_open_day = start_close_day - dt.timedelta(days=1)
    fetch_start_utc = dt.datetime.combine(first_open_day, dt.time(0, 0), UTC)
    fetch_end_utc = dt.datetime.combine(end_close_day + dt.timedelta(days=1), dt.time(23, 59), UTC)
    rows = fetch_klines_1h(
        BINANCE_SYMBOL[symbol],
        int(fetch_start_utc.timestamp() * 1000),
        int(fetch_end_utc.timestamp() * 1000),
    )
    if not rows:
        msg = f"no klines returned for {symbol}"
        raise RuntimeError(msg)
    open_price: dict[int, float] = {}
    close_price: dict[int, float] = {}
    for row in rows:
        open_ts = int(row[0] // 1000)
        open_px = float(row[1])
        close_px = float(row[4])
        open_price[open_ts] = open_px
        close_price[open_ts + ONE_HOUR_SEC] = close_px
    return open_price, close_price


class DeltaCalibrator:
    """
    Hierarchical median-delta model:
      delta = p_flip_market - p_flip
      p_flip_market_hat = clamp01(p_flip + delta_hat)

    Fallback order:
      (symbol,tau,lead_bin,group,hold_side)
      (symbol,tau,lead_bin,group)
      (symbol,tau,lead_bin)
      (symbol,tau)
      (symbol,)
      global
    """

    def __init__(self) -> None:
        self.level_maps: list[dict[tuple, float]] = [{} for _ in range(6)]
        self.level_counts: list[dict[tuple, int]] = [{} for _ in range(6)]
        self.global_delta = 0.0

    @staticmethod
    def from_event_logs(glob_expr: str) -> DeltaCalibrator:
        files = sorted(glob.glob(glob_expr))
        if not files:
            msg = f"no event files found for glob: {glob_expr}"
            raise RuntimeError(msg)

        levels: list[defaultdict] = [defaultdict(list) for _ in range(6)]
        global_deltas: list[float] = []

        for fn in files:
            with open(fn, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "evcurve_checkpoint_decision" not in line or '"timeframe":"1d"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("kind") != "evcurve_checkpoint_decision":
                        continue
                    p = obj.get("payload", {})
                    if p.get("strategy_id") != "evcurve_v1":
                        continue
                    if p.get("timeframe") != "1d" or p.get("sub_strategy") != "d1_ev":
                        continue

                    symbol = p.get("symbol")
                    tau_sec = p.get("tau_sec")
                    lead_bin_idx = p.get("lead_bin_idx")
                    group_key = p.get("group_key")
                    hold_side = p.get("chosen_side")
                    p_flip = p.get("p_flip")
                    p_flip_market = p.get("p_flip_market")
                    if (
                        symbol not in SYMBOLS
                        or not isinstance(tau_sec, int)
                        or not isinstance(lead_bin_idx, int)
                        or not isinstance(group_key, str)
                        or hold_side not in ("UP", "DOWN")
                        or not isinstance(p_flip, (int, float))
                        or not isinstance(p_flip_market, (int, float))
                    ):
                        continue
                    p_flip = float(p_flip)
                    p_flip_market = float(p_flip_market)
                    if not (math.isfinite(p_flip) and math.isfinite(p_flip_market)):
                        continue
                    delta = p_flip_market - p_flip
                    if not math.isfinite(delta):
                        continue

                    levels[0][(symbol, tau_sec, lead_bin_idx, group_key, hold_side)].append(delta)
                    levels[1][(symbol, tau_sec, lead_bin_idx, group_key)].append(delta)
                    levels[2][(symbol, tau_sec, lead_bin_idx)].append(delta)
                    levels[3][(symbol, tau_sec)].append(delta)
                    levels[4][(symbol,)].append(delta)
                    levels[5][("global",)].append(delta)
                    global_deltas.append(delta)

        if not global_deltas:
            msg = "no usable evcurve 1d calibration rows found in events logs"
            raise RuntimeError(msg)

        model = DeltaCalibrator()
        model.global_delta = statistics.median(global_deltas)
        for lvl_idx, bucket in enumerate(levels):
            for k, vals in bucket.items():
                model.level_maps[lvl_idx][k] = statistics.median(vals)
                model.level_counts[lvl_idx][k] = len(vals)
        return model

    def predict_p_flip_market(
        self,
        symbol: str,
        tau_sec: int,
        lead_bin_idx: int,
        group_key: str,
        hold_side: str,
        p_flip: float,
    ) -> float:
        keys = [
            (symbol, tau_sec, lead_bin_idx, group_key, hold_side),
            (symbol, tau_sec, lead_bin_idx, group_key),
            (symbol, tau_sec, lead_bin_idx),
            (symbol, tau_sec),
            (symbol,),
            ("global",),
        ]
        delta = None
        for lvl_idx, key in enumerate(keys):
            delta = self.level_maps[lvl_idx].get(key)
            if delta is not None:
                break
        if delta is None:
            delta = self.global_delta
        return clamp01(p_flip + delta)


def evaluate_threshold(
    symbol: str,
    opportunities: Sequence[Opportunity],
    gap_threshold: float,
    min_cell_n: int,
    stake_usd: float,
) -> ThresholdMetrics:
    selected = [
        o
        for o in opportunities
        if o.symbol == symbol and o.n >= min_cell_n and o.gap_abs >= gap_threshold and o.ask <= o.max_buy
    ]
    selected = sorted(selected, key=lambda x: x.ts_ms)

    pnls: list[float] = []
    wins = 0
    losses = 0
    gross_win = 0.0
    gross_loss = 0.0
    for o in selected:
        shares = stake_usd / o.ask
        pnl = shares - stake_usd if o.win else -stake_usd
        pnls.append(pnl)
        if pnl >= 0.0:
            wins += 1
            gross_win += pnl
        else:
            losses += 1
            gross_loss += abs(pnl)

    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        cum += pnl
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)

    trades = len(selected)
    win_rate = (wins / trades) if trades > 0 else 0.0
    pnl_usd = sum(pnls)
    avg_ask = (sum(o.ask for o in selected) / trades) if trades else 0.0
    avg_gap = (sum(o.gap_abs for o in selected) / trades) if trades else 0.0
    avg_n = (sum(o.n for o in selected) / trades) if trades else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    expectancy = (pnl_usd / trades) if trades > 0 else 0.0
    return ThresholdMetrics(
        symbol=symbol,
        gap=gap_threshold,
        trades=trades,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        pnl_usd=pnl_usd,
        avg_ask=avg_ask,
        avg_gap=avg_gap,
        avg_n=avg_n,
        max_drawdown_usd=max_dd,
        profit_factor=profit_factor,
        expectancy_usd=expectancy,
    )


def choose_best_gap(metrics: Sequence[ThresholdMetrics], min_trades: int) -> ThresholdMetrics | None:
    eligible = [m for m in metrics if m.trades >= min_trades]
    if not eligible:
        eligible = [m for m in metrics if m.trades > 0]
    if not eligible:
        return None
    # Higher pnl is primary. Then less severe drawdown, then higher win rate, then more trades.
    eligible.sort(
        key=lambda m: (
            m.pnl_usd,
            m.max_drawdown_usd,  # closer to zero is better
            m.win_rate,
            m.trades,
        ),
        reverse=True,
    )
    return eligible[0]


def parse_threshold_grid(spec: str) -> list[float]:
    if ":" in spec:
        parts = spec.split(":")
        if len(parts) != 3:
            msg = "threshold grid format must be start:stop:step"
            raise ValueError(msg)
        start, stop, step = map(float, parts)
        out: list[float] = []
        cur = start
        while cur <= stop + 1e-12:
            out.append(round(cur, 6))
            cur += step
        return out
    out = [float(x.strip()) for x in spec.split(",") if x.strip()]
    if not out:
        msg = "empty threshold grid"
        raise ValueError(msg)
    return out


def iter_close_days(start_day: dt.date, end_day: dt.date) -> Iterable[dt.date]:
    span = (end_day - start_day).days
    for i in range(span + 1):
        yield start_day + dt.timedelta(days=i)


def build_opportunities(
    tables: PlanDailyTablesPy,
    calibrator: DeltaCalibrator,
    start_close_day: dt.date,
    end_close_day: dt.date,
    spread_buffer: float,
    impact_buffer: float,
) -> list[Opportunity]:
    opportunities: list[Opportunity] = []

    for symbol in SYMBOLS:
        print(f"[backtest] fetching Binance 1h candles for {symbol}...", file=sys.stderr)
        open_px, close_px = load_symbol_prices(symbol, start_close_day, end_close_day)
        checkpoints = tables.checkpoints_for_symbol(symbol)
        if not checkpoints:
            print(f"[backtest] WARN no checkpoints in plandaily for {symbol}", file=sys.stderr)
            continue

        for close_day in iter_close_days(start_close_day, end_close_day):
            open_ts = et_noon_ts(close_day - dt.timedelta(days=1))
            close_ts = et_noon_ts(close_day)
            base = open_px.get(open_ts)
            final = close_px.get(close_ts)
            if final is None:
                final = open_px.get(close_ts)
            if base is None or final is None or base <= 0.0:
                continue
            final_dir = "UP" if (final - base) >= 0.0 else "DOWN"
            group_key = group_key_for_close_day(close_day)

            for tau_sec in checkpoints:
                checkpoint_ts = close_ts - tau_sec
                current = open_px.get(checkpoint_ts)
                if current is None:
                    continue
                lead_pct = abs(current - base) / max(base, 1e-12) * 100.0
                lookup = tables.lookup(symbol, group_key, tau_sec, lead_pct)
                if lookup is None:
                    continue

                hold_side = "UP" if current >= base else "DOWN"
                flip_side = "DOWN" if hold_side == "UP" else "UP"
                p_flip_market = calibrator.predict_p_flip_market(
                    symbol=symbol,
                    tau_sec=tau_sec,
                    lead_bin_idx=lookup.lead_bin_idx,
                    group_key=group_key,
                    hold_side=hold_side,
                    p_flip=lookup.p_flip,
                )
                gap_abs = abs(lookup.p_flip - p_flip_market)

                buy_side = flip_side if lookup.p_flip > p_flip_market else hold_side
                market_side_prob = p_flip_market if buy_side == flip_side else (1.0 - p_flip_market)
                ask = clamp01(market_side_prob + spread_buffer + impact_buffer)
                max_buy = lookup.p_flip if buy_side == flip_side else lookup.p_hold
                ts_ms = checkpoint_ts * 1000

                opportunities.append(
                    Opportunity(
                        symbol=symbol,
                        close_day=close_day,
                        ts_ms=ts_ms,
                        tau_sec=tau_sec,
                        group_key=group_key,
                        hold_side=hold_side,
                        buy_side=buy_side,
                        lead_bin_idx=lookup.lead_bin_idx,
                        n=lookup.n,
                        flips=lookup.flips,
                        p_flip=lookup.p_flip,
                        p_hold=lookup.p_hold,
                        p_flip_market=p_flip_market,
                        gap_abs=gap_abs,
                        ask=ask,
                        max_buy=max_buy,
                        final_dir=final_dir,
                    )
                )

    return opportunities


def format_metrics_row(m: ThresholdMetrics) -> str:
    pf = "inf" if math.isinf(m.profit_factor) else f"{m.profit_factor:.3f}"
    return (
        f"gap={m.gap:.3f} "
        f"trades={m.trades} "
        f"win={m.wins}/{m.trades} ({m.win_rate * 100:.2f}%) "
        f"pnl={m.pnl_usd:+.3f} "
        f"dd={m.max_drawdown_usd:.3f} "
        f"pf={pf} "
        f"exp={m.expectancy_usd:+.3f} "
        f"avg_ask={m.avg_ask:.3f} "
        f"avg_gap={m.avg_gap:.3f} "
        f"avg_n={m.avg_n:.1f}"
    )


def write_report(
    out_path: Path,
    args: argparse.Namespace,
    per_symbol_best_full: dict[str, ThresholdMetrics | None],
    per_symbol_best_train: dict[str, ThresholdMetrics | None],
    per_symbol_train_eval_on_train_gap: dict[str, ThresholdMetrics | None],
    per_symbol_test_eval_on_train_gap: dict[str, ThresholdMetrics | None],
    per_symbol_all_metrics: dict[str, list[ThresholdMetrics]],
    opportunities: list[Opportunity],
    calibrator: DeltaCalibrator,
) -> None:
    now = dt.datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = []
    lines.append("# D1 EVcurve Gap Backtest")
    lines.append("")
    lines.append(f"- Generated: {now}")
    lines.append(f"- Start close day: {args.start_close_day}")
    lines.append(f"- End close day: {args.end_close_day}")
    lines.append(f"- Stake per trade: {args.stake_usd:.2f} USD")
    lines.append(f"- Min cell n gate: {args.min_cell_n}")
    lines.append(f"- Min trades for best-gap eligibility: {args.min_trades}")
    lines.append(
        f"- Synthetic ask model: market_prob + spread({args.spread_buffer:.4f}) + impact({args.impact_buffer:.4f})"
    )
    lines.append(f"- Threshold grid: {args.thresholds}")
    lines.append(f"- Train/Test split close day: {args.split_close_day}")
    lines.append(f"- Calibration files: {args.calibration_glob}")
    lines.append("")

    lines.append("## Calibration Coverage")
    lines.append("")
    for sym in SYMBOLS:
        n_sym = calibrator.level_counts[4].get((sym,), 0)
        lines.append(f"- {sym}: {n_sym} d1_ev rows")
    lines.append(f"- Global rows: {calibrator.level_counts[5].get(('global',), 0)}")
    lines.append("")

    lines.append("## Best Gap (Full Window)")
    lines.append("")
    for sym in SYMBOLS:
        m = per_symbol_best_full.get(sym)
        if m is None:
            lines.append(f"- {sym}: no eligible trades")
        else:
            lines.append(f"- {sym}: {format_metrics_row(m)}")
    lines.append("")

    lines.append("## Train-Selected Gap -> Train/Test")
    lines.append("")
    for sym in SYMBOLS:
        best_train = per_symbol_best_train.get(sym)
        train_eval = per_symbol_train_eval_on_train_gap.get(sym)
        test_eval = per_symbol_test_eval_on_train_gap.get(sym)
        if best_train is None or train_eval is None or test_eval is None:
            lines.append(f"- {sym}: no eligible train/test evaluation")
            continue
        lines.append(f"- {sym}: selected_gap={best_train.gap:.3f}")
        lines.append(f"  - train: {format_metrics_row(train_eval)}")
        lines.append(f"  - test:  {format_metrics_row(test_eval)}")
    lines.append("")

    lines.append("## Gap Grid Details")
    lines.append("")
    for sym in SYMBOLS:
        lines.append(f"### {sym}")
        rows = per_symbol_all_metrics.get(sym, [])
        if not rows:
            lines.append("- no rows")
            lines.append("")
            continue
        for m in rows:
            lines.append(f"- {format_metrics_row(m)}")
        lines.append("")

    lines.append("## Opportunity Counts")
    lines.append("")
    by_symbol = defaultdict(int)
    by_symbol_pass_n = defaultdict(int)
    for o in opportunities:
        by_symbol[o.symbol] += 1
        if o.n >= args.min_cell_n:
            by_symbol_pass_n[o.symbol] += 1
    for sym in SYMBOLS:
        lines.append(f"- {sym}: total_opportunities={by_symbol[sym]} with_n>={args.min_cell_n}={by_symbol_pass_n[sym]}")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest EVcurve D1 gap thresholds (2021-03-01 -> now) with synthetic PM pricing"
    )
    parser.add_argument("--plandaily", default="docs/plandaily.md")
    parser.add_argument("--start-close-day", default="2021-03-01")
    parser.add_argument("--end-close-day", default=None)
    parser.add_argument("--thresholds", default="0.02:0.20:0.01")
    parser.add_argument("--min-cell-n", type=int, default=150)
    parser.add_argument("--min-trades", type=int, default=30)
    parser.add_argument("--stake-usd", type=float, default=500.0)
    parser.add_argument("--spread-buffer", type=float, default=0.01)
    parser.add_argument("--impact-buffer", type=float, default=0.005)
    parser.add_argument("--calibration-glob", default="events.jsonl*")
    parser.add_argument("--split-close-day", default="2025-01-01")
    parser.add_argument(
        "--report-out",
        default=None,
        help="Markdown report path. Default: reports/d1_gap_optimization_<UTCSTAMP>.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.start_close_day = parse_date(args.start_close_day)
    args.end_close_day = parse_date(args.end_close_day) if args.end_close_day else default_end_close_day()
    args.split_close_day = parse_date(args.split_close_day)
    thresholds = parse_threshold_grid(args.thresholds)
    if args.end_close_day < args.start_close_day:
        msg = "end-close-day must be >= start-close-day"
        raise RuntimeError(msg)

    plandaily_path = Path(args.plandaily)
    if not plandaily_path.exists():
        msg = f"plandaily file not found: {plandaily_path}"
        raise RuntimeError(msg)
    tables = PlanDailyTablesPy.load(plandaily_path)

    calibrator = DeltaCalibrator.from_event_logs(args.calibration_glob)
    opportunities = build_opportunities(
        tables=tables,
        calibrator=calibrator,
        start_close_day=args.start_close_day,
        end_close_day=args.end_close_day,
        spread_buffer=args.spread_buffer,
        impact_buffer=args.impact_buffer,
    )
    if not opportunities:
        msg = "no opportunities generated"
        raise RuntimeError(msg)

    by_symbol = defaultdict(list)
    by_symbol_train = defaultdict(list)
    by_symbol_test = defaultdict(list)
    for o in opportunities:
        by_symbol[o.symbol].append(o)
        if o.close_day < args.split_close_day:
            by_symbol_train[o.symbol].append(o)
        else:
            by_symbol_test[o.symbol].append(o)

    per_symbol_all_metrics: dict[str, list[ThresholdMetrics]] = {}
    per_symbol_best_full: dict[str, ThresholdMetrics | None] = {}
    per_symbol_best_train: dict[str, ThresholdMetrics | None] = {}
    per_symbol_train_eval_on_train_gap: dict[str, ThresholdMetrics | None] = {}
    per_symbol_test_eval_on_train_gap: dict[str, ThresholdMetrics | None] = {}

    for sym in SYMBOLS:
        metrics_full = [evaluate_threshold(sym, by_symbol[sym], g, args.min_cell_n, args.stake_usd) for g in thresholds]
        per_symbol_all_metrics[sym] = metrics_full
        per_symbol_best_full[sym] = choose_best_gap(metrics_full, args.min_trades)

        metrics_train = [
            evaluate_threshold(sym, by_symbol_train[sym], g, args.min_cell_n, args.stake_usd) for g in thresholds
        ]
        best_train = choose_best_gap(metrics_train, args.min_trades)
        per_symbol_best_train[sym] = best_train
        if best_train is not None:
            per_symbol_train_eval_on_train_gap[sym] = evaluate_threshold(
                sym,
                by_symbol_train[sym],
                best_train.gap,
                args.min_cell_n,
                args.stake_usd,
            )
            per_symbol_test_eval_on_train_gap[sym] = evaluate_threshold(
                sym,
                by_symbol_test[sym],
                best_train.gap,
                args.min_cell_n,
                args.stake_usd,
            )
        else:
            per_symbol_train_eval_on_train_gap[sym] = None
            per_symbol_test_eval_on_train_gap[sym] = None

    out_path = (
        Path(args.report_out)
        if args.report_out
        else Path("reports") / f"d1_gap_optimization_{dt.datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}.md"
    )
    write_report(
        out_path=out_path,
        args=args,
        per_symbol_best_full=per_symbol_best_full,
        per_symbol_best_train=per_symbol_best_train,
        per_symbol_train_eval_on_train_gap=per_symbol_train_eval_on_train_gap,
        per_symbol_test_eval_on_train_gap=per_symbol_test_eval_on_train_gap,
        per_symbol_all_metrics=per_symbol_all_metrics,
        opportunities=opportunities,
        calibrator=calibrator,
    )

    print("=== D1 Gap Backtest Summary ===")
    print(f"window: {args.start_close_day} -> {args.end_close_day}")
    print(f"opportunities: {len(opportunities)}")
    for sym in SYMBOLS:
        best = per_symbol_best_full.get(sym)
        if best is None:
            print(f"{sym}: no eligible trades")
            continue
        print(
            f"{sym}: best_gap={best.gap:.3f} trades={best.trades} "
            f"win_rate={best.win_rate * 100:.2f}% pnl={best.pnl_usd:+.2f} dd={best.max_drawdown_usd:.2f}"
        )
    print(f"report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
