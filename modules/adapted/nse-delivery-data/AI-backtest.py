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
import logging
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dateutil.relativedelta import relativedelta
from google import genai
from google.genai import types

# ========================= CONFIGURATION =========================
client = genai.Client()
MODEL_ID = "gemini-2.5-flash"

OUTPUT_DIR = Path("reports")
PROGRESS_FILE = Path("progress.json")
LOG_FILE = Path("backtest_run.log")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ========================= LOGGING SETUP =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)


# ========================= DATA FEED STUBS =========================
def get_market_data_feed(date_str: str) -> dict[str, Any]:
    """Fetch macro, option chain, and index data for the specific date."""
    return {
        "status": "Simulated Feed",
        "nifty_close": 23500.0,
        "nifty_mid_select_close": 13100.0,
        "macro_note": "Data feed integrated.",
    }


def get_microcap_universe(date_str: str) -> list[dict[str, Any]]:
    """Fetch the 50 filtered micro-cap stocks valid as of the cutoff date."""
    return [
        {"ticker": "MARKSANS", "close_price": 185.00},
        {"ticker": "HBLPOWER", "close_price": 520.00},
        {"ticker": "DATAMATICS", "close_price": 610.00},
        # Add your actual scraped universe here
    ]


# ========================= CORE FUNCTIONS =========================
def get_all_dates(months_total: int = 6) -> list[str]:
    dates = []
    current = datetime.now()
    for _ in range(months_total):
        next_month = current.replace(day=28) + relativedelta(days=4)
        last_day = next_month - relativedelta(days=next_month.day)
        dates.append(last_day.strftime("%d-%b-%Y"))
        current -= relativedelta(months=1)
    return dates[::-1]


def load_progress() -> dict[str, list]:
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logging.exception(f"⚠️ {PROGRESS_FILE} is corrupted. Starting fresh.")
    return {"completed": []}


def save_progress(completed_dates: list[str]) -> None:
    temp_file = PROGRESS_FILE.with_suffix(".tmp")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump({"completed": completed_dates}, f, indent=2)
        os.replace(temp_file, PROGRESS_FILE)
    except Exception as e:
        logging.exception(f"Failed to save progress: {e}")


def get_previous_month_state(current_date_str: str, all_dates: list[str]) -> str:
    try:
        current_idx = all_dates.index(current_date_str)
        if current_idx == 0:
            return (
                "NONE (This is the inception month. Create a new portfolio based strictly on the current month's data.)"
            )

        prev_date_str = all_dates[current_idx - 1]
        prev_file = OUTPUT_DIR / f"{prev_date_str.replace('-', '_')}.json"

        if prev_file.exists():
            with open(prev_file, encoding="utf-8") as f:
                prev_data = json.load(f)
                portfolio_state = prev_data.get("model_portfolio", {})
                return json.dumps(portfolio_state, indent=2)
        else:
            return "ERROR_MISSING_PREVIOUS"
    except Exception as e:
        logging.exception(f"Error fetching previous state: {e}")
        return "ERROR_MISSING_PREVIOUS"


def generate_analysis(
    cutoff_date_str: str, prev_month_data: str, market_feed: dict, universe_data: list
) -> dict[str, Any] | None:
    try:
        with open("prompt_template.txt", encoding="utf-8") as f:
            prompt = f.read()
            prompt = prompt.replace("{CUTOFF_DATE}", cutoff_date_str)
            prompt = prompt.replace("{PREVIOUS_MONTH_DATA}", prev_month_data)
            prompt = prompt.replace("{MARKET_DATA_FEED}", json.dumps(market_feed))
            prompt = prompt.replace("{AVAILABLE_MICROCAP_UNIVERSE}", json.dumps(universe_data))
    except FileNotFoundError:
        logging.exception("🛑 prompt_template.txt not found!")
        return None

    # Extract valid tickers for the firewall
    valid_scraped_universe_list = [stock.get("ticker") for stock in universe_data]
    max_retries = 15

    for attempt in range(1, max_retries + 1):
        try:
            logging.info(f"    Requesting Gemini API for {cutoff_date_str} (Attempt {attempt}/{max_retries})...")
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1, max_output_tokens=15000, response_mime_type="application/json"
                ),
            )

            raw_text = response.text
            cb = chr(96) * 3
            pattern = rf"{cb}(?:json)?\s*(.*?)\s*{cb}"
            json_match = re.search(pattern, raw_text, re.DOTALL)
            text_to_parse = json_match.group(1) if json_match else raw_text.strip()

            data = json.loads(text_to_parse)

            # =================================================================
            # 🚨 THE DATA FIREWALL VALIDATOR
            # =================================================================
            logging.info("    Running Institutional Data Firewall Checks...")

            # 1. Structural Check
            required_keys = ["cutoff_date", "model_portfolio", "one_week_outlook"]
            for key in required_keys:
                if key not in data:
                    msg = f"Missing critical structural key: {key}"
                    raise ValueError(msg)

            model_portfolio = data.get("model_portfolio", {})
            open_positions = model_portfolio.get("open_positions", [])

            # 2. Universe Integrity Check (Anti-Hallucination)
            if (
                prev_month_data
                == "NONE (This is the inception month. Create a new portfolio based strictly on the current month's data.)"
            ):
                allocated_tickers = [pos.get("ticker") for pos in open_positions]
                for ticker in allocated_tickers:
                    if ticker not in valid_scraped_universe_list:
                        msg = f"Security Alert: AI hallucinated unverified asset: {ticker}"
                        raise ValueError(msg)

            # 3. Weight Cap Guardrail (Enforce Cash Buffer)
            total_weight = sum([float(pos.get("target_allocation_pct", 0.0)) for pos in open_positions])
            if total_weight > 0.985:  # 0.985 used to handle minor floating point rounding
                msg = f"Allocation Alert: Total weight {total_weight} exceeds 0.98 limit (2% cash buffer breached)."
                raise ValueError(msg)
            # =================================================================

            logging.info(f"    ✅ Success & Validated for {cutoff_date_str}")
            return data

        except (json.JSONDecodeError, ValueError) as ve:
            logging.warning(f"    ⚠️ Validation/Parser Error for {cutoff_date_str}: {ve}. Retrying...")
            time.sleep(5)

        except Exception as e:
            error_str = str(e).lower()
            if any(k in error_str for k in ["rate limit", "429", "quota", "resource exhausted"]):
                wait = min(60 * (2 ** (attempt - 1)), 900)
                logging.warning(f"    ⚠️ Rate limit hit. Waiting {wait} seconds before retrying...")
                time.sleep(wait)
            else:
                logging.exception(f"    ❌ Network/API Error for {cutoff_date_str}: {e}")
                time.sleep(30)

    logging.error(f"    🚨 FAILED completely for {cutoff_date_str} after {max_retries} attempts.")
    return None


