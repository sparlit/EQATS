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
import sys
import time
from datetime import UTC, datetime, timezone

from google import genai
from google.genai import types

# ==============================================================================
# 1. SETUP STRUCTURED LOGGING
# ==============================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)

# ==============================================================================
# 2. INITIALIZE CLIENT & STABLE MODEL CASCADE
# ==============================================================================
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# The 5-Tier Stable Cascade
GEMINI_MODEL_CASCADE = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]

SAFETY_CONFIG = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE
    ),
]

# ==============================================================================
# 3. DIRECTORY & PROMPT LOADER
# ==============================================================================
script_dir = os.path.dirname(os.path.abspath(__file__))
output_dir = os.path.join(script_dir, "forensic_reports")
prompts_dir = os.path.join(script_dir, "Prompts")
status_file = os.path.join(output_dir, "pipeline_status.json")

os.makedirs(output_dir, exist_ok=True)


def load_prompt(filename):
    path = os.path.join(prompts_dir, filename)
    if not os.path.exists(path):
        logger.error(f"CRITICAL: Missing prompt file at {path}. Please create it.")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_stock_queue(filename="target_stocks.txt"):
    path = os.path.join(prompts_dir, filename)
    if not os.path.exists(path):
        logger.error(f"CRITICAL ERROR: {path} not found. Please create it.")
        sys.exit(1)

    stocks = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            clean_line = line.strip()
            if clean_line and not clean_line.startswith("#"):
                stocks.append(clean_line)
    return stocks


system_master_prompt_template = load_prompt("master_prompt.txt")
validation_prompt_template = load_prompt("validation_prompt.txt")
stock_list = load_stock_queue("target_stocks.txt")

# ==============================================================================
# 4. STATE TRACKER
# ==============================================================================
status_tracker = {
    "last_updated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "total_stocks": len(stock_list),
    "completed": 0,
    "failed": 0,
    "stocks": dict.fromkeys(stock_list, "Pending"),
}


def save_status():
    status_tracker["last_updated"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_tracker, f, indent=4)


def extract_json_from_text(raw_text, stock_name, attempt):
    if not raw_text:
        msg = "API returned an empty response. (Check finish_reason in logs)."
        raise ValueError(msg)

    start_idx = raw_text.find("{")
    end_idx = raw_text.rfind("}")

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return raw_text[start_idx : end_idx + 1]
    debug_filename = os.path.join(output_dir, f"ERROR_LOG_{stock_name.replace(' ', '_')}_Tier{attempt}.txt")
    with open(debug_filename, "w", encoding="utf-8") as f:
        f.write(raw_text)
    msg_0 = f"No JSON brackets found. AI's raw output saved to {debug_filename} for debugging."
    raise ValueError(msg_0)


