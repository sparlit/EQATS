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
Shared Couchbase connection factory.
Single source of truth for connection credentials, bucket name,
document key patterns, and timeout — used by both scanner.py and api.py.
"""
import os
from datetime import timedelta

BUCKET_NAME = "scan-results"
CB_TIMEOUT_SEC = int(os.environ.get("CB_TIMEOUT_SECONDS", "10"))


# Document key helpers
def result_key(watchlist_name: str) -> str:
    return f"results::{watchlist_name}"


INDEX_KEY = "index::watchlists"

# Timestamp field name — consistent across ALL documents
TIMESTAMP_FIELD = "scanned_at"


def get_cluster():
    """Return a ready Couchbase Cluster (new connection each call — use for scanner)."""
    from couchbase.auth import PasswordAuthenticator
    from couchbase.cluster import Cluster
    from couchbase.options import ClusterOptions

    auth = PasswordAuthenticator(os.environ["CB_USERNAME"], os.environ["CB_PASSWORD"])
    cluster = Cluster(os.environ["CB_CONN_STR"], ClusterOptions(auth))
    cluster.wait_until_ready(timedelta(seconds=CB_TIMEOUT_SEC))
    return cluster


def get_collection(cluster=None):
    """Return the default collection. Creates its own cluster if none given."""
    if cluster is None:
        cluster = get_cluster()
    return cluster.bucket(BUCKET_NAME).default_collection()