# ========================= DASHBOARD GENERATOR =========================
def generate_dashboard():
    logging.info("\n📊 Compiling results and generating Institutional Dashboard...")

    compiled_data = {}
    if OUTPUT_DIR.exists():
        for filename in os.listdir(OUTPUT_DIR):
            if filename.endswith(".json"):
                date_key = filename.replace("_", "-").replace(".json", "")
                filepath = OUTPUT_DIR / filename
                try:
                    with open(filepath, encoding="utf-8") as f:
                        compiled_data[date_key] = json.load(f)
                except Exception as e:
                    logging.exception(f"  ⚠️ Error loading {filename}: {e}")

    if not compiled_data:
        logging.warning("  ⚠️ No data found to generate dashboard.")
        return

    json_data_str = json.dumps(compiled_data)

    try:
        with open("dashboard_template.html", encoding="utf-8") as f:
            html_template = f.read()
    except FileNotFoundError:
        logging.exception("🛑 dashboard_template.html not found! Cannot build visual dashboard.")
        return

    final_html = html_template.replace("__PYTHON_INJECT_DATA_HERE__", json_data_str)

    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(final_html)

    logging.info("✅ Successfully created 'dashboard.html'! Data injected properly.")


# ========================= MAIN SEQUENTIAL LOOP =========================
if __name__ == "__main__":
    logging.info("🚀 Starting CONTINUOUS STATEFUL Indian Market Backtest...")

    all_dates = get_all_dates(months_total=6)
    progress = load_progress()
    completed = progress.get("completed", [])

    months_processed_this_run = 0
    MAX_MONTHS_PER_RUN = 6

    for date_str in all_dates:
        if date_str in completed:
            continue

        if months_processed_this_run >= MAX_MONTHS_PER_RUN:
            logging.info("🛑 Reached safe run limit. Shutting down cleanly.")
            break

        logging.info(f"\n➡️ Processing {date_str}...")

        prev_state = get_previous_month_state(date_str, all_dates)

        if prev_state == "ERROR_MISSING_PREVIOUS":
            logging.error(f"🛑 FATAL: Cannot process {date_str} because the previous month's JSON is missing.")
            break

        # Fetch actual data for injection
        market_feed = get_market_data_feed(date_str)
        universe_data = get_microcap_universe(date_str)

        analysis = generate_analysis(date_str, prev_state, market_feed, universe_data)

        if analysis:
            filename = OUTPUT_DIR / f"{date_str.replace('-', '_')}.json"
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(analysis, f, indent=2, ensure_ascii=False)

            completed.append(date_str)
            save_progress(completed)
            logging.info(f"    💾 Saved state for {date_str}. Integrity maintained.")

            months_processed_this_run += 1

            delay = 35 + random.uniform(5, 10)
            logging.info(f"    Sleeping for {delay:.1f}s...")
            time.sleep(delay)
        else:
            logging.error(f"🛑 API failed to return valid data for {date_str}.")
            break

    logging.info("🎉 RUN COMPLETE. Checking for data to build Dashboard...")

    json_files = list(OUTPUT_DIR.glob("*.json")) if OUTPUT_DIR.exists() else []

    if len(json_files) > 0:
        generate_dashboard()
    else:
        logging.warning("No JSON files found in reports directory. Dashboard will not be generated.")