# ==============================================================================
# 5. EXECUTION NODE
# ==============================================================================
def generate_institutional_report(stock_name):
    logger.info(f"STARTING: Initiating structured JSON pipeline for: {stock_name}")
    status_tracker["stocks"][stock_name] = "Processing..."
    save_status()

    total_models = len(GEMINI_MODEL_CASCADE)

    for attempt, current_model in enumerate(GEMINI_MODEL_CASCADE, 1):
        try:
            logger.info(
                f"[{stock_name}] Stage 1: Scrape & Synthesis using [{current_model}] (Tier {attempt}/{total_models})"
            )

            master_prompt = system_master_prompt_template.replace("{stock_name}", stock_name)

            response = client.models.generate_content(
                model=current_model,
                contents=f"Execute the 8-module JSON master analysis strictly for: {stock_name}",
                config=types.GenerateContentConfig(
                    system_instruction=master_prompt,
                    temperature=0.1,
                    tools=[{"google_search": {}}],
                    safety_settings=SAFETY_CONFIG,
                ),
            )

            if not response.candidates or not response.candidates[0].content.parts:
                finish_reason = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
                msg = f"API returned empty text. Finish Reason: {finish_reason}"
                raise ValueError(msg)

            clean_text = extract_json_from_text(response.text, stock_name, attempt)
            json_payload = json.loads(clean_text)

            logger.info(f"[{stock_name}] Stage 2: Independent Verification Audit using [{current_model}]")

            memory_metadata = json_payload.get("metadata", {})
            memory_kpis = json_payload.get("kpis", {})

            # ---------------------------------------------------------
            # THE FIX: Use .replace() instead of .format() to avoid JSON bracket conflicts
            # ---------------------------------------------------------
            val_prompt = validation_prompt_template.replace("{stock_name}", stock_name)
            val_prompt = val_prompt.replace("{metadata}", json.dumps(memory_metadata, indent=2))
            val_prompt = val_prompt.replace("{kpis}", json.dumps(memory_kpis, indent=2))

            val_response = client.models.generate_content(
                model=current_model,
                contents=val_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0, tools=[{"google_search": {}}], safety_settings=SAFETY_CONFIG
                ),
            )

            if not val_response.candidates or not val_response.candidates[0].content.parts:
                finish_reason = val_response.candidates[0].finish_reason if val_response.candidates else "UNKNOWN"
                logger.warning(f"[{stock_name}] Audit failed (Empty API Response). Finish Reason: {finish_reason}")
                val_payload = {
                    "status": "FAIL",
                    "discrepancies": f"API returned empty response. Reason: {finish_reason}",
                }
            else:
                clean_val_text = extract_json_from_text(val_response.text, stock_name, attempt)
                try:
                    val_payload = json.loads(clean_val_text)
                    logger.info(f"[{stock_name}] Audit Result: {val_payload.get('status', 'UNKNOWN')}")
                except Exception:
                    logger.warning(f"[{stock_name}] Audit failed to parse correctly. Defaulting to FAIL.")
                    val_payload = {"status": "FAIL", "discrepancies": "Audit JSON parsing failed."}

            json_payload["verification"] = val_payload

            filename = f"{output_dir}/{stock_name.replace(' ', '_')}_Forensic_Report.json"
            with open(filename, "w", encoding="utf-8") as file:
                json.dump(json_payload, file, indent=4)

            logger.info(f"SUCCESS: JSON data committed cleanly to {filename}")
            status_tracker["stocks"][stock_name] = (
                f"Completed via {current_model} (Audit: {val_payload.get('status', 'N/A')})"
            )
            status_tracker["completed"] += 1
            save_status()

            return

        except json.JSONDecodeError as je:
            logger.warning(
                f"Tier {attempt}/{total_models} FAILED (JSON Decoding Error) using [{current_model}] for {stock_name}. Error: {je}"
            )
            if attempt < total_models:
                logger.info("Parsing failure. Escaping to next model layer in 15 seconds...")
                time.sleep(15)
            else:
                status_tracker["stocks"][stock_name] = "Failed (JSON Parse Error on all models)"
                status_tracker["failed"] += 1
                save_status()

        except Exception as e:
            logger.warning(f"Tier {attempt}/{total_models} FAILED using [{current_model}] for {stock_name}. Error: {e}")
            if attempt < total_models:
                logger.info("API/Network/Quota failure. Escaping to next model layer in 15 seconds...")
                time.sleep(15)
            else:
                status_tracker["stocks"][stock_name] = f"Failed (All Models Exhausted): {e!s}"
                status_tracker["failed"] += 1
                save_status()


if __name__ == "__main__":
    logger.info(f"PIPELINE INITIATED: Loaded {len(stock_list)} nodes into JSON queue.")
    save_status()

    for idx, stock in enumerate(stock_list, 1):
        logger.info(f"--- Processing {idx}/{len(stock_list)} ---")
        generate_institutional_report(stock)

        if idx < len(stock_list):
            logger.info("Enforcing 30-second rate-limit cooling index...")
            time.sleep(30)

    logger.info(f"PIPELINE SUMMARY COMPLETE: {status_tracker['completed']} clean, {status_tracker['failed']} breaks.")
