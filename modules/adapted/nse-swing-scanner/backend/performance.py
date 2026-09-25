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
performance.py
Forward-return attribution for the gate-passed cohort of each historical
snapshot. Implements the C1 plan item.

Statistical rules (per the strategic review §6 — non-negotiable):
  - Report per-scan-date cohorts, not pooled per-name rows (avoid the
    apparent N-inflation from overlapping T+20 windows across consecutive
    scans).
  - Report N per cohort, median + IQR (not just mean — small samples
    and skewed distributions make means misleading).
  - Mark untrackable symbols (delisted / suspended / yfinance fetch
    failed) as a separate bucket; never silently drop them.
  - window_not_closed is NOT untrackable — it is expected for recent
    snapshots and excluded from quality alarms.
  - Compute excess return per-name vs ^NSEI over the same window — pooled
    stock returns without subtracting the index overstate hit rate in
    bull regimes and understate it in bear regimes.
  - Report a deterministic bootstrap 95% CI for the cohort mean (seeded;
    None below BOOTSTRAP_MIN_N) so interval width is visible — cohorts
    are small and skewed, and a bare median invites over-reading.

Cohorts: T+5, T+10, T+20 trading sessions from the snapshot date.
Trailing window: matches snapshot retention (90 days).

This module is import-safe (no yfinance dependency at import time) so
it can be tested without network access.
"""

import contextlib
import json
import os
import random
import statistics
import time
from collections import Counter
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# Trading days to evaluate at. T+5/T+10/T+20 covers short and medium swing
# windows; widen cautiously — small-sample noise grows fast.
WINDOWS = [5, 10, 20]

# Bucket scheme history:
#   pass_v2 — 60+/55-59/50-54/<50. Fine bands showed 60-64 behaving
#             differently from 63+ while 55-59 was the worst cohort, so the
#             5-point bands hid the top-end inflection (1.4.0 review).
#   pass_v3 — current. Finer cut at the top (63+), weak band kept visible
#             (55-60) rather than merged away, mid-range left coarse
#             (45-55) where the fine-band signal is a coin flip. Cut points
#             come from the 2026-09-06 fine-band review of per_name rows
#             (69 snapshots, n=1454); not from an optimisation pass.
# BUCKET_BANDS pairs each label with its INCLUSIVE lower bound, descending.
# Anything below the last lower bound falls into "<45". Keep BUCKET_ORDER
# (display order, consumed by meta.buckets and the empty bucket maps) in sync.
BUCKET_SCHEME = "pass_v3"
BUCKET_BANDS = [("63+", 63), ("60-63", 60), ("55-60", 55), ("45-55", 45)]
BUCKET_ORDER = [label for label, _ in BUCKET_BANDS] + ["<45", "unknown"]

# Deterministic bootstrap CI for cohort means.
# BOOTSTRAP_SEED pins the resampling RNG so identical input always yields
# identical intervals — the weekly tracker output stays diffable/reproducible.
# BOOTSTRAP_ITERS=500 keeps the 2.5/97.5 percentile endpoints stable enough
# for display without a visible runtime cost in the weekly CLI.
# BOOTSTRAP_MIN_N: below ~30 the percentile bootstrap for a mean is mostly
# noise (and wide open); report None instead of a misleadingly precise
# -looking interval.
BOOTSTRAP_SEED = 20260906
BOOTSTRAP_ITERS = 500
BOOTSTRAP_MIN_N = 30

# Reasons that mean "not yet measurable" rather than fetch failure.
WINDOW_NOT_CLOSED = "window_not_closed"


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    """Linear-interpolated percentile (no numpy). p in [0, 100]."""
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return sorted_vals[0]
    k = (p / 100) * (n - 1)
    f = int(k)
    c = min(f + 1, n - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def cohort_stats(returns_pct: list[float]) -> dict:
    """
    Median + IQR + N + mean + hit_rate + bootstrap CI for one cohort.
    hit_rate = fraction with excess_return_pct > 0 (None when empty).
    ci95 = deterministic bootstrap 95% CI for the mean (None when n <
    BOOTSTRAP_MIN_N — see bootstrap_ci).
    """
    if not returns_pct:
        return {
            "n": 0,
            "median": None,
            "q1": None,
            "q3": None,
            "mean": None,
            "hit_rate": None,
            "ci95": None,
        }
    s = sorted(returns_pct)
    median = statistics.median(s)
    mean = statistics.fmean(s)
    q1 = _percentile(s, 25)
    q3 = _percentile(s, 75)
    hits = sum(1 for v in s if v > 0)
    return {
        "n": len(s),
        "median": round(median, 2),
        "q1": round(q1, 2) if q1 is not None else None,
        "q3": round(q3, 2) if q3 is not None else None,
        "mean": round(mean, 2),
        "hit_rate": round(hits / len(s), 3),
        "ci95": bootstrap_ci(s),
    }


def bootstrap_ci(sorted_vals: list[float]) -> dict | None:
    """
    Deterministic bootstrap 95% CI for the cohort MEAN (percentile method).

    Mean, not median: with BOOTSTRAP_ITERS resamples the mean's bootstrap
    distribution is smooth, while a median CI from an ordered sample is
    dominated by the middle order statistics (granular and sticky).
    Fixed BOOTSTRAP_SEED means repeated weekly runs produce identical
    output for identical input. Returns None below BOOTSTRAP_MIN_N.
    """
    n = len(sorted_vals)
    if n < BOOTSTRAP_MIN_N:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    means: list[float] = []
    for _ in range(BOOTSTRAP_ITERS):
        counts = Counter(rng.choices(range(n), k=n))
        means.append(sum(v * counts.get(i, 0) for i, v in enumerate(sorted_vals)) / n)
    means.sort()
    return {
        "low": round(_percentile(means, 2.5), 2),
        "high": round(_percentile(means, 97.5), 2),
    }


def score_bucket_pass_v2(score: float | None) -> str:
    """Legacy 1.3.x bucketing, kept for re-bucketing historical per_name rows."""
    if not isinstance(score, (int, float)):
        return "unknown"
    if score >= 60:
        return "60+"
    if score >= 55:
        return "55-59"
    if score >= 50:
        return "50-54"
    return "<50"


def score_bucket(score: float | None) -> str:
    """pass_v3 buckets — see BUCKET_BANDS / BUCKET_ORDER above."""
    if not isinstance(score, (int, float)):
        return "unknown"
    for label, lower in BUCKET_BANDS:
        if score >= lower:
            return label
    return "<45"


# Regime tag thresholds — mirror the frontend regime chip (scanPlan.js).
# risk_on: Nifty > +2% above 200EMA; risk_off: < -2%; neutral: in between.
def regime_tag(idx_pct_from_ema200: float | None) -> str:
    if not isinstance(idx_pct_from_ema200, (int, float)):
        return "unknown"
    if idx_pct_from_ema200 > 2:
        return "risk_on"
    if idx_pct_from_ema200 < -2:
        return "risk_off"
    return "neutral"


def _scan_regime(scan: dict) -> str:
    """Pick the regime tag for a whole snapshot from any row's
    market_index_pct_from_ema200 (universe-constant)."""
    for s in scan.get("stocks", []):
        v = s.get("market_index_pct_from_ema200")
        if isinstance(v, (int, float)):
            return regime_tag(v)
    return "unknown"


def _window_label(window: int) -> str:
    return f"T+{window}"


def _empty_bucket_map() -> dict[str, list[float]]:
    return {b: [] for b in BUCKET_ORDER}


def build_performance_payload(
    snapshots: list[tuple[str, dict]],
    forward_returns: dict[tuple[str, str], dict[int, dict]],
    *,
    retention_days: int = 90,
) -> dict:
    """
    Combine snapshot metadata with pre-computed forward returns into the
    `data/performance.json` payload.

    Args:
      snapshots: list of (snapshot_label, scan_payload) e.g.
                 [("2026-07-18-pm", {...}), ...] sorted ascending.
      forward_returns: dict keyed by (snapshot_label, symbol) -> {5: {...},
                 10: {...}, 20: {...}}. Each per-window dict has shape
                 {"stock_return_pct": float|None,
                  "index_return_pct": float|None,
                  "excess_return_pct": float|None,
                  "untrackable": bool,
                  "reason": str|None}.

    Returns a JSON-serialisable dict with five sections:
      - windows:    aggregated stats by (window, score_bucket)
      - by_regime:  aggregated stats by (window, regime) — calibration input
      - per_scan:   per-snapshot cohort stats (by window, with regime tag)
      - per_name:   raw labelled rows (snapshot, symbol, score, bucket,
                    regime, confirmation, windows) — calibration raw material
      - meta:       config + trackable / untrackable / window_not_closed counts
    """
    per_window_buckets: dict[int, dict[str, list[float]]] = {w: _empty_bucket_map() for w in WINDOWS}
    per_window_untrackable: dict[int, int] = dict.fromkeys(WINDOWS, 0)
    per_window_trackable: dict[int, int] = dict.fromkeys(WINDOWS, 0)
    per_window_not_closed: dict[int, int] = dict.fromkeys(WINDOWS, 0)
    per_window_reasons: dict[int, Counter] = {w: Counter() for w in WINDOWS}
    by_regime_buckets: dict[int, dict[str, list[float]]] = {
        w: {"risk_on": [], "neutral": [], "risk_off": [], "unknown": []} for w in WINDOWS
    }
    # Bucket x regime cross-tab (1.4.0 drawer table): per window,
    # per score bucket, per regime — {w: {bucket: {regime: [excess, ...]}}}
    by_regime_cross: dict[int, dict[str, dict[str, list[float]]]] = {
        w: {b: {rg: [] for rg in ("risk_on", "neutral", "risk_off", "unknown")} for b in BUCKET_ORDER} for w in WINDOWS
    }
    per_scan: list[dict] = []
    per_name: list[dict] = []

    for label, scan in snapshots:
        passed = [s for s in scan.get("stocks", []) if s.get("gate_pass")]
        scan_regime = _scan_regime(scan)
        bucket_excess: dict[int, dict[str, list[float]]] = {w: _empty_bucket_map() for w in WINDOWS}
        for s in passed:
            sym = s.get("symbol")
            key = (label, sym)
            fetches = forward_returns.get(key, {})
            bucket = score_bucket(s.get("swing_score"))
            confirmation = s.get("confirmation_state") or "unknown"
            name_row = {
                "snapshot": label,
                "symbol": sym,
                "score": s.get("swing_score"),
                "bucket": bucket,
                "regime": scan_regime,
                "confirmation": confirmation,
                # 1.5.0 feedback loop: raw component scores + the weights
                # regime that produced them, so evaluate_feedback.py can
                # re-score history under candidate weight sets.
                "sub_scores": s.get("sub_scores") if isinstance(s.get("sub_scores"), dict) else None,
                "score_version": s.get("score_version"),
                "windows": {},
            }
            for w in WINDOWS:
                fr = fetches.get(w)
                reason = fr.get("reason") if fr else "no_data"
                excess = fr.get("excess_return_pct") if fr else None
                untrackable = True if not fr else bool(fr.get("untrackable"))
                # window_not_closed: expected for recent snapshots — not a failure.
                if reason == WINDOW_NOT_CLOSED or (fr and fr.get("reason") == WINDOW_NOT_CLOSED):
                    per_window_not_closed[w] += 1
                    per_window_reasons[w][WINDOW_NOT_CLOSED] += 1
                    name_row["windows"][_window_label(w)] = {
                        "excess_return_pct": None,
                        "untrackable": False,
                        "reason": WINDOW_NOT_CLOSED,
                    }
                    continue
                if not fr or untrackable or excess is None:
                    per_window_untrackable[w] += 1
                    rsn = reason or "no_data"
                    per_window_reasons[w][rsn] += 1
                    name_row["windows"][_window_label(w)] = {
                        "excess_return_pct": None,
                        "untrackable": True,
                        "reason": rsn,
                    }
                    continue
                per_window_trackable[w] += 1
                per_window_buckets[w][bucket].append(excess)
                bucket_excess[w][bucket].append(excess)
                by_regime_buckets[w][scan_regime].append(excess)
                by_regime_cross[w][bucket][scan_regime].append(excess)
                name_row["windows"][_window_label(w)] = {
                    "excess_return_pct": excess,
                    "untrackable": False,
                    "reason": None,
                }
            per_name.append(name_row)

        cohort_summary = {
            "date": label,
            "passed_count": len(passed),
            "regime": scan_regime,
            "windows": {},
        }
        for w in WINDOWS:
            all_excess: list[float] = []
            for vals in bucket_excess[w].values():
                all_excess.extend(vals)
            cohort_summary["windows"][_window_label(w)] = {
                "n": len(all_excess),
                "stats": cohort_stats(all_excess),
            }
        per_scan.append(cohort_summary)

    out_windows = {}
    for w in WINDOWS:
        bucket_stats = {}
        for b, vals in per_window_buckets[w].items():
            bucket_stats[b] = cohort_stats(vals)
        regime_bucket_stats = {}
        for b in BUCKET_ORDER:
            regime_bucket_stats[b] = {rg: cohort_stats(vals) for rg, vals in by_regime_cross[w][b].items()}
        out_windows[_window_label(w)] = {
            "buckets": bucket_stats,
            # Bucket x regime cross-tab for the drawer evidence table.
            # Regime cohorts are small — cells carry their own n so the
            # frontend can suppress below its floor.
            "by_regime_buckets": regime_bucket_stats,
            "trackable_count": per_window_trackable[w],
            "untrackable_count": per_window_untrackable[w],
            "window_not_closed_count": per_window_not_closed[w],
            "reasons": dict(per_window_reasons[w]),
        }

    out_by_regime = {}
    for w in WINDOWS:
        regime_stats = {}
        for rg, vals in by_regime_buckets[w].items():
            regime_stats[rg] = cohort_stats(vals)
        out_by_regime[_window_label(w)] = regime_stats

    return {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "retention_days": retention_days,
        "windows": out_windows,
        "by_regime": out_by_regime,
        "per_scan": per_scan,
        "per_name": per_name,
        "meta": {
            "snapshots_used": len(snapshots),
            "total_passed": sum(
                len([s for s in scan.get("stocks", []) if s.get("gate_pass")]) for _, scan in snapshots
            ),
            "windows": WINDOWS,
            "regimes": ["risk_on", "neutral", "risk_off", "unknown"],
            "bucket_scheme": BUCKET_SCHEME,
            # Schemes that ever produced a committed performance.json.
            # per_name bucket labels are computed at build time with the
            # CURRENT scheme — regeneration re-buckets history from the
            # stored scores (lossless: score is the immutable source of
            # truth; score_bucket_pass_v2 is retained for old-scheme views).
            "bucket_scheme_history": ["pass_v2", "pass_v3"],
            "buckets": [b for b in BUCKET_ORDER if b != "unknown"],
            "trackable_count": {_window_label(w): per_window_trackable[w] for w in WINDOWS},
            "untrackable_count": {_window_label(w): per_window_untrackable[w] for w in WINDOWS},
            "window_not_closed_count": {_window_label(w): per_window_not_closed[w] for w in WINDOWS},
        },
    }


def write_performance_payload(payload: dict, output_path: str) -> None:
    """Pretty-print; the file is human-readable and small."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# --- Pure helpers (unit-tested, no network) ---------------------------------


