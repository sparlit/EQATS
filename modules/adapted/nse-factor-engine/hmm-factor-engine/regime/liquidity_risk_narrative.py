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


# liquidity_risk_narrative.py
#
# STRUCTURE:
# 1. Tier functions per measure     (tier_rv ... tier_skew)
#    Each returns (tier_label, one_line_reading) for today's snapshot value.
#
# 2. Trend helpers                  (TIER_ORDER, get_tier, fmt_val, get_trend_sentence)
#    get_tier   — unified tier lookup used for lookback dates (label only, no reading)
#    fmt_val    — display formatter per measure
#    get_trend_sentence — builds the trend sentence appended to each reading
#
# 3. Severity + overall story       (SEVERITY, build_overall_story)
#    SEVERITY   — maps tier labels to stress scores for overall characterisation
#    TIER_ORDER — maps tier labels to ordinal rank for trend direction logic
#    Both cover the same tier labels but serve different purposes; kept separate.
#
# 4. Formatting + orchestration     (fmt_row, generate_narrative)
#    generate_narrative — computes lookbacks, calls tier fns, appends trend, builds output
#
# 5. Entry point                    (main)

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = "/home/ec2-user/nse-factor-engine/hmm-factor-engine/regime/data"
CAL_PATH = f"{OUT_DIR}/calibration.json"

UNIVERSES = ["nifty100", "nifty500", "niftymidcap150", "niftysmallcap250"]

MEASURE_LABELS = {
    "rv": "Realised Volatility",
    "avg_corr": "Avg Correlation",
    "vov": "Vol of Vol",
    "dispersion": "Dispersion",
    "drawdown": "Drawdown",
    "skew": "Skew",
    "amihud": "Amihud Illiquidity",
    "cs_spread": "CS Spread",
    "turnover": "Turnover",
}


# ─────────────────────────────────────────────
# 1. TIER FUNCTIONS
# Each returns (tier_label, one_line_reading)
# ─────────────────────────────────────────────


def tier_rv(val, cal):
    p25, p75, p90 = cal["p25"], cal["p75"], cal["p90"]
    pct = round(val * 100, 1)
    if val < p25:
        return "calm", f"Realized vol at {pct}% annualised — well within normal range"
    if val < p75:
        return "moderate", f"Realized vol at {pct}% annualised — unremarkable"
    if val < p90:
        return "elevated", f"Realized vol at {pct}% annualised — above median, stress building"
    return "extreme", f"Realized vol at {pct}% annualised — systemic stress territory"


def tier_avg_corr(val, cal):
    p25, p75, p90 = cal["p25"], cal["p75"], cal["p90"]
    pct = round(val * 100, 1)
    if val < p25:
        return "calm", f"Avg stock-index correlation {pct}% — stocks moving independently, low macro influence"
    if val < p75:
        return "moderate", f"Avg stock-index correlation {pct}% — moderate co-movement, some macro influence"
    if val < p90:
        return (
            "elevated",
            f"Avg stock-index correlation {pct}% — macro influence rising, stocks increasingly correlated",
        )
    return "extreme", f"Avg stock-index correlation {pct}% — high macro dominance, stocks moving in lockstep"


def tier_vov(val, cal):
    p25, p75, p90 = cal["p25"], cal["p75"], cal["p90"]
    if val < p25:
        return "calm", "VoV low — volatility regime stable, no transition in progress"
    if val < p75:
        return "moderate", "VoV moderate — vol oscillating normally"
    if val < p90:
        return "elevated", "VoV elevated — regime transition likely underway"
    return "extreme", "VoV extreme — sharp regime shift, vol itself becoming volatile"


