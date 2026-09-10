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


import sqlite3
from datetime import date

from nse_corporate_actions_collector import collect, normalize_listing


def test_normalize_listing_creates_stable_material_record():
    rows = normalize_listing(
        [
            {
                "symbol": "ABC",
                "exDate": "20-Aug-2026",
                "subject": "Bonus issue 1:1",
                "caBroadcastDate": "15-Aug-2026",
            }
        ],
        "https://www.nseindia.com/api/corporates-corporateActions",
    )
    assert rows[0]["symbol"] == "ABC"
    assert rows[0]["ex_date"] == "2026-08-20"
    assert rows[0]["available_date"] == "2026-08-15"
    assert rows[0]["material"] is True
    assert len(rows[0]["filing_id"]) == 32


def test_collect_keeps_database_on_listing_failure(tmp_path, monkeypatch):
    db = tmp_path / "actions.db"
    with sqlite3.connect(db) as conn:
        from v2.database import V2Database

        V2Database(db).ensure_v3_schema()
        conn.execute("""INSERT INTO corporate_actions_v3
          (symbol,ex_date,available_date,action_type,source) VALUES
          ('OLD','2026-08-01','2026-07-30','Split','NSE')""")
    monkeypatch.setattr(
        "nse_corporate_actions_collector.fetch_listing",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("blocked")),
    )
    health = collect(db, date(2026, 8, 17))
    assert health.status == "REUSED_LAST_VALID"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM corporate_actions_v3").fetchone()[0] == 1