def session_index_dates(session_dates: Sequence[datetime.date]) -> list[datetime.date]:
    """Return sorted unique session dates."""
    return sorted(set(session_dates))


def t_plus_session(
    sessions: Sequence[datetime.date],
    scan_date: datetime.date,
    window: int,
) -> datetime.date | None:
    """
    Map scan_date + T+window trading sessions using an ordered session calendar.
    scan_date is snapped to the first session on or after it (evening scans
    after the close still use that session as T+0).
    """
    if not sessions or window < 0:
        return None
    sess = list(sessions)
    # First session on or after scan_date
    start_i = None
    for i, d in enumerate(sess):
        if d >= scan_date:
            start_i = i
            break
    if start_i is None:
        return None
    target_i = start_i + window
    if target_i >= len(sess):
        return None
    return sess[target_i]


def closes_dict_from_frame(df) -> dict[str, float]:
    """
    Extract {YYYY-MM-DD: close} from a yfinance-like DataFrame.
    Handles MultiIndex columns (single-ticker download quirk).
    """
    if df is None:
        return {}
    try:
        empty = df.empty
    except Exception:
        return {}
    if empty:
        return {}

    close_col = None
    cols = getattr(df, "columns", None)
    if cols is None:
        return {}

    # MultiIndex: ('Close', 'RELIANCE.NS') or ('RELIANCE.NS', 'Close')
    if getattr(cols, "nlevels", 1) > 1:
        for c in cols:
            parts = [str(p) for p in (c if isinstance(c, tuple) else (c,))]
            if any(p == "Close" for p in parts):
                close_col = c
                break
    elif "Close" in cols:
        close_col = "Close"
    else:
        # case-insensitive fallback
        for c in cols:
            if str(c).lower() == "close":
                close_col = c
                break
    if close_col is None:
        return {}

    out: dict[str, float] = {}
    try:
        series = df[close_col]
    except Exception:
        return {}
    for idx, val in series.items():
        try:
            if val is None:
                continue
            # pandas NA
            if val != val:  # NaN
                continue
            key = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            out[key] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def cache_entry_usable(entry: dict | None, *, min_end_date: str) -> bool:
    """
    True when a prices_cache entry has non-empty closes and covers at least
    min_end_date. Empty closes are never usable (anti-poison).
    """
    if not entry or not isinstance(entry, dict):
        return False
    closes = entry.get("closes") or {}
    if not closes:
        return False
    end = entry.get("end_date") or ""
    # Usable if cached end >= needed end (extra history is fine)
    return end >= min_end_date