def tier_dispersion(val, cal):
    p25, p75, p95 = cal["p25"], cal["p75"], cal["p95"]
    pct = round(val * 100, 2)
    if val < p25:
        return "calm", f"Cross-sectional dispersion {pct}% — stocks moving together, macro driven"
    if val < p75:
        return "moderate", f"Cross-sectional dispersion {pct}% — normal stock divergence"
    if val < p95:
        return "elevated", f"Cross-sectional dispersion {pct}% — stocks diverging, factor or sector stress"
    if val > 2 * p75:
        return "extreme", f"Cross-sectional dispersion {pct}% — crash-day spike, extreme stock divergence"
    return (
        "extreme",
        f"Cross-sectional dispersion {pct}% — tail dispersion, stocks diverging sharply but not crash-day magnitude",
    )


def tier_amihud(val, cal):
    # cal thresholds stored scaled (x1e10) — compare on same scale
    scaled = val * 1e10
    p25, p75, p90 = cal["p25"], cal["p75"], cal["p90"]
    display = round(scaled, 3)
    if scaled < p25:
        return "liquid", f"Amihud {display} (x1e10) — deep market, low price impact"
    if scaled < p75:
        return "normal", f"Amihud {display} (x1e10) — normal liquidity"
    if scaled < p90:
        return "illiquid", f"Amihud {display} (x1e10) — elevated price impact, liquidity thinning"
    return "severely illiquid", f"Amihud {display} (x1e10) — severe illiquidity, large trades moving prices"


def tier_cs_spread(val, cal):
    p10, p75, p90 = cal["p10"], cal["p75"], cal["p90"]
    bps = round(val * 10000, 1)
    if val < p10:
        return (
            "compressed",
            f"CS spread {bps}bps — spread compressed, likely slow-burn macro stress not a liquidity crisis",
        )
    if val < p75:
        return "normal", f"CS spread {bps}bps — normal transaction cost"
    if val < p90:
        return "wide", f"CS spread {bps}bps — elevated transaction cost, liquidity thinning"
    return "spike", f"CS spread {bps}bps — sudden liquidity event, bid-ask blowing out"


def tier_turnover(val, cal):
    p10, p75, p90 = cal["p10"], cal["p75"], cal["p90"]
    pct = round(val * 100, 3)
    if val < p10:
        return "low", f"Turnover {pct}% — very thin participation, market quiet or disengaged"
    if val < p75:
        return "normal", f"Turnover {pct}% — normal market participation"
    if val < p90:
        return "elevated", f"Turnover {pct}% — active market, above-average participation"
    return "surge", f"Turnover {pct}% — volume surge, panic buying or selling"


def tier_drawdown(val, cal):
    mag = abs(val)
    p25, p75, p90 = cal["p25"], cal["p75"], cal["p90"]
    pct = round(val * 100, 1)
    if mag < p25:
        return "shallow", f"Drawdown {pct}% — near recent highs, no structural damage"
    if mag < p75:
        return "moderate", f"Drawdown {pct}% — moderate correction from 52-week high"
    if mag < p90:
        return "deep", f"Drawdown {pct}% — deep correction, meaningful distance from peak"
    return "severe", f"Drawdown {pct}% — severe drawdown, market well below peak"


def tier_skew(val, cal):
    p10, p25, p75 = cal["p10"], cal["p25"], cal["p75"]
    rounded = round(val, 3)
    if val > p75:
        return "rally-like", f"Skew {rounded} — recent 60-day return distribution positively skewed, rally-like"
    if val > p25:
        return "neutral", f"Skew {rounded} — return distribution neutral, no strong directional memory"
    if val > p10:
        return "crash-like", f"Skew {rounded} — moderately negative skew, crash-like distribution memory"
    return (
        "extreme crash memory",
        f"Skew {rounded} — strongly negative, extreme crash-like distribution (lags stress by ~60 days)",
    )


# ─────────────────────────────────────────────
# 2. TREND HELPERS
# ─────────────────────────────────────────────

