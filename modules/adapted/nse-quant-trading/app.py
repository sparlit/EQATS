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


import os
import re

from dotenv import load_dotenv

load_dotenv()

import contextlib
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from supabase import Client, create_client

st.set_page_config(
    page_title="NSE Quantitative Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "output"

REPORTS = {
    "All Scores": "all_scores.csv",
    "Next-Day Candidates": "next_day_candidates.csv",
    "Swing Candidates": "swing_candidates.csv",
    "Historical Setup Stats": "historical_setup_stats.csv",
    "Position Selection": "position_selection.csv",
    "High-Priority Overlap": "high_priority_overlap.csv",
}

FREE_REPORTS = {
    "All Scores",
    "Historical Setup Stats",
    "Swing Candidates",
    "Position Selection",
}
PREMIUM_REPORTS = {
    "Next-Day Candidates",
    "High-Priority Overlap",
}


@st.cache_data(ttl=300, show_spinner=False)
def build_symbol_index(report_items):
    symbols = set()
    for _, df in report_items:
        sc = symbol_col(df)
        if sc and not df.empty:
            symbols.update(str(v).strip().upper() for v in df[sc].dropna().tolist() if str(v).strip())
    return sorted(symbols)


@st.cache_data(ttl=300, show_spinner=False)
def build_stock_profile(symbol, report_items):
    found = []
    target = str(symbol).strip().upper()
    for name, df in report_items:
        sc = symbol_col(df)
        if sc and not df.empty:
            matches = df[df[sc].astype(str).str.upper().eq(target)]
            if not matches.empty:
                found.append((name, matches.copy()))
    return found


def secret(name, default=None):
    try:
        value = st.secrets.get(name)
        if value is not None:
            return value
    except Exception:
        pass
    return os.getenv(name, default)


SUPABASE_URL = secret("SUPABASE_URL")
SUPABASE_ANON_KEY = secret("SUPABASE_ANON_KEY") or secret("SUPABASE_KEY")


PAYMENT_API_URL = secret(
    "PAYMENT_API_URL",
    "https://nse-quant-trading.onrender.com",
)
RAZORPAY_KEY_ID = secret("RAZORPAY_KEY_ID")
RAZORPAY_PLAN_ID = secret(
    "RAZORPAY_PLAN_ID",
    "plan_TVJ8M57jAt8Ddj",
)

supabase = None
if SUPABASE_URL and SUPABASE_ANON_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    except Exception:
        supabase = None

st.markdown(
    """
    <style>
    .block-container{max-width:1900px;padding:1.2rem 2rem 3rem}
    .hero,.stock-page-hero{padding:clamp(18px,4vw,34px);border-radius:20px;margin-bottom:18px;border:1px solid rgba(128,128,128,.20);background:linear-gradient(135deg,rgba(51,153,204,.14),rgba(128,128,128,.06))}
    .hero-kicker{font-size:.72rem;font-weight:800;letter-spacing:.14em;opacity:.65;margin-bottom:8px}
    .hero h1,.stock-page-hero h1{margin:0 0 8px;font-size:clamp(1.8rem,5vw,3rem)}
    .hero p,.stock-page-hero p{margin:0;opacity:.78}
    .metric-card,.signal-card{border:1px solid rgba(128,128,128,.22);border-radius:14px;padding:14px;margin:5px 0;min-height:84px}
    .metric-title,.signal-label{font-size:.74rem;font-weight:700;opacity:.65;text-transform:uppercase;letter-spacing:.04em}
    .metric-value{font-size:1.45rem;font-weight:800;margin-top:6px}
    .metric-access{font-size:.74rem;opacity:.6;margin-top:3px}
    .signal-value{font-size:1rem;font-weight:750;margin-top:6px;word-break:break-word}
    .premium-lock{border:1px dashed rgba(128,128,128,.38);border-radius:14px;padding:18px;text-align:center;margin:6px 0}
    @media (max-width:768px){
        .block-container{padding:.55rem .45rem 1.75rem}
        .stTabs [data-baseweb="tab-list"]{overflow-x:auto;white-space:nowrap}
        .stTabs [data-baseweb="tab"]{font-size:.8rem;padding:8px}
        .stButton button,.stTextInput input{min-height:44px}
        div[data-testid="stDataFrame"]{max-width:100%;overflow-x:auto;border-radius:10px}
        .metric-card,.signal-card{padding:11px}
    }
    @media (max-width:480px){
        .block-container{padding:.4rem .3rem 1.25rem}
        .hero,.stock-page-hero{padding:15px;border-radius:15px}
        .metric-value{font-size:1.2rem}
        .signal-value{font-size:.92rem}
    }
    .paid-box{border:1px solid rgba(128,128,128,.30);border-radius:14px;padding:22px;margin:10px 0}

    .hero{
        padding:clamp(20px,4vw,34px);
        border-radius:22px;
        margin-bottom:18px;
        border:1px solid rgba(128,128,128,.20);
        background:linear-gradient(135deg,rgba(51,153,204,.14),rgba(128,128,128,.06));
    }
    .hero h1{margin:0 0 8px;font-size:clamp(1.8rem,5vw,3rem)}
    .hero p{margin:0;opacity:.76}
    .hero-kicker,.report-kicker,.stock-profile-kicker{
        font-size:.70rem;
        font-weight:800;
        letter-spacing:.14em;
        opacity:.62;
    }
    .report-header-card{
        padding:18px 20px;
        margin:12px 0;
        border:1px solid rgba(128,128,128,.20);
        border-radius:16px;
        background:rgba(128,128,128,.035);
    }
    .report-header-card h2{margin:5px 0;font-size:clamp(1.25rem,3vw,1.75rem)}
    .report-header-card p{margin:0;opacity:.65;font-size:.86rem}
    .metric-card,.signal-card,.data-field-card{
        border:1px solid rgba(128,128,128,.20);
        border-radius:14px;
        padding:13px;
        margin:5px 0;
        background:rgba(128,128,128,.025);
    }
    .metric-title,.signal-label,.data-field-label{
        font-size:.70rem;
        font-weight:750;
        text-transform:uppercase;
        letter-spacing:.04em;
        opacity:.62;
    }
    .metric-value,.signal-value{
        font-size:1.15rem;
        font-weight:800;
        margin-top:6px;
        word-break:break-word;
    }
    .data-field-value{
        margin-top:6px;
        font-size:.92rem;
        line-height:1.35;
        word-break:break-word;
        overflow-wrap:anywhere;
    }
    .stock-profile-header{
        padding:clamp(20px,4vw,36px);
        border-radius:22px;
        margin-bottom:16px;
        border:1px solid rgba(128,128,128,.20);
        background:linear-gradient(135deg,rgba(51,153,204,.16),rgba(128,128,128,.06));
    }
    .stock-symbol{
        font-size:clamp(2.2rem,8vw,4.5rem);
        line-height:1;
        font-weight:900;
        margin:8px 0;
        letter-spacing:-.04em;
    }
    .stock-profile-subtitle{opacity:.68;font-size:.92rem}
    .profile-report-title{
        display:flex;
        justify-content:space-between;
        align-items:center;
        gap:12px;
        padding:12px 14px;
        margin:16px 0 7px;
        border-radius:12px;
        border:1px solid rgba(128,128,128,.18);
    }
    .profile-report-title span{font-size:.75rem;opacity:.62}
    @media (max-width:768px){
        .block-container{padding:.5rem .4rem 1.5rem}
        .stButton button,.stTextInput input{min-height:44px}
        div[data-testid="stDataFrame"]{
            max-width:100%!important;
            overflow-x:auto!important;
            border-radius:10px;
        }
        .report-header-card,.stock-profile-header{border-radius:15px;padding:15px}
        .profile-report-title{align-items:flex-start;flex-direction:column;gap:3px}
        .data-field-card,.signal-card{padding:11px}
        .data-field-value{font-size:.86rem}
    }
    @media (max-width:480px){
        .block-container{padding:.35rem .25rem 1.25rem}
        .stock-symbol{font-size:2.5rem}
        .metric-value,.signal-value{font-size:1rem}
        .stSelectbox label,.stTextInput label{font-size:.82rem}
    }

    /* Keep the initial viewport compact; detailed tables open on demand. */
    .report-header-card{content-visibility:auto;contain-intrinsic-size:120px}
    .profile-report-title{content-visibility:auto;contain-intrinsic-size:55px}

    .stock-profile-header{content-visibility:auto;contain-intrinsic-size:180px}
    .signal-card,.data-field-card{content-visibility:auto;contain-intrinsic-size:80px}
    @media (max-width:768px){
        .block-container{padding:.45rem .35rem 1.4rem}
        .stButton button,.stSelectbox [data-baseweb="select"]{min-height:44px}
        .data-field-card{min-height:70px}
        div[data-testid="stDataFrame"]{max-width:100%!important;overflow-x:auto!important}
    }
    </style>
    """,
    unsafe_allow_html=True,
)

for key, value in {
    "analysis_symbol": None,
    "logged_in": False,
    "user": None,
    "access_token": None,
    "subscription": None,
    "checkout_subscription_id": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = value


def clear_login():
    st.session_state.logged_in = False
    st.session_state.user = None
    st.session_state.access_token = None
    st.session_state.subscription = None
    st.session_state.analysis_symbol = None
    st.session_state.checkout_subscription_id = None


def login_user(email, password):
    if supabase is None:
        return False, "Supabase is not configured in Streamlit Secrets."
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        session = getattr(response, "session", None)
        user = getattr(response, "user", None)
        if not session or not user:
            return False, "Login failed. Check email and password."
        st.session_state.logged_in = True
        st.session_state.user = user
        st.session_state.access_token = session.access_token
        return True, None
    except Exception as exc:
        return False, str(exc)


def register_user(email, password):
    if supabase is None:
        return False, "Supabase is not configured in Streamlit Secrets."
    try:
        response = supabase.auth.sign_up({"email": email, "password": password})
        user = getattr(response, "user", None)
        session = getattr(response, "session", None)
        if not user:
            return False, "Registration failed."
        if session:
            st.session_state.logged_in = True
            st.session_state.user = user
            st.session_state.access_token = session.access_token
            return True, None
        return True, "Account created. Check your email to confirm your account."
    except Exception as exc:
        return False, str(exc)


def load_subscription():
    if supabase is None or not st.session_state.logged_in:
        return None
    try:
        user = st.session_state.user
        user_id = getattr(user, "id", None)
        if not user_id:
            return None
        client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        # Keep the authenticated user's JWT for RLS.
        client.auth.set_session(st.session_state.access_token, "")
        response = (
            client.table("subscriptions")
            .select("status,plan_name,amount,razorpay_subscription_id,start_date,end_date")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None
    except Exception:
        return None


def subscription_is_active(subscription):
    return bool(subscription and str(subscription.get("status", "")).lower() in {"active", "authenticated"})


# ------------------------- LOGIN -------------------------

if not st.session_state.logged_in:
    st.title("📈 NSE Quantitative Trading Dashboard")
    st.caption("Login required to access the stock research dashboard.")

    if supabase is None:
        st.error(
            "Supabase authentication is not configured. Add SUPABASE_URL and SUPABASE_ANON_KEY to Streamlit Secrets."
        )
        st.stop()

    login_tab, register_tab = st.tabs(["🔐 Login", "📝 Create Account"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)
        if submitted:
            if not email or not password:
                st.error("Enter both email and password.")
            else:
                ok, message = login_user(email.strip(), password)
                if ok:
                    if message:
                        st.info(message)
                    st.rerun()
                else:
                    st.error(message)

    with register_tab:
        with st.form("register_form"):
            new_email = st.text_input("Email", placeholder="you@example.com")
            new_password = st.text_input("Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            register = st.form_submit_button(
                "Create Account",
                use_container_width=True,
            )
        if register:
            if not new_email or not new_password:
                st.error("Enter email and password.")
            elif len(new_password) < 8:
                st.error("Password must be at least 8 characters.")
            elif new_password != confirm_password:
                st.error("Passwords do not match.")
            else:
                ok, message = register_user(new_email.strip(), new_password)
                if ok:
                    if message:
                        st.success(message)
                    if st.session_state.logged_in:
                        st.rerun()
                else:
                    st.error(message)
    st.stop()

# ------------------------- SIDEBAR -------------------------

with st.sidebar:
    st.success(f"Logged in\n{getattr(st.session_state.user, 'email', 'User')}")
    if st.button("🚪 Logout", use_container_width=True):
        with contextlib.suppress(Exception):
            supabase.auth.sign_out()
        clear_login()
        st.rerun()

# ------------------------- SUBSCRIPTION -------------------------

subscription = load_subscription()
st.session_state.subscription = subscription
has_paid_access = subscription_is_active(subscription)

# Free users can use the selected free reports without a subscription.
# Paid users receive the complete research dashboard.
if not has_paid_access:
    st.markdown(
        """
        <div class="paid-box">
            <h2>🔓 Free Research Access</h2>
            <p>
                All Scores, Historical Setup Stats, Swing Candidates and
                Position Selection are available free. Stock Analysis is
                available when you select a stock.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info("Premium unlocks Next-Day Candidates, High-Priority Overlap and future premium features.")

    if subscription:
        st.caption(f"Current subscription status: {subscription.get('status', 'unknown')}")

    if not RAZORPAY_KEY_ID:
        st.warning("Razorpay checkout is not configured yet. Add RAZORPAY_KEY_ID to Streamlit Secrets.")
    elif st.button(
        "💳 Upgrade to Premium — ₹100 / month",
        type="primary",
        use_container_width=True,
    ):
        try:
            response = requests.post(
                f"{PAYMENT_API_URL.rstrip('/')}/create-subscription",
                headers={
                    "Authorization": f"Bearer {st.session_state.access_token}",
                    "Content-Type": "application/json",
                },
                json={},
                timeout=30,
            )
            if response.status_code != 200:
                try:
                    detail = response.json()
                except Exception:
                    detail = response.text
                st.error(f"Unable to create subscription: {detail}")
            else:
                data = response.json()
                sid = data.get("subscription_id")
                if sid:
                    st.session_state.checkout_subscription_id = sid
                else:
                    st.error("Payment API did not return a subscription ID.")
        except Exception as exc:
            st.error(f"Payment service error: {exc}")

    sid = st.session_state.checkout_subscription_id
    if sid:
        checkout_html = f"""
        <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
        <button id="rzp-button" style="
            width:100%;max-width:600px;margin:auto;display:block;
            padding:14px;border:0;border-radius:10px;
            cursor:pointer;font-size:16px;font-weight:700;">
            Continue to Razorpay Checkout
        </button>
        <script>
        document.getElementById("rzp-button").onclick = function(e) {{
            var options = {{
                "key": "{RAZORPAY_KEY_ID}",
                "subscription_id": "{sid}",
                "name": "NSE Quant Trading",
                "description": "₹100 monthly subscription",
                "handler": function(response) {{
                    document.getElementById("rzp-button").innerText =
                        "Payment submitted — refresh this page after payment.";
                }},
                "theme": {{"color": "#3399cc"}}
            }};
            var rzp = new Razorpay(options);
            rzp.on("payment.failed", function(response) {{
                alert("Payment failed: " + response.error.description);
            }});
            rzp.open();
            e.preventDefault();
        }};
        </script>
        """
        st.components.v1.html(
            checkout_html,
            height=750,
            scrolling=True,
        )

# ------------------------- DASHBOARD -------------------------


st.markdown(
    """
    <div class="hero">
        <div class="hero-kicker">NSE QUANT • RESEARCH PLATFORM</div>
        <h1>📈 Quantitative Trading Dashboard</h1>
        <p>Discover signals, compare setups and inspect any stock in a dedicated research view.</p>
    </div>
    """,
    unsafe_allow_html=True,
)
if has_paid_access:
    st.success(f"Premium access active — {(subscription or {}).get('plan_name', 'Monthly Plan')}")
else:
    st.info("Free plan active — selected research features are available.")


@st.cache_data(ttl=300, show_spinner=False)
def load_csv(name):
    p = OUTPUT / name
    if not p.exists():
        return pd.DataFrame()
    try:
        d = pd.read_csv(p, low_memory=False)
        d.columns = [str(c).strip().replace("\n", " ") for c in d.columns]
        return d
    except Exception as e:
        return pd.DataFrame({"_READ_ERROR_": [str(e)]})


def symbol_col(df):
    if df.empty:
        return None
    for c in ["SYMBOL", "Symbol", "symbol", "STOCK", "Stock", "TICKER", "Ticker", "SECURITY", "Security"]:
        if c in df.columns:
            return c
    for c in df.columns:
        u = str(c).upper()
        if "SYMBOL" in u or "TICKER" in u:
            return c
    return None


def fmt(v):
    if pd.isna(v):
        return "—"
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return str(v)


def safe_key(value):
    return re.sub(r"[^a-zA-Z0-9]+", "_", str(value)).strip("_").lower()


reports = {k: load_csv(v) for k, v in REPORTS.items()}

mods = []
for filename in REPORTS.values():
    p = OUTPUT / filename
    if p.exists():
        mods.append(datetime.fromtimestamp(p.stat().st_mtime))
if mods:
    st.info(f"Latest report update: {max(mods):%d-%b-%Y %H:%M:%S}")

all_df = reports["All Scores"]
next_df = reports["Next-Day Candidates"]
swing_df = reports["Swing Candidates"]
pos_df = reports["Position Selection"]
overlap_df = reports["High-Priority Overlap"]

c = st.columns(6)
metrics = [
    ("All Scores", all_df),
    ("Next-Day", next_df),
    ("Swing", swing_df),
    ("Position", pos_df),
    ("High Priority", overlap_df),
    ("Reports Loaded", None),
]
for box, (title, df) in zip(c, metrics, strict=False):
    value = f"{sum(not x.empty for x in reports.values())}/6" if df is None else f"{len(df):,}"
    box.metric(title, value)

st.markdown("## 🔎 Stock Finder")

symbol_options = build_symbol_index(tuple(reports.items()))

if symbol_options:
    selected_symbol = st.selectbox(
        "Search and select a stock",
        symbol_options,
        index=(
            symbol_options.index(st.session_state.analysis_symbol)
            if st.session_state.analysis_symbol in symbol_options
            else 0
        ),
        placeholder="Type a stock symbol",
    )
    if st.button("🔬 Open Stock Analysis →", type="primary", use_container_width=True):
        st.session_state.analysis_symbol = selected_symbol
        st.query_params["view"] = "stock"
        st.query_params["symbol"] = selected_symbol
        st.rerun()
    st.caption("Choose a stock to open a dedicated, mobile-friendly analysis page.")
else:
    st.warning("No stock symbols are currently available.")

# ------------------------- RESEARCH WORKSPACE -------------------------

st.markdown("## 📊 Research Workspace")

# Desktop: horizontal report navigation.
# Mobile: a single dropdown is easier to use and prevents six tiny tabs.
report_names = list(REPORTS)
available_reports = report_names if has_paid_access else [n for n in report_names if n in FREE_REPORTS]

# Report selector: use the dropdown as the compact/mobile-safe navigation.
# Desktop also gets the side-by-side navigation buttons below.
selected_report_mobile = st.selectbox(
    "📱 Select report",
    available_reports,
    format_func=lambda n: f"{'🔒 ' if n in PREMIUM_REPORTS else '📄 '}{n}",
)

# A professional desktop navigation row.
if True:
    nav_cols = st.columns(min(len(available_reports), 6))
    for col, name in zip(nav_cols, available_reports, strict=False):
        with col:
            if st.button(
                name,
                key="nav_" + safe_key(name),
                use_container_width=True,
            ):
                st.session_state.active_report = name

    if "active_report" not in st.session_state or st.session_state.active_report not in available_reports:
        st.session_state.active_report = available_reports[0]

    active_reports = [st.session_state.active_report]

name = st.session_state.get("active_report", selected_report_mobile)
if selected_report_mobile and st.session_state.get("_last_mobile_report") != selected_report_mobile:
    st.session_state["_last_mobile_report"] = selected_report_mobile
    name = selected_report_mobile
    st.session_state.active_report = selected_report_mobile
filename = REPORTS[name]
df = reports[name]

st.markdown(
    f"""
    <div class="report-header-card">
        <div class="report-kicker">RESEARCH REPORT</div>
        <h2>{name}</h2>
        <p>{"Premium" if name in PREMIUM_REPORTS else "Available on Free plan"} • {len(df):,} rows • {len(df.columns):,} data fields</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if df.empty:
    st.warning(f"{name}: file missing or empty. Expected output/{filename}")
else:
    q = st.text_input(
        "🔎 Search stocks",
        key="workspace_search_" + safe_key(name),
        placeholder="Search stock symbol or any value…",
    )

    view = df
    if q.strip():
        mask = view.astype(str).apply(lambda s: s.str.contains(q.strip(), case=False, na=False)).any(axis=1)
        view = view.loc[mask]

    st.caption(f"Showing {len(view):,} of {len(df):,} rows • Select a stock row to open its complete research profile.")

    # The dataframe remains the primary desktop table.
    # Selecting a row immediately opens the complete stock profile.
    try:
        event = st.dataframe(
            view,
            hide_index=True,
            width="stretch",
            height=520,
            on_select="rerun",
            selection_mode="single-row",
        )
        selected_rows = getattr(event.selection, "rows", []) if event else []
    except TypeError:
        event = st.dataframe(
            view,
            hide_index=True,
            width="stretch",
            height=650,
        )
        selected_rows = []

    if selected_rows:
        sc = symbol_col(view)
        if sc:
            selected_symbol = str(view.iloc[selected_rows[0]][sc]).strip().upper()
            st.session_state.analysis_symbol = selected_symbol
            st.query_params["view"] = "stock"
            st.query_params["symbol"] = selected_symbol
            st.rerun()

    st.info(
        "💡 Select/double-click a stock row to open its dedicated profile. "
        "The profile combines every matching field from every generated report."
    )

# ------------------------- STOCK PROFILE -------------------------

sym = st.query_params.get("symbol") or st.session_state.analysis_symbol
view_mode = st.query_params.get("view")

if view_mode == "stock" and sym:
    st.markdown("---")
    st.markdown(
        f"""
        <div class="stock-profile-header">
            <div class="stock-profile-kicker">NSE QUANT • STOCK PROFILE</div>
            <div class="stock-symbol">{sym}</div>
            <div class="stock-profile-subtitle">
                Complete cross-report research — load one report at a time
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    back_col, refresh_col = st.columns(2)
    with back_col:
        if st.button("← Back to Reports", use_container_width=True):
            st.query_params.clear()
            st.session_state.analysis_symbol = None
            st.rerun()
    with refresh_col:
        if st.button("↻ Refresh", use_container_width=True):
            st.rerun()

    # Cache the lookup once. The UI below deliberately renders only one
    # selected report at a time, avoiding six simultaneous large tables.
    found = build_stock_profile(str(sym), tuple(reports.items()))

    if not found:
        st.warning(f"No matching rows found for {sym}.")
    else:
        found_map = dict(found)
        found_names = [name for name, _ in found]

        st.markdown("### 📌 Stock Snapshot")

        # Small, fast snapshot from the first matching row in each report.
        snapshot_keys = [
            "CMP",
            "PRICE",
            "LTP",
            "BIAS",
            "SIGNAL",
            "CONFIDENCE",
            "SCORE",
            "NEXT_DAY_SCORE",
            "SWING_SCORE",
            "HISTORICAL_SCORE",
            "POSITION_SCORE",
            "FACTOR_RATIO",
            "ALIGNED_FACTORS",
            "EXPECTED_RANGE_LOW_PCT",
            "EXPECTED_RANGE_HIGH_PCT",
            "INVALIDATION",
            "PRIMARY_DRIVER",
            "CONFLICTING_SIGNAL",
            "TRADE_MODE",
            "IN_NEXT_DAY",
            "IN_SWING",
            "OVERLAP",
        ]
        snapshot = {}
        for report_name in found_names:
            row = found_map[report_name].iloc[0]
            for key in snapshot_keys:
                if key in row.index and key not in snapshot:
                    snapshot[key] = row[key]

        if snapshot:
            items = list(snapshot.items())
            # Keep the snapshot deliberately small; complete data is below.
            for i in range(0, min(len(items), 8), 2):
                cols = st.columns(2)
                for col, (key, value) in zip(cols, items[i : i + 2], strict=False):
                    with col:
                        st.markdown(
                            f"""
                            <div class="signal-card">
                                <div class="signal-label">{key.replace("_", " ")}</div>
                                <div class="signal-value">{fmt(value)}</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

        st.markdown("### 📚 Stock Reports")

        # Mobile and desktop both use a single report selector.
        selected_report = st.selectbox(
            "Select report to inspect",
            found_names,
            format_func=lambda n: f"{'🔒 ' if n in PREMIUM_REPORTS else '📄 '}{n}",
        )

        selected_df = found_map[selected_report]

        st.caption(f"{selected_report} • {len(selected_df):,} matching row(s) • {len(selected_df.columns):,} fields")

        # COMPLETE DATA for the selected report, but rendered only on demand.
        # Transpose is much easier to read on phones for a single stock.
        if len(selected_df) == 1:
            row = selected_df.iloc[0]
            field_items = list(row.items())

            st.markdown("#### Complete Stock Data")
            for i in range(0, len(field_items), 2):
                cols = st.columns(2)
                for col, (field, value) in zip(cols, field_items[i : i + 2], strict=False):
                    with col:
                        st.markdown(
                            f"""
                            <div class="data-field-card">
                                <div class="data-field-label">{field}</div>
                                <div class="data-field-value">{fmt(value)}</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
        else:
            # Multiple matches: native table is more efficient than hundreds
            # of individual HTML cards.
            st.dataframe(
                selected_df,
                hide_index=True,
                width="stretch",
                height=560,
            )

        with st.expander("🖥️ View original table format"):
            st.dataframe(
                selected_df,
                hide_index=True,
                width="stretch",
                height=560,
            )

    st.markdown("---")
    st.caption("Research/ranking tool only. Scores are not guaranteed returns; leverage magnifies gains and losses.")
    st.stop()

st.markdown("---")
st.caption("Research/ranking tool only. Scores are not guaranteed returns; leverage magnifies gains and losses.")
