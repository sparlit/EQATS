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


import sys

PROJECT_ROOT = "/app/python/source_code"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import streamlit as st
from agent import tools
from agent.agent import run_agent

st.set_page_config(page_title="Stock Research Assistant", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.header("Watchlist")
    try:
        watchlist = tools.manage_watchlist("list")
        for t in watchlist:
            st.write(f"- {t}")
    except Exception as e:
        st.error(f"Could not load watchlist: {e}")

    st.divider()
    st.header("Recent notes")
    try:
        from lakebase.db import get_connection

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT ticker, note_text, created_at FROM research_notes ORDER BY created_at DESC LIMIT 5")
            rows = cur.fetchall()
        if not rows:
            st.caption("No notes yet.")
        for ticker, note_text, created_at in rows:
            st.caption(f"**{ticker}** ({created_at:%Y-%m-%d})")
            st.write(note_text)
    except Exception as e:
        st.error(f"Could not load notes: {e}")

st.title("AI Stock Research Assistant")
st.caption(
    "Ask about NSE stocks -- prices, comparisons, semantic context, your watchlist, "
    "or what's changed since you last looked."
)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask a question..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                answer, _ = run_agent(prompt, history=st.session_state.messages[:-1])
            except Exception as e:
                answer = f"Something went wrong: {e}"
        st.markdown(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