# Ordinal rank of each tier — used for trend direction logic only.
# Higher = more stress. See SEVERITY below for overall story scoring.
TIER_ORDER = {
    "calm": 0,
    "moderate": 1,
    "elevated": 2,
    "extreme": 3,
    "liquid": 0,
    "normal": 1,
    "illiquid": 2,
    "severely illiquid": 3,
    "compressed": 2,
    "wide": 2,
    "spike": 3,
    "low": 1,
    "surge": 2,
    "shallow": 0,
    "deep": 2,
    "severe": 3,
    "rally-like": 0,
    "neutral": 1,
    "crash-like": 2,
    "extreme crash memory": 3,
    "unavailable": -1,
}


def get_tier(measure, val, cal):
    """Unified tier lookup for lookback dates — returns label only, no reading string."""
    if pd.isna(val):
        return "unavailable"
    if measure in ("rv", "avg_corr", "vov"):
        p25, p75, p90 = cal["p25"], cal["p75"], cal["p90"]
        if val < p25:
            return "calm"
        if val < p75:
            return "moderate"
        if val < p90:
            return "elevated"
        return "extreme"
    if measure == "dispersion":
        p25, p75, p95 = cal["p25"], cal["p75"], cal["p95"]
        if val < p25:
            return "calm"
        if val < p75:
            return "moderate"
        if val < p95:
            return "elevated"
        return "extreme"
    if measure == "amihud":
        scaled = val * 1e10
        p25, p75, p90 = cal["p25"], cal["p75"], cal["p90"]
        if scaled < p25:
            return "liquid"
        if scaled < p75:
            return "normal"
        if scaled < p90:
            return "illiquid"
        return "severely illiquid"
    if measure == "cs_spread":
        p10, p75, p90 = cal["p10"], cal["p75"], cal["p90"]
        if val < p10:
            return "compressed"
        if val < p75:
            return "normal"
        if val < p90:
            return "wide"
        return "spike"
    if measure == "turnover":
        p10, p75, p90 = cal["p10"], cal["p75"], cal["p90"]
        if val < p10:
            return "low"
        if val < p75:
            return "normal"
        if val < p90:
            return "elevated"
        return "surge"
    if measure == "drawdown":
        mag = abs(val)
        p25, p75, p90 = cal["p25"], cal["p75"], cal["p90"]
        if mag < p25:
            return "shallow"
        if mag < p75:
            return "moderate"
        if mag < p90:
            return "deep"
        return "severe"
    if measure == "skew":
        p10, p25, p75 = cal["p10"], cal["p25"], cal["p75"]
        if val > p75:
            return "rally-like"
        if val > p25:
            return "neutral"
        if val > p10:
            return "crash-like"
        return "extreme crash memory"
    return "unavailable"


def fmt_val(measure, val):
    """Display formatter — converts raw values to human-readable strings."""
    if pd.isna(val):
        return "N/A"
    if measure == "amihud":
        return f"{round(val * 1e10, 3)} (x1e10)"
    if measure in ("rv", "avg_corr", "turnover", "drawdown"):
        return f"{round(val * 100, 1)}%"
    if measure == "cs_spread":
        return f"{round(val * 10000, 1)}bps"
    if measure == "dispersion":
        return f"{round(val * 100, 2)}%"
    if measure == "vov":
        return f"{round(val, 4)}"
    if measure == "skew":
        return f"{round(val, 3)}"
    return f"{round(val, 4)}"


