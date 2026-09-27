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
Hand-rolled tool-calling agent loop against Databricks Foundation Model APIs
-- no framework, every step (tool picked, args, result) is visible.

Model note: Claude isn't available as a pay-per-token Foundation Model API
endpoint on Free Edition (needs Anthropic Marketplace entitlement, gated
behind Account Console access Free Edition doesn't expose). Using Llama 3.3
70B instead -- a strong open-weight model with solid tool-calling support.
"""
import json

from agent import tools
from databricks.sdk import WorkspaceClient

MODEL = "databricks-meta-llama-3-3-70b-instruct"

SYSTEM_PROMPT = (
    "You are a research assistant for Indian (NSE) stocks. You have tools to fetch "
    "price history, compare tickers, semantically search company profiles and news, "
    "manage a personal watchlist, save notes/reports, and check what's moved since the "
    "user's last visit. Use tools whenever a question needs current data -- don't guess "
    "numbers. Be concise and cite specific figures/dates from tool results."
)

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_price_history",
            "description": "Get recent daily OHLCV price history and day-over-day % change for a single NSE ticker.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "NSE ticker symbol, e.g. 'TCS.NS'"},
                    "days": {"type": "integer", "description": "Number of most recent trading days to return"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_tickers",
            "description": "Get recent price history for multiple tickers at once, for side-by-side comparison.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of NSE ticker symbols",
                    },
                    "days": {"type": "integer"},
                },
                "required": ["tickers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_context",
            "description": "Semantic search over company profiles and recent market news. Use this for open-ended or thematic questions (sector exposure, qualitative context) rather than exact price data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language search query"},
                    "num_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_watchlist",
            "description": "Add, remove, or list tickers on the user's watchlist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "remove", "list"]},
                    "ticker": {"type": "string", "description": "Required for 'add'/'remove'; NSE ticker symbol"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_note",
            "description": "Save a free-text research note about a ticker.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "note_text": {"type": "string"},
                },
                "required": ["ticker", "note_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_report",
            "description": "Save a longer analysis report about a ticker, tagged with a report_type (e.g. 'comparison', 'summary').",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "report_type": {"type": "string"},
                    "report_text": {"type": "string"},
                },
                "required": ["ticker", "report_type", "report_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_notable_moves",
            "description": "Get tickers with a >3% single-day price move since the user's last visit (also updates the last-visit timestamp). Use this to answer 'what changed since I last looked'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_FUNCTIONS = {
    "get_price_history": tools.get_price_history,
    "compare_tickers": tools.compare_tickers,
    "search_context": tools.search_context,
    "manage_watchlist": tools.manage_watchlist,
    "save_note": tools.save_note,
    "save_report": tools.save_report,
    "check_notable_moves": tools.check_notable_moves,
}


def run_agent(user_message: str, history=None, max_turns: int = 6):
    client = WorkspaceClient().serving_endpoints.get_open_ai_client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    for _ in range(max_turns):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if not message.tool_calls:
            return message.content, messages

        for tool_call in message.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments or "{}")
            print(f"[tool call] {name}({args})")
            try:
                result = TOOL_FUNCTIONS[name](**args)
            except Exception as e:
                import traceback

                print(f"[tool error] {name}: {e}")
                traceback.print_exc()
                result = {"error": str(e)}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, default=str),
                }
            )

    return "Reached max tool-calling turns without a final answer.", messages