# --- Live forward-return computation (yfinance) -----------------------------


def _default_download(tickers: list[str], start: str, end: str):
    """Batch yfinance download. end is exclusive (yfinance convention)."""
    import yfinance as yf

    if not tickers:
        return None
    if len(tickers) == 1:
        return yf.download(
            tickers[0],
            start=start,
            end=end,
            progress=False,
            auto_adjust=True,
            threads=False,
        )
    return yf.download(
        tickers,
        start=start,
        end=end,
        progress=False,
        auto_adjust=True,
        group_by="ticker",
        threads=False,
    )


def _split_batch_frame(df, tickers: list[str]) -> dict[str, dict[str, float]]:
    """Split a batch (or single) download frame into per-ticker close dicts."""
    out: dict[str, dict[str, float]] = {tk: {} for tk in tickers}
    if df is None:
        return out
    try:
        if df.empty:
            return out
    except Exception:
        return out

    cols = df.columns
    # Single ticker: flat or MultiIndex with one symbol
    if len(tickers) == 1:
        out[tickers[0]] = closes_dict_from_frame(df)
        return out

    # group_by=ticker → top level is ticker
    if getattr(cols, "nlevels", 1) > 1:
        level0 = list(cols.get_level_values(0).unique())
        for tk in tickers:
            if tk in level0:
                try:
                    sub = df[tk]
                except Exception:
                    sub = None
                out[tk] = closes_dict_from_frame(sub)
            else:
                # Sometimes level order is OHLCV first
                out[tk] = closes_dict_from_frame(df)
        # If every ticker empty, try column-sliced Close MultiIndex
        if all(not v for v in out.values()) and "Close" in level0:
            try:
                close_df = df["Close"]
                for tk in tickers:
                    if tk in close_df.columns:
                        series = close_df[tk]
                        tmp = series.to_frame(name="Close")
                        out[tk] = closes_dict_from_frame(tmp)
            except Exception:
                pass
        return out

    # Flat multi-ticker is unusual; best-effort single Close shared
    shared = closes_dict_from_frame(df)
    if len(tickers) == 1:
        out[tickers[0]] = shared
    return out


