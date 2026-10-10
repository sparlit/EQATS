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
NSE-Neuron FastAPI Backend
Entry point — run with: uvicorn src.backend.main:app --reload --port 8000
"""
import os
import sys

# ── Add project root to sys.path so all existing modules are importable ──────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.backend.routers import analysis, cache, data, forecast

app = FastAPI(
    title="NSE-Neuron API",
    description="Deep Learning Stock Forecasting API for NSE India",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(forecast.router, prefix="/api", tags=["Forecast"])
app.include_router(analysis.router, prefix="/api", tags=["Analysis"])
app.include_router(data.router, prefix="/api", tags=["Data"])
app.include_router(cache.router, prefix="/api", tags=["Model Cache"])


@app.get("/")
def root():
    return {"message": "NSE-Neuron API is running 🚀", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}
