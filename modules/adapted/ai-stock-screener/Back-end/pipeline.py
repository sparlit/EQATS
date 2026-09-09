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


# pipeline.py
import json
import os
from typing import Any, Dict, List, TypedDict

from data_screener import fetch_and_screen_stocks
from google import genai
from google.genai import types
from langgraph.graph import END, StateGraph
from stock_universes import get_universe


# --- 1. STATE DEFINITION ---
# This dictionary tracks the data as it moves step-by-step through the LangGraph pipeline.
class MarketState(TypedDict):
    category: str  # e.g., 'nifty_50', 'midcap'
    universe: list[str]  # The raw list of tickers to check
    technical_screened: list[dict[str, Any]]  # Stocks that passed the data_screener.py rules
    final_picks: list[dict[str, Any]]  # Stocks that Gemini approved


# --- 2. PIPELINE NODES ---
def technical_screener_node(state: MarketState) -> dict[str, Any]:
    """Node 1: Passes the raw universe list to the technical screener and updates the state."""
    print(f"\n[Graph] Running Technical Screener for category: {state['category'].upper()}...")
    screened = fetch_and_screen_stocks(state["universe"])
    return {"technical_screened": screened}


def llm_synthesis_node(state: MarketState) -> dict[str, Any]:
    """Node 2: Sends technically sound stocks to Gemini 3.6 Flash for final approval and saves to desktop."""
    screened_stocks = state.get("technical_screened", [])
    print(f"\n[Graph] Sending {len(screened_stocks)} screened stocks to Gemini...")

    if not screened_stocks:
        print("  No stocks met technical criteria. Skipping LLM call.")
        return {"final_picks": []}

    client = genai.Client()
    picks = []

    # Define your specific Windows desktop path
    desktop_file_path = r"C:\Users\Amul\OneDrive\Desktop\gemini_analysis.txt"

    for stock in screened_stocks:
        print(f"  Analyzing {stock['ticker']}...")

        prompt = f"""
        Analyze {stock["ticker"]} ({state["category"].upper()} segment) for a 1-2 week swing trade in the Indian Stock Market.
        Technical Profile: Close: ₹{stock["close"]}, RSI: {stock["rsi"]}, Trend: {stock["trend"]}.
        Target: ₹{stock["target"]}, Stop Loss: ₹{stock["stop_loss"]}.

        Provide a concise thesis on whether this setup offers favorable risk-to-reward.
        """

        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "OBJECT",
                        "properties": {
                            "score": {"type": "INTEGER", "description": "0 to 100 confidence score"},
                            "conviction": {"type": "STRING", "enum": ["High", "Medium", "Low"]},
                            "thesis": {"type": "STRING", "description": "1-2 sentence core reason"},
                        },
                        "required": ["score", "conviction", "thesis"],
                    },
                ),
            )

            analysis = json.loads(response.text)

            # --- NEW: Save the output to a text file on your Desktop ---
            try:
                # 'a' mode appends to the file instead of overwriting it each time
                with open(desktop_file_path, "a", encoding="utf-8") as file:
                    file.write(f"=== {stock['ticker']} Analysis ===\n")
                    file.write(f"Category: {state['category'].upper()}\n")
                    file.write(f"Technical Data: {json.dumps(stock, indent=2)}\n")
                    file.write(f"Gemini Output: {json.dumps(analysis, indent=2)}\n")
                    file.write("-" * 40 + "\n\n")
            except Exception as e:
                # Fails silently if running on PythonAnywhere (which doesn't have a C: drive)
                print(f"  [Note] Could not save to desktop (likely running on cloud server): {e}")

            if analysis.get("score", 0) >= 50:
                picks.append({**stock, **analysis, "category": state["category"]})

        except Exception as e:
            print(f"  Error analyzing {stock['ticker']}: {e}")

    picks.sort(key=lambda x: x["score"], reverse=True)
    return {"final_picks": picks}

    for stock in screened_stocks:
        print(f"  Analyzing {stock['ticker']}...")

        # The prompt forces Gemini to act as a trader evaluating the risk-to-reward
        prompt = f"""
        Analyze {stock["ticker"]} ({state["category"].upper()} segment) for a 1-2 week swing trade in the Indian Stock Market.
        Technical Profile: Close: ₹{stock["close"]}, RSI: {stock["rsi"]}, Trend: {stock["trend"]}.
        Target: ₹{stock["target"]}, Stop Loss: ₹{stock["stop_loss"]}.

        Provide a concise thesis on whether this setup offers favorable risk-to-reward.
        """

        try:
            # We strictly enforce JSON output so our React frontend can easily display it in a table
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "OBJECT",
                        "properties": {
                            "score": {"type": "INTEGER", "description": "0 to 100 confidence score"},
                            "conviction": {"type": "STRING", "enum": ["High", "Medium", "Low"]},
                            "thesis": {"type": "STRING", "description": "1-2 sentence core reason"},
                        },
                        "required": ["score", "conviction", "thesis"],
                    },
                ),
            )

            analysis = json.loads(response.text)

            # --- THE AI FILTER ---
            # Lowered to 50 to allow medium-conviction setups to display on the dashboard
            if analysis.get("score", 0) >= 50:
                picks.append({**stock, **analysis, "category": state["category"]})

        except Exception as e:
            print(f"  Error analyzing {stock['ticker']}: {e}")

    # Sort the final picks so the highest AI score appears at the top of the table
    picks.sort(key=lambda x: x["score"], reverse=True)
    return {"final_picks": picks}


# --- 3. BUILD GRAPH ---
def build_pipeline():
    """Compiles the nodes into a LangGraph workflow."""
    builder = StateGraph(MarketState)

    builder.add_node("screen_technicals", technical_screener_node)
    builder.add_node("llm_reasoning", llm_synthesis_node)

    # Define the order of operations
    builder.set_entry_point("screen_technicals")
    builder.add_edge("screen_technicals", "llm_reasoning")
    builder.add_edge("llm_reasoning", END)

    return builder.compile()


# --- 4. EXECUTION HELPER ---
def run_analysis_for_category(category: str = "nifty_50"):
    """Entry function called by the Flask server to trigger a specific category scan."""
    universe = get_universe(category)
    app = build_pipeline()

    # Inject the initial state into the graph and start the run
    return app.invoke({"category": category, "universe": universe, "technical_screened": [], "final_picks": []})