def get_trend_sentence(measure, today_tier, today_val, lookbacks, cal):
    """
    Builds the trend sentence appended to each measure reading.
    lookbacks: dict of period -> {val, tier, date}  (periods: 1W, 1M, 3M)
    """
    available = {p: v for p, v in lookbacks.items() if v["tier"] != "unavailable"}
    if not available:
        return ""

    # Build ordered sequence: 3M -> 1M -> 1W -> today
    ordered_periods = [p for p in ["3M", "1M", "1W"] if p in available]
    ordered_tiers = [TIER_ORDER.get(available[p]["tier"], 1) for p in ordered_periods]
    today_score = TIER_ORDER.get(today_tier, 1)
    full_sequence = [*ordered_tiers, today_score]

    # Check trajectory — monotonically worsening, improving, flat, or mixed
    diffs_seq = [full_sequence[i + 1] - full_sequence[i] for i in range(len(full_sequence) - 1)]
    all_up = all(d >= 0 for d in diffs_seq) and any(d > 0 for d in diffs_seq)
    all_down = all(d <= 0 for d in diffs_seq) and any(d < 0 for d in diffs_seq)
    all_flat = all(d == 0 for d in diffs_seq)

    # ── Measure-specific trajectory words — no universal stress/improve judgement ──
    if measure == "drawdown":
        # raw values negative — worsening = more negative = higher tier score
        if all_flat:
            direction = "Stable"
        elif all_up:
            direction = "Worsening consistently"
        elif all_down:
            direction = "Recovering consistently"
        else:
            net = today_score - ordered_tiers[0]
            direction = "Net worsening" if net > 0 else "Net recovering" if net < 0 else "Fluctuating"

    elif measure == "skew":
        # directional memory — higher score = more crash-like
        if all_flat:
            direction = "Stable"
        elif all_up:
            direction = "Becoming more crash-like consistently"
        elif all_down:
            direction = "Becoming more rally-like consistently"
        else:
            net = today_score - ordered_tiers[0]
            direction = (
                "Trending more crash-like" if net > 0 else "Trending more rally-like" if net < 0 else "Fluctuating"
            )

    # all others: rising / falling — let reader interpret
    elif all_flat:
        direction = "Stable"
    elif all_up:
        direction = "Rising consistently"
    elif all_down:
        direction = "Falling consistently"
    else:
        net = today_score - ordered_tiers[0]
        direction = "Rising overall" if net > 0 else "Falling overall" if net < 0 else "Fluctuating"

    if direction == "Stable":
        return "Stable across all lookback windows."

    # Window label
    n = len(available)
    window = "over 3 months" if n == 3 else "over available windows" if n == 2 else "over available window"

    # Lookback clauses — oldest first
    period_labels = {"3M": "three months ago", "1M": "a month ago", "1W": "last week"}
    clauses = []
    for period in ["3M", "1M", "1W"]:
        if period not in available:
            continue
        lb = lookbacks[period]
        clauses.append(f"{lb['tier']} at {fmt_val(measure, lb['val'])} {period_labels[period]}")

    return f"{direction} {window}: was {', '.join(clauses)}."


# ─────────────────────────────────────────────
# 3. SEVERITY + OVERALL STORY
# ─────────────────────────────────────────────

# Stress scores for overall characterisation — separate from TIER_ORDER.
# TIER_ORDER is for trend direction; SEVERITY is for snapshot stress level.
SEVERITY = {
    "calm": 0,
    "moderate": 1,
    "elevated": 2,
    "extreme": 3,
    "liquid": 0,
    "normal": 1,
    "illiquid": 2,
    "severely illiquid": 3,
    "compressed": 2,
    "wide": 2,
    "spike": 3,
    "low": 1,
    "surge": 2,
    "shallow": 0,
    "deep": 2,
    "severe": 3,
    "rally-like": 0,
    "neutral": 1,
    "crash-like": 2,
    "extreme crash memory": 3,
}


