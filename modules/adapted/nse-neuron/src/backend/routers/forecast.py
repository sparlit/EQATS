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
routers/forecast.py
━━━━━━━━━━━━━━━━━━━
POST /api/forecast        — start a forecast job
GET  /api/jobs/{job_id}  — poll job status / result
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.backend.services.job_manager import job_manager
from src.backend.services.nse_service import run_all_forecast, run_single_forecast

router = APIRouter()


class ForecastRequest(BaseModel):
    symbol: str
    algorithm: str  # "lstm" | "bilstm" | "gru" | "cnn_lstm" | "all"
    force_retrain: bool = False  # ignore cached weights and train from scratch


@router.post("/forecast")
def start_forecast(req: ForecastRequest):
    symbol = req.symbol.upper().strip()
    algorithm = req.algorithm.lower().strip()

    valid = {"lstm", "bilstm", "gru", "cnn_lstm", "all"}
    if algorithm not in valid:
        raise HTTPException(status_code=400, detail=f"algorithm must be one of {valid}")

    suffix = " (forced retrain)" if req.force_retrain else ""

    if algorithm == "all":
        job_id = job_manager.submit(
            run_all_forecast,
            symbol,
            req.force_retrain,
            description=f"All algorithms — {symbol}{suffix}",
        )
    else:
        job_id = job_manager.submit(
            run_single_forecast,
            symbol,
            algorithm,
            req.force_retrain,
            description=f"{algorithm.upper()} forecast — {symbol}{suffix}",
        )

    return {"job_id": job_id, "status": "pending"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_manager.to_dict(job)
