import datetime
import json
import tkinter as tk
from typing import Any

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


filename = "option_chain.json"
atm = 0


def plot_open_interest_data(
    spot: float,
    strikes: list[float],
    expiry_list: list[str],
    expiry: str,
    index: str,
    container_window: tk.Tk | tk.Toplevel | None = None,
) -> dict[str, Any]:
    global atm
    content: dict[str, Any] = {}

    with open(filename) as json_file:
        content = json.load(json_file)

    index_dict: dict[str, dict[str, float | int]] = {
        "NIFTY": {"slicer": 25, "lot_size": 50},
        "BANKNIFTY": {"slicer": 100, "lot_size": 25},
        "USDINR": {
            "slicer": 0.1250,
            "lot_size": 1,
        },
    }

    atm_slicer = index_dict[index]["slicer"]
    lot_size = index_dict[index]["lot_size"]

    f_strikes: list[float] = []
    call_oi: list[int] = []
    put_oi: list[int] = []
    call_change_oi: list[int] = []
    put_change_oi: list[int] = []

    for item in strikes:
        if abs(item - spot) < atm_slicer:
            atm = item

    print(f"{index} Spot is : {spot}")
    print(f"{index} ATM strike is : {atm}")

    for item in content.get("records", {}).get("data", []):
        if item["strikePrice"] in strikes:
            if item["expiryDate"] == expiry:
                f_strikes.append(item["strikePrice"])

                if "CE" in item:
                    call_oi.append(item["CE"].get("openInterest", 0))
                    call_change_oi.append(item["CE"].get("changeinOpenInterest", 0))
                else:
                    call_oi.append(0)
                    call_change_oi.append(0)

                if "PE" in item:
                    put_oi.append(item["PE"].get("openInterest", 0))
                    put_change_oi.append(item["PE"].get("changeinOpenInterest", 0))
                else:
                    put_oi.append(0)
                    put_change_oi.append(0)

    atm_oi_yval = max(*call_oi, *put_oi) if (call_oi or put_oi) else 0
    atm_change_oi_yval = max(*call_change_oi, *put_change_oi) if (call_change_oi or put_change_oi) else 0

    return {
        "strikes": f_strikes,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "call_change_oi": call_change_oi,
        "put_change_oi": put_change_oi,
        "atm_oi_yval": atm_oi_yval,
        "atm_change_oi_yval": atm_change_oi_yval,
        "atm": atm,
        "lot_size": lot_size,
    }
