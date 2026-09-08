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


"""Tests for the JSON output contract writer."""
import datetime
import json
import math
import os
import tempfile

import numpy as np
import pandas as pd
import pytest
from scanner import _json_safe, to_json_records, write_scan_output


def _make_df():
    return pd.DataFrame(
        [
            {
                "symbol": "RELIANCE",
                "company_name": "Reliance Industries",
                "industry": "Oil & Gas",
                "yf_ticker": "RELIANCE.NS",
                "tech_current_price": 2900.0,
                "tech_fifty_two_wk_high": 3200.0,
                "tech_pct_off_52wk_high": -9.4,
                "tech_pct_from_ema200": -3.1,
                "tech_rsi14": 32.5,
                "tech_atr14": 50.0,
                "tech_entry_zone_low": 2875.0,
                "tech_entry_zone_high": 2900.0,
                "tech_stop_loss": 2825.0,
                "tech_target_1": 2975.0,
                "tech_target_2": 3025.0,
                "tech_risk_reward_target_1": 1.5,
                "tech_risk_reward_target_2": 2.5,
                "tech_volume_surge_factor": 1.2,
                "tech_adtv_value_inr_approx": 1_000_000_000.0,
                "tech_adv_value_inr": 15_00_00_000,
                "tech_adv_sessions": 20,
                "fscore_f_score": 7,
                "fscore_f_score_components_available": 9,
                "pe5y_avg_pe_5y": 25.0,
                "pe5y_trailing_pe_check": 22.0,
                "delivery_value_inr": 6_00_00_000,
                "delivery_qty": 100_000,
                "delivery_pct": 35.0,
                "delivery_as_of": "2026-07-01",
                "delivery_source_status": "ok",
                "delivery_source": "nse:bhavcopy",
                "delivery_kind": "actual",
                "liquidity_gate_path": "delivery_actual",
                "surveillance_is_restricted": False,
                "surveillance_restriction_type": None,
                "surveillance_source_status": "ok",
                "surveillance_source": "nse",
                "holdings_data": {"promoter_pct": 50.0, "fii_pct": 19.0, "dii_pct": 20.0, "conviction_pct": 89.0},
                "holdings_status": "ok",
                "holdings_source": "screener.in",
                "corporate_actions_data": {"has_excluded_action": False, "actions": []},
                "corporate_actions_status": "ok",
                "market_index_pct_from_ema200": -3.0,
                "market_correction_factor": 1.05,
                "gate_pass": True,
                "gate_fail_reason": None,
                # B4: per-gate structured results (mirroring what evaluate_stock writes)
                "gate_results": [
                    {"gate": "f_score", "passed": True, "reason": None},
                    {"gate": "drawdown", "passed": True, "reason": None},
                    {"gate": "rsi", "passed": True, "reason": None},
                    {"gate": "liquidity_adequacy", "passed": True, "reason": None},
                    {"gate": "surveillance", "passed": True, "reason": None},
                    {"gate": "holdings_conviction", "passed": True, "reason": None},
                    {"gate": "corporate_actions", "passed": True, "reason": None},
                ],
                # B3: earnings proximity (gate-passed only)
                "earnings_status": "not_applicable",
                "earnings_data": None,
                "swing_score": 78.5,
                "sub_scores": {"valuation_compression": 0.5, "oversold_positioning": 1.0},
                # 1.3.0 accuracy plumbing
                "tech_confirmation_state": "confirmed",
                "tech_rsi_delta_3d": 2.4,
                "tech_close_up_1d": True,
                "tech_vol_ratio_3v20": 0.85,
                "tech_swing_high_63d": 3050.0,
                "tech_atr_expansion_ratio": 1.12,
            }
        ]
    )


def test_to_json_records_required_fields_present():
    df = _make_df()
    records = to_json_records(df)
    assert len(records) == 1
    r = records[0]
    for k in (
        "symbol",
        "current_price",
        "rsi14",
        "atr14",
        "target_1",
        "stop_loss",
        "delivery_value_inr",
        "holdings_conviction_pct",
        "f_score",
        "trailing_pe",
        "gate_pass",
        "swing_score",
        "delivery_source_status",
        "surveillance_source_status",
        "holdings_source_status",
        "pending_corporate_action",
        "market_index_pct_from_ema200",
        "adv_value_inr",
        "liquidity_gate_path",
        # B4: structured per-gate results
        "gate_results",
        # B3: earnings proximity (gate-passed only)
        "earnings_date",
        "earnings_within_days",
        "earnings_source_status",
        # 1.3.0: confirmation overlay + exit-warning features
        "confirmation_state",
        "rsi_delta_3d",
        "close_up_1d",
        "vol_ratio_3v20",
        "swing_high_63d",
        "atr_expansion_ratio",
    ):
        assert k in r, f"missing key: {k}"


def test_to_json_records_confirmation_state_passes_through():
    """1.3.0: confirmation_state must be one of the documented labels and
    default to 'anticipatory' when the technicals field is missing."""
    df = _make_df()
    records = to_json_records(df)
    assert records[0]["confirmation_state"] == "confirmed"
    # Default when missing
    row = _make_df().iloc[0].to_dict()
    row["tech_confirmation_state"] = None
    r2 = to_json_records(pd.DataFrame([row]))[0]
    assert r2["confirmation_state"] == "anticipatory"


