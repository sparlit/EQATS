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


import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from scipy import stats

# ── Page config ───────────────────────────────────────────────────────────
st.set_page_config(page_title="NSE VaR Dashboard", page_icon="📊", layout="wide")

# ── Header ─────────────────────────────────────────────────────────────────
st.title("📊 NSE Portfolio Risk Dashboard")
st.markdown("**Historical Value at Risk (VaR) Model** — Built by Athrey Sethumadhavan")
st.markdown("---")

# ── Sidebar inputs ─────────────────────────────────────────────────────────
st.sidebar.header("⚙️ Portfolio Settings")

tickers = st.sidebar.multiselect(
    "Select NSE Stocks",
    [
        "RELIANCE.NS",
        "HDFCBANK.NS",
        "TCS.NS",
        "INFY.NS",
        "WIPRO.NS",
        "ICICIBANK.NS",
        "HINDUNILVR.NS",
        "BAJFINANCE.NS",
        "SBIN.NS",
        "AXISBANK.NS",
    ],
    default=["RELIANCE.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "WIPRO.NS"],
)

start_date = st.sidebar.date_input("Start Date", value=pd.to_datetime("2025-01-01"))
end_date = st.sidebar.date_input("End Date", value=pd.to_datetime("2025-12-31"))

confidence = st.sidebar.selectbox("Confidence Level", ["95%", "99%"], index=0)
conf_level = 0.95 if confidence == "95%" else 0.99
quantile = 1 - conf_level

investment = st.sidebar.number_input(
    "Portfolio Value (₹)", min_value=10000, max_value=10000000, value=1000000, step=10000
)

# ── Load data ──────────────────────────────────────────────────────────────
if len(tickers) < 2:
    st.warning("Please select at least 2 stocks.")
    st.stop()

with st.spinner("Fetching market data..."):
    raw = yf.download(tickers, start=start_date, end=end_date, auto_adjust=True)
    prices = raw["Close"]
    returns = prices.pct_change().dropna()

weights = np.array([1 / len(tickers)] * len(tickers))
port_returns = returns.dot(weights)

# ── VaR calculations ───────────────────────────────────────────────────────
hist_var = port_returns.quantile(quantile)
mean_r = port_returns.mean()
std_r = port_returns.std()
z = stats.norm.ppf(quantile)
param_var = mean_r + z * std_r

hist_var_inr = abs(hist_var) * investment
param_var_inr = abs(param_var) * investment

ann_vol = returns.std() * (252**0.5)

# ── KPI row ────────────────────────────────────────────────────────────────
st.subheader("📌 Portfolio Risk Summary")
c1, c2, c3, c4 = st.columns(4)

c1.metric(
    f"Historical VaR ({confidence})",
    f"{hist_var:.2%}",
    help="Worst expected daily loss based on actual historical returns",
)
c2.metric(
    f"Parametric VaR ({confidence})",
    f"{param_var:.2%}",
    help="Worst expected loss assuming normally distributed returns",
)
c3.metric("Max 1-Day Loss at Risk (₹)", f"₹{hist_var_inr:,.0f}", help=f"On your ₹{investment:,} portfolio")
c4.metric(
    "Portfolio Volatility (Ann.)",
    f"{std_r * (252**0.5):.2%}",
    help="Annualised standard deviation of portfolio returns",
)

st.markdown("---")

# ── Two column layout ──────────────────────────────────────────────────────
left, right = st.columns(2)

# ── Histogram ─────────────────────────────────────────────────────────────
with left:
    st.subheader("📉 Return Distribution with VaR Lines")
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(port_returns, bins=50, alpha=0.7, color="#1f77b4", edgecolor="white")
    ax.axvline(hist_var, color="red", linestyle="--", linewidth=2, label=f"Historical VaR {confidence}: {hist_var:.2%}")
    ax.axvline(
        param_var, color="orange", linestyle=":", linewidth=2, label=f"Parametric VaR {confidence}: {param_var:.2%}"
    )
    ax.set_xlabel("Daily Return")
    ax.set_ylabel("Frequency")
    ax.set_title("Portfolio Daily Return Distribution")
    ax.legend()
    fig.tight_layout()
    st.pyplot(fig)

# ── Volatility bar chart ───────────────────────────────────────────────────
with right:
    st.subheader("📊 Annualised Volatility by Stock")
    fig2, ax2 = plt.subplots(figsize=(8, 4))
    colors = ["#d62728" if v == ann_vol.max() else "#2ca02c" if v == ann_vol.min() else "#1f77b4" for v in ann_vol]
    ax2.barh(ann_vol.index, ann_vol.values, color=colors)
    ax2.set_xlabel("Annualised Volatility")
    ax2.set_title("Volatility Comparison (Red = Highest Risk)")
    for i, v in enumerate(ann_vol.values):
        ax2.text(v + 0.002, i, f"{v:.1%}", va="center", fontsize=9)
    fig2.tight_layout()
    st.pyplot(fig2)

st.markdown("---")

# ── VaR comparison table ───────────────────────────────────────────────────
st.subheader("🔍 Historical vs Parametric VaR — What the Difference Tells Us")

var_df = pd.DataFrame(
    {
        "Method": ["Historical Simulation", "Parametric (Normal)"],
        "VaR": [f"{hist_var:.2%}", f"{param_var:.2%}"],
        "₹ at Risk": [f"₹{hist_var_inr:,.0f}", f"₹{param_var_inr:,.0f}"],
        "Assumption": ["Uses actual return distribution", "Assumes returns are normally distributed"],
    }
)

# fix the typo in column reference
var_df = pd.DataFrame(
    {
        "Method": ["Historical Simulation", "Parametric (Normal)"],
        "VaR": [f"{hist_var:.2%}", f"{param_var:.2%}"],
        "Rs at Risk": [f"Rs {hist_var_inr:,.0f}", f"Rs {param_var_inr:,.0f}"],
        "Assumption": ["Uses actual return distribution", "Assumes returns are normally distributed"],
    }
)
st.dataframe(var_df, use_container_width=True, hide_index=True)

diff = abs(hist_var - param_var)
if diff > 0.005:
    st.warning(
        f"⚠️ The two methods diverge by {diff:.2%} — suggesting non-normal (fat-tailed) return behaviour in this portfolio."
    )
else:
    st.success(
        f"✅ The two methods are close (difference: {diff:.2%}) — returns are approximately normally distributed."
    )

st.markdown("---")

# ── Individual stock VaR table ─────────────────────────────────────────────
st.subheader("📋 Individual Stock VaR")

stock_var = pd.DataFrame(
    {
        "Stock": returns.columns,
        "95% Hist VaR": [f"{returns[s].quantile(0.05):.2%}" for s in returns.columns],
        "99% Hist VaR": [f"{returns[s].quantile(0.01):.2%}" for s in returns.columns],
        "Ann. Volatility": [f"{ann_vol[s]:.2%}" for s in returns.columns],
        "Weight": [f"{w:.0%}" for w in weights],
    }
).reset_index(drop=True)

st.dataframe(stock_var, use_container_width=True, hide_index=True)

st.markdown("---")

# ── Footer ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='text-align: center; color: grey; font-size: 12px;'>
    Built by <b>Athrey Sethumadhavan</b> |
    Historical VaR Model | 5 NSE Stocks |
    Pre-study project — MSc Financial Risk Management, Trinity College Dublin 2026
    </div>
    """,
    unsafe_allow_html=True,
)
