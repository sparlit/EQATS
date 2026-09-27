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


import os

import psycopg
from databricks.sdk import WorkspaceClient

LAKEBASE_ENDPOINT = "projects/stock-research-lakebase/branches/production/endpoints/primary"
LAKEBASE_HOST = "ep-autumn-sea-d8lyx439.database.us-east-2.cloud.databricks.com"
LAKEBASE_DB = "databricks_postgres"
LAKEBASE_PERSONAL_USER = "kalyanroyinfo@gmail.com"


def _lakebase_user():
    # Databricks Apps inject DATABRICKS_CLIENT_ID for their dedicated service
    # principal; jobs/notebooks running as us don't have it set, so fall back
    # to the personal user. The Postgres role name must match whichever OAuth
    # identity actually generated the credential below.
    return os.environ.get("DATABRICKS_CLIENT_ID", LAKEBASE_PERSONAL_USER)


def get_connection():
    client = WorkspaceClient()
    cred = client.postgres.generate_database_credential(endpoint=LAKEBASE_ENDPOINT)
    return psycopg.connect(
        host=LAKEBASE_HOST,
        port=5432,
        dbname=LAKEBASE_DB,
        user=_lakebase_user(),
        password=cred.token,
        sslmode="require",
        connect_timeout=10,
    )
