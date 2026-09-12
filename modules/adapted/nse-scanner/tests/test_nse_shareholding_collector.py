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


import csv
from datetime import date

import nse_shareholding_collector as collector


def _listing(
    url="https://nsearchives.nseindia.com/corporate/xbrl/SHP_1_14082026103303_WEB.xml", promoter="37.23", public="62.77"
):
    return {
        "ACTION": url,
        "AS ON DATE": "05-AUG-2026",
        "SUBMISSION DATE": "14-AUG-2026",
        "EXCHANGE DISSEMINATION TIME": "14-AUG-2026 10:33:12",
        "PROMOTER & PROMOTER GROUP (A)": promoter,
        "PUBLIC (B)": public,
    }


def _xml(promoter="0.3723", public="0.6277", promoter_shares="9541002", public_shares="16086186"):
    return f"""<x xmlns="urn:test"><context id="ShareholdingOfPromoterAndPromoterGroup_ContextI"/><context id="PublicShareholding_ContextI"/>
    <Symbol>KRISHIVAL</Symbol>
    <NumberOfFullyPaidUpEquityShares contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">{promoter_shares}</NumberOfFullyPaidUpEquityShares>
    <ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">{promoter}</ShareholdingAsAPercentageOfTotalNumberOfShares>
    <NumberOfFullyPaidUpEquityShares contextRef="PublicShareholding_ContextI">{public_shares}</NumberOfFullyPaidUpEquityShares>
    <ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="PublicShareholding_ContextI">{public}</ShareholdingAsAPercentageOfTotalNumberOfShares></x>""".encode()


def test_parse_fraction_and_percent_scale():
    parsed = collector.parse_xbrl(_xml(), _listing())
    assert parsed["symbol"] == "KRISHIVAL"
    assert parsed["shares_outstanding"] == 25627188
    parsed = collector.parse_xbrl(_xml("37.23", "62.77"), _listing())
    assert parsed["promoter_holding_pct"] == 37.23


def test_current_nse_api_schema_is_normalized_to_listing_contract():
    row = collector._normalize_listing_row(
        {
            "name": "Krishival",
            "pr_and_prgrp": "37.23",
            "public_val": "62.77",
            "date": "05-AUG-2026",
            "submissionDate": "14-AUG-2026",
            "broadcastDate": "14-AUG-2026 10:33:07",
            "systemDate": "14-AUG-2026 10:33:12",
            "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/SHP_1_WEB.xml",
        }
    )
    assert row["ACTION"].endswith("SHP_1_WEB.xml")
    assert row["EXCHANGE DISSEMINATION TIME"] == "14-AUG-2026 10:33:12"


def test_parse_public_fallback_and_inconsistent_context_rejected():
    parsed = collector.parse_xbrl(
        _xml("0", "62.77", "0", "16086186"),
        _listing("https://nsearchives.nseindia.com/corporate/xbrl/SHP_2_WEB.xml", "0", "62.77"),
    )
    assert parsed["shares_outstanding"] == 25627188
    try:
        collector.parse_xbrl(_xml(public_shares="14000000"), _listing())
    except ValueError as exc:
        assert "inconsistent" in str(exc)
    else:
        msg = "inconsistent aggregates accepted"
        raise AssertionError(msg)


def test_incremental_listing_is_idempotent_and_preserves_last_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "HISTORY_PATH", tmp_path / "history.csv")
    monkeypatch.setattr(collector, "NORMALIZED_PATH", tmp_path / "normalized.csv")
    monkeypatch.setattr(collector, "RAW_ROOT", tmp_path / "raw")
    row = _listing()
    monkeypatch.setattr(collector, "fetch_listing", lambda *args, **kwargs: [row, row])
    monkeypatch.setattr(collector, "_request", lambda *args, **kwargs: _xml())
    first = collector.collect(as_of=date(2026, 8, 17))
    assert first.status == "FRESH"
    assert first.normalized == 1
    second = collector.collect(as_of=date(2026, 8, 17))
    assert second.status == "NO_NEW_FILINGS"
    assert len(list(csv.DictReader((tmp_path / "normalized.csv").open()))) == 1
    monkeypatch.setattr(
        collector, "fetch_listing", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("blocked"))
    )
    failed = collector.collect(as_of=date(2026, 8, 17))
    assert failed.status == "REUSED_LAST_VALID"


def test_listing_fallback_and_after_cutoff_exclusion(tmp_path, monkeypatch):
    fallback = tmp_path / "listing.csv"
    row = _listing()
    row["EXCHANGE DISSEMINATION TIME"] = "18-AUG-2026 10:33:12"
    with fallback.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)
    monkeypatch.setattr(collector, "HISTORY_PATH", tmp_path / "history.csv")
    monkeypatch.setattr(collector, "NORMALIZED_PATH", tmp_path / "normalized.csv")
    monkeypatch.setattr(
        collector, "fetch_listing", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("blocked"))
    )
    result = collector.collect(as_of=date(2026, 8, 17), csv_fallback=fallback)
    assert result.status == "DEGRADED"
    assert result.unseen == 0


def test_invalid_listing_action_is_excluded_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "HISTORY_PATH", tmp_path / "history.csv")
    monkeypatch.setattr(collector, "NORMALIZED_PATH", tmp_path / "normalized.csv")
    row = _listing("https://nsearchives.nseindia.com/corporate/xbrl/-")
    monkeypatch.setattr(collector, "fetch_listing", lambda *args, **kwargs: [row])
    result = collector.collect(as_of=date(2026, 8, 17))
    assert result.status == "DEGRADED"
    assert result.excluded == 1