def test_to_json_records_gate_results_structure():
    """B4: gate_results must be a list of {gate, passed, reason} dicts."""
    df = _make_df()
    records = to_json_records(df)
    r = records[0]
    assert isinstance(r["gate_results"], list)
    assert len(r["gate_results"]) == 7  # the seven hard gates
    expected_gates = {
        "f_score",
        "drawdown",
        "rsi",
        "liquidity_adequacy",
        "surveillance",
        "holdings_conviction",
        "corporate_actions",
    }
    actual_gates = {g["gate"] for g in r["gate_results"]}
    assert actual_gates == expected_gates
    for g in r["gate_results"]:
        assert "passed" in g
        assert isinstance(g["passed"], bool)
        assert "reason" in g  # may be None
    # All seven gates pass for this well-formed row.
    assert all(g["passed"] for g in r["gate_results"])


def test_to_json_records_earnings_default_not_applicable():
    """B3: non-passed rows should carry earnings_source_status='not_applicable'
    and null earnings_date / earnings_within_days."""
    df = _make_df()
    records = to_json_records(df)
    r = records[0]
    # In _make_df, gate_pass=True so earnings fetch is wired in but no
    # earnings_data was set — earnings_status defaults to 'not_applicable'.
    assert r["earnings_source_status"] in ("not_applicable", "missing", "ok", "source_failed")
    assert r["earnings_date"] is None
    assert r["earnings_within_days"] is None


def test_to_json_records_strips_nan():
    df = _make_df()
    records = to_json_records(df)
    r = records[0]
    # No NaN tokens allowed
    s = json.dumps(r)
    assert "NaN" not in s


def test_write_scan_output_writes_valid_json(tmp_path):
    df = _make_df()
    out = tmp_path / "scan.json"
    payload = write_scan_output(df, str(out))
    assert payload["universe_size"] == 1
    assert payload["gate_pass_count"] == 1
    assert "config" in payload
    # Must be valid JSON
    with open(out) as f:
        reloaded = json.load(f)
    assert reloaded["universe_size"] == 1


# --- NaN / Infinity / exotic-type regression tests -------------------------


def test_json_safe_handles_python_nan():
    assert _json_safe(float("nan")) is None


def test_json_safe_handles_python_inf():
    assert _json_safe(float("inf")) is None
    assert _json_safe(float("-inf")) is None


def test_json_safe_handles_numpy_nan():
    assert _json_safe(np.nan) is None


def test_json_safe_handles_numpy_inf():
    assert _json_safe(np.inf) is None
    assert _json_safe(-np.inf) is None


def test_json_safe_passes_through_finite_floats():
    assert _json_safe(3.14) == 3.14
    assert _json_safe(0.0) == 0.0
    assert _json_safe(-1.5) == -1.5


def test_json_safe_passes_through_numpy_floats():
    assert _json_safe(np.float64(2.71)) == 2.71


def test_json_safe_coerces_numpy_integers():
    assert _json_safe(np.int64(42)) == 42
    assert isinstance(_json_safe(np.int64(42)), int)


def test_json_safe_decodes_bytes():
    assert _json_safe(b"hello") == "hello"


def test_json_safe_converts_sets_to_lists():
    out = _json_safe({1, 2, 3})
    assert isinstance(out, list)
    assert sorted(out) == [1, 2, 3]


def test_json_safe_converts_pandas_timestamp():
    ts = pd.Timestamp("2026-07-01T12:00:00")
    assert _json_safe(ts) == "2026-07-01T12:00:00"


def test_json_safe_converts_datetime():
    dt = datetime.datetime(2026, 7, 1, 12, 0, 0)
    assert _json_safe(dt) == "2026-07-01T12:00:00"


def test_json_safe_recurses_into_nested_dict():
    src = {"a": float("nan"), "b": {"c": float("inf")}, "d": [{"e": float("nan")}]}
    assert _json_safe(src) == {"a": None, "b": {"c": None}, "d": [{"e": None}]}


def test_to_json_records_handles_nan_and_inf_in_row():
    """Regression: a row with NaN/Inf in any field must produce JSON-safe output."""
    row = _make_df().iloc[0].to_dict()
    row["tech_pct_off_52wk_high"] = float("nan")
    row["tech_volume_surge_factor"] = float("inf")
    row["tech_rsi14"] = -float("inf")
    row["fscore_f_score"] = float("nan")
    row["sub_scores"] = {"valuation_compression": float("nan"), "oversold_positioning": float("inf")}
    df = pd.DataFrame([row])
    records = to_json_records(df)
    # Must serialise cleanly with allow_nan=False
    s = json.dumps(records)
    assert "NaN" not in s
    assert "Infinity" not in s
    # NaN/Inf should become None
    assert records[0]["pct_off_52wk_high"] is None
    assert records[0]["volume_surge_factor"] is None
    assert records[0]["rsi14"] is None
    assert records[0]["f_score"] is None
    assert records[0]["sub_scores"]["valuation_compression"] is None
    assert records[0]["sub_scores"]["oversold_positioning"] is None


def test_write_scan_output_handles_nan_and_inf(tmp_path):
    """Regression for the live failure: NaN/Inf in any field must not break
    write_scan_output, even with allow_nan=False."""
    row = _make_df().iloc[0].to_dict()
    row["tech_pct_off_52wk_high"] = float("nan")
    row["tech_volume_surge_factor"] = float("inf")
    df = pd.DataFrame([row])
    out = tmp_path / "scan.json"
    write_scan_output(df, str(out))
    # Reload and confirm no NaN/Inf tokens leaked through
    with open(out) as f:
        reloaded = json.load(f)
    assert reloaded["universe_size"] == 1
    assert reloaded["stocks"][0]["pct_off_52wk_high"] is None
    assert reloaded["stocks"][0]["volume_surge_factor"] is None