def build_overall_story(tiers, readings):
    rv_t = tiers.get("rv", "moderate")
    corr_t = tiers.get("avg_corr", "moderate")
    vov_t = tiers.get("vov", "moderate")
    dd_t = tiers.get("drawdown", "moderate")
    disp_t = tiers.get("dispersion", "moderate")
    amihud_t = tiers.get("amihud", "normal")
    cs_t = tiers.get("cs_spread", "normal")
    turn_t = tiers.get("turnover", "normal")
    skew_t = tiers.get("skew", "neutral")

    avg_stress = (
        sum([SEVERITY.get(rv_t, 1), SEVERITY.get(corr_t, 1), SEVERITY.get(vov_t, 1), SEVERITY.get(dd_t, 1)]) / 4
    )

    # CS spike or extreme dispersion lift the overall stress level independently
    liquidity_event = cs_t == "spike"
    dispersion_extreme = disp_t == "extreme"

    if avg_stress >= 2.5:
        stress_char = "under severe systemic stress"
    elif avg_stress >= 1.5:
        stress_char = "under meaningful risk stress"
    elif avg_stress >= 1.25 or liquidity_event or dispersion_extreme:
        stress_char = "in a moderately elevated risk environment"
    else:
        stress_char = "in a calm, low-stress regime"

    if amihud_t == "severely illiquid" and cs_t in ("spike", "wide"):
        liq_char = "with liquidity significantly impaired"
    elif amihud_t == "severely illiquid":
        liq_char = "with price impact elevated but transaction costs normal — depth impaired, not a liquidity crisis"
    elif amihud_t == "illiquid" and cs_t in ("spike", "wide"):
        liq_char = "with some liquidity deterioration"
    elif cs_t == "spike":
        liq_char = "with a sudden bid-ask spike — transaction costs spiked sharply, not broad market impairment"
    elif cs_t == "compressed":
        liq_char = "with structurally adequate liquidity despite spread compression — macro not liquidity stress"
    else:
        liq_char = "with adequate market liquidity"

    sentence1 = f"Market is {stress_char}, {liq_char}."

    drivers = []
    if rv_t in ("elevated", "extreme") and corr_t in ("elevated", "extreme"):
        if dd_t in ("deep", "severe"):
            drivers.append("correlated macro selloff — elevated vol, herding, and significant drawdown confirming it")
        elif dd_t == "unavailable":
            if skew_t in ("crash-like", "extreme crash memory"):
                drivers.append(
                    "correlated stress event — skew confirms crash-like character despite drawdown data unavailable"
                )
            elif skew_t == "rally-like":
                drivers.append("elevated vol and correlation in rally conditions — euphoric or momentum-driven market")
            else:
                drivers.append(
                    "elevated vol and correlation — direction unclear, drawdown data unavailable and skew neutral"
                )
        else:
            drivers.append(
                "elevated vol and correlation but no drawdown confirmation — heightened macro sensitivity, not a selloff"
            )
    elif rv_t in ("elevated", "extreme"):
        drivers.append("elevated realised volatility without broad herding — idiosyncratic stress")
    elif corr_t in ("elevated", "extreme"):
        drivers.append("macro-driven correlation spike without extreme volatility — positioning/sentiment shift")

    if dd_t in ("deep", "severe"):
        drivers.append(f"significant drawdown from peak ({readings.get('drawdown', '').split('—')[0].strip()})")

    if disp_t == "extreme":
        disp_reading = readings.get("dispersion", "")
        if "crash-day spike" in disp_reading:
            drivers.append("crash-day dispersion spike — extreme stock-level divergence")
        else:
            drivers.append("tail dispersion — stocks diverging sharply, not crash-day magnitude")
    elif disp_t == "elevated":
        drivers.append("elevated cross-sectional dispersion suggesting factor or sector rotation")

    if cs_t == "spike":
        drivers.append("bid-ask blowout indicating sudden liquidity event")
    elif cs_t == "compressed":
        drivers.append("spread compression consistent with slow-burn macro stress rather than a liquidity crisis")

    if turn_t == "surge":
        drivers.append("volume surge suggesting panic activity")

    sentence2 = (
        "Primary signal: " + "; ".join(drivers) + "."
        if drivers
        else "No single dominant driver — conditions are broadly normal across measures."
    )

    if skew_t == "rally-like" and dd_t in ("deep", "severe"):
        sentence3 = "Skew positive but contradicts deep drawdown — skew is lagging, likely reflecting a prior recovery window before current stress."
    elif skew_t in ("crash-like", "extreme crash memory") and dd_t == "shallow":
        sentence3 = "Skew negative but drawdown is shallow — skew is lagging, likely reflecting a prior stress event now fading."
    elif skew_t == "extreme crash memory":
        sentence3 = "Skew confirms recent 60-day window is strongly crash-like — this lags the stress event, not a leading signal."
    elif skew_t == "crash-like":
        sentence3 = (
            "Skew mildly negative — some crash memory in the 60-day window, likely trailing a recent stress event."
        )
    elif skew_t == "rally-like":
        sentence3 = "Skew positive — recent 60-day return distribution is rally-like, no crash memory."
    else:
        sentence3 = "Skew neutral — no strong directional memory in the recent return distribution."

    return f"{sentence1} {sentence2} {sentence3}"


