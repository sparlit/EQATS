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


from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from MarketInsight.utils.logger import get_logger
from MarketInsight.utils.tools import *

load_dotenv()
logger = get_logger(__name__)

model = ChatOpenAI(model="c1/openai/gpt-5/v-20250930", base_url="https://api.thesys.dev/v1/embed/")

agent = create_agent(
    model,
    tools=[
        get_stock_price,
        get_historical_data,
        get_stock_news,
        get_balance_sheet,
        get_income_statement,
        get_cash_flow,
        get_company_info,
        get_dividends,
        get_splits,
        get_institutional_holders,
        get_major_shareholders,
        get_mutual_fund_holders,
        get_insider_transactions,
        get_analyst_recommendations,
        get_analyst_recommendations_summary,
        get_ticker,
    ],
    checkpointer=MemorySaver(),
)

logger.info("Agent Initiated Successfully")
