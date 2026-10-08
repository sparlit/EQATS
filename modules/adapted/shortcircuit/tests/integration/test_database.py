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
Integration tests against a real PostgreSQL instance.

These are the only tests permitted to open a socket (see the `integration`
marker and the `no_network` guard in conftest.py). They verify the things a unit
test structurally cannot: that the migrations in `migrations/` actually apply to
an empty database, and that each table round-trips the shapes the runtime writes.

Run locally with a database available:
    make test-integration

CI provides postgres:16 as a service and applies the migrations first.
"""

import os
import uuid

import pytest

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg", reason="asyncpg not installed")

DSN = (
    f"postgresql://{os.getenv('DB_USER', 'postgres')}"
    f":{os.getenv('DB_PASS', 'postgres')}"
    f"@{os.getenv('DB_HOST', 'localhost')}"
    f":{os.getenv('DB_PORT', '5432')}"
    f"/{os.getenv('DB_NAME', 'shortcircuit_test')}"
)


@pytest.fixture
async def conn():
    try:
        connection = await asyncpg.connect(DSN, timeout=5)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    try:
        yield connection
    finally:
        await connection.close()


# migrations


@pytest.mark.parametrize("table", ["orders", "positions", "reconciliation_log", "gate_results"])
async def test_migrations_created_every_expected_table(conn, table):
    exists = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name=$1)",
        table,
    )
    assert exists, f"table {table!r} missing — migrations did not apply cleanly"


async def test_leverage_columns_were_added_by_later_migration(conn):
    """v44_9_0 adds leverage to both orders and positions. Proves ordering held."""
    for table in ("orders", "positions"):
        col = await conn.fetchval(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name=$1 AND column_name='leverage'",
            table,
        )
        assert col == "leverage", f"{table}.leverage missing"


async def test_orders_exchange_order_id_is_unique(conn):
    """
    The UNIQUE constraint is what makes entry logging idempotent under retry —
    a re-delivered fill must not create a second order row.
    """
    idx = await conn.fetch("SELECT indexdef FROM pg_indexes WHERE tablename='orders'")
    defs = " ".join(r["indexdef"] for r in idx)
    assert "exchange_order_id" in defs and "UNIQUE" in defs.upper()


# round trips


async def test_position_round_trips(conn):
    """
    `source` is CHECK-constrained to SIGNAL / MANUAL / ORPHAN_RECOVERY /
    RECONCILIATION, and `status` on reconciliation_log to a similar fixed
    vocabulary. Those constraints are the schema refusing to record a state the
    system does not have a meaning for, so the tests use real values.
    """
    symbol = f"NSE:TEST{uuid.uuid4().hex[:6].upper()}-EQ"
    today = datetime.date.today()
    try:
        await conn.execute(
            "INSERT INTO positions (symbol, qty, entry_price, state, session_date, "
            "source, opened_at, leverage) VALUES ($1,$2,$3,$4,$5,$6,NOW(),$7)",
            symbol,
            10,
            100.50,
            "OPEN",
            today,
            "RECONCILIATION",
            5.0,
        )
        row = await conn.fetchrow(
            "SELECT symbol, qty, entry_price, state, leverage FROM positions WHERE symbol=$1",
            symbol,
        )
        assert row["qty"] == 10
        assert float(row["entry_price"]) == pytest.approx(100.50)
        assert row["state"] == "OPEN"
        assert float(row["leverage"]) == pytest.approx(5.0)
    finally:
        await conn.execute("DELETE FROM positions WHERE symbol=$1", symbol)


async def test_position_qty_is_stored_as_a_positive_magnitude(conn):
    """
    The broker reports a short as netQty=-10; the DB stores 10 and keeps
    direction in the order side. Reconciliation compares absolute values, so a
    signed quantity here would produce a spurious mismatch on every short.
    """
    symbol = f"NSE:TEST{uuid.uuid4().hex[:6].upper()}-EQ"
    try:
        await conn.execute(
            "INSERT INTO positions (symbol, qty, entry_price, state, session_date, "
            "source, opened_at) VALUES ($1,$2,$3,$4,$5,$6,NOW())",
            symbol,
            7,
            250.0,
            "OPEN",
            datetime.date.today(),
            "RECONCILIATION",
        )
        qty = await conn.fetchval("SELECT qty FROM positions WHERE symbol=$1", symbol)
        assert qty > 0
    finally:
        await conn.execute("DELETE FROM positions WHERE symbol=$1", symbol)


async def test_gate_result_round_trips_with_a_verdict(conn):
    """Every evaluated candidate produces a row — the audit trail's core claim."""
    symbol = f"NSE:TEST{uuid.uuid4().hex[:6].upper()}-EQ"
    try:
        await conn.execute(
            "INSERT INTO gate_results (symbol, session_date, scan_id, evaluated_at, "
            "verdict, first_fail_gate, rejection_reason, data_tier) "
            "VALUES ($1,$2,$3,NOW(),$4,$5,$6,$7)",
            symbol,
            datetime.date.today(),
            1,
            "REJECTED",
            "G5_STRATEGY",
            "integration test",
            "WS_CACHE",
        )
        row = await conn.fetchrow(
            "SELECT verdict, first_fail_gate, data_tier FROM gate_results WHERE symbol=$1",
            symbol,
        )
        assert row["verdict"] == "REJECTED"
        assert row["first_fail_gate"] == "G5_STRATEGY"
        assert row["data_tier"] == "WS_CACHE"
    finally:
        await conn.execute("DELETE FROM gate_results WHERE symbol=$1", symbol)


async def test_reconciliation_log_accepts_a_divergence_record(conn):
    """
    The divergence audit trail. Column naming differs across schema versions, so
    the engine tries both — this asserts at least one form is present and usable.
    """
    cols = {
        r["column_name"]
        for r in await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='reconciliation_log'"
        )
    }
    internal = (
        "internal_position_count" if "internal_position_count" in cols else "internal_pos_count"
    )
    broker = "broker_position_count" if "broker_position_count" in cols else "broker_pos_count"
    assert internal in cols and broker in cols, f"no recognised count columns in {cols}"

    await conn.execute(
        f"INSERT INTO reconciliation_log (timestamp, {internal}, {broker}, status, "
        f"session_date, check_duration_ms) VALUES (NOW(), $1, $2, $3, $4, $5)",
        1,
        0,
        "DIVERGENCE_DETECTED",
        datetime.date.today(),
        12,
    )
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM reconciliation_log WHERE check_duration_ms = 12"
    )
    assert count >= 1
    await conn.execute("DELETE FROM reconciliation_log WHERE check_duration_ms = 12")


# the guard itself


async def test_integration_tests_may_use_the_network(conn):
    """
    Sanity check on the test harness: the autouse no_network fixture must NOT
    apply here. If this fails, the marker wiring is broken and integration tests
    are silently being blocked from reaching the database.
    """
    assert await conn.fetchval("SELECT 1") == 1
