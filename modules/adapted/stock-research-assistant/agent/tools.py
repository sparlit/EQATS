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
Agent tool functions. Plain Python callables, no framework -- every SQL
statement and Lakebase call is visible and directly debuggable.
"""
import os

from databricks import sql as dbsql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config, oauth_service_principal
from databricks.sdk.credentials_provider import runtime_native_auth
from lakebase.db import get_connection as get_lakebase_connection

WAREHOUSE_ID = "377d26238d1c7b33"
CATALOG = "stock_research"
SEARCH_INDEX = f"{CATALOG}.gold.gold_context_chunks_index"


def _escape(value: str) -> str:
    return value.replace("'", "''")


def _get_sql_connection():
    client = WorkspaceClient()
    http_path = f"/sql/1.0/warehouses/{WAREHOUSE_ID}"

    client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    client_secret = os.environ.get("DATABRICKS_CLIENT_SECRET")

    if client_id and client_secret:
        # Running as a Databricks App's dedicated service principal (M2M OAuth).
        print("[_get_sql_connection] using service-principal M2M auth", flush=True)
        sp_config = Config(
            host=client.config.host, client_id=client_id, client_secret=client_secret
        )
        return dbsql.connect(
            server_hostname=client.config.host,
            http_path=http_path,
            credentials_provider=lambda: oauth_service_principal(sp_config),
        )

    # Running as us (job/notebook), personal ambient OAuth.
    print("[_get_sql_connection] using personal ambient auth", flush=True)
    return dbsql.connect(
        server_hostname=client.config.host,
        http_path=http_path,
        credentials_provider=lambda: runtime_native_auth(client.config),
    )


def _rows_as_dicts(cursor):
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]


def get_price_history(ticker: str, days: int = 30):
    """Return the last `days` daily OHLCV + notable-move rows for a ticker."""
    print(f"[get_price_history] start ticker={ticker} days={days}", flush=True)
    with _get_sql_connection() as conn, conn.cursor() as cur:
        print("[get_price_history] executing query...", flush=True)
        cur.execute(
            f"""
            SELECT date, open, high, low, close, volume, daily_change_pct, is_notable_move
            FROM {CATALOG}.gold.gold_price_daily_agg
            WHERE ticker = '{_escape(ticker)}'
            ORDER BY date DESC
            LIMIT {int(days)}
            """
        )
        print("[get_price_history] query executed, fetching rows...", flush=True)
        return _rows_as_dicts(cur)


def compare_tickers(tickers: list, days: int = 30):
    """Return recent price history for each of the given tickers, for side-by-side comparison."""
    return {ticker: get_price_history(ticker, days=days) for ticker in tickers}


def search_context(query: str, num_results: int = 5):
    """Semantic search over company profiles + news via the AI Search index."""
    with _get_sql_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT chunk_id, content_type, ticker, title, chunk_text, source, search_score
            FROM vector_search(
                index => '{SEARCH_INDEX}',
                query_text => '{_escape(query)}',
                num_results => {int(num_results)}
            )
            """
        )
        return _rows_as_dicts(cur)


def manage_watchlist(action: str, ticker: str = None, watchlist_id: int = 1):
    """Add, remove, or list tickers in a watchlist. action is 'add', 'remove', or 'list'."""
    with get_lakebase_connection() as conn, conn.cursor() as cur:
        if action == "add":
            cur.execute(
                """
                INSERT INTO watchlist_tickers (watchlist_id, ticker)
                VALUES (%s, %s)
                ON CONFLICT (watchlist_id, ticker) DO NOTHING
                """,
                (watchlist_id, ticker),
            )
            conn.commit()
            return f"Added {ticker} to watchlist {watchlist_id}."
        if action == "remove":
            cur.execute(
                "DELETE FROM watchlist_tickers WHERE watchlist_id = %s AND ticker = %s",
                (watchlist_id, ticker),
            )
            conn.commit()
            return f"Removed {ticker} from watchlist {watchlist_id}."
        if action == "list":
            cur.execute(
                "SELECT ticker FROM watchlist_tickers WHERE watchlist_id = %s ORDER BY ticker",
                (watchlist_id,),
            )
            return [row[0] for row in cur.fetchall()]
        raise ValueError(f"Unknown action: {action}")


def save_note(ticker: str, note_text: str, user_id: int = 1):
    with get_lakebase_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO research_notes (user_id, ticker, note_text) VALUES (%s, %s, %s)",
            (user_id, ticker, note_text),
        )
        conn.commit()
    return f"Saved note for {ticker}."


def save_report(ticker: str, report_type: str, report_text: str, user_id: int = 1):
    with get_lakebase_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO analysis_reports (user_id, ticker, report_type, report_text) VALUES (%s, %s, %s, %s)",
            (user_id, ticker, report_type, report_text),
        )
        conn.commit()
    return f"Saved {report_type} report for {ticker}."


def check_notable_moves(user_id: int = 1):
    """Notable price moves (>3%) since this user's last visit; bumps last_visit_at to now."""
    with get_lakebase_connection() as lb_conn, lb_conn.cursor() as lb_cur:
        lb_cur.execute("SELECT last_visit_at FROM users WHERE user_id = %s", (user_id,))
        row = lb_cur.fetchone()
        since = row[0] if row and row[0] else None

    with _get_sql_connection() as conn, conn.cursor() as cur:
        if since:
            cur.execute(
                f"""
                SELECT ticker, date, close, daily_change_pct
                FROM {CATALOG}.gold.gold_price_daily_agg
                WHERE is_notable_move = true AND date >= '{since.date().isoformat()}'
                ORDER BY date DESC
                """
            )
        else:
            cur.execute(
                f"""
                SELECT ticker, date, close, daily_change_pct
                FROM {CATALOG}.gold.gold_price_daily_agg
                WHERE is_notable_move = true
                ORDER BY date DESC
                LIMIT 20
                """
            )
        moves = _rows_as_dicts(cur)

    with get_lakebase_connection() as lb_conn, lb_conn.cursor() as lb_cur:
        lb_cur.execute("UPDATE users SET last_visit_at = now() WHERE user_id = %s", (user_id,))
        lb_conn.commit()

    return moves