# ─────────────────────────────────────────────
# 4. FORMATTING + ORCHESTRATION
# ─────────────────────────────────────────────


def save_narrative_json(univ, actual_date, overall, tiers, readings):
    """Save narrative output as JSON for downstream ingestion."""
    payload = {
        "universe": univ,
        "date": str(actual_date.date()),
        "overall": overall,
        "measures": {
            measure: {
                "tier": tiers.get(measure, "unavailable"),
                "reading": readings.get(measure, ""),
            }
            for measure in [
                "rv",
                "avg_corr",
                "vov",
                "dispersion",
                "drawdown",
                "skew",
                "amihud",
                "cs_spread",
                "turnover",
            ]
        },
    }
    out_path = Path(OUT_DIR) / f"narrative_{univ}_{actual_date.date()}.json"
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    return out_path


def fmt_row(measure, tier, reading):
    label = MEASURE_LABELS.get(measure, measure)
    tier_str = f"[{tier.upper()}]"
    return f"  {label:<22}  {tier_str:<22}  {reading}"


def generate_narrative(univ, query_date, cal, df):
    dt = pd.Timestamp(query_date)

    if dt in df.index:
        actual_date = dt
    else:
        idx = df.index.get_indexer([dt], method="nearest")[0]
        actual_date = df.index[idx]
        print(f"  Note: {query_date} not a trading day — using nearest: {actual_date.date()}")

    row = df.loc[actual_date]

    def nearest_valid_date(target, measure, window_days=5):
        """Find nearest date within window_days of target that has a non-null value."""
        lo = target - pd.DateOffset(days=window_days)
        hi = target + pd.DateOffset(days=window_days)
        candidates = df.index[(df.index >= lo) & (df.index <= hi) & (df[measure].notna())]
        if len(candidates) == 0:
            return None
        return candidates[np.argmin(np.abs(candidates - target))]

    def build_lookbacks(measure):
        measure_cal = cal.get(measure, {})
        offsets = {
            "1W": actual_date - pd.DateOffset(weeks=1),
            "1M": actual_date - pd.DateOffset(months=1),
            "3M": actual_date - pd.DateOffset(months=3),
        }
        result = {}
        for period, target in offsets.items():
            ldate = nearest_valid_date(target, measure)
            if ldate is None:
                result[period] = {"val": np.nan, "tier": "unavailable", "date": None}
                continue
            val = df.loc[ldate, measure]
            tier = get_tier(measure, val, measure_cal)
            result[period] = {"val": val, "tier": tier, "date": ldate}
        return result

    tier_fns = {
        "rv": (tier_rv, cal.get("rv", {})),
        "avg_corr": (tier_avg_corr, cal.get("avg_corr", {})),
        "vov": (tier_vov, cal.get("vov", {})),
        "dispersion": (tier_dispersion, cal.get("dispersion", {})),
        "amihud": (tier_amihud, cal.get("amihud", {})),
        "cs_spread": (tier_cs_spread, cal.get("cs_spread", {})),
        "turnover": (tier_turnover, cal.get("turnover", {})),
        "drawdown": (tier_drawdown, cal.get("drawdown", {})),
        "skew": (tier_skew, cal.get("skew", {})),
    }

    tiers = {}
    readings = {}

    for measure, (fn, measure_cal) in tier_fns.items():
        val = row.get(measure, np.nan)
        if pd.isna(val):
            tiers[measure] = "unavailable"
            readings[measure] = "data not available for this date"
        else:
            tier, reading = fn(val, measure_cal)
            lookbacks = build_lookbacks(measure)
            trend_sent = get_trend_sentence(measure, tier, val, lookbacks, measure_cal)
            tiers[measure] = tier
            readings[measure] = f"{reading}. {trend_sent}" if trend_sent else reading

    overall = build_overall_story(tiers, readings)

    save_narrative_json(univ, actual_date, overall, tiers, readings)

    lines = [
        f"{'=' * 80}",
        f"  LIQUIDITY & RISK NARRATIVE  |  {univ}  |  {actual_date.date()}",
        f"{'=' * 80}",
        "",
        "OVERALL",
        "-------",
        overall,
        "",
        "RISK MEASURES",
        f"  {'Measure':<22}  {'Tier':<22}  Reading",
        f"  {'-' * 22}  {'-' * 22}  {'-' * 40}",
        fmt_row("rv", tiers["rv"], readings["rv"]),
        fmt_row("avg_corr", tiers["avg_corr"], readings["avg_corr"]),
        fmt_row("vov", tiers["vov"], readings["vov"]),
        fmt_row("dispersion", tiers["dispersion"], readings["dispersion"]),
        fmt_row("drawdown", tiers["drawdown"], readings["drawdown"]),
        fmt_row("skew", tiers["skew"], readings["skew"]),
        "",
        "LIQUIDITY MEASURES",
        f"  {'Measure':<22}  {'Tier':<22}  Reading",
        f"  {'-' * 22}  {'-' * 22}  {'-' * 40}",
        fmt_row("amihud", tiers["amihud"], readings["amihud"]),
        fmt_row("cs_spread", tiers["cs_spread"], readings["cs_spread"]),
        fmt_row("turnover", tiers["turnover"], readings["turnover"]),
        "",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────
# 5. ENTRY POINT
# ─────────────────────────────────────────────


def main():
    if not os.path.exists(CAL_PATH):
        print(f"ERROR: calibration not found at {CAL_PATH}")
        print("Run liquidity_risk_parameters_calibration.py first.")
        sys.exit(1)

    with open(CAL_PATH) as f:
        cal_all = json.load(f)

    # Hardcoded dates for explicit validation runs only
    STRESS_DATES = [
        "2024-06-04",
        "2024-08-06",
        "2025-04-07",
        "2025-07-21",
        "2026-04-01",
        "2026-08-03",
    ]

    if len(sys.argv) == 3:
        # python3 liquidity_risk_narrative.py nifty100 2026-04-01
        target_univs = [sys.argv[1]]
        target_dates = [sys.argv[2]]
    elif len(sys.argv) == 2 and sys.argv[1] == "--validate":
        # python3 liquidity_risk_narrative.py --validate
        target_univs = UNIVERSES
        target_dates = STRESS_DATES
    else:
        # default: latest available date across all universes
        target_univs = UNIVERSES
        target_dates = None  # resolved per universe below

    for univ in target_univs:
        if univ not in cal_all:
            print(f"ERROR: {univ} not in calibration. Available: {list(cal_all.keys())}")
            continue
        cal = cal_all[univ]
        df = pd.read_parquet(f"{OUT_DIR}/liquidity_risk_{univ}.parquet")
        dates = target_dates or [str(df.index.max().date())]
        for d in dates:
            narrative = generate_narrative(univ, d, cal, df)
            print(narrative)


if __name__ == "__main__":
    main()
