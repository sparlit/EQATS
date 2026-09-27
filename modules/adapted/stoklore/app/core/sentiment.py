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


"""Financial sentiment scoring via a local Hugging Face model - no API keys, no network calls."""
from functools import lru_cache

MODEL_ID = "soleimanian/financial-roberta-large-sentiment"


@lru_cache(maxsize=1)
def _pipeline():
    # ponytail: loaded lazily on first use (not at import time) - the model is ~1.4GB and this
    # module is imported by api.py on every startup, most of which never touch sentiment analysis.
    from transformers import pipeline

    return pipeline("text-classification", model=MODEL_ID, top_k=None)


def analyze(text):
    """Returns {label, score} for the dominant sentiment class (positive/negative/neutral)."""
    scores = _pipeline()(text[:2000], truncation=True)[0]
    top = max(scores, key=lambda s: s["score"])
    return {"label": top["label"], "score": round(top["score"], 4)}
