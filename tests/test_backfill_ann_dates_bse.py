import datetime

from backfill_ann_dates_bse import (
    is_ist_market_session_active,
    q_neighbors,
    resolve,
    round_to_ist_tick,
)


def test_q_neighbors():
    assert q_neighbors(20230331) == (20221231, 20230630)
    assert q_neighbors(20230630) == (20230331, 20230930)
    assert q_neighbors(20230930) == (20230630, 20231231)
    assert q_neighbors(20231231) == (20230930, 20240331)


def test_round_to_ist_tick():
    assert round_to_ist_tick(100.02) == 100.0
    assert round_to_ist_tick(100.03) == 100.05
    assert round_to_ist_tick(100.08) == 100.10
    assert round_to_ist_tick(-5.0) == 0.0


def test_is_ist_market_session_active():
    # Tuesday at 10:00 AM IST (Active)
    dt_active = datetime.datetime(2026, 3, 10, 10, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    assert is_ist_market_session_active(dt_active) is True

    # Sunday at 10:00 AM IST (Inactive)
    dt_weekend = datetime.datetime(2026, 3, 8, 10, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    assert is_ist_market_session_active(dt_weekend) is False

    # Tuesday at 08:00 AM IST (Inactive, before open)
    dt_early = datetime.datetime(2026, 3, 10, 8, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    assert is_ist_market_session_active(dt_early) is False


def test_resolve_empty_candidates():
    ann, reason = resolve([], 20230331)
    assert ann is None
    assert reason == "no-candidates"


def test_resolve_exact_match(monkeypatch):
    import backfill_ann_dates_bse
    monkeypatch.setattr(backfill_ann_dates_bse, "parse_qe", lambda txt: 20230331 if "Mar-2023" in txt else 0)

    cands = [(20230515, "att1", "Financial Results for Mar-2023")]
    ann, how = resolve(cands, 20230331)
    assert ann == 20230515
    assert how == "exact"
