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


"""Export canonical pydantic contracts as JSON Schema files into schemas/.

Usage:
    python scripts/export_schemas.py
"""


import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.schemas import (
    Announcement,
    CorporateAction,
    InstrumentIdentity,
    MarketBar,
    OptionInstrument,
    OptionQuote,
)

CONTRACTS = {
    "instrument.json": InstrumentIdentity,
    "option_instrument.json": OptionInstrument,
    "market_bar.json": MarketBar,
    "option_quote.json": OptionQuote,
    "corporate_action.json": CorporateAction,
    "announcement.json": Announcement,
}


def main() -> int:
    out_dir = Path(__file__).resolve().parents[1] / "schemas"
    out_dir.mkdir(exist_ok=True)
    for name, model in CONTRACTS.items():
        schema = model.model_json_schema()
        (out_dir / name).write_text(json.dumps(schema, indent=2, sort_keys=True))
        print(f"wrote schemas/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