def fetch_forward_returns(
    snapshots: list[tuple[str, dict]],
    *,
    cache_dir: str | None = None,
    no_cache: bool = False,
    today: datetime.date | None = None,
    download_fn: Callable[[list[str], str, str], object] | None = None,
    max_attempts: int = 3,
) -> dict[tuple[str, str], dict[int, dict]]:
    """
    For each (snapshot_label, symbol) where the stock gate-passed, fetch
    closing prices and compute per-name excess returns vs ^NSEI.

    download_fn: injectable (tickers, start, end) -> DataFrame for tests.
    today: injectable "as of" date for window_not_closed (default: UTC today).
    """
    from yf_retry import call_with_retry, is_rate_limit_error

    download = download_fn or _default_download
    as_of = today or datetime.datetime.now(datetime.UTC).date()

    cache_path = os.path.join(cache_dir, "performance_prices.json") if cache_dir else None
    prices_cache: dict[str, dict] = {}
    if cache_path and os.path.exists(cache_path) and not no_cache:
        try:
            with open(cache_path) as f:
                prices_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            prices_cache = {}

    # Global date range covering all snapshots + T+20 buffer
    scan_dates: list[datetime.date] = []
    work: list[tuple[str, dict, datetime.date, list[dict]]] = []
    for label, scan in snapshots:
        generated_at = (scan.get("generated_at") or "")[:10]
        try:
            scan_date = datetime.date.fromisoformat(generated_at)
        except ValueError:
            continue
        passed = [s for s in scan.get("stocks", []) if s.get("gate_pass")]
        if not passed:
            continue
        scan_dates.append(scan_date)
        work.append((label, scan, scan_date, passed))

    if not work:
        return {}

    global_start = min(scan_dates) - datetime.timedelta(days=5)
    # T+20 ≈ 28 calendar days + holiday buffer; exclusive end needs +1
    global_end = max(scan_dates) + datetime.timedelta(days=45)
    # Always fetch through as_of+1 so open windows can resolve later
    if global_end <= as_of:
        global_end = as_of + datetime.timedelta(days=2)
    end_exclusive = global_end + datetime.timedelta(days=1)
    min_end_iso = global_end.isoformat()

    all_tickers: set = set()
    for _, _, _, passed in work:
        for s in passed:
            all_tickers.add(s.get("yf_ticker") or f"{s.get('symbol')}.NS")
    all_tickers.add("^NSEI")
    ticker_list = sorted(all_tickers)

    closes_by_ticker: dict[str, dict[str, float]] = {}
    need_fetch: list[str] = []
    for tk in ticker_list:
        entry = prices_cache.get(tk)
        if not no_cache and cache_entry_usable(entry, min_end_date=min_end_iso):
            closes_by_ticker[tk] = dict(entry.get("closes") or {})
        else:
            need_fetch.append(tk)

    def _fetch_batch(batch: list[str]) -> dict[str, dict[str, float]]:
        def _once():
            df = download(batch, global_start.isoformat(), end_exclusive.isoformat())
            return _split_batch_frame(df, batch)

        try:
            result = call_with_retry(
                _once,
                max_attempts=max_attempts,
                base_delay_s=2.0,
                retryable_result=lambda d: all(not v for v in d.values()),
            )
        except Exception as exc:
            if is_rate_limit_error(exc):
                print(f"performance: rate-limited fetching {len(batch)} tickers: {exc}")
            else:
                print(f"performance: download failed for {len(batch)} tickers: {exc}")
            return {tk: {} for tk in batch}
        return result

    # Chunk to keep request size reasonable
    CHUNK = 40
    for i in range(0, len(need_fetch), CHUNK):
        batch = need_fetch[i : i + CHUNK]
        fetched = _fetch_batch(batch)
        for tk, closes in fetched.items():
            closes_by_ticker[tk] = closes
            # Never cache empty closes (anti-poison)
            if closes:
                prices_cache[tk] = {
                    "end_date": global_end.isoformat(),
                    "closes": closes,
                    "ok": True,
                }
            elif tk in prices_cache and not (prices_cache[tk].get("closes")):
                # Drop poisoned empty entries
                prices_cache.pop(tk, None)
        # Courtesy pause between chunks
        if i + CHUNK < len(need_fetch) and download_fn is None:
            time.sleep(0.4)

    if cache_path:
        try:
            os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
            with open(cache_path, "w") as f:
                json.dump(prices_cache, f)
        except OSError:
            pass

    # Trading calendar from Nifty session dates (union with any stock dates)
    nifty_closes = closes_by_ticker.get("^NSEI") or {}
    session_set = set()
    for d_str in nifty_closes:
        with contextlib.suppress(ValueError):
            session_set.add(datetime.date.fromisoformat(d_str))
    if not session_set:
        # Fallback: union of all ticker dates
        for closes in closes_by_ticker.values():
            for d_str in closes:
                with contextlib.suppress(ValueError):
                    session_set.add(datetime.date.fromisoformat(d_str))
    sessions = session_index_dates(session_set)

    def _close_on(tk: str, session: datetime.date | None) -> float | None:
        if session is None:
            return None
        series = closes_by_ticker.get(tk) or {}
        # Exact session, then walk forward up to 3 sessions in calendar
        for offset in range(4):
            d = session + datetime.timedelta(days=offset)
            v = series.get(d.isoformat())
            if v is not None:
                return v
        return None

    out: dict[tuple[str, str], dict[int, dict]] = {}

    for label, scan, scan_date, passed in work:
        index_start_sess = t_plus_session(sessions, scan_date, 0)
        index_start = _close_on("^NSEI", index_start_sess)

        for s in passed:
            sym = s.get("symbol")
            tk = s.get("yf_ticker") or f"{sym}.NS"
            stock_start = _close_on(tk, index_start_sess)
            per_window: dict[int, dict] = {}

            for w in WINDOWS:
                end_sess = t_plus_session(sessions, scan_date, w)
                if end_sess is None or end_sess > as_of:
                    per_window[w] = {
                        "stock_return_pct": None,
                        "index_return_pct": None,
                        "excess_return_pct": None,
                        "untrackable": False,
                        "reason": WINDOW_NOT_CLOSED,
                    }
                    continue

                stock_end = _close_on(tk, end_sess)
                index_end = _close_on("^NSEI", end_sess)

                if stock_start is None or stock_end is None:
                    per_window[w] = {
                        "stock_return_pct": None,
                        "index_return_pct": None,
                        "excess_return_pct": None,
                        "untrackable": True,
                        "reason": "missing_stock_price",
                    }
                    continue
                sr = (stock_end / stock_start - 1) * 100
                if index_start is None or index_end is None:
                    per_window[w] = {
                        "stock_return_pct": round(sr, 2),
                        "index_return_pct": None,
                        "excess_return_pct": None,
                        "untrackable": True,
                        "reason": "missing_index_price",
                    }
                    continue
                ir = (index_end / index_start - 1) * 100
                per_window[w] = {
                    "stock_return_pct": round(sr, 2),
                    "index_return_pct": round(ir, 2),
                    "excess_return_pct": round(sr - ir, 2),
                    "untrackable": False,
                    "reason": None,
                }
            out[(label, sym)] = per_window

    return out


def outcome_quality_ok(payload: dict, *, min_trackable_t5: int = 1) -> tuple[bool, str]:
    """
    True when the payload has enough T+5 trackable rows for a quality gate.
    Used by compute_performance.py to fail loudly instead of committing
    empty truth.
    """
    meta = payload.get("meta") or {}
    snapshots = meta.get("snapshots_used") or 0
    if snapshots == 0:
        return True, "no_snapshots"
    t5 = (meta.get("trackable_count") or {}).get("T+5", 0)
    not_closed = (meta.get("window_not_closed_count") or {}).get("T+5", 0)
    untrack = (meta.get("untrackable_count") or {}).get("T+5", 0)
    # If everything is simply not closed yet, that is OK (brand-new history).
    if t5 == 0 and untrack == 0 and not_closed > 0:
        return True, "all_windows_open"
    if t5 < min_trackable_t5 and untrack > 0:
        return False, (
            f"T+5 trackable_count={t5} untrackable={untrack} "
            f"window_not_closed={not_closed} — outcome fetch looks broken"
        )
    return True, f"T+5 trackable={t5}"
