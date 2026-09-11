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


import json

import requests


def test_simulation():
    url = "http://localhost:8000/api/simulate-headline"

    # Mock prediction data
    mock_prediction = {
        "symbol": "RELIANCE",
        "company_name": "Reliance Industries",
        "dates": ["2026-04-06", "2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10"],
        "prices": [2500, 2510, 2520, 2530, 2540],
        "prediction_start_index": 2,
        "confidence_score": 75,
    }

    test_cases = [
        "Massive profit surge and strategic expansion",
        "Unexpected lawsuit and catastrophic crash",
        "Neutral market update",
    ]

    for headline in test_cases:
        print(f"\nTesting Headline: {headline}")
        payload = {"prediction": mock_prediction, "headline": headline}
        try:
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                result = response.json()
                shift_label = result.get("simulation_label")
                original_forecast = mock_prediction["prices"][2:]
                new_forecast = result["prices"][2:]
                print(f"Result: {shift_label}")
                print(f"Original Forecast: {original_forecast}")
                print(f"Simulated Forecast: {new_forecast}")
            else:
                print(f"Error: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Request failed: {e}")


if __name__ == "__main__":
    test_simulation()
