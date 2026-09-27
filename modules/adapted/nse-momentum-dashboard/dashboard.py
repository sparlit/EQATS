from __future__ import annotations

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
NSE Calendar-Entry Momentum Cockpit (Streamlit)

Run:  streamlit run dashboard.py

Pages (sidebar navigation):
  Overview          - everything that matters at a glance: cash, portfolio
                      value, realized/unrealized P&L, XIRR, open positions,
                      today's pending actions
  Screener          - full ranked universe (all gate-passers, not just what
                      fits your open slots), plus a symbol chart
  Live Rebalance    - run the daily scan, review proposed sells/buys, execute
  Positions & Trade - live holdings/positions, square-off, manual order entry
  Backtest          - calendar-entry engine on real Kite data, 1-5 years
  Fundamentals      - primary-source XBRL value score, all F&O stocks
  Admin             - dashboard password, Kite API settings, deposit/
                      withdrawal ledger

Single strategy: calendar-entry momentum (buy the instant a slot opens,
monthly rebalance + daily stop checks). No AI/LLM anywhere in this app.
"""


import base64
import datetime as dt
import html as html_lib
import math
import os
import re

import backtest as bt
import backtest_report
import fundamentals_agent as fa
import intraday_db as idb
import intraday_market as imkt
import intraday_strategy as istrat
import kite_client
import live_rebalance as lr
import live_ticker
import notify
import nse_holidays
import pandas as pd
import plotly.graph_objects as go
import screener
import sector_universe as su
import streamlit as st
from background_jobs import cancel_background_job, clear_background_job, get_background_job, start_background_job
from kiteconnect.exceptions import TokenException
from plotly.subplots import make_subplots

import config
import indicators

# Windows' asyncio ProactorEventLoop logs a spurious traceback whenever a
# client's TCP connection resets mid-request (e.g. a mobile browser over
# Tailscale losing signal) -- _call_connection_lost's socket.shutdown() raises
# ConnectionResetError on a socket the peer already reset. It's cosmetic
# noise, not a crash (Streamlit/Tornado already handles a disconnected client
# through its own websocket layer).
#
# A per-loop exception handler (asyncio.get_event_loop().set_exception_
# handler(...)) does NOT work here: Streamlit re-executes this script inside
# a per-session ScriptRunner worker thread, not the thread that owns the
# actual server event loop where the connection-lost callback fires --
# asyncio.get_event_loop() in that worker thread either raises RuntimeError
# (Python 3.12+, no loop set for a non-main thread) or, if it didn't, would
# still only patch a throwaway loop nobody's connections use. Patching the
# transport class method directly works regardless of which thread applies
# it, since the class is one shared object across every thread. Guarded by
# a sentinel attribute so re-running this script (every Streamlit rerun)
# doesn't stack another wrapper on top of the last one.
if os.name == "nt":
    from asyncio.proactor_events import _ProactorBasePipeTransport

    if not getattr(_ProactorBasePipeTransport, "_connection_reset_silenced", False):
        _orig_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost

        def _call_connection_lost_quietly(self, exc=None):
            try:
                _orig_call_connection_lost(self, exc)
            except ConnectionResetError:
                pass

        _ProactorBasePipeTransport._call_connection_lost = _call_connection_lost_quietly
        _ProactorBasePipeTransport._connection_reset_silenced = True
import contextlib

import state_db
import trade_chart

st.set_page_config(
    page_title="KK Trading System",
    layout="wide",
    page_icon="assets/logo.png" if os.path.exists("assets/logo.png") else "📈",
)


def _redirect_to_kite_login(error: str | None = None) -> None:
    """Auto-redirects the browser to Zerodha's real login + 2FA page --
    same tab, no click needed (HTML meta-refresh, immediate). Since this
    app's redirect URL is registered as this dashboard's own address,
    completing login there lands back on this app with request_token in
    its query params, which the block below auto-exchanges. A visible
    fallback link is also shown in case a browser/extension blocks the
    auto-redirect. `error` is only set for a genuine unexpected failure
    (e.g. token exchange itself failing) -- a routine expired/missing
    token redirects silently, no alarming red banner for something that
    happens every single day by design."""
    url = kite_client.login_url()
    if error:
        st.error(error)
    else:
        st.info("Kite session expired — redirecting to login...")
    st.markdown(f'<meta http-equiv="refresh" content="0; url={url}">', unsafe_allow_html=True)
    st.caption(
        "Opens Zerodha's real login + 2FA page. Nothing here ever "
        "sees your password — only the one-time token Kite sends "
        f"back after you log in. Not redirected automatically? "
        f"[Click here]({url})."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Kite request_token exchange -- MUST run before the dashboard login gate
# below, not after. An external OAuth redirect (leaving to Zerodha's site
# and back) tears down and recreates the browser's Streamlit session, which
# resets st.session_state -- so if the dashboard login gate ran first, it
# would always intercept the return trip and show the sign-in form again,
# with the one-time request_token sitting unprocessed in the URL (and lost,
# since it's single-use, the moment anything else consumes this page load).
# Checking it here, first, means it gets exchanged immediately regardless
# of dashboard-session state.
#
# Guarded on session_state["_kite_token_exchanged_for"] == request_token,
# NOT on `not config.KITE_ACCESS_TOKEN` (a prior version's guard) -- that
# earlier guard broke the very first time this server process stayed alive
# across Kite's daily token expiry (~6 AM): config.KITE_ACCESS_TOKEN held
# yesterday's now-expired token, still a non-empty string, so `not
# config.KITE_ACCESS_TOKEN` was False and a genuinely fresh request_token
# from a brand-new login got silently discarded without ever being
# exchanged -- landing back on this app's own sign-in form with no valid
# Kite session, looking like a broken redirect.
#
# Which specific token was already exchanged stays in session_state, and an
# external OAuth redirect (leaving to Zerodha and back) tears down and
# recreates st.session_state anyway -- so a genuinely new request_token from
# a fresh Kite login always arrives in a fresh session_state with no
# matching "_kite_token_exchanged_for" entry, and gets exchanged regardless
# of whatever's cached in config.KITE_ACCESS_TOKEN.
# What this guard still protects against: the same already-used
# request_token lingering in the URL within the SAME session (over an
# unstable mobile/Tailscale connection, st.query_params.clear() can fail to
# propagate to the browser's actual address bar before the next
# interaction fires) -- that case DOES still have the matching session_state
# entry from the successful exchange moments earlier, so it's correctly
# skipped instead of retried (Kite tokens are single-use; retrying would
# fail and bounce back to Kite's login page for no reason).
# ---------------------------------------------------------------------------
request_token = st.query_params.get("request_token")
if request_token and request_token != st.session_state.get("_kite_token_exchanged_for"):
    try:
        token = kite_client.exchange_request_token(request_token)
        config.KITE_ACCESS_TOKEN = token
        st.session_state["_kite_token_exchanged_for"] = request_token
        # Completing Kite's own login+2FA on Zerodha's site is at least as
        # strong a proof of identity as this app's own password -- and by
        # definition, only someone who'd already passed the dashboard login
        # gate in some browser session could have reached the "Login to
        # Kite" redirect in the first place. So a successful exchange here
        # also authenticates this (fresh, redirect-reset) session directly,
        # rather than depending on a cookie surviving the external round
        # trip to prove the same thing less reliably.
        st.session_state["dashboard_authenticated"] = True
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.query_params.clear()
        _redirect_to_kite_login(
            f"Token exchange failed (request_token is single-use and may have already been used): {e}"
        )
elif request_token:
    st.query_params.clear()

# ---------------------------------------------------------------------------
# Dashboard login gate. A real credential check backs it: state_db.
# dashboard_auth stores a salted PBKDF2-HMAC-SHA256 hash, never the
# password itself -- seeded once from config.DASHBOARD_USERNAME/PASSWORD
# (which still default to the "Admin"/"Admin" placeholder in .env, but
# only ever used to seed the hash on first run, never compared against
# directly afterward). This app places real orders and shows real fund
# balances, so change the password via the Cockpit's "Change dashboard
# password" section before using this beyond your own machine -- a loud
# warning shows until you do.
#
# Note this session resets on a full external page reload (leaving to
# Kite's login page and back tears down and recreates it, Streamlit's
# design, unrelated to cookies) -- see the request_token block above,
# which re-authenticates that fresh session directly on a successful
# exchange rather than depending on this form again.
#
# "Remember me" bridges the OTHER case a session reset happens: this
# server process itself restarting (every deploy does this) or the
# browser's WebSocket dropping (network blip, laptop sleep) -- neither of
# those is a fresh external redirect, so nothing above re-authenticates
# them. A valid remember_token cookie (see state_db.create_remember_token)
# skips the form entirely; it deliberately expires at the next 6 AM
# (state_db._next_daily_cutoff) rather than after a fixed duration, so a
# fresh sign-in is still required every morning, same cadence as Kite's
# own daily token expiry.
# ---------------------------------------------------------------------------
state_db.ensure_dashboard_auth_seeded(config.DASHBOARD_USERNAME, config.DASHBOARD_PASSWORD)

if not st.session_state.get("dashboard_authenticated", False):
    remembered_user = state_db.verify_remember_token(st.context.cookies.get("remember_token", ""))
    if remembered_user:
        st.session_state["dashboard_authenticated"] = True
        st.session_state["dashboard_username"] = remembered_user
    else:
        st.title("🔒 KK Trading System — sign in")
        with st.form("login_form", clear_on_submit=True):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            remember = st.checkbox("Remember me on this device until tomorrow morning", value=True)
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            if state_db.verify_dashboard_login(u, p):
                st.session_state["dashboard_authenticated"] = True
                st.session_state["dashboard_username"] = u
                if remember:
                    token, max_age = state_db.create_remember_token(u)
                    st.session_state["_pending_remember_cookie"] = (token, max_age)
                st.rerun()
            else:
                st.error("Incorrect username or password.")
        st.stop()

# Sets the remember-me cookie via a one-off injected script -- can't be done
# in the same run as the st.rerun() above (the rerun cuts execution off
# before a component would ever reach the browser), so the token is stashed
# in session_state and the cookie gets set here, on the very next run, once.
_pending_cookie = st.session_state.pop("_pending_remember_cookie", None)
if _pending_cookie:
    _token, _max_age = _pending_cookie
    st.html(
        f'<script>document.cookie = "remember_token={_token}; max-age={_max_age}; '
        f'path=/; SameSite=Lax; Secure";</script>',
        unsafe_allow_javascript=True,
    )

# ---------------------------------------------------------------------------
# Kite connection health check -- only reached after the dashboard login
# above succeeds. Shows the Kite login redirect ONLY when the token is
# actually missing/expired; a still-valid token falls straight through to
# the normal dashboard pages below.
#
# Only TokenException triggers the login redirect -- previously a bare
# `except Exception` treated ANY margins() failure (a transient network
# blip, Kite API hiccup, timeout) identically to a genuinely expired
# token, so a real login prompt couldn't be trusted to mean "your session
# actually expired." Anything else surfaces as an explicit retryable
# error instead, since re-doing Zerodha's login+2FA wouldn't fix it
# anyway.
# ---------------------------------------------------------------------------
if not config.KITE_ACCESS_TOKEN:
    _redirect_to_kite_login()

try:
    margins = kite_client.get_margins()
    available_cash = margins["equity"]["available"]["live_balance"]
except TokenException:
    _redirect_to_kite_login()
except Exception as e:
    st.error(f"Couldn't reach Kite to check your account: {e}")
    st.caption(
        "This looks like a transient network/API issue, not an "
        "expired session -- your Kite login should still be fine. "
        "Try again in a moment."
    )
    if st.button("Retry"):
        st.rerun()
    st.stop()

SCREEN_CACHE = os.path.join("cache", "screen.pkl")
VALUE_SCORE_CACHE = os.path.join("cache", "fno_value_scores.pkl")
BACKTEST_CACHE = os.path.join("cache", "backtest_result.pkl")
FUNDAMENTALS_HISTORY_CACHE = os.path.join("cache", "fundamentals_history.pkl")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_OVERVIEW_CSS = """
<style>
:root {
    --ov-surface-2: #ffffff; --ov-text-primary: #1a1a18;
    --ov-text-secondary: #5f5e5a; --ov-text-muted: #8a8983;
    --ov-green-d: #0f6e56; --ov-green: #1d9e75; --ov-green-l: #e1f5ee;
    --ov-red-d: #a32d2d; --ov-red: #e24b4a; --ov-red-l: #fcebeb;
    --ov-amber-d: #854f0b; --ov-amber: #ef9f27; --ov-amber-l: #faeeda;
    --ov-blue-d: #185fa5; --ov-blue: #378add; --ov-blue-l: #e6f1fb;
    --ov-purple-d: #534ab7; --ov-purple: #7f77dd; --ov-purple-l: #eeedfe;
    --ov-teal: #5dcaa5; --ov-coral: #d85a30;
    --ov-pink-d: #993556; --ov-pink: #d4537e; --ov-pink-l: #fbeaf0;
    --ov-surface-1: #eeede6; --ov-border: #e0ded5; --ov-border-strong: #a8a69c;
}
@media (prefers-color-scheme: dark) {
    :root {
        --ov-surface-2: #2a2a2e; --ov-text-primary: #ececea;
        --ov-text-secondary: #a8a7a2; --ov-text-muted: #7c7b76;
        --ov-green-l: #08402f; --ov-red-l: #471414; --ov-amber-l: #3d2404;
        --ov-blue-l: #0b3a66; --ov-purple-l: #292361; --ov-pink-l: #451527;
        --ov-green-d: #5dcaa5; --ov-red-d: #f09595; --ov-amber-d: #fac775;
        --ov-blue-d: #85b7eb; --ov-purple: #afa9ec; --ov-purple-d: #afa9ec;
        --ov-teal: #5dcaa5; --ov-coral: #f0997b; --ov-pink-d: #ed93b1;
        --ov-surface-1: #222225; --ov-border: #38383c; --ov-border-strong: #5c5c60;
    }
}
/* ---- global compaction: match the mockup's density ----
   Streamlit defaults measured on 1.59.2: main padding 96/80/160px, block
   gap 16px, buttons 40px min-height, metric values 36px, alert padding
   16px, divider margin 32px -- all far looser than the mockup (page
   padding 14-20px, gaps 6-10px, 12px buttons, 16px metric values). */
[data-testid="stMainBlockContainer"] {
    padding: 1.2rem 1.4rem 3rem !important;
    max-width: 1120px !important; margin: 0 auto;
}
/* [data-testid="stAppToolbar"] never matched anything -- the actual
   testid Streamlit renders is "stHeader" (the outer bar) / "stToolbar"
   (the Deploy/menu strip inside it); "stAppToolbar" is only a CSS class
   name, not the testid. toolbarMode="minimal" already suppresses Deploy/
   hamburger content on its own. This bar only renders (non-null, with an
   OPAQUE background) once the sidebar is collapsed, specifically to host
   the expand-sidebar arrow -- that's what was painting over the brandbar
   chips right after collapsing. Keep the bar (needed for that arrow) but
   force it transparent so it never covers content underneath. */
[data-testid="stHeader"] { background: transparent !important; box-shadow: none !important; }
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: 0.45rem; }
[data-testid="stMainBlockContainer"] hr { margin: 10px 0 !important; }
[data-testid="stCaptionContainer"] p { font-size: 11px !important; }

.stButton button, [data-testid="stFormSubmitButton"] button,
[data-testid="stDownloadButton"] button {
    min-height: 1.9rem !important; padding: 3px 12px !important;
}
.stButton button p, [data-testid="stFormSubmitButton"] button p,
[data-testid="stDownloadButton"] button p { font-size: 12px !important; font-weight: 500 !important; }

[data-testid="stWidgetLabel"] { min-height: 0 !important; margin-bottom: 1px !important; }
[data-testid="stWidgetLabel"] p {
    font-size: 11px !important; color: var(--ov-text-muted) !important; font-weight: 500 !important;
}
.stCheckbox { min-height: 0 !important; }
.stCheckbox p, .stRadio p { font-size: 12px !important; }
.stNumberInput input, .stTextInput input, .stDateInput input {
    padding: 5px 10px !important; font-size: 12.5px !important;
}
.stNumberInput button { min-height: 0 !important; }
[data-baseweb="select"] > div { min-height: 2rem !important; font-size: 12.5px !important; }
/* 1.59's selectbox is a custom input+button combo, no data-baseweb hook */
[data-testid="stSelectbox"] > div > div { height: 2.1rem !important; min-height: 2.1rem !important; }
[data-baseweb="menu"] li { font-size: 12.5px !important; }
.stMultiSelect [data-baseweb="tag"] { font-size: 11px !important; }

[data-testid="stAlertContainer"] { padding: 6px 10px !important; border-radius: 6px !important; }
[data-testid="stAlertContainer"] p { font-size: 11.5px !important; margin-bottom: 0 !important; }

[data-testid="stMetric"] {
    background: var(--ov-surface-2); border-top: 2px solid var(--ov-blue);
    border-radius: 8px; padding: 8px 10px;
}
[data-testid="stMetricValue"] { font-size: 16px !important; font-weight: 700; padding-bottom: 0 !important; }
[data-testid="stMetricLabel"] p {
    font-size: 11px !important; color: var(--ov-text-muted) !important; font-weight: 500 !important;
}
[data-testid="stMetricDelta"] { font-size: 11px !important; }

[data-testid="stExpander"] details {
    background: var(--ov-surface-2); border: 1px solid var(--ov-border) !important;
    border-radius: 10px !important;
}
[data-testid="stExpander"] summary { min-height: 0 !important; padding: 8px 13px !important; }
[data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span {
    font-size: 12.5px !important; font-weight: 600 !important;
}
[data-testid="stExpander"] details > div { padding: 2px 13px 10px !important; }

[data-testid="stForm"] {
    background: var(--ov-surface-2); border: 1px solid var(--ov-border-strong) !important;
    border-radius: 10px !important; padding: 10px 13px !important;
}
.st-key-ov_sync button {
    font-size:12px !important; padding:5px 11px !important; min-height:0 !important;
    height:auto !important; border-radius:8px !important; width:auto !important;
}
/* Sync button is taken out of the chips' flex flow entirely (see the
   .st-key-ov-topbar rule below) -- pinned to this container's top-right
   corner instead of sharing a row/column with the chips, so it can't
   overlap the logo or squeeze the chips into wrapping no matter the
   window width. That's what repeated column/flex-ratio attempts here
   kept fighting. */
/* z-index above Streamlit's own [data-testid="stAppToolbar"] (999990) --
   that native toolbar spans the full viewport width at the very top
   (0-52.5px tall) on EVERY screen size, invisible/empty past its sidebar-
   expand button but still pointer-events:auto, so it silently swallows
   taps meant for anything under it. On desktop this container's own
   "top:2px" position happens to land below that 52.5px strip so it never
   came up; on a narrow phone viewport the topbar sits higher up (logo
   stacks above the chips there -- see the @media rule above) and the
   button's position overlaps the strip, so taps hit the toolbar's empty
   space instead of Sync and nothing happens. */
.st-key-ov_sync { position:absolute !important; top:2px !important; right:0 !important; z-index:1000000 !important; }
/* Divider line under the whole brandbar row, and the positioning
   context for the absolutely-placed Sync button above. */
.st-key-ov-topbar {
    position:relative !important;
    border-bottom:1px solid var(--ov-border) !important;
    padding-bottom:12px !important; margin-bottom:6px !important;
    padding-right:40px !important;
}
.st-key-ov_logout button {
    background:var(--ov-red) !important; color:#fff !important; border:none !important;
    border-radius:999px !important; font-weight:700 !important; text-transform:uppercase !important;
    letter-spacing:.03em !important; font-size:11px !important; padding:5px 13px !important;
    min-height:0 !important; height:auto !important; width:auto !important;
}
/* "Run today's scan" header button (Live Rebalance, manual mode) -- push
   it to the right edge of its column. align-items:flex-end on the outer
   stColumn still left a gap before the true page edge; margin-left:auto
   on the button's own element container is the same technique that
   reliably worked for the Sync icon button earlier -- it pushes flush
   right regardless of the parent's flex-direction. */
[data-testid="stColumn"]:has(.st-key-lr_run_scan_hdr) { display:flex !important; }
.st-key-lr_run_scan_hdr { margin-left:auto !important; width:fit-content !important; }
/* Auto-execute-mode header row: "Auto-execute ON" chip + "Run today's
   scan" button, side by side (chip on the left) and right-aligned to the
   page edge together -- same technique as .st-key-screen_run_row. The
   button used to live on its own separate row below the chip, only ever
   pushed as far right as its own [5,2] column. */
.st-key-lr_autoexec_header_row {
    display:flex !important; flex-direction:row !important;
    align-items:center !important; justify-content:flex-end !important; gap:12px !important;
}
/* Both "Run today's scan" buttons: a plain flex child (or a narrow
   [5,2] column) shrinks below the button's natural single-line width
   under pressure, wrapping "Run today's" / "scan" onto two lines --
   flex-shrink:0 stops the button itself from being squeezed, and
   white-space:nowrap on its label is the actual fix for the wrap (belt
   and suspenders: shrink:0 alone doesn't stop text inside from
   wrapping if the button's own width still ends up smaller than the
   text needs). */
.st-key-lr_run_scan_hdr, .st-key-lr_run_scan_autoexec {
    flex-shrink:0 !important; width:fit-content !important;
}
.st-key-lr_run_scan_hdr button p, .st-key-lr_run_scan_autoexec button p {
    white-space:nowrap !important;
}
/* Segmented control's real root is [data-testid="stButtonGroup"] (found
   by reading Streamlit's own source -- button_group.py/ButtonGroup.*.js
   -- after several guesses at the wrong element failed). It has exactly
   two children: the label (with an optional help/tooltip icon) and the
   pill row; by default these stack vertically, which is why "Auto-
   refresh" kept landing above the pills instead of beside them. */
.st-key-pt_refresh_interval [data-testid="stButtonGroup"] {
    display:flex !important; flex-direction:row !important;
    align-items:center !important; gap:8px !important; flex-wrap:nowrap !important;
    justify-content:flex-end !important;
}
.st-key-pt_refresh_interval label {
    padding:3px 8px !important; font-size:11px !important; white-space:nowrap !important;
}
/* The "(?)" help icon next to the label -- shrink it to match the
   compact pills instead of its default (larger) size. */
.st-key-pt_refresh_interval [data-testid="stTooltipIcon"] {
    width:14px !important; height:14px !important; font-size:11px !important;
}
/* Verified via a real headless-browser DOM inspection (Playwright) that
   stButtonGroup was ALREADY stretched to full column width thanks to
   this width cascade -- so margin-left:auto had nothing to push into
   (no slack space existed anywhere in the chain). The actual fix is the
   justify-content:flex-end added above, on stButtonGroup's OWN flex
   layout, pushing its label+pills to ITS OWN right edge. */
.st-key-pt_refresh_row,
.st-key-pt_refresh_row [data-testid="stVerticalBlock"],
.st-key-pt_refresh_row [data-testid="stElementContainer"] {
    width:100% !important;
}
.st-key-ov_logout button:hover { filter:brightness(0.9) !important; color:#fff !important; }
.st-key-ov_logout button p { color:#fff !important; }
/* Screener header: "Fetch fundamental score" checkbox + "Run screen"
   button, side by side and right-aligned instead of stacked. Confirmed
   via DOM inspection that st.container(key=...)'s class lands directly
   on the stVerticalBlock that arranges its own children -- no need to
   reach into a nested selector here. */
.st-key-screen_run_row {
    display:flex !important; flex-direction:row !important;
    align-items:center !important; justify-content:flex-end !important; gap:12px !important;
}
/* Fundamentals header: the info popover + "Run value score scan" button,
   side by side and right-aligned, same technique. */
.st-key-fund_scan_row {
    display:flex !important; flex-direction:row !important;
    align-items:center !important; justify-content:flex-end !important; gap:12px !important;
}
/* Every text/number/date/select/multiselect input's actual bordered
   wrapper has border:1px solid #fff by default (found via DOM inspection)
   -- an invisible white border against the light background, which is why
   "no border appears" on ANY form field app-wide. Selectboxes render as
   react-aria-ComboBox; multiselect renders classic BaseWeb instead (its
   bordered box is the DIRECT child of [data-baseweb="select"]); text/
   number/date inputs use stable testids. All safe to select on directly
   and applied app-wide rather than per-key. */
.react-aria-ComboBox > div,
[data-testid="stTextInputRootElement"],
[data-testid="stNumberInputContainer"],
[data-testid="stDateInput"] div[data-baseweb="input"],
[data-baseweb="select"] > div {
    border:1px solid var(--ov-border-strong) !important;
}
.st-key-value_score_detail_sym .react-aria-ComboBox > div {
    justify-content:flex-start !important;
}
.st-key-value_score_detail_sym input { text-align:left !important; }
/* number_input's +/- stepper buttons default to 38px tall against a 27.5px
   text field, ballooning the WHOLE bordered box to 40px -- taller than
   every other input type's ~29.5px (text/date/select all share that
   height since their content is just the 27.5px field + 1px border each
   side). Shrinking the steppers to match is what actually fixes the
   input row's overall height, not the outer container. */
[data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"] {
    height:27.5px !important; min-height:0 !important; padding:0 6px !important;
}
/* The steppers' own flex-row wrapper (unnamed testid, second child of
   stNumberInputContainer) still centers them in a taller box than the
   buttons themselves need -- align-items:center collapses that extra
   space instead of stretching to fit some invisible minimum. */
[data-testid="stNumberInputContainer"] > div:last-child {
    align-items:center !important; height:27.5px !important;
}
/* stNumberInputContainer itself also carries an explicit height:35px
   (Streamlit's own emotion-cache rule, sized for the ORIGINAL 38px-tall
   steppers) -- shrinking just the children above doesn't override an
   explicit height on the parent, so the box itself needs the same
   29.5px every other input type's wrapper measures (27.5px content +
   1px border each side). */
[data-testid="stNumberInputContainer"] {
    height:29.5px !important; align-items:center !important;
}
/* Download buttons sit flush against their card's bottom edge when
   they're the last element -- a bit of breathing room matches the
   padding every other end-of-card element gets. */
[data-testid="stDownloadButton"] { margin-bottom:8px; }
/* Requested directly via an emotion-hash class found in dev tools --
   unlike the testid/library-class selectors elsewhere in this file,
   emotion hashes like this can change on a Streamlit version bump or
   even a rebuild, so if this stops matching later that's why. */
.st-emotion-cache-eqh6wq { margin-bottom:0rem !important; }
.st-key-fund_sector_filter { max-width:140px !important; }
/* Slider track thickness -- found via DOM inspection (rail is normally
   only 3.5px tall). The component-identity suffix classes (e23vpic5 = rail,
   e23vpic3 = thumb/fill) are shared by EVERY slider instance, unlike the
   emotion-cache-XXXXXX prefix which is regenerated per-instance based on
   the rail's inline width % -- so targeting the prefix only thickened
   whichever slider happened to hash-collide with the rule. Scoped under
   the stable [data-testid="stSlider"] testid as a fallback safety net. */
[data-testid="stSlider"] [class*="e23vpic5"],
[data-testid="stSlider"] [class*="e23vpic3"] {
    height:8px !important;
}
/* Live Rebalance's "Execute all ..." action buttons -- solid color,
   full-width, matching the mockup's rose/green execute bars. Disabled
   state keeps the color but dims it so it doesn't read as just another
   plain gray Streamlit button once the confirm checkbox is ticked. */
.st-key-lr_execute_sells button {
    background:var(--ov-red) !important; color:#fff !important; border:none !important;
}
.st-key-lr_execute_sells button:hover:not(:disabled) { filter:brightness(0.92) !important; color:#fff !important; }
.st-key-lr_execute_sells button p { color:#fff !important; }
.st-key-lr_execute_buys button {
    background:var(--ov-green) !important; color:#fff !important; border:none !important;
}
.st-key-lr_execute_buys button:hover:not(:disabled) { filter:brightness(0.92) !important; color:#fff !important; }
.st-key-lr_execute_buys button p { color:#fff !important; }
.st-key-lr_execute_sells button:disabled, .st-key-lr_execute_buys button:disabled {
    opacity:0.45 !important; color:#fff !important;
}
.st-key-lr_execute_sells button:disabled p, .st-key-lr_execute_buys button:disabled p { color:#fff !important; }
/* Admin's "Delete entry" button (Ledger) -- outlined red, distinct from
   the blue primary "Save changes" button next to it. */
.st-key-admin_ledger_delete_btn button { color:var(--ov-red) !important; border-color:var(--ov-red) !important; }
.st-key-admin_ledger_delete_btn button p { color:var(--ov-red) !important; }
.st-key-admin_ledger_delete_btn button:hover { background:var(--ov-red-l) !important; }
/* Admin Ledger's manually-built table (st.columns per row instead of
   _ov_table_html) -- needed so each row's radio-select button can be a
   real Streamlit widget lined up with plain-text cells. .ov-manual-th/
   .ov-manual-cell mirror .ov-table's th/td font sizing so it still reads
   as "the same table style" as every other page. */
.ov-manual-th { font-weight:600; font-size:12px; color:var(--ov-text-muted); }
.ov-manual-th.r, .ov-manual-cell.r { display:block; text-align:right; }
.ov-manual-cell { font-size:12px; color:var(--ov-text-primary); }
/* No border-bottom here -- _ov_table_html's header row has none either;
   the single separator line under it comes from the first data row's own
   border-top below, same as every other table. A border here too was
   drawing a doubled/thicker line under the header than every other table. */
.st-key-admin_ledger_head { padding-bottom:2px; }
/* Markdown wraps a lone <span> in a <p>, which carries the browser's
   default ~1em paragraph margin -- that's what was ballooning each row to
   ~47px tall instead of the ~30px every other table uses. */
.st-key-admin_ledger_rows [data-testid="stMarkdownContainer"] p,
.st-key-admin_ledger_head [data-testid="stMarkdownContainer"] p {
    margin:0 !important;
}
.st-key-admin_ledger_rows { gap:0 !important; }
.st-key-admin_ledger_rows [data-testid="stHorizontalBlock"] {
    border-top:1px solid var(--ov-border); padding:2px 0; align-items:center;
}
.st-key-admin_ledger_rows [data-testid="stButton"] button {
    background:transparent !important; border:none !important; padding:0 !important;
    min-height:0 !important; height:auto !important; font-size:15px !important;
    color:var(--ov-text-secondary) !important; line-height:1 !important;
}
.st-key-admin_ledger_rows [data-testid="stButton"] button:hover {
    color:var(--ov-blue) !important; background:transparent !important;
}
/* Positions & Trade's "Place stop-loss" and "Square off"/"Execute order"
   buttons -- solid blue, full-width, matching the mockup. */
.st-key-manual_sl_place button, .st-key-trade_execute button {
    background:var(--ov-blue) !important; color:#fff !important; border:none !important;
}
.st-key-manual_sl_place button:hover:not(:disabled),
.st-key-trade_execute button:hover:not(:disabled) { filter:brightness(0.92) !important; color:#fff !important; }
.st-key-manual_sl_place button p, .st-key-trade_execute button p { color:#fff !important; }
.st-key-manual_sl_place button:disabled, .st-key-trade_execute button:disabled {
    opacity:0.45 !important; color:#fff !important;
}
.st-key-manual_sl_place button:disabled p, .st-key-trade_execute button:disabled p { color:#fff !important; }
/* No extra left offset here -- the sidebar's own default content padding
   already lines this up with the page-link tabs/section labels above it. */
.st-key-ov_logout { margin:0 4px !important; }
.ov-header { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px; }
.ov-h1 { font-size:19px; font-weight:700; margin:0; color:var(--ov-text-primary); }
.ov-sub { font-size:12px; color:var(--ov-text-muted); font-weight:400; }
.ov-chips { display:flex; gap:6px; align-items:center; flex-wrap:wrap; flex-shrink:0; }
.ov-chip { font-size:11.5px; padding:4px 10px; border-radius:11px; font-weight:500; white-space:nowrap; }
/* flex-shrink:0 on .ov-chips (above) keeps it at its natural full width on
   desktop -- deliberately, so it never squeezes/wraps mid-fight with the
   logo (see the Sync-button comment further down for the history there).
   But on a narrow phone viewport that same natural width is wider than
   the screen, so the chips silently overflow off the right edge instead
   of wrapping, even though flex-wrap:wrap is already set -- wrapping only
   ever kicks in once the container is forced narrower than its content.
   Below this breakpoint the topbar has no logo/chips fight to referee
   (the sidebar is already collapsed to icons-only), so it's safe to let
   the chips container actually shrink to the viewport and wrap for real. */
@media (max-width: 600px) {
    .ov-header { flex-direction:column; align-items:flex-start; }
    .ov-chips { flex-shrink:1; width:100%; }
}
.ov-info-icon { cursor:help; font-size:13px; margin-left:4px; }
.ov-chip-accent { background:var(--ov-blue-l); color:var(--ov-blue-d); }
.ov-chip-success { background:var(--ov-green-l); color:var(--ov-green-d); }
.ov-chip-amber { background:var(--ov-amber-l); color:var(--ov-amber-d); }
.ov-chip-danger { background:var(--ov-red-l); color:var(--ov-red-d); }
.ov-chip-muted { background:var(--ov-surface-1); color:var(--ov-text-secondary); }
.ov-grid-metrics { display:grid; grid-template-columns:repeat(auto-fit, minmax(100px,1fr)); gap:8px; margin-bottom:10px; }
.ov-metric { background:var(--ov-surface-2); border-radius:8px; padding:8px 10px; border-top:2px solid var(--ov-border); }
.ov-metric.t-blue { border-top-color:var(--ov-blue); }
.ov-metric.t-purple { border-top-color:var(--ov-purple); }
.ov-metric.t-teal { border-top-color:var(--ov-teal); }
.ov-metric.t-amber { border-top-color:var(--ov-amber); }
.ov-metric.t-green { border-top-color:var(--ov-green); }
.ov-metric.t-coral { border-top-color:var(--ov-coral); }
.ov-metric.t-red { border-top-color:var(--ov-red); }
.ov-metric.t-pink { border-top-color:var(--ov-pink); }
.ov-metric .ov-label { font-size:11px; color:var(--ov-text-muted); margin:0; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ov-metric .ov-value { font-size:16px; font-weight:700; margin:1px 0 0; color:var(--ov-text-primary); }
.ov-metric .ov-note { font-size:11px; color:var(--ov-text-secondary); margin:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ov-pos { color:var(--ov-green-d) !important; }
.ov-neg { color:var(--ov-red-d) !important; }
[class*="st-key-ov-card-"] {
    border-radius:10px !important; background:var(--ov-surface-2) !important;
    border:1px solid var(--ov-border) !important;
    padding:10px 13px !important; gap:0.35rem !important;
}
.ov-card { background:var(--ov-surface-2); border:1px solid var(--ov-border); border-radius:10px; padding:10px 13px; margin-bottom:10px; }
.ov-two-col { display:grid; grid-template-columns:repeat(auto-fit, minmax(290px,1fr)); gap:10px; margin-bottom:10px; }
.ov-two-col .ov-card { margin-bottom:0; }
.ov-muted { color:var(--ov-text-muted); font-size:11.5px; margin:0 0 4px; font-weight:600; text-transform:uppercase; letter-spacing:.03em; }
.ov-card-title {
    font-size:13px; font-weight:700; margin:0 0 10px; display:flex; align-items:center;
    gap:7px; color:var(--ov-text-primary); padding-bottom:8px;
    border-bottom:1px solid var(--ov-border);
}
.ov-dot { width:7px; height:7px; border-radius:50%; display:inline-block; }
.ov-card-meta { font-size:11px; color:var(--ov-text-secondary); }
.ov-order-preview {
    font-size:11.5px; font-weight:700; color:var(--ov-blue-d); margin-left:auto;
}
.ov-table { width:100%; font-size:12px; border-collapse:collapse; }
/* Only horizontal (row) separators, matching the mockup -- no vertical
   lines between columns, ever, regardless of any inherited default. */
.ov-table th, .ov-table td { border-left:none !important; border-right:none !important; }
.ov-table th { font-weight:600; padding:4px 8px; text-align:left; color:var(--ov-text-muted); white-space:nowrap; }
/* white-space:nowrap is the actual fix for tables blowing up to ~68px
   row height on wide tables (e.g. Fundamentals' "Ranked" with ~19
   columns) -- a cell like "31-MAR-2026" was wrapping to 3 lines when its
   column got squeezed too narrow, and since a table row's height is the
   MAX of all its cells, that one wrapped cell stretched the entire row.
   Forcing single-line cells means the table just scrolls horizontally
   (.ov-tbl-scroll already supports that) instead of wrapping vertically. */
.ov-table td { padding:5px 8px; border-top:1px solid var(--ov-border); color:var(--ov-text-primary); white-space:nowrap; }
.ov-table th.r, .ov-table td.r { text-align:right; }
/* Wide tables (e.g. Fundamentals' "Ranked" with ~19 columns) get cut off
   hard at the container's right edge when they need to scroll, while
   narrower tables (e.g. Holdings) end cleanly with nothing to scroll --
   that abrupt cutoff on the wide ones was reading as an inconsistent
   "extra border" rather than an obviously-scrollable table. A visible,
   styled scrollbar (instead of the browser's default, easy to miss one)
   makes the scrollability clear so it looks intentional either way. */
.ov-tbl-scroll {
    overflow-x:auto; margin-bottom:6px;
    scrollbar-width:thin; scrollbar-color:var(--ov-border-strong) transparent;
}
.ov-tbl-scroll::-webkit-scrollbar { height:6px; }
.ov-tbl-scroll::-webkit-scrollbar-track { background:transparent; }
.ov-tbl-scroll::-webkit-scrollbar-thumb { background:var(--ov-border-strong); border-radius:3px; }
/* "Review rebalance orders" sits directly under the proposal rows with
   no breathing room, making the last row read as if the button were
   cutting it off -- give the button's own element-container a top gap. */
[class*="st-key-ov_review_rebal"] { margin-top:10px !important; }
.ov-sym { font-weight:700; }
.ov-badge { padding:1px 8px; border-radius:9px; font-size:11px; font-weight:600; white-space:nowrap; }
.ov-badge-green { background:var(--ov-green-l); color:var(--ov-green-d); }
.ov-badge-red { background:var(--ov-red-l); color:var(--ov-red-d); }
.ov-badge-amber { background:var(--ov-amber-l); color:var(--ov-amber-d); }
.ov-badge-blue { background:var(--ov-blue-l); color:var(--ov-blue-d); }
.ov-badge-purple { background:var(--ov-purple-l); color:var(--ov-purple-d); }
.ov-badge-pink { background:var(--ov-pink-l); color:var(--ov-pink-d); }
.ov-badge-gray { background:var(--ov-surface-1); color:var(--ov-text-secondary); }
.ov-row { display:flex; justify-content:space-between; align-items:center; padding:5px 0; border-bottom:1px solid var(--ov-border); font-size:12px; color:var(--ov-text-primary); gap:8px; }
.ov-row:last-of-type { border-bottom:none; }
.ov-minibar { position:relative; height:7px; background:var(--ov-surface-1); border-radius:4px; }
.ov-minibar .ov-fill { position:absolute; left:0; top:0; height:7px; border-radius:4px; }
.ov-minibar .ov-tick { position:absolute; left:80%; top:-2px; width:2px; height:11px; background:var(--ov-border-strong); }
.ov-allocbar { display:flex; height:16px; border-radius:6px; overflow:hidden; margin-bottom:6px; }
.ov-sector-row { margin-bottom:7px; }
.ov-sector-row:last-child { margin-bottom:0; }
.ov-sector-head { display:flex; justify-content:space-between; font-size:11.5px; margin-bottom:2px; color:var(--ov-text-primary); gap:6px; }
.ov-sector-bar { height:7px; background:var(--ov-surface-1); border-radius:4px; }
.ov-sector-fill { height:7px; border-radius:4px; }
/* padding-left is 5px, not 10px, so the 3px left border + padding lands
   at ~8px total inset -- matching the table cells' own 8px padding
   above it, instead of sitting ~5px further right/misaligned. */
.ov-alert { margin-top:0; padding:4px 8px 4px 5px; border-radius:6px; background:var(--ov-amber-l); color:var(--ov-amber-d); font-size:11px; border-left:3px solid var(--ov-amber); }
.ov-alert-success { background:var(--ov-green-l); color:var(--ov-green-d); border-left-color:var(--ov-green); }
.ov-alert-info { background:var(--ov-blue-l); color:var(--ov-blue-d); border-left-color:var(--ov-blue); }
.ov-donut-wrap { display:flex; gap:16px; align-items:center; flex-wrap:wrap; }
.ov-donut-legend { flex:1; min-width:170px; }
.ov-sw { display:inline-block; width:9px; height:9px; border-radius:2px; vertical-align:-1px; margin-right:4px; }

/* ---- sidebar / side menu, matching the mockup's .side/.side-label/.tab ---- */
[data-testid="stSidebar"] { background:var(--ov-surface-1) !important; }
[data-testid="stSidebar"] [data-testid="stElementContainer"] {
    margin-bottom:0 !important;
}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap:0.1rem !important; }
/* The pill is the ANCHOR (stPageLink-NavLink), not the outer stPageLink
   container -- padding/hover/active must live on the anchor or the
   highlight renders as a thin strip inside a padded box. */
section[data-testid="stSidebar"][aria-expanded="true"] {
    width:205px !important; max-width:205px !important; min-width:205px !important;
    box-sizing:border-box !important; overflow-x:hidden !important;
}
[data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"] {
    overflow-x:hidden !important; max-width:100% !important; box-sizing:border-box !important;
    padding-top:12px !important;
}
[data-testid="stSidebarHeader"] { height:auto !important; min-height:0 !important; }
[data-testid="stSidebar"] [data-testid="stPageLink"] {
    padding:0 !important; margin:0 !important; min-height:0 !important;
}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] {
    border-radius:8px !important; padding:5px 10px !important; width:100%;
    background:transparent;
}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover { background:var(--ov-surface-2) !important; }
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] span {
    font-size:12.5px !important; font-weight:600 !important; color:var(--ov-text-secondary) !important;
}
/* Active page: blue pill, exactly like the mockup's checked tab. The
   aria-current attribute is stamped by the small script in the sidebar
   block (Streamlit itself gives the current link no stable marker). */
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"][aria-current="page"] {
    background:var(--ov-blue-l) !important;
}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"][aria-current="page"] span {
    color:var(--ov-blue-d) !important;
}
[data-testid="stSidebar"] hr { margin:8px 0 !important; }
[data-testid="stSidebarUserContent"] { padding-bottom:1rem !important; }
.ov-side-label {
    font-size:10.5px; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
    color:var(--ov-text-muted); margin:0 4px !important;
}
/* Space around a section label lives on ITS OWN element-container (via
   margin-top/padding-bottom), not on the <p> itself -- a margin on the
   <p> sits inside a container whose margin-bottom is already forced to 0
   above, which was silently eating the intended gap. margin-top pushes
   the label away from the PREVIOUS section's last tab; padding-bottom
   (never collapses) pushes the FIRST tab of this section away from the
   label text, on top of the small 0.1rem inter-tab gap. */
[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.ov-side-label) {
    margin-top:12px !important;
    padding-bottom:12px !important;
}
/* "Trading" is now the sidebar's first element (brand moved to the top
   page brandbar) -- a smaller top gap for the very first label than the
   shared 12px the rule above gives Audit Trail/Testing, since there's no
   preceding tab to separate it from, just the sidebar's own edge. */
[data-testid="stSidebar"] [data-testid="stElementContainer"]:first-child:has(.ov-side-label) {
    margin-top:4px !important;
}
.ov-brand { font-size:15px; font-weight:700; color:var(--ov-text-primary); line-height:1.3; }
.ov-brand .ov-sub {
    display:block; font-weight:400; font-size:12px; color:var(--ov-text-muted); margin-top:1px;
}
.ov-topbar-logo { display:block; height:50px; width:auto; }
</style>
"""

_OV_TONE_CYCLE = ["blue", "purple", "teal", "amber", "green", "coral"]
_OV_HEX_CYCLE = ["#534ab7", "#7f77dd", "#1d9e75", "#5dcaa5", "#ef9f27", "#378add", "#d85a30", "#d4537e"]


def _ov_arrow(better: bool | None) -> str:
    """A small ▲/▼ span, colored green/red -- better=True renders the "this
    improved" arrow (▲), False the "this worsened" arrow (▼), None (the
    reference value is missing, e.g. no entry-rank on record) renders
    nothing. Shared by every arrow_cols comparison in _ov_table_html so
    "up/down vs a reference column" always looks the same everywhere."""
    if better is None:
        return ""
    cls = "ov-pos" if better else "ov-neg"
    arrow = "▲" if better else "▼"
    return f'<span class="{cls}">{arrow}</span> '


def _ov_table_html(
    df: pd.DataFrame,
    columns: list[str] | None = None,
    badges: dict | None = None,
    pnl_cols: list[str] | None = None,
    num_fmt: dict | None = None,
    sym_cols: list[str] | None = None,
    arrow_cols: dict | None = None,
    na_rep: str = "—",
) -> str:
    """Renders a DataFrame as the mockup's compact .ov-table -- plain HTML,
    no Streamlit dataframe chrome (sort/resize/selection). Used for every
    purely-DISPLAY table site-wide: none of these ever used row-selection
    or in-place editing, only the Overview holdings table (click-through to
    Tradebook) and the equity chart do, and those stay real Streamlit
    widgets -- this never trades away functionality, just chrome.

    columns: ordered column list to show (default: every column in df).
    badges: {col: {value: css_class}} or {col: callable(value) -> css_class}
        -- renders that cell as a colored pill instead of plain text.
    pnl_cols: columns whose sign colors the cell green/red (also bolded).
    num_fmt: {col: format_spec} for numeric columns (right-aligned).
    sym_cols: columns rendered bold (e.g. the symbol column).
    arrow_cols: {displayed_col: (value_col, reference_col, higher_is_better)}
        -- prepends a ▲/▼ to displayed_col's cell comparing df[value_col]
        against df[reference_col] for the same row (value_col is usually
        displayed_col itself -- e.g. current_capital vs invested_capital
        -- but can differ, e.g. displaying the badge-formatted "rank_fmt"
        string while comparing the underlying numeric "rank" against
        "entry_rank"; lower is better for rank, so higher_is_better=
        False there). Missing/NaN/equal values render no arrow rather
        than a misleading one. Composes with badges/pnl_cols/num_fmt --
        the arrow is just prepended to whatever that cell would
        otherwise show.
    """
    columns = columns or list(df.columns)
    num_fmt = num_fmt or {}
    badges = badges or {}
    pnl_cols = set(pnl_cols or [])
    sym_cols = set(sym_cols or [])
    arrow_cols = arrow_cols or {}
    right_cols = set(num_fmt) | pnl_cols

    def _label(c):
        return COLUMN_LABELS.get(c, c.replace("_", " ").title())

    def _arrow_prefix(c, row) -> str:
        if c not in arrow_cols:
            return ""
        value_col, ref_col, higher_is_better = arrow_cols[c]
        v, ref = row.get(value_col), row.get(ref_col)
        if pd.isna(v) or pd.isna(ref) or v == ref:
            return _ov_arrow(None)
        better = (v > ref) == higher_is_better
        return _ov_arrow(better)

    header = "".join(f"<th{' class="r"' if c in right_cols else ''}>{html_lib.escape(_label(c))}</th>" for c in columns)

    rows_html = []
    for _, row in df.iterrows():
        cells = []
        for c in columns:
            v = row[c]
            r_attr = ' class="r"' if c in right_cols else ""
            sym_cls = "ov-sym" if c in sym_cols else ""
            if pd.isna(v):
                cells.append(f'<td{r_attr}><span class="{sym_cls}">{na_rep}</span></td>')
            elif c in badges:
                mapping = badges[c]
                css = mapping(v) if callable(mapping) else mapping.get(v, "ov-badge-gray")
                cells.append(
                    f'<td{r_attr}>{_arrow_prefix(c, row)}<span class="ov-badge {css}">'
                    f"{html_lib.escape(str(v))}</span></td>"
                )
            elif c in pnl_cols:
                fv = float(v)
                cls = "ov-pos" if fv >= 0 else "ov-neg"
                fmt = num_fmt.get(c, "{:+,.2f}")
                cells.append(
                    f'<td{r_attr}>{_arrow_prefix(c, row)}<span class="{cls} ov-sym">{fmt.format(fv)}</span></td>'
                )
            elif c in num_fmt:
                cells.append(
                    f'<td{r_attr}>{_arrow_prefix(c, row)}<span class="{sym_cls}">{num_fmt[c].format(v)}</span></td>'
                )
            else:
                cells.append(
                    f'<td>{_arrow_prefix(c, row)}<span class="{sym_cls}">{html_lib.escape(str(v))}</span></td>'
                )
        rows_html.append(f"<tr>{''.join(cells)}</tr>")

    return f'<div class="ov-tbl-scroll"><table class="ov-table"><tr>{header}</tr>{"".join(rows_html)}</table></div>'


def _ov_page_slice(df: pd.DataFrame, key: str, page_size: int = 10) -> pd.DataFrame:
    """Returns just the current page's slice of `df` -- tables render
    everything via raw HTML (_ov_table_html), so there's no native
    st.dataframe pagination to lean on; this keeps long tables (e.g. the
    full screener universe) from dumping hundreds of rows at once. Pairs
    with _ov_pagination_controls() using the SAME (df, key, page_size) --
    call that AFTER the table so the Prev/Next strip sits below it, not
    above. Page position is kept in st.session_state under a name derived
    from `key`, so multiple tables on the same page paginate independently."""
    n = len(df)
    n_pages = max(1, math.ceil(n / page_size))
    state_key = f"_ov_page_{key}"
    page = min(st.session_state.get(state_key, 0), n_pages - 1)
    start = page * page_size
    return df.iloc[start : start + page_size]


def _ov_pagination_controls(df: pd.DataFrame, key: str, page_size: int = 10) -> None:
    """Prev/Next control strip for the table already sliced by
    _ov_page_slice() with this SAME (df, key, page_size) -- render this
    right after the table so it appears below it."""
    n = len(df)
    n_pages = max(1, math.ceil(n / page_size))
    if n_pages <= 1:
        return
    state_key = f"_ov_page_{key}"
    page = min(st.session_state.get(state_key, 0), n_pages - 1)
    pc1, pc2, pc3 = st.columns([1, 3, 1])
    with pc1:
        if st.button("← Prev", key=f"{key}_pg_prev", disabled=page <= 0, use_container_width=True):
            st.session_state[state_key] = page - 1
            st.rerun()
    with pc2:
        st.markdown(
            f'<p class="ov-card-meta" style="text-align:center;margin:6px 0;">'
            f"Page {page + 1} of {n_pages} ({n} rows)</p>",
            unsafe_allow_html=True,
        )
    with pc3:
        if st.button("Next →", key=f"{key}_pg_next", disabled=page >= n_pages - 1, use_container_width=True):
            st.session_state[state_key] = page + 1
            st.rerun()


def _ov_order_status_cls(v: str) -> str:
    """Badge color for a raw Kite order status string."""
    v = str(v).upper()
    if v in ("COMPLETE", "COMPLETED"):
        return "ov-badge-green"
    if v in ("OPEN", "TRIGGER PENDING", "PENDING", "PUT ORDER REQ RECEIVED"):
        return "ov-badge-amber"
    if v in ("REJECTED", "CANCELLED"):
        return "ov-badge-red"
    return "ov-badge-gray"


def _ov_donut_svg(values: list[float], center_label: str) -> str:
    """A hand-drawn ring-arc donut (stacked stroke-dasharray circles) --
    matches the compact hand-styled look used elsewhere on this page
    instead of a full Plotly figure (no hover/click needed here, so the
    lighter-weight static SVG costs nothing functionally)."""
    total = sum(values) or 1.0
    r = 44
    circumference = 2 * math.pi * r
    offset = 0.0
    circles = []
    for i, value in enumerate(values):
        color = _OV_HEX_CYCLE[i % len(_OV_HEX_CYCLE)]
        dash = value / total * circumference
        gap = circumference - dash
        circles.append(
            f'<circle cx="60" cy="60" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="18" stroke-dasharray="{dash:.1f} {gap:.1f}" '
            f'stroke-dashoffset="{-offset:.1f}" transform="rotate(-90 60 60)"/>'
        )
        offset += dash
    return (
        '<svg viewBox="0 0 120 120" width="104" height="104" role="img">'
        + "".join(circles)
        + f'<text x="60" y="57" text-anchor="middle" style="font-size:14px;font-weight:700;" '
        f'fill="currentColor">{center_label}</text></svg>'
    )


def _ov_metric_html(
    label: str, value: str, note: str | None = None, note_cls: str = "", tone: str = "blue", value_cls: str = ""
) -> str:
    """One metric-card's HTML -- callers join several of these into one
    `<div class="ov-grid-metrics">...</div>` and render with a SINGLE
    st.markdown call, so the whole dense metrics strip is one lightweight
    DOM write instead of 9 separate bordered st.container widgets."""
    note_html = f'<p class="ov-note {note_cls}">{note}</p>' if note else ""
    return (
        f'<div class="ov-metric t-{tone}"><p class="ov-label">{label}</p>'
        f'<p class="ov-value {value_cls}">{value}</p>{note_html}</div>'
    )


# Raw/snake_case field name -> human-readable table header, applied by
# pnl_style() (and readable_df() for the few tables that don't need P&L
# coloring or number formatting) so no table in this app ever shows a
# header like `pnl_pct` or `tradingsymbol`. One shared dict rather than a
# per-page copy, since the same fields (symbol, qty, entry/exit price, P&L,
# ATR-based stops...) repeat across Overview, Live Rebalance, Positions &
# Trade, Backtest, and Fundamentals.
COLUMN_LABELS = {
    "symbol": "Symbol",
    "tradingsymbol": "Symbol",
    "qty": "Qty",
    "quantity": "Qty",
    "avg_price": "Avg price",
    "average_price": "Avg price",
    "ltp": "LTP",
    "last_price": "LTP",
    "pnl": "P&L",
    "pnl_pct": "P&L %",
    "entry_date": "Entry date",
    "exit_date": "Exit date",
    "entry_price": "Entry price",
    "exit_price": "Exit price",
    "current_price": "Current price",
    "current_stop": "Current stop",
    "recommended_stop": "Recommended stop",
    "suggested_stop": "Suggested stop",
    "stop": "Stop",
    "gtt_active": "GTT active",
    "gtt_trigger_id": "GTT trigger ID",
    "days_held": "Days held",
    "holding_days": "Days held",
    "source": "Source",
    "reason": "Reason",
    "skip": "Skip?",
    "product": "Product",
    "status": "Status",
    "transaction_type": "Type",
    "order_timestamp": "Time",
    "unrealized_pnl": "Unrealized P&L",
    "unrealized_ret_pct": "Unrealized return %",
    "ret_pct": "Return %",
    "date": "Date",
    "amount": "Amount (₹)",
    "note": "Note",
    "value": "Current value (₹)",
    "allocation_pct": "Allocation %",
    "run_id": "Run ID",
    "run_time": "Run time",
    "action_type": "Action",
    "detail": "Reason/Detail",
    "resolved_at": "Resolved at",
    "current_qty": "Current qty",
    "rank": "Momentum rank",
    "rank_fmt": "Rank",
    "cand_rank": "Rank",
    "cand_sector": "Sector",
    "ret_first15_pct": "1st-15m %",
    "gap_pct": "09:15 gap %",
    "chg_pct": "Chg %",
    "gate": "Sector gate",
    "state": "State",
    "direction": "Direction",
    "qty_remaining": "Qty",
    "upnl": "Unrealized P&L",
    # Screener / momentum
    "score": "Score",
    "price": "Price",
    "rs_3m": "RS 3M",
    "rs_6m": "RS 6M",
    "pct_52w_high": "% of 52W high",
    "rsi": "RSI",
    "vol_expansion": "Vol expansion",
    "avg_volume_3m": "3M Avg Volume",
    "atr_pct": "ATR %",
    "fundamental_score": "Fundamental score",
    "fundamental_rubric": "Sector rubric",
    "trend_ok": "Trend",
    "near_high_ok": "Near-high",
    "rsi_ok": "RSI",
    "quality_ok": "Quality",
    "quality_fails": "Quality fails",
    # Fundamentals (Value Score)
    "total_score": "Score (0-100)",
    "rubric": "Sector",
    "roe": "ROE %",
    "roa": "ROA %",
    "debt_to_equity": "Debt / equity",
    "current_ratio": "Current ratio",
    "revenue_cagr_pct": "Revenue CAGR %",
    "fcf_yoy_pct": "FCF growth %",
    "peg": "PEG ratio",
    "gross_npa_pct": "Gross NPA %",
    "net_npa_pct": "Net NPA %",
    "nim_proxy_pct": "NIM (approx.) %",
    "advances_yoy_pct": "Advances growth %",
    "pat_yoy_pct": "Profit growth %",
    "combined_ratio_pct": "Combined ratio %",
    "incurred_claim_ratio_pct": "Claims ratio %",
    "premium_yoy_pct": "Premium growth %",
    "loan_yoy_pct": "Loan book growth %",
    "fiscal_year_end": "As of",
    "missing_pillars": "Data gaps",
    "pillar_coverage": "Coverage",
    # Job execution log
    "job_type": "Job",
    "trigger_type": "Trigger",
    "started_at": "Started",
    "finished_at": "Finished",
    "duration_sec": "Duration (s)",
    "summary": "Summary",
    "error_message": "Error",
    # Tradebook
    "initial_stop": "Initial stop",
    "entry_score": "Entry score",
    "entry_rsi": "Entry RSI",
    "entry_pct_52w_high": "Entry % of 52W high",
    "entry_vol_expansion": "Entry vol expansion",
    "entry_fundamental_score": "Entry fundamental score",
    "exit_reason": "Exit reason",
    "exit_type": "Exit type",
    "entry_reason": "Why this trade",
    "latest_recommended_stop": "Latest stop",
    "extra_qty": "Extra qty",
    "trigger_price": "GTT trigger price",
    "updated_at": "Last updated",
    "apply_error": "Why it needs attention",
    "realized_pnl": "Realized P&L",
    "realized_ret_pct": "Realized return %",
}


def merged_holdings() -> pd.DataFrame:
    """Positions + holdings merged into one live table with current P&L,
    GROUPED BY SYMBOL. A same-day CNC buy or top-up transiently appears in
    BOTH Kite endpoints until it settles into holdings overnight -- a naive
    concat (the previous behavior here) double-lists that symbol as two
    partial rows instead of one true combined position. Real example hit
    live: after executing top-ups, BHEL/LODHA/KALYANKJIL/SONACOMS each
    briefly split across a position-row and a holding-row the same day,
    silently understating each row's own qty/value even though the
    aggregate .sum() totals downstream happened to still be correct.
    Grouping here means every reader -- the Holdings table, invested/
    holdings-value totals, and the per-stock allocation view -- always
    sees one accurate row per symbol.

    Deliberately excludes the idle-cash-sweep instrument (config.STRATEGY
    ["cash_sweep_symbol"], e.g. LIQUIDCASE), same reasoning and same fix
    as live_rebalance.get_live_holdings(): it isn't a momentum swing
    position, so it must never inflate holdings-value/invested-amount,
    double-count against the separate cash_sweep_value already folded
    into "Cash" (page_cockpit/_live_kpi_row), or show up as "Unclassified"
    in the sector-allocation view. Its value is surfaced separately -- see
    live_rebalance.get_cash_sweep_holding()."""
    sweep_sym = config.STRATEGY.get("cash_sweep_symbol", "LIQUIDCASE")
    pos = kite_client.get_positions()
    hold = kite_client.get_holdings()
    rows = []
    if not pos.empty and "quantity" in pos.columns:
        # > 0, not != 0 -- a same-day SELL of an existing holding shows up
        # here as a NEGATIVE "day" quantity (the settlement-lag leg, nets
        # to 0 against the holding once it clears), not a real short
        # position (this app is long-only CNC swing trading). Including
        # it double-counted a fully-closed position as still "held" with
        # a negative qty, which also poisoned avg_price = cost/qty here
        # (dividing by a negative number). Confirmed live 2026-08-04: a
        # same-day SONACOMS sell left qty=-13 in positions(), 0 in
        # holdings() -- summed to a phantom -13 "holding" instead of
        # correctly disappearing.
        for _, r in pos[(pos["quantity"] > 0) & (pos["tradingsymbol"] != sweep_sym)].iterrows():
            rows.append(
                {
                    "symbol": r["tradingsymbol"],
                    "qty": r["quantity"],
                    "avg_price": r["average_price"],
                    "ltp": r["last_price"],
                    "pnl": r["pnl"],
                }
            )
    if not hold.empty and "quantity" in hold.columns:
        for _, r in hold[(hold["quantity"] > 0) & (hold["tradingsymbol"] != sweep_sym)].iterrows():
            rows.append(
                {
                    "symbol": r["tradingsymbol"],
                    "qty": r["quantity"],
                    "avg_price": r["average_price"],
                    "ltp": r["last_price"],
                    "pnl": r["pnl"],
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["cost"] = df["qty"] * df["avg_price"]
    merged = df.groupby("symbol", as_index=False).agg(
        qty=("qty", "sum"), cost=("cost", "sum"), ltp=("ltp", "last"), pnl=("pnl", "sum")
    )
    merged["avg_price"] = merged["cost"] / merged["qty"]
    return merged.drop(columns="cost")


def log_equity_snapshot(
    value: float, invested_amount: float | None = None, holdings_value: float | None = None
) -> pd.DataFrame:
    """Upserts today's portfolio value (and cost basis / holdings-only
    market value, for the chart overlay), so the Cockpit can chart
    account growth over time -- Kite has no such history endpoint for a
    specific strategy's slice of the account. See state_db.py."""
    return state_db.log_equity_snapshot(value, invested_amount, holdings_value)


def _annualized_returns(portfolio_value: float, equity_log: pd.DataFrame) -> tuple[float | None, float | None]:
    """Returns (current_year_xirr, overall_xirr) as fractions (0.12 = 12%),
    or None for either if there isn't enough data yet to annualize.

    Overall XIRR: the full cash_flows ledger (deposits negative, i.e. money
    going in; withdrawals positive) plus today's portfolio value as a final,
    hypothetical-liquidation cash flow.

    Current-year XIRR mirrors backtest.py's yearly_performance() pattern
    (the prior available snapshot's value as this year's start value, not
    inflated by starting exactly at the first snapshot of a partial year):
    the equity_log's last value before this year, or the earliest snapshot
    this year if the log doesn't go back further, seeds the series alongside
    this year's cash flows and today's value."""
    cash_flows = state_db.get_cash_flows()
    today = dt.date.today()
    year_start = dt.date(today.year, 1, 1)

    overall_series = [(dt.date.fromisoformat(r["date"]), -float(r["amount"])) for _, r in cash_flows.iterrows()]
    overall_series.append((today, portfolio_value))
    overall = indicators.xirr(sorted(overall_series))

    start_date = start_value = None
    if not equity_log.empty:
        log = equity_log.copy()
        log["date"] = pd.to_datetime(log["date"]).dt.date
        before_year = log[log["date"] < year_start]
        if not before_year.empty:
            start_date = before_year.iloc[-1]["date"]
            start_value = float(before_year.iloc[-1]["value"])
        else:
            start_date = log["date"].iloc[0]
            start_value = float(log["value"].iloc[0])

    current_year = None
    if start_date is not None and start_date < today:
        this_year_series = [(start_date, -start_value)]
        for _, r in cash_flows.iterrows():
            d = dt.date.fromisoformat(r["date"])
            if start_date < d <= today:
                this_year_series.append((d, -float(r["amount"])))
        this_year_series.append((today, portfolio_value))
        current_year = indicators.xirr(sorted(this_year_series))

    return current_year, overall


# ---------------------------------------------------------------------------
# Page: Overview
# ---------------------------------------------------------------------------


def _is_market_hours(now: dt.datetime | None = None) -> bool:
    """NSE cash-market hours, weekday-only approximation (no holiday
    calendar) -- good enough for gating a display-only auto-refresh so it
    doesn't keep polling Kite every 30s all night for numbers that can't
    have changed."""
    now = now or dt.datetime.now()
    return now.weekday() < 5 and dt.time(9, 15) <= now.time() <= dt.time(15, 30)


@st.cache_data(ttl="6h", show_spinner=False)
def _benchmark_cagr_since(start_date_iso: str) -> float | None:
    """NIFTY 50's own annualized return (XIRR of a single buy-and-hold from
    `start_date_iso` to today) -- the correct apples-to-apples comparison
    for 'Alpha vs NIFTY50' against the portfolio's own overall XIRR (both
    annualized, so a young account and an old one are compared fairly).
    Cached 6h: this is a real Kite historical-data network call and index
    closes don't meaningfully change within a session."""
    try:
        start_date = dt.date.fromisoformat(start_date_iso)
        days = max((dt.date.today() - start_date).days + 5, 30)
        bench = kite_client.benchmark_candles(days)
        if bench.empty:
            return None
        if bench.index.tz is not None:
            bench = bench.set_axis(bench.index.tz_localize(None))
        bench = bench[bench.index >= pd.Timestamp(start_date)]
        if len(bench) < 2:
            return None
        start_price = float(bench["close"].iloc[0])
        end_price = float(bench["close"].iloc[-1])
        return indicators.xirr([(start_date, -1.0), (dt.date.today(), end_price / start_price)])
    except Exception:
        return None


@st.cache_data
def _asset_data_uri(filename: str) -> str | None:
    """Any assets/ image as an inline data URI -- embedded rather than
    referenced by path since Streamlit doesn't serve arbitrary project
    directories by default. Cached so each file is only read/base64-
    encoded once per process, not on every script rerun."""
    path = os.path.join("assets", filename)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


def _sidebar_logo_data_uri() -> str | None:
    return _asset_data_uri("logo.png")


def _max_drawdown_pct(equity_log: pd.DataFrame) -> float | None:
    """Largest peak-to-trough decline in the logged total-capital series so
    far, as a negative percentage -- pure arithmetic on data the equity
    chart already reads, no new storage or network call."""
    if equity_log.empty or len(equity_log) < 2:
        return None
    vals = equity_log["value"].astype(float)
    running_peak = vals.cummax()
    drawdown = (vals - running_peak) / running_peak.replace(0, pd.NA)
    dd = drawdown.min()
    return float(dd) * 100 if pd.notna(dd) else None


def _load_screen_cache() -> pd.DataFrame | None:
    """The last screener run's ranked table (written by both the Screener
    page's 'Run screen' button and every rebalance scan -- see
    screener.run_screen()'s caching note). Used for a live 'rank' column
    on Holdings and the Watchlist card; gracefully returns None if no scan
    has ever run yet rather than erroring the whole Overview page."""
    try:
        if os.path.exists(SCREEN_CACHE):
            return pd.read_pickle(SCREEN_CACHE)
    except Exception:
        pass
    return None


@st.fragment(run_every="30s" if _is_market_hours() else None)
def _live_kpi_row():
    """The Overview page's top KPI strip, isolated into its own fragment so
    it can tick on a timer without rerunning (and re-fetching Kite data
    for) the rest of the page -- equity chart, holdings table, funds
    breakdown all stay exactly as they render today. Every value here is
    independently re-fetched fresh each tick via the SAME functions the
    page already used (merged_holdings(), kite_client.get_margins(),
    state_db.get_realized_pnl()/get_equity_log(), _annualized_returns()) --
    no calculation logic duplicated or changed, just called again on a
    schedule. The 30s timer itself is only armed during market hours (see
    the decorator above) so an open tab doesn't keep re-rendering/polling
    Kite all night for numbers that can't have moved; the still-present
    _is_market_hours() branch below covers the same tab staying open
    across the market open/close transition within one session."""
    if _is_market_hours():
        live_merged = merged_holdings()
        try:
            live_cash = kite_client.get_margins()["equity"]["available"]["live_balance"]
        except Exception:
            live_cash = available_cash
    else:
        live_merged = merged_holdings()
        live_cash = available_cash

    # Idle-cash sweep: whatever's parked in the cash-sweep instrument
    # (e.g. LIQUIDCASE) is still YOUR liquid capital, just earning
    # interest instead of sitting as raw broker margin -- folded into
    # "Cash" here so it (and everything derived from it below: Total
    # capital, % deployed, XIRR) reflects true total liquid capital, not
    # just whatever Kite's margins API calls "available". 0 whenever the
    # feature is off or the lookup fails, byte-identical to before this
    # existed. The raw Kite-cash vs LIQUIDCASE split is still visible
    # separately on the Ledger page's Cash management card.
    if config.STRATEGY.get("cash_sweep_enabled", False):
        with contextlib.suppress(Exception):
            live_cash += lr.get_cash_sweep_holding()[1]

    live_invested = float((live_merged["qty"] * live_merged["avg_price"]).sum()) if not live_merged.empty else 0.0
    live_holdings_value = float((live_merged["qty"] * live_merged["ltp"]).sum()) if not live_merged.empty else 0.0
    live_unrealized_pnl = float(live_merged["pnl"].sum()) if not live_merged.empty else 0.0
    live_portfolio_value = live_cash + live_holdings_value
    live_realized_pnl = state_db.get_realized_pnl()
    live_total_pnl = live_realized_pnl + live_unrealized_pnl
    live_current_xirr, live_overall_xirr = _annualized_returns(live_portfolio_value, state_db.get_equity_log())

    unrealized_pct = (live_unrealized_pnl / live_invested * 100) if live_invested else None
    pct_deployed = (live_invested / live_portfolio_value * 100) if live_portfolio_value else None

    # Day's gain/loss: today's live total capital vs the most recent
    # logged snapshot BEFORE today (i.e. last night's close) -- the same
    # equity_log the performance chart already reads, no new storage.
    _day_log = state_db.get_equity_log()
    _prior_day_log = _day_log[_day_log["date"] < dt.date.today().isoformat()]
    _day_start_value = float(_prior_day_log.iloc[-1]["value"]) if not _prior_day_log.empty else None
    day_change = (live_portfolio_value - _day_start_value) if _day_start_value else None
    (day_change / _day_start_value * 100) if _day_start_value else None

    max_dd = _max_drawdown_pct(_day_log)
    alpha = None
    if live_overall_xirr is not None and not _day_log.empty:
        bench_cagr = _benchmark_cagr_since(_day_log.iloc[0]["date"])
        if bench_cagr is not None:
            alpha = (live_overall_xirr - bench_cagr) * 100

    _refresh_note = "🟢 live" if _is_market_hours() else "⚪ market closed"
    st.markdown(
        '<div class="ov-header" style="margin-bottom:14px;">'
        '<div><span class="ov-h1">Positional Dashboard</span> '
        '<span class="ov-sub">· everything at a glance</span></div>'
        f'<span class="ov-card-meta">{_refresh_note} · '
        f"last updated {dt.datetime.now():%H:%M:%S}</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    metrics_html = "".join(
        [
            _ov_metric_html(
                "Total capital",
                f"₹{live_portfolio_value:,.0f}",
                (f"{day_change:+,.0f} today" if day_change is not None else "no prior snapshot yet"),
                "ov-pos" if (day_change or 0) >= 0 else "ov-neg",
                "blue",
            ),
            _ov_metric_html("Invested", f"₹{live_invested:,.0f}", "Cost basis", "", "purple"),
            _ov_metric_html(
                "Holdings",
                f"₹{live_holdings_value:,.0f}",
                (f"{unrealized_pct:+.1f}% MTM" if unrealized_pct is not None else None),
                "ov-pos" if (unrealized_pct or 0) >= 0 else "ov-neg",
                "teal",
            ),
            _ov_metric_html(
                "Cash",
                f"₹{live_cash:,.0f}",
                (f"{pct_deployed:.0f}% deployed" if pct_deployed is not None else None),
                "",
                "amber",
            ),
            _ov_metric_html(
                "Total P&L",
                f"₹{live_total_pnl:+,.0f}",
                f"₹{live_unrealized_pnl:+,.0f} unrealized",
                "ov-pos" if live_unrealized_pnl >= 0 else "ov-neg",
                "green",
                "ov-pos" if live_total_pnl >= 0 else "ov-neg",
            ),
            _ov_metric_html(
                "Realized P&L",
                f"₹{live_realized_pnl:+,.0f}",
                "From closed trades",
                "",
                "green",
                "ov-pos" if live_realized_pnl >= 0 else "ov-neg",
            ),
            _ov_metric_html(
                "XIRR — year",
                f"{live_current_xirr * 100:+.1f}%" if live_current_xirr is not None else "—",
                "Annualized",
                "",
                "green",
                "ov-pos" if (live_current_xirr or 0) >= 0 else "ov-neg",
            ),
            _ov_metric_html(
                "XIRR — overall",
                f"{live_overall_xirr * 100:+.1f}%" if live_overall_xirr is not None else "—",
                "Inception",
                "",
                "green",
                "ov-pos" if (live_overall_xirr or 0) >= 0 else "ov-neg",
            ),
            _ov_metric_html(
                "Alpha vs NIFTY50",
                f"{alpha:+.1f}%" if alpha is not None else "—",
                "vs index CAGR, same period",
                "",
                "blue",
                "ov-pos" if (alpha or 0) >= 0 else "ov-neg",
            ),
            _ov_metric_html(
                "Max drawdown", f"{max_dd:.1f}%" if max_dd is not None else "—", "Peak to trough", "", "coral"
            ),
        ]
    )
    st.markdown(f'<div class="ov-grid-metrics">{metrics_html}</div>', unsafe_allow_html=True)

    if live_overall_xirr is None:
        st.caption(
            "XIRR needs at least one logged deposit and one portfolio "
            "value snapshot — log a deposit on the Admin page (or fund "
            "the account) to start tracking annualized return."
        )


def page_cockpit():
    merged = merged_holdings()
    if not merged.empty:
        merged["value"] = merged["qty"] * merged["ltp"]
    invested_amount = float((merged["qty"] * merged["avg_price"]).sum()) if not merged.empty else 0.0
    holdings_value = float(merged["value"].sum()) if not merged.empty else 0.0
    # Whatever's parked in the cash-sweep instrument is still real capital
    # -- fold it in here too, not just the live KPI strip, since this
    # portfolio_value is what gets PERSISTED as today's equity snapshot
    # below. Leaving it out would make the equity curve/XIRR history show
    # a fake drop the moment cash moves into the sweep instrument, when
    # nothing was actually lost. 0 whenever the feature is off or the
    # lookup fails, byte-identical to before this existed.
    cash_sweep_value = 0.0
    if config.STRATEGY.get("cash_sweep_enabled", False):
        with contextlib.suppress(Exception):
            cash_sweep_value = lr.get_cash_sweep_holding()[1]
    portfolio_value = available_cash + holdings_value + cash_sweep_value

    if portfolio_value > 0:
        log = log_equity_snapshot(portfolio_value, invested_amount, holdings_value)
    else:
        # A Kite auth failure or transient fetch error can silently leave
        # available_cash/holdings_value at 0 -- logging that as a real
        # snapshot would put a fake drop-to-zero in the equity curve (this
        # happened for real on a live install; see get_equity_log()'s
        # docstring). Skip the write, just show the log as it already is.
        log = state_db.get_equity_log()
        st.warning(
            "⚠️ Computed portfolio value is ₹0 — not logging today's "
            "snapshot (likely a Kite connection issue, not a real "
            "zero balance). Check the Kite login if this persists."
        )
    state_db.ensure_first_cash_flow_captured(available_cash)

    _pending_corp_actions = state_db.get_corporate_action_flags(status="pending")
    if not _pending_corp_actions.empty:
        _n = len(_pending_corp_actions)
        st.warning(
            f"⚠️ Possible stock split/bonus detected on {_n} position"
            f"{'s' if _n != 1 else ''} ({', '.join(_pending_corp_actions['symbol'])}) -- "
            "review on the Positions & Trade page before it affects the stop-loss."
        )

    _live_kpi_row()

    col_chart, col_positions = st.columns(2)

    with col_chart, st.container(border=True, key="ov-card-chart"):
        if len(log) > 1:
            plot_log_full = log.copy()
            plot_log_full["date"] = pd.to_datetime(plot_log_full["date"])

            _chart_title_slot = st.empty()
            _range_days = {"1W": 7, "1M": 30, "3M": 90, "6M": 182, "1Y": 365, "All": None}
            _range_choice = st.segmented_control(
                "Range", list(_range_days), default="All", required=True, key="perf_range", label_visibility="collapsed"
            )
            _chart_title_slot.markdown(
                '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
                '<span class="ov-dot" style="background:var(--ov-green);"></span>'
                "Portfolio value over time"
                f'<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
                f"{html_lib.escape(_range_choice)}</span></p>",
                unsafe_allow_html=True,
            )
            _cutoff_days = _range_days[_range_choice]
            if _cutoff_days:
                _cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=_cutoff_days)
                plot_log = plot_log_full[plot_log_full["date"] >= _cutoff].reset_index(drop=True)
                if len(plot_log) < 2:
                    # Not enough history in the selected window yet -- fall
                    # back to the full series rather than show a near-empty
                    # chart for a brand-new account.
                    plot_log = plot_log_full
            else:
                plot_log = plot_log_full

            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=plot_log["date"],
                    y=plot_log["holdings_value"],
                    name="Holdings value (₹)",
                    mode="lines+markers",
                    line={"color": "#16a34a", "width": 2},
                    marker={"size": 5},
                    hovertemplate="₹%{y:,.0f}<extra>Holdings value</extra>",
                )
            )
            if plot_log["invested_amount"].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=plot_log["date"],
                        y=plot_log["invested_amount"],
                        name="Invested amount (₹)",
                        mode="lines+markers",
                        line={"color": "#378add", "width": 2},
                        marker={"size": 5},
                        hovertemplate="₹%{y:,.0f}<extra>Invested amount</extra>",
                    )
                )
            # No fill-to-zero and an explicit, padded y-range -- with a small
            # account and only a few days of history, the day-to-day move is
            # tiny relative to the absolute total (e.g. ~2.5% over 4 days), so
            # an axis forced to include ₹0 (which "fill: tozeroy" does) squashes
            # that real movement into an invisible sliver at the top: the chart
            # LOOKS flat/broken even though the underlying data is fine. Padding
            # off the actual min/max instead makes real day-to-day change
            # visible regardless of how large the total balance is.
            all_vals = pd.concat([plot_log["holdings_value"], plot_log["invested_amount"]]).dropna()
            y_lo, y_hi = float(all_vals.min()), float(all_vals.max())
            pad = (y_hi - y_lo) * 0.15 or max(y_hi * 0.02, 100.0)
            fig.update_layout(
                height=310,
                margin={"l": 10, "r": 10, "t": 20, "b": 10},
                hovermode="x unified",
                yaxis={"tickprefix": "₹", "separatethousands": True, "range": [y_lo - pad, y_hi + pad]},
                legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0},
            )
            chart_selection = st.plotly_chart(
                fig, width="stretch", on_select="rerun", selection_mode="points", key="equity_chart_select"
            )
            if plot_log["holdings_value"].isna().any() or plot_log["invested_amount"].isna().any():
                st.caption(
                    "Holdings value / invested amount only started being logged "
                    "recently — earlier days show a gap until enough history "
                    "builds up. (Total capital, cash+holdings, is still tracked "
                    "in the KPI strip above; this chart is holdings-only vs cost "
                    "basis, so idle cash doesn't make the comparison misleading.)"
                )

            _clicked_points = chart_selection.selection.points if chart_selection else []
            if _clicked_points:
                _idx = _clicked_points[0]["point_index"]
                _day = plot_log.iloc[_idx]
                _prev = plot_log.iloc[_idx - 1] if _idx > 0 else None
                with st.expander(f"📅 {_day['date']:%d %b %Y} detail", expanded=True):
                    dc1, dc2, dc3 = st.columns(3)
                    _day_holdings = _day["holdings_value"]
                    _prev_holdings = _prev["holdings_value"] if _prev is not None else None
                    dc1.metric(
                        "Holdings value",
                        f"₹{_day_holdings:,.0f}" if pd.notna(_day_holdings) else "—",
                        delta=(
                            f"₹{_day_holdings - _prev_holdings:+,.0f} vs prev. day"
                            if pd.notna(_day_holdings) and pd.notna(_prev_holdings)
                            else None
                        ),
                    )
                    _day_invested = _day["invested_amount"]
                    _prev_invested = _prev["invested_amount"] if _prev is not None else None
                    dc2.metric(
                        "Invested amount",
                        f"₹{_day_invested:,.0f}" if pd.notna(_day_invested) else "—",
                        delta=(
                            f"₹{_day_invested - _prev_invested:+,.0f} vs prev. day"
                            if pd.notna(_day_invested) and pd.notna(_prev_invested)
                            else None
                        ),
                    )
                    _pct_deployed_day = (
                        _day_invested / _day["value"] * 100 if pd.notna(_day_invested) and _day["value"] else None
                    )
                    dc3.metric("% deployed", f"{_pct_deployed_day:.0f}%" if _pct_deployed_day is not None else "—")
        else:
            st.caption(
                "Portfolio value is logged once a day when you open this page — "
                "the chart builds up over time as you keep using the dashboard."
            )

    with col_positions, st.container(border=True, key="ov-card-positions"):
        st.markdown(
            '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
            '<span class="ov-dot" '
            'style="background:var(--ov-purple);"></span>Positions '
            '<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
            "By momentum rank</span></p>",
            unsafe_allow_html=True,
        )
        if merged.empty:
            st.caption("No open positions or holdings.")
        else:
            _screen = _load_screen_cache()
            _rank_map = {}
            if _screen is not None and "score" in _screen.columns:
                # Rank among GATE-PASSERS only (all_gates), matching both
                # the Screener page's own "rank" column (candidates =
                # t[t["all_gates"]]) and live_rebalance.py's candidates =
                # ranked[ranked["all_gates"]] -- was ranking across the
                # FULL unfiltered universe instead, so a stock scoring
                # higher than everyone but failing a gate silently
                # shifted every gate-passer's rank number down by one
                # (or more) versus what the Screener page showed for the
                # exact same stock. Confirmed live 2026-08-04: KALYANKJIL
                # showed #1 on Screener, #2 here.
                _screen_candidates = _screen[_screen["all_gates"]] if "all_gates" in _screen.columns else _screen
                _rank_map = {sym: i + 1 for i, sym in enumerate(_screen_candidates.index)}
            _keep_zone = (config.STRATEGY.get("max_positions") or 0) * 2

            # Held positions whose ONLY failing gate is the entry-band
            # RSI ceiling still get force-sell protection from screener.
            # sell_check()'s rsi_exit_gate_enabled carve-out (see its own
            # docstring) -- but until now they just silently vanished
            # from this card's rank (NaN -> "—"), which read as "this
            # dropped off the radar" even though it's actually safely
            # held. Mirrors sell_check()'s exact protection condition
            # (same non-RSI gates + rsi <= rsi_exit_max check) so this
            # label only appears for a symbol genuinely covered by that
            # mechanism, not just any gate failure.
            _rsi_exit_protected = set()
            if (
                _screen is not None
                and "all_gates" in _screen.columns
                and config.STRATEGY.get("rsi_exit_gate_enabled", False)
            ):
                _rsi_exit_max = config.STRATEGY.get("rsi_exit_max", config.STRATEGY.get("rsi_max"))
                _ng = _screen[~_screen["all_gates"]]
                _protected = _ng[
                    _ng["trend_ok"].fillna(True)
                    & _ng["near_high_ok"].fillna(True)
                    & _ng["quality_ok"].fillna(True)
                    & _ng["price_ok"].fillna(True)
                    & (_ng["rsi"] <= _rsi_exit_max)
                ]
                _rsi_exit_protected = set(_protected.index)

            # Sort by momentum rank (ascending -- rank 1 first), matching
            # the "By momentum rank" label above; a symbol not in
            # today's ranked universe (rank is NaN) sorts to the end
            # rather than breaking the sort. Was sorting by value
            # (position size) instead while still claiming "By momentum
            # rank" -- confirmed real mismatch, fixed 2026-08-04.
            pos_desc = merged.copy()
            pos_desc["rank"] = pos_desc["symbol"].map(_rank_map)
            pos_desc = pos_desc.sort_values("rank", ascending=True, na_position="last").reset_index(drop=True)

            # Entry rank -- the "Ranked #N of M momentum candidates"
            # this symbol's FIRST open trade recorded (live_rebalance.
            # propose_rebalance()'s buy reason string, see state_db.
            # record_trade_entry()) -- so the arrow below reflects
            # this specific holding's own rank drift since it was
            # bought, not just today's snapshot. Absent for a position
            # opened outside this app (backfilled trades, no rank in
            # their reason text), which renders as no arrow rather
            # than a misleading one.
            _open_trades = state_db.get_trades(status="open")
            _entry_rank_map = {}
            if not _open_trades.empty:
                _first_entries = _open_trades.sort_values("entry_date").groupby("symbol").first()
                for _sym, _t in _first_entries.iterrows():
                    _m = re.search(r"Ranked #(\d+)", str(_t.get("entry_reason") or ""))
                    if _m:
                        _entry_rank_map[_sym] = int(_m.group(1))
            pos_desc["entry_rank"] = pos_desc["symbol"].map(_entry_rank_map)

            def _rank_badge_cls(v: str) -> str:
                if v == "RSI-held":
                    return "ov-badge-amber"
                if v == "—":
                    return "ov-badge-gray"
                return "ov-badge-green" if int(v) <= _keep_zone else "ov-badge-red"

            def _rank_fmt(row):
                if pd.notna(row["rank"]):
                    return str(int(row["rank"]))
                if row["symbol"] in _rsi_exit_protected:
                    return "RSI-held"
                return "—"

            pos_desc["rank_fmt"] = pos_desc.apply(_rank_fmt, axis=1)
            st.markdown(
                _ov_table_html(
                    pos_desc,
                    columns=["symbol", "value", "rank_fmt", "pnl"],
                    sym_cols=["symbol"],
                    pnl_cols=["pnl"],
                    num_fmt={"value": "₹{:,.0f}"},
                    badges={"rank_fmt": _rank_badge_cls},
                    arrow_cols={"rank_fmt": ("rank", "entry_rank", False)},
                ),
                unsafe_allow_html=True,
            )

            # Real, data-driven equivalent of the mockup's "likely
            # exit" alert -- flags currently-held symbols the LAST
            # rebalance scan actually proposed selling, not a guess.
            _last_run_pos = state_db.get_last_rebalance_run()
            if _last_run_pos is not None:
                _sells_pos = _last_run_pos.get("sells", pd.DataFrame())
                _at_risk = [s for s in pos_desc["symbol"] if not _sells_pos.empty and s in set(_sells_pos["symbol"])]
                if _at_risk:
                    st.markdown(
                        f'<div class="ov-alert">⚠ Likely exit next rebalance: {", ".join(_at_risk)}</div>',
                        unsafe_allow_html=True,
                    )

    if not merged.empty:
        # ---- Capital allocation per stock (weight vs equal-weight target,
        # as a mini-bar drift gauge) + Asset allocation by sector (hand-
        # drawn donut + legend) -- both pure static HTML/SVG (neither had a
        # click-handler even as Plotly figures), rendered as ONE markdown
        # call each so the two-column CSS grid actually lays them out
        # side by side.
        max_positions = config.STRATEGY.get("max_positions") or 0
        target_pct = 100.0 / max_positions if max_positions else None
        total_value = float(merged["value"].sum())
        # Denominator for weight/drift is TOTAL portfolio value (cash +
        # holdings), matching target_pct's own basis -- screener.
        # allocate_equal_weight_buys() defines its target as total_equity
        # (cash+holdings) / max_positions, not holdings-only. Using
        # holdings-only here (the previous behavior) systematically
        # understated drift whenever real cash was sitting uninvested --
        # e.g. 10 positions each truly at 7.5% of a $200k account with
        # $50k idle cash would each read as exactly 10.0%/on-target
        # instead of correctly showing -2.5% drift, since 15k/150k
        # (holdings-only) = 10% even though 15k/200k (true) = 7.5%. Same
        # reasoning extends to cash_sweep_value (computed at the top of
        # this page) -- live_rebalance.propose_rebalance()'s own sizing
        # denominator already includes it, so this gauge would otherwise
        # show a smaller total than what actually sizes new buys.
        total_equity = available_cash + total_value + cash_sweep_value
        alloc_desc = merged.sort_values("value", ascending=False).reset_index(drop=True)

        allocbar_segments, alloc_rows = [], []
        for i, row in alloc_desc.iterrows():
            color = _OV_HEX_CYCLE[i % len(_OV_HEX_CYCLE)]
            weight_pct = (row["value"] / total_equity * 100) if total_equity else 0.0
            allocbar_segments.append(f'<div style="width:{weight_pct:.2f}%;background:{color};"></div>')
            if target_pct:
                drift = weight_pct - target_pct
                fill_pct = min(100.0, (weight_pct / target_pct) * 80)
                drift_cls = "ov-pos" if drift >= 0 else "ov-neg"
                alloc_rows.append(
                    f'<tr><td class="ov-sym">{row["symbol"]}</td><td>{weight_pct:.1f}%</td>'
                    f'<td><div class="ov-minibar"><div class="ov-fill" '
                    f'style="width:{fill_pct:.1f}%;background:{color};"></div>'
                    f'<div class="ov-tick"></div></div></td>'
                    f'<td class="r {drift_cls}">{drift:+.1f}%</td></tr>'
                )
            else:
                alloc_rows.append(
                    f'<tr><td class="ov-sym">{row["symbol"]}</td>'
                    f'<td>{weight_pct:.1f}%</td><td></td><td class="r">—</td></tr>'
                )
        target_meta = f"Target {target_pct:.0f}% ±" if target_pct else ""
        alloc_html = (
            '<div class="ov-card"><p class="ov-card-title">'
            '<span class="ov-dot" style="background:var(--ov-blue);"></span>'
            f'Capital allocation per stock <span class="ov-card-meta" '
            f'style="font-weight:400;margin-left:auto;">{target_meta}</span></p>'
            f'<div class="ov-allocbar">{"".join(allocbar_segments)}</div>'
            '<table class="ov-table"><tr><th>Symbol</th><th>Weight</th>'
            '<th style="width:38%;">vs target</th><th class="r">Drift</th></tr>'
            + "".join(alloc_rows)
            + "</table></div>"
        )

        donut_html = ""
        try:
            membership = su.sector_membership_only(merged["symbol"].tolist(), verbose=False)
            sector_of = merged["symbol"].map(lambda s: (membership.get(s) or ["Unclassified"])[0])
            symbols_by_sector = merged.assign(sector=sector_of).groupby("sector")["symbol"].apply(", ".join)
            sector_group = merged.assign(sector=sector_of).groupby("sector")["value"].sum().sort_values(ascending=False)
            donut_total = float(sector_group.sum()) or 1.0
            legend_rows = []
            for i, (sector, value) in enumerate(sector_group.items()):
                color = _OV_HEX_CYCLE[i % len(_OV_HEX_CYCLE)]
                pct = value / donut_total * 100
                legend_rows.append(
                    '<div class="ov-sector-row"><div class="ov-sector-head">'
                    f'<span><span class="ov-sw" style="background:{color};"></span>'
                    f"{sector} · {symbols_by_sector[sector]}</span>"
                    f'<span class="ov-sym">{pct:.1f}%</span></div>'
                    '<div class="ov-sector-bar"><div class="ov-sector-fill" '
                    f'style="width:{pct:.1f}%;background:{color};"></div></div></div>'
                )
            n_sectors = len(sector_group)
            svg = _ov_donut_svg(list(sector_group.values), str(n_sectors))
            max_sector_pct = float((sector_group / donut_total * 100).max())
            # margin-top here (unlike the Positions card's own "Likely
            # exit" ov-alert) -- that one sits inside a real st.container,
            # where Streamlit's own inter-block gap already separates it
            # from the table above; this one is glued into one raw HTML
            # string right after the donut/legend markup with no such
            # gap, so it needs its own spacing to not look flush/cramped.
            if max_sector_pct <= 25:
                alert_html = (
                    '<div class="ov-alert ov-alert-success" style="margin-top:8px;">'
                    "✓ Diversified — no sector above 25%</div>"
                )
            else:
                top_sector = (sector_group / donut_total * 100).idxmax()
                alert_html = (
                    f'<div class="ov-alert" style="margin-top:8px;">'
                    f"⚠ Concentrated — {top_sector} is "
                    f"{max_sector_pct:.0f}% of the portfolio</div>"
                )
            donut_html = (
                '<div class="ov-card"><p class="ov-card-title">'
                '<span class="ov-dot" style="background:var(--ov-purple);"></span>'
                'Asset allocation by sector <span class="ov-card-meta" '
                'style="font-weight:400;margin-left:auto;">Concentration check</span></p>'
                f'<div class="ov-donut-wrap">{svg}'
                f'<div class="ov-donut-legend">{"".join(legend_rows)}</div></div>'
                f"{alert_html}</div>"
            )
        except Exception as e:
            donut_html = (
                '<div class="ov-card"><p class="ov-card-title">Asset allocation by sector</p>'
                f'<p class="ov-card-meta">Sector data unavailable right now: {e}</p></div>'
            )

        st.markdown(f'<div class="ov-two-col">{alloc_html}{donut_html}</div>', unsafe_allow_html=True)

        # ---- Rebalance preview (real data from the last scan) + Watchlist
        # (next-in-queue candidates from the cached screener ranking), laid
        # out side by side like the allocation/donut row above -- these two
        # have real Streamlit widgets inside (a button, cached data calls),
        # so they need actual st.columns rather than the flattened
        # single-markdown ov-two-col trick used for the pure-HTML cards.
        _last_run = state_db.get_last_rebalance_run()
        col_rebal, col_watch = st.columns(2)
        with col_rebal, st.container(border=True, key="ov-card-rebal"):
            _scan_meta = f"as of {_last_run['run_time']:%d %b %H:%M}" if _last_run is not None else ""
            st.markdown(
                '<p class="ov-card-title"><span class="ov-dot" '
                'style="background:var(--ov-amber);"></span>Rebalance preview '
                f'<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
                f"{_scan_meta}</span></p>",
                unsafe_allow_html=True,
            )
            rebal_rows = []
            if _last_run is not None:
                sells_df = _last_run.get("sells", pd.DataFrame())
                buys_df = _last_run.get("buys", pd.DataFrame())
                sold_syms = set(sells_df["symbol"]) if not sells_df.empty else set()
                for _, r in sells_df.iterrows():
                    rebal_rows.append(
                        '<div class="ov-row"><span><span class="ov-badge ov-badge-red">'
                        f"Exit</span>&nbsp; {r['symbol']}</span>"
                        f'<span class="ov-card-meta">{r.get("reason", "")}</span></div>'
                    )
                for _, r in buys_df.iterrows():
                    price = r.get("price")
                    price_str = f"~₹{price:,.0f}" if pd.notna(price) else ""
                    rebal_rows.append(
                        '<div class="ov-row"><span><span class="ov-badge ov-badge-green">'
                        f"Enter</span>&nbsp; {r['symbol']}</span>"
                        f'<span class="ov-card-meta">{price_str}</span></div>'
                    )
                hold_syms = [s for s in merged["symbol"] if s not in sold_syms] if not merged.empty else []
                if hold_syms:
                    rebal_rows.append(
                        '<div class="ov-row"><span><span class="ov-badge ov-badge-gray">'
                        f"Hold</span>&nbsp; {', '.join(hold_syms)}</span>"
                        '<span class="ov-card-meta">Within cutoff</span></div>'
                    )
            if rebal_rows:
                st.markdown("".join(rebal_rows), unsafe_allow_html=True)
            else:
                st.markdown(
                    '<p class="ov-card-meta">'
                    + ("No changes proposed in the last scan." if _last_run is not None else "No scan has run yet.")
                    + "</p>",
                    unsafe_allow_html=True,
                )
            if st.button("Review rebalance orders →", key="ov_review_rebal", type="primary", use_container_width=True):
                st.switch_page(page_live_rebalance_p)

        with col_watch, st.container(border=True, key="ov-card-watchlist"):
            st.markdown(
                '<p class="ov-card-title"><span class="ov-dot" '
                'style="background:var(--ov-teal);"></span>'
                "Watchlist — next in queue</p>",
                unsafe_allow_html=True,
            )
            _screen = _load_screen_cache()
            watch_rows = []
            if _screen is not None and "all_gates" in _screen.columns:
                held_syms = set(merged["symbol"])
                buy_syms = (
                    set(_last_run["buys"]["symbol"])
                    if _last_run is not None and not _last_run.get("buys", pd.DataFrame()).empty
                    else set()
                )
                candidates = _screen[_screen["all_gates"]]
                for i, sym in enumerate(candidates.index):
                    if sym in held_syms:
                        continue
                    rank = i + 1
                    if sym in buy_syms:
                        watch_rows.append(
                            f'<div class="ov-row"><span class="ov-sym">{sym}</span>'
                            f'<span class="ov-badge ov-badge-green">Rank {rank} · entering</span></div>'
                        )
                    else:
                        watch_rows.append(
                            f'<div class="ov-row"><span class="ov-sym">{sym}</span>'
                            f'<span class="ov-card-meta">Rank {rank} · reserve</span></div>'
                        )
                    if len(watch_rows) >= 4:
                        break
            if watch_rows:
                st.markdown("".join(watch_rows), unsafe_allow_html=True)
            else:
                st.markdown(
                    '<p class="ov-card-meta">Run a scan (Live Rebalance or Screener) to populate the watchlist.</p>',
                    unsafe_allow_html=True,
                )

    st.divider()
    with st.expander("Full funds breakdown (from Kite margins API)"):

        def _breakdown_table(section: dict) -> pd.DataFrame:
            rows = []
            for k, v in section.items():
                try:
                    v = f"{float(v):,.2f}"
                except (TypeError, ValueError):
                    v = str(v)
                rows.append({"Metric": k.replace("_", " ").title(), "Value": v})
            return pd.DataFrame(rows)

        try:
            m = kite_client.get_margins()["equity"]
            fc1, fc2 = st.columns(2)
            with fc1, st.container(border=True, key="ov-card-funds-available"):
                st.markdown('<p class="ov-card-title">Available</p>', unsafe_allow_html=True)
                st.markdown(_ov_table_html(_breakdown_table(m["available"])), unsafe_allow_html=True)
            with fc2, st.container(border=True, key="ov-card-funds-utilised"):
                st.markdown('<p class="ov-card-title">Utilised</p>', unsafe_allow_html=True)
                st.markdown(_ov_table_html(_breakdown_table(m["utilised"])), unsafe_allow_html=True)
        except Exception as e:
            st.warning(f"Could not fetch funds breakdown: {e}")


# ---------------------------------------------------------------------------
# Page: Ledger
# ---------------------------------------------------------------------------


def page_ledger():
    st.markdown(
        '<div class="ov-header"><div><span class="ov-h1">💰 Ledger</span> '
        '<span class="ov-sub">· The deposit/withdrawal ledger used for XIRR</span></div></div>',
        unsafe_allow_html=True,
    )

    ledger = state_db.get_cash_flows()
    _ledger_sel_id = st.session_state.get("_admin_ledger_sel_id")
    _editing = _ledger_sel_id is not None and not ledger.empty and _ledger_sel_id in ledger["id"].values

    _cashflow_tip = html_lib.escape(
        "Kite's API can't see bank transfers — this ledger is what keeps XIRR accurate as you add money over time."
    )
    with st.container(border=True, key="ov-card-admin-cashflow"):
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" '
            'style="background:var(--ov-green);"></span>💰 Log a deposit / withdrawal'
            f'<span class="ov-info-icon" title="{_cashflow_tip}">ℹ️</span>'
            + (
                '<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
                "Editing the entry selected below</span>"
                if _editing
                else ""
            )
            + "</p>",
            unsafe_allow_html=True,
        )
        if _editing:
            _edit_row = ledger.set_index("id").loc[_ledger_sel_id]
            _def_date = pd.to_datetime(_edit_row["date"]).date()
            _def_amount = float(_edit_row["amount"])
            _def_note = _edit_row["note"] or ""
        else:
            _def_date, _def_amount, _def_note = dt.date.today(), 0.0, ""
        with st.form(f"cash_flow_form_{_ledger_sel_id if _editing else 'new'}", clear_on_submit=not _editing):
            cff1, cff2 = st.columns(2)
            cf_date = cff1.date_input("Date", value=_def_date)
            cf_amount = cff2.number_input(
                "Amount (₹) — + deposit / − withdrawal", value=_def_amount, step=1000.0, format="%.2f"
            )
            cf_note = st.text_input("Note (optional)", value=_def_note)
            if _editing:
                fb1, fb2 = st.columns(2)
                cf_submitted = fb1.form_submit_button("Save changes", type="primary", use_container_width=True)
                cf_delete_clicked = fb2.form_submit_button(
                    "Delete entry", key="admin_ledger_delete_btn", use_container_width=True
                )
            else:
                cf_submitted = st.form_submit_button("Log cash flow", type="primary")
                cf_delete_clicked = False
        if cf_submitted:
            if cf_amount == 0:
                st.error("Amount can't be zero.")
            elif _editing:
                state_db.update_cash_flow(_ledger_sel_id, cf_date.isoformat(), float(cf_amount), cf_note)
                st.session_state["_admin_ledger_sel_id"] = None
                st.success("Updated.")
                st.rerun()
            else:
                state_db.record_cash_flow(cf_date.isoformat(), float(cf_amount), cf_note)
                st.success("Logged.")
                st.rerun()
        if cf_delete_clicked:
            state_db.delete_cash_flow(_ledger_sel_id)
            st.session_state["_admin_ledger_sel_id"] = None
            st.success("Deleted.")
            st.rerun()
        if _editing:
            if st.button("+ Log a new entry instead", key="admin_ledger_new_entry_btn"):
                st.session_state["_admin_ledger_sel_id"] = None
                st.rerun()

    with st.container(border=True, key="ov-card-admin-ledger"):
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" '
            'style="background:var(--ov-green);"></span>Ledger'
            '<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
            "Select a row to edit or delete it above</span></p>",
            unsafe_allow_html=True,
        )
        if ledger.empty:
            st.caption("No cash flows logged yet.")
        else:
            display_ledger = ledger.sort_values("date", ascending=False).reset_index(drop=True)
            display_ledger["date"] = pd.to_datetime(display_ledger["date"]).dt.date
            ledger_page = _ov_page_slice(display_ledger, key="admin_ledger")

            with st.container(key="admin_ledger_head"):
                _hh1, hh2, hh3, hh4 = st.columns([0.4, 1.3, 1.3, 2.4])
                hh2.markdown('<span class="ov-manual-th">Date</span>', unsafe_allow_html=True)
                hh3.markdown('<span class="ov-manual-th r">Amount (₹)</span>', unsafe_allow_html=True)
                hh4.markdown('<span class="ov-manual-th">Note</span>', unsafe_allow_html=True)
            with st.container(key="admin_ledger_rows"):
                for _, r in ledger_page.iterrows():
                    rid = int(r["id"])
                    rc1, rc2, rc3, rc4 = st.columns([0.4, 1.3, 1.3, 2.4])
                    with rc1:
                        if st.button(
                            "●" if rid == _ledger_sel_id else "○",
                            key=f"admin_ledger_radio_{rid}",
                            help="Select to edit/delete",
                        ):
                            st.session_state["_admin_ledger_sel_id"] = None if rid == _ledger_sel_id else rid
                            st.rerun()
                    amt = float(r["amount"])
                    amt_cls = "ov-pos" if amt >= 0 else "ov-neg"
                    rc2.markdown(f'<span class="ov-manual-cell">{r["date"]}</span>', unsafe_allow_html=True)
                    rc3.markdown(
                        f'<span class="ov-manual-cell r {amt_cls} ov-sym">{amt:+,.2f}</span>', unsafe_allow_html=True
                    )
                    rc4.markdown(
                        f'<span class="ov-manual-cell">{html_lib.escape(r["note"] or "—")}</span>',
                        unsafe_allow_html=True,
                    )
            _ov_pagination_controls(display_ledger, key="admin_ledger")

    st.divider()
    st.markdown(
        '<div class="ov-header"><div><span class="ov-h1">🧾 Trading Charges</span>'
        '<span class="ov-sub">· DP charges &amp; recurring costs like Demat AMC'
        "</span></div></div>",
        unsafe_allow_html=True,
    )

    with st.container(border=True, key="ov-card-cash-management"):
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" '
            'style="background:var(--ov-teal);"></span>Cash management</p>',
            unsafe_allow_html=True,
        )
        st.caption(
            "The DP (Depository Participant) charge your broker debits per "
            "scrip, per day you sell -- auto-logged below every time a "
            "position actually closes (any path: rebalance sell, gap-down "
            "stop, manual square-off, or a GTT/external fill), so it's "
            "never missed the way a manually-remembered entry can be."
        )
        with st.form("dp_charge_form"):
            dp_charge_per_scrip = st.number_input(
                "DP charge per scrip sold (₹)",
                min_value=0.0,
                max_value=100.0,
                value=float(config.STRATEGY.get("dp_charge_per_scrip", 15.34)),
                step=0.01,
                format="%.2f",
                help="0 disables this entirely -- no cash-flow entry posted.",
            )
            if st.form_submit_button("Save", type="primary"):
                state_db.update_strategy_config({"dp_charge_per_scrip": float(dp_charge_per_scrip)})
                config.STRATEGY["dp_charge_per_scrip"] = float(dp_charge_per_scrip)
                st.success("Saved.")
                st.rerun()

        st.divider()
        st.markdown("**Idle cash sweep**")
        st.caption(
            "Park uninvested cash in a liquid-fund ETF so it earns interest "
            "instead of sitting idle -- swept in automatically after any "
            "rebalance run, gap-down sell, or manual trade, and redeemed "
            "back (just enough to cover the shortfall) whenever a new buy "
            "needs more cash than what's free. Buying it carries no DP "
            "charge (that only applies to a sell), so every idle rupee "
            "gets swept, no minimum. This places real automatic orders on "
            "a new instrument, so it starts off, same as auto-execute."
        )
        _sweep_qty, _sweep_value = (0, 0.0)
        if config.STRATEGY.get("cash_sweep_enabled", False):
            with contextlib.suppress(Exception):
                _sweep_qty, _sweep_value = lr.get_cash_sweep_holding()
        if _sweep_qty:
            st.markdown(
                f'<div class="ov-row"><span class="ov-card-meta">Currently parked</span>'
                f'<span class="ov-sym">{_sweep_qty} units · ₹{_sweep_value:,.0f}</span></div>',
                unsafe_allow_html=True,
            )
        # Fetched live from Kite's own instrument list (every tradable
        # symbol containing "LIQUID"), not hardcoded -- a new fund listing
        # or a delisting is picked up automatically. Falls back to just
        # the currently-saved value if the fetch fails (e.g. Kite session
        # issue) or that value isn't in the fetched list, so a legacy/
        # custom choice never silently disappears from the dropdown.
        try:
            _cash_instruments = kite_client.get_cash_instruments()
        except Exception:
            _cash_instruments = []
        _current_symbol = config.STRATEGY.get("cash_sweep_symbol", "LIQUIDCASE")
        if _current_symbol not in _cash_instruments:
            _cash_instruments = sorted(set(_cash_instruments) | {_current_symbol})
        with st.form("cash_sweep_form"):
            csf1, csf2 = st.columns([1, 2])
            cash_sweep_enabled = csf1.checkbox("Enabled", value=bool(config.STRATEGY.get("cash_sweep_enabled", False)))
            cash_sweep_symbol = csf2.selectbox(
                "Instrument", _cash_instruments, index=_cash_instruments.index(_current_symbol)
            )
            if st.form_submit_button("Save", type="primary"):
                updates = {"cash_sweep_enabled": bool(cash_sweep_enabled), "cash_sweep_symbol": cash_sweep_symbol}
                state_db.update_strategy_config(updates)
                config.STRATEGY.update(updates)
                st.success("Saved.")
                st.rerun()

    _recurring = state_db.get_recurring_charges()
    _rec_sel_id = st.session_state.get("_admin_recurring_sel_id")
    _rec_editing = _rec_sel_id is not None and not _recurring.empty and _rec_sel_id in _recurring["id"].values
    _interval_labels = {1: "Monthly", 3: "Quarterly", 6: "Half-yearly", 12: "Yearly"}
    _interval_months = {v: k for k, v in _interval_labels.items()}

    _recurring_tip = html_lib.escape(
        "Fixed, predictable recurring costs (e.g. quarterly Demat AMC) -- "
        "define once and the daily scheduled job auto-posts a Ledger entry "
        "each time it's due, instead of you re-adding it by hand every "
        "cycle. Per-sale DP charges are handled separately (Cash "
        "management, above) since they're posted automatically on every "
        "real exit, not on a fixed schedule."
    )
    with st.container(border=True, key="ov-card-recurring-charges"):
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" '
            'style="background:var(--ov-purple);"></span>Recurring charges'
            f'<span class="ov-info-icon" title="{_recurring_tip}">ℹ️</span>'
            + (
                '<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
                "Editing the entry selected below</span>"
                if _rec_editing
                else ""
            )
            + "</p>",
            unsafe_allow_html=True,
        )
        if _rec_editing:
            _rec_row = _recurring.set_index("id").loc[_rec_sel_id]
            _rdef_note = _rec_row["note"]
            _rdef_amount = float(_rec_row["amount"])
            _rdef_interval = int(_rec_row["interval_months"])
            _rdef_due = pd.to_datetime(_rec_row["next_due_date"]).date()
            _rdef_active = bool(_rec_row["active"])
        else:
            _rdef_note, _rdef_amount, _rdef_interval = "", 0.0, 3
            _rdef_due, _rdef_active = dt.date.today(), True
        with st.form(
            f"recurring_charge_form_{_rec_sel_id if _rec_editing else 'new'}", clear_on_submit=not _rec_editing
        ):
            rcf1, rcf2 = st.columns(2)
            rc_note = rcf1.text_input('Note (e.g. "Demat AMC")', value=_rdef_note)
            rc_amount = rcf2.number_input(
                "Amount (₹) — always a charge, sign handled automatically",
                min_value=0.0,
                value=_rdef_amount,
                step=1.0,
                format="%.2f",
            )
            rcf3, rcf4, rcf5 = st.columns(3)
            rc_interval_label = rcf3.selectbox(
                "Repeats", list(_interval_labels.values()), index=list(_interval_labels.keys()).index(_rdef_interval)
            )
            rc_due = rcf4.date_input("Next due date", value=_rdef_due)
            rc_active = rcf5.checkbox("Active", value=_rdef_active)
            if _rec_editing:
                rfb1, rfb2 = st.columns(2)
                rc_submitted = rfb1.form_submit_button("Save changes", type="primary", use_container_width=True)
                rc_delete_clicked = rfb2.form_submit_button(
                    "Delete", key="admin_recurring_delete_btn", use_container_width=True
                )
            else:
                rc_submitted = st.form_submit_button("Add recurring charge", type="primary")
                rc_delete_clicked = False
        if rc_submitted:
            if not rc_note.strip():
                st.error("Note can't be empty.")
            elif rc_amount <= 0:
                st.error("Amount must be positive.")
            elif _rec_editing:
                state_db.update_recurring_charge(
                    _rec_sel_id,
                    rc_note.strip(),
                    float(rc_amount),
                    _interval_months[rc_interval_label],
                    rc_due.isoformat(),
                    bool(rc_active),
                )
                st.session_state["_admin_recurring_sel_id"] = None
                st.success("Updated.")
                st.rerun()
            else:
                state_db.add_recurring_charge(
                    rc_note.strip(), float(rc_amount), _interval_months[rc_interval_label], rc_due.isoformat()
                )
                st.success("Added.")
                st.rerun()
        if rc_delete_clicked:
            state_db.delete_recurring_charge(_rec_sel_id)
            st.session_state["_admin_recurring_sel_id"] = None
            st.success("Deleted.")
            st.rerun()
        if _rec_editing:
            if st.button("+ Add a new recurring charge instead", key="admin_recurring_new_btn"):
                st.session_state["_admin_recurring_sel_id"] = None
                st.rerun()

        if _recurring.empty:
            st.caption("No recurring charges defined yet.")
        else:
            with st.container(key="admin_recurring_rows"):
                _rh1, rh2, rh3, rh4, rh5 = st.columns([0.4, 2.0, 1.2, 1.2, 1.2])
                rh2.markdown('<span class="ov-manual-th">Note</span>', unsafe_allow_html=True)
                rh3.markdown('<span class="ov-manual-th r">Amount (₹)</span>', unsafe_allow_html=True)
                rh4.markdown('<span class="ov-manual-th">Repeats</span>', unsafe_allow_html=True)
                rh5.markdown('<span class="ov-manual-th">Next due</span>', unsafe_allow_html=True)
                for _, r in _recurring.iterrows():
                    rid = int(r["id"])
                    rrc1, rrc2, rrc3, rrc4, rrc5 = st.columns([0.4, 2.0, 1.2, 1.2, 1.2])
                    with rrc1:
                        if st.button(
                            "●" if rid == _rec_sel_id else "○",
                            key=f"admin_recurring_radio_{rid}",
                            help="Select to edit/delete",
                        ):
                            st.session_state["_admin_recurring_sel_id"] = None if rid == _rec_sel_id else rid
                            st.rerun()
                    _note_disp = html_lib.escape(r["note"]) + ("" if r["active"] else " (inactive)")
                    rrc2.markdown(f'<span class="ov-manual-cell">{_note_disp}</span>', unsafe_allow_html=True)
                    rrc3.markdown(
                        f'<span class="ov-manual-cell r ov-sym">{-abs(float(r["amount"])):,.2f}</span>',
                        unsafe_allow_html=True,
                    )
                    rrc4.markdown(
                        f'<span class="ov-manual-cell">'
                        f"{_interval_labels.get(int(r['interval_months']), f'{int(r["interval_months"])}mo')}</span>",
                        unsafe_allow_html=True,
                    )
                    rrc5.markdown(f'<span class="ov-manual-cell">{r["next_due_date"]}</span>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Page: Admin
# ---------------------------------------------------------------------------


def page_admin():
    st.markdown(
        '<div class="ov-header"><div><span class="ov-h1">⚙️ Admin</span> '
        '<span class="ov-sub">Kite settings and strategy configuration</span></div></div>',
        unsafe_allow_html=True,
    )

    if state_db.is_using_default_dashboard_password(config.DASHBOARD_USERNAME, config.DASHBOARD_PASSWORD):
        st.markdown(
            '<div class="ov-alert">⚠️ Using the default Admin/Admin login — '
            'this app places real orders. Change it in "Change dashboard '
            'password" below.</div>',
            unsafe_allow_html=True,
        )

    _strategy_tip = html_lib.escape(
        "Stored in state.db (strategy_config table) — takes effect "
        "immediately for this dashboard process (no restart needed), and "
        "for the next scheduled/manual rebalance scan. See the README for "
        "the research behind each default."
    )
    st.markdown(
        '<p class="ov-card-title" style="margin-top:14px;"><span class="ov-dot" '
        'style="background:var(--ov-purple);"></span>🎯 Strategy configuration'
        f'<span class="ov-info-icon" title="{_strategy_tip}">ℹ️</span>'
        '<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
        "Takes effect immediately — no restart needed</span></p>",
        unsafe_allow_html=True,
    )
    cfg = config.STRATEGY
    with st.container(border=True, key="ov-card-admin-strategy"):
        # Stop mechanism: mutually exclusive (MAD replaces BOTH the initial
        # and trailing ATR stop entirely when on -- backtest.py's
        # _initial_stop()/trailing-ratchet block ignore atr_stop_multiple/
        # trailing_atr_multiple outright whenever mad_stop_enabled is True).
        # Rendered OUTSIDE st.form() deliberately: widgets inside a form
        # don't trigger a rerun on their own (only the submit button does),
        # so neither the mutual-exclusion callback nor a disabled= tied to
        # these checkboxes could update live from inside one -- toggling
        # either would visibly do nothing until "Save strategy settings"
        # was already clicked once. Out here, both react instantly.
        st.markdown('<p class="ov-muted">Trade management — stop mechanism (choose one)</p>', unsafe_allow_html=True)
        stop_c1, stop_c2 = st.columns(2)

        def _on_toggle_admin_trailing():
            if st.session_state.get("admin_trailing_stop_enabled"):
                st.session_state["admin_use_mad_stop"] = False

        def _on_toggle_admin_mad_stop():
            if st.session_state.get("admin_use_mad_stop"):
                st.session_state["admin_trailing_stop_enabled"] = False

        trailing_stop_enabled = stop_c1.checkbox(
            "Use ATR trailing stop",
            key="admin_trailing_stop_enabled",
            value=bool(cfg["trailing_stop_enabled"]),
            on_change=_on_toggle_admin_trailing,
            help="Ratchets the stop up to highest_close_since_entry - "
            "multiple*ATR as a position gains, never back down. "
            "Mutually exclusive with the MAD trail stop to the right "
            "-- turning one on turns the other off.",
        )
        mad_stop_enabled = stop_c2.checkbox(
            "Use MAD Volatility Trail stop instead of ATR",
            key="admin_use_mad_stop",
            value=bool(cfg.get("mad_stop_enabled", False)),
            on_change=_on_toggle_admin_mad_stop,
            help="Replaces BOTH the initial and trailing ATR stop below "
            "with the MAD trail's own one-sided ratcheting lower band "
            "(median + MAD-scaled bands, ATR floor). A 5.6yr "
            "PDF-config backtest (regime filter ON) found the default "
            "params here raised CAGR 38.65%->40.37% and shrank max "
            "drawdown -30.67%->-28.81% at once, verified against this "
            "exact production engine -- verify against your own "
            "config in Backtest before relying on it live.",
        )

        with st.form("strategy_config_form"):
            st.markdown('<p class="ov-muted">Portfolio &amp; risk</p>', unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            max_positions = c1.number_input(
                "Portfolio size (max open positions)",
                min_value=1,
                max_value=50,
                value=int(cfg["max_positions"]),
                step=1,
            )
            risk_per_trade_pct = c2.number_input(
                "Risk per trade (% of capital)",
                min_value=0.1,
                max_value=10.0,
                value=float(cfg["risk_per_trade_pct"]),
                step=0.1,
            )
            atr_stop_multiple = c3.number_input(
                "Initial stop (× ATR)",
                min_value=0.5,
                max_value=10.0,
                value=float(cfg["atr_stop_multiple"]),
                step=0.1,
                disabled=mad_stop_enabled,
                help="Unused while the MAD trail stop is active above.",
            )

            st.markdown('<p class="ov-muted">Trailing stop</p>', unsafe_allow_html=True)
            trailing_atr_multiple = st.number_input(
                "Trailing stop (× ATR)",
                min_value=0.5,
                max_value=10.0,
                value=float(cfg["trailing_atr_multiple"]),
                step=0.1,
                disabled=not trailing_stop_enabled,
                help="Only used while 'Use ATR trailing stop' is checked above.",
            )

            mad_c1, mad_c2, mad_c3, mad_c4 = st.columns(4)
            mad_stop_med_len = mad_c1.number_input(
                "Median length",
                min_value=5,
                max_value=100,
                value=int(cfg.get("mad_stop_med_len", 21)),
                step=1,
                disabled=not mad_stop_enabled,
                help="Rolling window for the trail's median center line.",
            )
            mad_stop_mad_len = mad_c2.number_input(
                "MAD length",
                min_value=5,
                max_value=100,
                value=int(cfg.get("mad_stop_mad_len", 21)),
                step=1,
                disabled=not mad_stop_enabled,
                help="Rolling window for the median-absolute-deviation band width.",
            )
            mad_stop_dev_factor = mad_c3.number_input(
                "Deviation factor",
                min_value=0.5,
                max_value=5.0,
                value=float(cfg.get("mad_stop_dev_factor", 2.0)),
                step=0.1,
                disabled=not mad_stop_enabled,
                help="MAD band half-width multiplier -- wider band = looser stop.",
            )
            mad_stop_atr_floor_mult = mad_c4.number_input(
                "ATR floor ×",
                min_value=0.5,
                max_value=5.0,
                value=float(cfg.get("mad_stop_atr_floor_mult", 2.0)),
                step=0.1,
                disabled=not mad_stop_enabled,
                help="Floors the band width at this × ATR(14) so it never "
                "gets unrealistically tight in a low-volatility lull.",
            )

            st.markdown('<p class="ov-muted">Automation</p>', unsafe_allow_html=True)
            c4b, c4c, c4d = st.columns(3)
            auto_apply_stop_updates = c4b.checkbox(
                "Auto-apply trailing-stop ratchets",
                value=bool(cfg["auto_apply_stop_updates"]),
                help="Push a ratcheted stop straight to the real broker GTT as "
                "soon as it's computed, instead of waiting for a manual "
                "'Apply stop updates' click. Low-risk (only ever tightens "
                "an existing stop) -- on by default.",
            )
            auto_execute_trades = c4c.checkbox(
                "Auto-execute sells/buys/top-ups",
                value=bool(cfg["auto_execute_trades"]),
                help="Have the SCHEDULED daily rebalance job place proposed "
                "sells/buys/top-ups as real orders automatically, with no "
                "confirmation step (never affects the dashboard's manual "
                "'Run today's scan' button, which always stays "
                "review-first). Off by default -- this deploys new "
                "capital and exits real positions, so it's a deliberate "
                "opt-in once you trust the proposal quality.",
            )
            rebalance_cadence = c4d.segmented_control(
                "Rebalance cadence",
                ["daily", "weekly", "monthly"],
                default=cfg.get("rebalance_cadence", "daily"),
                key="admin_rebalance_cadence",
                help="How often the SELL/keep-zone decision is re-evaluated. "
                "'daily' checks every scheduled run; 'weekly' only on "
                "the last trading day of each ISO week (Friday, or the "
                "prior trading day if Friday is a market holiday); "
                "'monthly' only on the first trading day of each month "
                "-- both match backtest.py's own weekly/monthly "
                "rb_dates. Either way, new buys still fill any "
                "already-open slot the same day it opens -- only the "
                "sell decision is gated. Real 2016-2026 data + a "
                "5-seed synthetic test both found daily meaningfully "
                "reduces max drawdown (~-50% to ~-35% over 10 years) at "
                "a real but smaller cost to CAGR -- a priced trade-off, "
                "not a free win.",
            )

            st.markdown('<p class="ov-muted">Momentum &amp; trend</p>', unsafe_allow_html=True)
            c6, c7, c8 = st.columns(3)
            mom_lookback_days_short = c6.number_input(
                "Momentum lookback — short (days)",
                min_value=5,
                max_value=252,
                value=int(cfg["mom_lookback_days_short"]),
                step=1,
            )
            mom_lookback_days_long = c7.number_input(
                "Momentum lookback — long (days)",
                min_value=5,
                max_value=504,
                value=int(cfg["mom_lookback_days_long"]),
                step=1,
            )
            skip_recent_days = c8.number_input(
                "Skip most recent (days)", min_value=0, max_value=30, value=int(cfg["skip_recent_days"]), step=1
            )
            c9, c10, c11 = st.columns(3)
            near_high_threshold = c9.number_input(
                "52-week-high proximity (%)",
                min_value=50.0,
                max_value=100.0,
                value=float(cfg["near_high_threshold"]) * 100,
                step=1.0,
                help="Price must be at least this % of its 52-week high to qualify.",
            )
            ema_fast = c10.number_input("EMA (fast)", min_value=5, max_value=100, value=int(cfg["ema_fast"]), step=1)
            ema_slow = c11.number_input("EMA (slow)", min_value=50, max_value=400, value=int(cfg["ema_slow"]), step=1)

            st.markdown(
                '<p class="ov-muted">Momentum score weights (fixed, not configurable)</p>', unsafe_allow_html=True
            )
            st.caption(
                "Score = **0.40** × 6-month relative strength + **0.25** × "
                "3-month relative strength + **0.20** × 52-week-high "
                "proximity + **0.15** × volume expansion (20d avg volume ÷ "
                "60d avg volume) — each Z-scored across that day's universe "
                "before weighting. These four weights are hardcoded in "
                "`screener.score()`, the same function backtest.py and live "
                "both call — there's no slider for them here because there's "
                "nothing to save. The two tilts below (sector/fundamental "
                "bonus) are the only adjustable additions on top of this "
                "base score."
            )

            st.markdown('<p class="ov-muted">RSI</p>', unsafe_allow_html=True)
            c12, c13 = st.columns(2)
            rsi_min = c12.number_input("RSI min", min_value=0, max_value=100, value=int(cfg["rsi_min"]), step=1)
            rsi_max = c13.number_input("RSI max", min_value=0, max_value=100, value=int(cfg["rsi_max"]), step=1)
            c13b, c13c = st.columns([1, 1])
            rsi_exit_gate_enabled = c13b.checkbox(
                "Separate exit RSI ceiling",
                key="admin_use_rsi_exit_gate",
                value=bool(cfg.get("rsi_exit_gate_enabled", False)),
                help="OFF by default. When on, a held position whose only "
                "failing gate is the entry-band RSI max above stays "
                "held (instead of being force-sold) as long as RSI is "
                "still under the separate ceiling to the right -- lets "
                "a hot winner keep running instead of selling the "
                "moment it crosses the entry ceiling. Note: this exact "
                "idea was already A/B tested once and made every "
                "metric worse -- verify against current data in "
                "Backtest before relying on it live.",
            )
            rsi_exit_max = c13c.number_input(
                "Exit RSI ceiling",
                min_value=0.0,
                max_value=100.0,
                value=float(cfg.get("rsi_exit_max", cfg["rsi_max"])),
                step=1.0,
                format="%.2f",
            )
            weekly_monthly_gate_enabled = st.checkbox(
                "Weekly/monthly EMA trend gate",
                key="admin_use_wm_rsi_gate",
                value=bool(cfg.get("weekly_monthly_gate_enabled", False)),
                help="OFF by default. Extra entry gate on top of the daily "
                "checks above: weekly close must be above its own "
                "200-EMA, AND monthly close above its own 200-EMA "
                "(each falls back to a 50-EMA when there isn't enough "
                "resampled history for 200 yet). Needs deep (~16-year) "
                "history per symbol, fetched and cached the first time "
                "this is checked (slow, one-time). Untested -- verify "
                "in Backtest before relying on it live.",
            )

            st.markdown(
                '<p class="ov-muted">Fundamental gate &amp; sector bonus (opt-in features)</p>', unsafe_allow_html=True
            )
            fundamental_gate_enabled = st.checkbox(
                "Filter candidates on fundamental score (Live Rebalance + Screener)",
                value=bool(cfg["fundamental_gate_enabled"]),
                help="On by default (5-year A/B, equal-weight sizing, "
                "max_positions=10): trades ~2pp CAGR for a real ~4pp max "
                "drawdown reduction (-28.65%->-24.47%) — see config.py's "
                "comment for the full year-by-year breakdown. The "
                "fundamental score still shows for every candidate "
                "wherever fundamentals data is fetched regardless of this "
                "toggle, for your own reference.",
            )
            c15, c16, c17, c18 = st.columns(4)
            min_fundamental_score = c15.number_input(
                "Min fundamental score (0-100)",
                min_value=0.0,
                max_value=100.0,
                value=float(cfg["min_fundamental_score"]),
                step=1.0,
                help="Only enforced when the checkbox above is on.",
            )
            fundamental_bonus_weight = c16.number_input(
                "Fundamental score ranking tilt",
                min_value=0.0,
                max_value=2.0,
                value=float(cfg["fundamental_bonus_weight"]),
                step=0.1,
                help="0 = off (gate only, no ranking effect). 5-year A/B "
                "(equal-weight sizing, max_positions=10) found an "
                "inverted-U peaking near 0.5 -- CAGR 43.70%->43.03%, "
                "Sharpe 1.62->1.64, max drawdown -24.61%->-20.30%. "
                "Anything above 0.5 tested worse across the board.",
            )
            sector_bonus_weight = c17.number_input(
                "Sector bonus weight",
                min_value=0.0,
                max_value=1.0,
                value=float(cfg["sector_bonus_weight"]),
                step=0.05,
                help="0 = off (recommended). Re-tested with the equal-weight "
                "allocator specifically (0.5/1.0/2.0): loses on CAGR and "
                "Sharpe at every weight, AND drawdown gets worse too "
                "(-19.58%->-22 to -27%), so there's no risk/reward "
                "trade-off to make here, unlike the fundamental gate. "
                "See README's Sector relative-strength section.",
            )
            history_days = c18.number_input(
                "Candle history fetched (days)", min_value=300, max_value=3000, value=int(cfg["history_days"]), step=100
            )

            with st.expander("⚠️ Advanced / experimental (verify in Backtest first)", expanded=False):
                ew_c1, ew_c2 = st.columns([1, 1])
                advanced_equal_weight_sizing = ew_c1.checkbox(
                    "Equal-weight allocator",
                    key="admin_use_equal_weight",
                    value=bool(cfg["advanced_equal_weight_sizing"]),
                    help="LIVE default is ON. Sizes the whole day's buys in "
                    "one pass -- cross-slot borrowing within tolerance, "
                    "partial fill on shortfall, hard-stop-not-"
                    "substitute, top-up of under-target holdings -- "
                    "instead of one-symbol-at-a-time greedy sizing.",
                )
                equal_weight_tolerance_pct = ew_c2.number_input(
                    "Tolerance",
                    min_value=0.0,
                    max_value=1.0,
                    value=float(cfg["equal_weight_tolerance_pct"]),
                    step=0.01,
                    format="%.2f",
                    help="A 5-year A/B found 0.20 (the live default) beats "
                    "the original one-at-a-time fill on every metric "
                    "at once.",
                )
                capital_equal_weight_sizing = st.checkbox(
                    "Capital-weighted sizing (uncheck for risk-based)",
                    key="admin_use_capital_equal_weight",
                    value=bool(cfg.get("capital_equal_weight_sizing", True)),
                    help="ON by default -- sizes each position off capital/"
                    "portfolio value (the allocator above, or the "
                    "one-at-a-time fallback when it's off). Uncheck to "
                    "size off risk instead: risk_per_trade_pct of "
                    "capital, position width = (entry - stop) -- can "
                    "come out arbitrarily small on modest capital "
                    "combined with a wide ATR stop. Verify in Backtest "
                    "before switching this live.",
                )

                sd_c1, sd_c2, sd_c3 = st.columns([1, 1, 1])
                sector_diversification_enabled = sd_c1.checkbox(
                    "Sector diversification cap",
                    key="admin_use_sector_diversification",
                    value=bool(cfg.get("sector_diversification_enabled", False)),
                    help="OFF by default. Hard constraint: a stock only "
                    "qualifies if its best-matching sector GROUP is "
                    "currently among the top N strongest (right), AND "
                    "no single group can hold more than the position "
                    "cap (right) at once -- enforced at buy time, "
                    "never forces an exit. Untested -- verify in "
                    "Backtest before relying on it live.",
                )
                top_n_sectors = sd_c2.number_input(
                    "Top N sectors", min_value=1, max_value=10, value=int(cfg.get("top_n_sectors", 3)), step=1
                )
                max_positions_per_sector = sd_c3.number_input(
                    "Max positions / sector",
                    min_value=1,
                    max_value=10,
                    value=int(cfg.get("max_positions_per_sector", 3)),
                    step=1,
                )
                sector_composite_score_enabled = st.checkbox(
                    "Use composite sector score (RS + 52w-high + breadth) instead of RS alone",
                    key="admin_use_sector_composite",
                    value=bool(cfg.get("sector_composite_score_enabled", False)),
                    help="Only affects which sectors count as 'top N' "
                    "above -- OFF ranks sectors on relative strength "
                    "alone; ON blends in 52-week-high proximity and "
                    "breadth too. Untested -- A/B against RS-alone in "
                    "Backtest first.",
                )

                resistance_zone_weight = st.number_input(
                    "Resistance zone weight",
                    min_value=0.0,
                    max_value=1.0,
                    value=float(cfg.get("resistance_zone_weight", 0.0)),
                    step=0.05,
                    help="0 = off. Tilts ranking toward stocks with more "
                    "clean room before the nearest strong multi-year "
                    "price zone above them. Untested -- verify in "
                    "Backtest before relying on it live.",
                )

                rg_c1, rg_c2 = st.columns(2)
                regime_filter_enabled = rg_c1.checkbox(
                    "Market regime filter",
                    key="admin_use_regime_filter",
                    value=bool(cfg.get("regime_filter_enabled", False)),
                    help="OFF by default. When NIFTY 50's own close is "
                    "below its 200 EMA, caps how many NEW positions "
                    "may open to max_positions x the multiplier "
                    "(right) -- never force-sells an existing "
                    "position purely because the regime flipped. A "
                    "real 5-year A/B improved every headline metric "
                    "at once, but wasn't uniform year to year -- "
                    "verify against your own fuller config before "
                    "relying on it live.",
                )
                regime_position_multiplier = rg_c2.number_input(
                    "Regime position multiplier",
                    min_value=0.1,
                    max_value=1.0,
                    value=float(cfg.get("regime_position_multiplier", 0.5)),
                    step=0.05,
                    help="Fraction of max_positions allowed while NIFTY is below its 200 EMA.",
                )

                cf_c1, cf_c2 = st.columns(2)
                entry_confirm_days = cf_c1.number_input(
                    "Entry confirmation (consecutive rebalance events)",
                    min_value=0,
                    max_value=10,
                    value=int(cfg.get("entry_confirm_days", 0) or 0),
                    step=1,
                    key="admin_entry_confirm_days",
                    help="0 = OFF (default). Requires a stock to have "
                    "stayed in the confirm-pool (right) for this many "
                    "CONSECUTIVE rebalance events before a NEW buy is "
                    "allowed. TESTED AND NOT RECOMMENDED: a 5.6yr "
                    "PDF-style config backtest found 0 -> 2 made every "
                    "headline metric worse at once. Left here as a "
                    "re-testable toggle, not because it's expected to "
                    "help.",
                )
                entry_confirm_pool_size = cf_c2.number_input(
                    "Confirm-pool size",
                    min_value=1,
                    max_value=100,
                    value=int(cfg.get("entry_confirm_pool_size") or (int(max_positions) * 2)),
                    step=1,
                    key="admin_entry_confirm_pool_size",
                    help="How many top-scored candidates count as the "
                    "confirm-pool each rebalance -- defaults to 2x "
                    "portfolio size.",
                )

            strategy_submitted = st.form_submit_button("Save strategy settings", type="primary")

        if strategy_submitted:
            updates = {
                "max_positions": int(max_positions),
                "risk_per_trade_pct": float(risk_per_trade_pct),
                "atr_stop_multiple": float(atr_stop_multiple),
                "trailing_stop_enabled": bool(trailing_stop_enabled),
                "trailing_atr_multiple": float(trailing_atr_multiple),
                "auto_apply_stop_updates": bool(auto_apply_stop_updates),
                "auto_execute_trades": bool(auto_execute_trades),
                "rebalance_cadence": rebalance_cadence,
                "mom_lookback_days_short": int(mom_lookback_days_short),
                "mom_lookback_days_long": int(mom_lookback_days_long),
                "skip_recent_days": int(skip_recent_days),
                "near_high_threshold": float(near_high_threshold) / 100,
                "ema_fast": int(ema_fast),
                "ema_slow": int(ema_slow),
                "rsi_min": int(rsi_min),
                "rsi_max": int(rsi_max),
                "fundamental_gate_enabled": bool(fundamental_gate_enabled),
                "min_fundamental_score": float(min_fundamental_score),
                "fundamental_bonus_weight": float(fundamental_bonus_weight),
                "sector_bonus_weight": float(sector_bonus_weight),
                "history_days": int(history_days),
                "mad_stop_enabled": bool(mad_stop_enabled),
                "mad_stop_med_len": int(mad_stop_med_len),
                "mad_stop_mad_len": int(mad_stop_mad_len),
                "mad_stop_dev_factor": float(mad_stop_dev_factor),
                "mad_stop_atr_floor_mult": float(mad_stop_atr_floor_mult),
                "rsi_exit_gate_enabled": bool(rsi_exit_gate_enabled),
                "rsi_exit_max": float(rsi_exit_max),
                "weekly_monthly_gate_enabled": bool(weekly_monthly_gate_enabled),
                "advanced_equal_weight_sizing": bool(advanced_equal_weight_sizing),
                "capital_equal_weight_sizing": bool(capital_equal_weight_sizing),
                "equal_weight_tolerance_pct": float(equal_weight_tolerance_pct),
                "sector_diversification_enabled": bool(sector_diversification_enabled),
                "top_n_sectors": int(top_n_sectors),
                "max_positions_per_sector": int(max_positions_per_sector),
                "sector_composite_score_enabled": bool(sector_composite_score_enabled),
                "resistance_zone_weight": float(resistance_zone_weight),
                "regime_filter_enabled": bool(regime_filter_enabled),
                "regime_position_multiplier": float(regime_position_multiplier),
                "entry_confirm_days": int(entry_confirm_days),
                "entry_confirm_pool_size": int(entry_confirm_pool_size),
            }
            # Keeps this form honest against config.ADMIN_EDITABLE_KEYS -- if
            # a new field is added to the form without adding its key here
            # (or vice versa), this trips instead of the two silently
            # drifting apart.
            assert set(updates.keys()) == set(config.ADMIN_EDITABLE_KEYS), set(updates.keys()) ^ set(
                config.ADMIN_EDITABLE_KEYS
            )
            state_db.update_strategy_config(updates)
            config.STRATEGY.update(updates)  # live for this process -- no restart needed
            st.success("Strategy settings saved — in effect immediately.")

    st.markdown(
        '<p class="ov-card-title" style="margin-top:14px;"><span class="ov-dot" '
        'style="background:var(--ov-red);"></span>⚡ Intraday strategy (DaysLowVolumnBreakout)</p>',
        unsafe_allow_html=True,
    )
    with st.container(border=True, key="ov-card-admin-intraday"):
        st.caption(
            "Completely separate from the swing/momentum settings above -- "
            "its own capital tracks, its own live/paper switch. Paper mode "
            "(the default) simulates every fill with zero real orders. "
            "This checkbox is the ONLY thing intraday_engine.py's plain "
            "`python intraday_engine.py` (no flags) checks to decide which "
            "mode to trade in -- so a scheduled daily launch auto-trades "
            "live starting the very next run after you save this on, with "
            "no per-day manual step. A paper-mode engine process already "
            "running does not hot-swap -- it must be restarted to pick up "
            "a change here."
        )
        _live_cap_row = idb.get_capital("live")
        _paper_cap_row = idb.get_capital("paper")
        with st.form("intraday_strategy_form"):
            ic1, ic2, ic3 = st.columns(3)
            intraday_live_enabled = ic1.checkbox(
                "Enable live intraday trading",
                value=bool(config.STRATEGY.get("intraday_live_enabled", False)),
                help="OFF by default. Places real MIS (5x leveraged) intraday "
                "orders starting the next time the engine is (re)started -- "
                "a materially different risk profile from the CNC swing "
                "book already running live. Only flip this on once "
                "you've watched paper mode work correctly for real "
                "trading days.",
            )
            intraday_live_capital = ic2.number_input(
                "Live capital allocation (₹)",
                min_value=0.0,
                step=10_000.0,
                value=float(_live_cap_row["starting_capital"])
                if _live_cap_row
                else float(config.STRATEGY.get("intraday_live_capital", 1_000_000.0)),
                disabled=_live_cap_row is not None,
                help=(
                    "Already seeded at ₹{:,.0f} the first time live mode ran -- "
                    "editing this field no longer has any effect, so a save "
                    "here can never silently reset an already-compounding "
                    "live account.".format(_live_cap_row["starting_capital"])
                    if _live_cap_row
                    else "Seeded as the live track's starting capital the FIRST "
                    "time live mode actually runs (intraday_capital_state, "
                    "mode='live') -- separate from the paper track's "
                    "capital and from the swing book's cash. Change this "
                    "before going live for the first time; it has no "
                    "effect afterward."
                ),
            )
            intraday_paper_capital = ic3.number_input(
                "Paper capital allocation (₹)",
                min_value=0.0,
                step=10_000.0,
                value=float(_paper_cap_row["starting_capital"])
                if _paper_cap_row
                else float(config.STRATEGY.get("intraday_paper_capital", 1_000_000.0)),
                disabled=_paper_cap_row is not None,
                help=(
                    "Already seeded at ₹{:,.0f} the first time paper mode ran -- "
                    "editing this field no longer has any effect.".format(_paper_cap_row["starting_capital"])
                    if _paper_cap_row
                    else "Same idea as the live field, for the paper track "
                    "(intraday_capital_state, mode='paper') -- only takes "
                    "effect before paper mode has ever run."
                ),
            )
            intraday_submitted = st.form_submit_button("Save intraday settings", type="primary")
        if intraday_submitted:
            idb.ensure_capital_seeded("live", float(intraday_live_capital))
            idb.ensure_capital_seeded("paper", float(intraday_paper_capital))
            intraday_updates = {
                "intraday_live_enabled": bool(intraday_live_enabled),
                "intraday_live_capital": float(intraday_live_capital),
                "intraday_paper_capital": float(intraday_paper_capital),
            }
            state_db.update_strategy_config(intraday_updates)
            config.STRATEGY.update(intraday_updates)
            st.success("Intraday settings saved — in effect immediately.")

    st.markdown(
        '<p class="ov-card-title" style="margin-top:14px;"><span class="ov-dot" '
        'style="background:var(--ov-blue);"></span>🔔 Push notifications</p>',
        unsafe_allow_html=True,
    )
    with st.container(border=True, key="ov-card-admin-push"):
        _n_subs = len(state_db.get_push_subscriptions())
        if not notify.VAPID_PUBLIC_KEY:
            st.caption(
                "Not configured -- set VAPID_PRIVATE_KEY/VAPID_PUBLIC_KEY "
                "in .env to enable this (see notify.py's docstring for "
                "how to generate a keypair)."
            )
        else:
            st.caption(
                f"{_n_subs} device(s) currently subscribed. Alerts fire "
                "when today's Kite session expires and needs a fresh "
                "login (the daily ~07:00 check, or any scheduled job "
                "that hits it mid-run), and after every scheduled "
                "rebalance completes. Click below on every phone or "
                "laptop browser you want alerted."
            )
            pb1, pb2 = st.columns(2)
            if pb1.button("Enable notifications on this device"):
                st.html(
                    f"""
<script>
(async () => {{
  try {{
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {{
      alert('Push notifications are not supported in this browser.');
      return;
    }}
    function urlBase64ToUint8Array(base64String) {{
      const padding = '='.repeat((4 - base64String.length % 4) % 4);
      const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
      const rawData = window.atob(base64);
      const arr = new Uint8Array(rawData.length);
      for (let i = 0; i < rawData.length; ++i) arr[i] = rawData.charCodeAt(i);
      return arr;
    }}
    const reg = await navigator.serviceWorker.register('/app/static/sw.js');
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') {{ alert('Notification permission was not granted.'); return; }}
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {{
      sub = await reg.pushManager.subscribe({{
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array('{notify.VAPID_PUBLIC_KEY}')
      }});
    }}
    const pushServerUrl = 'https://' + window.location.hostname + ':{notify.PUSH_SERVER_PORT}';
    const resp = await fetch(pushServerUrl + '/subscribe', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(sub.toJSON())
    }});
    alert(resp.ok ? 'Notifications enabled on this device.'
                  : 'Could not save the subscription (server error). Try again in a moment.');
  }} catch (e) {{
    alert('Failed to enable notifications: ' + e.message);
  }}
}})();
</script>
""",
                    unsafe_allow_javascript=True,
                )
            if pb2.button("Send test notification", disabled=_n_subs == 0):
                _dead = notify.send_webpush_all(
                    state_db.get_push_subscriptions(),
                    "KK Trading -- test notification",
                    "If you see this, browser push is wired up correctly.",
                    notify.DASHBOARD_URL,
                )
                for _d in _dead:
                    state_db.delete_push_subscription(_d)
                st.success(
                    f"Sent to {_n_subs - len(_dead)} device(s)."
                    + (f" Removed {len(_dead)} dead subscription(s)." if _dead else "")
                )

    _skip_tip = html_lib.escape(
        "Manually excluded symbols are removed from config.UNIVERSE — the "
        "shared candidate list the Screener, Live Rebalance, and "
        "backtest.py all fetch candles for. Tick/untick Skip, optionally "
        "edit the reason, then click Update — nothing changes until you do."
    )
    st.markdown(
        '<p class="ov-card-title" style="margin-top:14px;"><span class="ov-dot" '
        'style="background:var(--ov-coral);"></span>🚫 Skip stocks from scanner'
        f'<span class="ov-info-icon" title="{_skip_tip}">ℹ️</span>'
        '<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
        "Removed from the shared universe everywhere at once</span></p>",
        unsafe_allow_html=True,
    )
    with st.container(border=True, key="ov-card-admin-skip"):
        _skipped_df = state_db.get_skipped_symbols_df()
        skipped_reasons = _skipped_df.set_index("symbol")["reason"] if not _skipped_df.empty else pd.Series(dtype=str)
        all_syms_for_skip = sorted(set(config.UNIVERSE_RAW) | set(skipped_reasons.index))

        st.markdown('<p class="ov-muted">Skip / un-skip a symbol</p>', unsafe_allow_html=True)
        skip_sym = st.selectbox("Symbol", all_syms_for_skip, key="admin_skip_sym_sel")
        skip_checked = skip_sym in skipped_reasons.index
        with st.form(f"admin_skip_form_{skip_sym}"):
            skip_toggle = st.checkbox("Skip this symbol", value=skip_checked)
            skip_reason = st.text_input("Reason (optional)", value=skipped_reasons.get(skip_sym, ""))
            skip_save_clicked = st.form_submit_button("Save", type="primary")
        if skip_save_clicked:
            if skip_toggle:
                state_db.add_skipped_symbol(skip_sym, skip_reason)
            elif skip_checked:
                state_db.remove_skipped_symbol(skip_sym)
            config.refresh_universe()
            st.success(f"{skip_sym} updated — in effect immediately.")
            st.rerun()

        st.divider()
        skip_filter = st.radio(
            "Show",
            ["All", "Skipped only", "Not skipped"],
            horizontal=True,
            key="admin_skip_filter",
            label_visibility="collapsed",
        )

        try:
            skip_prices = kite_client.get_ltp(all_syms_for_skip)
        except Exception as e:
            st.warning(f"Couldn't fetch live prices: {e}")
            skip_prices = {}

        skip_table = pd.DataFrame(
            {
                "symbol": all_syms_for_skip,
                "price": [skip_prices.get(s) for s in all_syms_for_skip],
                "skip": ["✓" if s in skipped_reasons.index else "✗" for s in all_syms_for_skip],
                "reason": [skipped_reasons.get(s, "") or "—" for s in all_syms_for_skip],
            }
        )
        if skip_filter == "Skipped only":
            skip_table = skip_table[skip_table["skip"] == "✓"]
        elif skip_filter == "Not skipped":
            skip_table = skip_table[skip_table["skip"] == "✗"]
        skip_page = _ov_page_slice(skip_table, key="admin_skip")
        st.markdown(
            _ov_table_html(
                skip_page,
                columns=["symbol", "price", "skip", "reason"],
                sym_cols=["symbol"],
                num_fmt={"price": "₹{:,.2f}"},
                badges={"skip": {"✓": "ov-badge-red", "✗": "ov-badge-gray"}},
            ),
            unsafe_allow_html=True,
        )
        _ov_pagination_controls(skip_table, key="admin_skip")

    col_pw, col_api = st.columns(2)
    with col_pw, st.container(border=True, key="ov-card-admin-password"):
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" '
            'style="background:var(--ov-amber);"></span>🔑 Change dashboard password</p>',
            unsafe_allow_html=True,
        )
        st.caption("Stored as a salted hash in state.db — the password itself is never saved anywhere, not even here.")
        with st.form("change_password_form", clear_on_submit=True):
            new_user = st.text_input("Username", value=config.DASHBOARD_USERNAME)
            new_pw = st.text_input("New password", type="password")
            confirm_pw = st.text_input("Confirm new password", type="password")
            change_submitted = st.form_submit_button("Update credentials", type="primary")
        if change_submitted:
            if not new_user or not new_pw:
                st.error("Username and password can't be empty.")
            elif new_pw != confirm_pw:
                st.error("Passwords don't match.")
            else:
                state_db.update_dashboard_password(new_user, new_pw)
                st.success("Credentials updated — use the new username/password next time you sign in.")

    with col_api, st.container(border=True, key="ov-card-admin-kite"):
        _kite_tip = html_lib.escape(
            "Stored in state.db, not .env — only needed if you regenerate "
            "keys in the Kite developer console. Unlike the dashboard "
            "password, these are kept plaintext (Kite's own login flow "
            "needs the real api_secret value back), so this is a "
            "convenience move, not a security upgrade."
        )
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" '
            'style="background:var(--ov-blue);"></span>🔑 Kite API settings'
            f'<span class="ov-info-icon" title="{_kite_tip}">ℹ️</span></p>',
            unsafe_allow_html=True,
        )
        masked_key = (
            config.KITE_API_KEY[:4] + "…" + config.KITE_API_KEY[-4:] if len(config.KITE_API_KEY) > 8 else "(not set)"
        )
        st.caption(f"Current API key: `{masked_key}` · stored in state.db, only needed after regenerating keys.")
        with st.form("kite_api_settings_form", clear_on_submit=True):
            new_api_key = st.text_input("New API key (blank = keep current)")
            new_api_secret = st.text_input("New API secret (blank = keep current)", type="password")
            api_submitted = st.form_submit_button("Update Kite API credentials", type="primary")
        if api_submitted:
            if not new_api_key and not new_api_secret:
                st.error("Enter at least one value to update.")
            else:
                state_db.update_kite_api_credentials(
                    new_api_key or config.KITE_API_KEY, new_api_secret or config.KITE_API_SECRET
                )
                st.success("Kite API credentials updated — restart the dashboard for this process to pick them up.")


# ---------------------------------------------------------------------------
# Page: Screener
# ---------------------------------------------------------------------------


def page_screener():
    _screener_tip = html_lib.escape(
        "Every F&O stock passing the technical gates (trend structure, "
        "52-week-high proximity, RSI regime) and the fundamental quality "
        "gate, ranked by momentum score. This is the broader browse/chart "
        "view; Live Rebalance shows only what actually fits your open "
        "position slots."
    )
    hdr_l, hdr_r = st.columns([2, 2])
    with hdr_l:
        st.markdown(
            '<div class="ov-header" style="margin-bottom:0;">'
            '<div><span class="ov-h1">🔍 Screener</span> '
            '<span class="ov-sub">· full ranked universe</span>'
            f'<span class="ov-info-icon" title="{_screener_tip}">ℹ️</span></div></div>',
            unsafe_allow_html=True,
        )

    if "screen" not in st.session_state and os.path.exists(SCREEN_CACHE):
        st.session_state["screen"] = pd.read_pickle(SCREEN_CACHE)
        st.session_state["screen_time"] = dt.datetime.fromtimestamp(os.path.getmtime(SCREEN_CACHE))
        st.session_state["screen_is_cached"] = True

    def _run_and_cache_screen(with_fund, fundamentals, progress_cb):
        result = screener.run_screen(with_fund, fundamentals=fundamentals, progress_cb=progress_cb)
        os.makedirs("cache", exist_ok=True)
        result.to_pickle(SCREEN_CACHE)
        return result

    screen_job = get_background_job("screen_run")
    screen_running = screen_job is not None and not screen_job["done"]

    with hdr_r, st.container(key="screen_run_row"):
        with_fund = st.checkbox(
            "Fetch fundamental score",
            value=True,
            help="Shows each candidate's fundamental score/sector rubric for "
            "reference (uses the Fundamentals page's primary-XBRL score, "
            "reusing the on-disk cache if present rather than re-scanning "
            "NSE). Whether it also FILTERS candidates is a separate "
            "toggle — see Admin → Strategy configuration → 'Filter "
            "candidates on fundamental score' (off by default).",
        )
        if st.button("Run screen", type="primary", disabled=screen_running):
            start_background_job(
                "screen_run",
                _run_and_cache_screen,
                with_fund,
                st.session_state.get("value_scores"),
                job_type="screen_run",
                summarize_fn=lambda r: f"{len(r)} candidates",
            )
            st.rerun()
    if screen_running:
        st.info(f"⏳ Scan running since {screen_job['started_at']:%H:%M:%S} — safe to switch tabs.")

    @st.fragment(run_every="1s" if screen_running else None)
    def _screen_job_status():
        job = get_background_job("screen_run")
        if job is None:
            return
        if not job["done"]:
            frac, stage = job["progress"]
            st.progress(
                frac, text=f"{stage} — started {job['started_at']:%H:%M:%S}, keeps running even if you switch tabs"
            )
            return
        if job["error"]:
            st.error(f"Scan failed: {job['error']}")
        else:
            st.session_state["screen"] = job["result"]
            st.session_state["screen_time"] = dt.datetime.now()
            st.session_state["screen_is_cached"] = False
        clear_background_job("screen_run")
        st.rerun()

    _screen_job_status()

    if "screen" not in st.session_state:
        st.info("Click **Run screen** to fetch Kite data and rank the universe.")
        return

    t: pd.DataFrame = st.session_state["screen"]
    cached_note = " 📁 (from cache — click Run screen to refresh)" if st.session_state.get("screen_is_cached") else ""
    st.caption(f"Last run: {st.session_state['screen_time']:%d %b %Y %H:%M}{cached_note}")

    candidates = t[t["all_gates"]].copy()  # already sorted by score, descending
    candidates.insert(0, "rank", range(1, len(candidates) + 1))
    show_cols = [
        "rank",
        "score",
        "price",
        "rs_3m",
        "rs_6m",
        "pct_52w_high",
        "rsi",
        "vol_expansion",
        "avg_volume_3m",
        "atr_pct",
        "suggested_stop",
        "fundamental_score",
        "fundamental_rubric",
    ]
    show_cols = [c for c in show_cols if c in candidates.columns]
    if "fundamental_score" not in t.columns:
        # apply_gates() only attaches these two columns at all when it was
        # given non-empty fundamentals -- silently absent otherwise, which
        # used to look like a bug rather than a consequence of the checkbox
        # (or this exact result being cached from a run where it was off).
        st.caption(
            "ℹ️ No fundamental score column — this result was scanned "
            "with **Include fundamental quality gate** off, or "
            "fundamentals data wasn't available at scan time. Check the "
            "box above and click **Run screen** again to include it."
        )
    if "avg_volume_3m" not in candidates.columns:
        st.caption(
            "ℹ️ No 3M Avg Volume column — this result is from a cached "
            "scan run before this metric was added. Click **Run screen** "
            "again to include it."
        )
    # fundamental_rubric is a string column ("general"/"nbfc"/...), rank is
    # already a plain int, and avg_volume_3m is a whole-share-count that
    # reads better with thousands separators than 2 decimals -- a single
    # global "{:.2f}" format spec would crash on the first and look wrong
    # on the other two.
    num_fmt = {c: "{:.2f}" for c in show_cols if c not in ("fundamental_rubric", "rank", "avg_volume_3m")}
    if "avg_volume_3m" in show_cols:
        num_fmt["avg_volume_3m"] = "{:,.0f}"

    keep_zone_size = config.STRATEGY["max_positions"] * 2
    _candidates_tip = html_lib.escape(
        f"Sorted by score, highest first — Live Rebalance keeps a held "
        f"position only while it's ranked in the top {keep_zone_size} "
        f"here (max_positions × 2); dropping below that rank is what "
        f"triggers a proposed sell."
    )
    with st.container(border=True, key="ov-card-screen-candidates"):
        st.markdown(
            '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
            '<span class="ov-dot" style="background:var(--ov-green);">'
            f'</span>Candidates passing all gates <span class="ov-badge ov-badge-green">'
            f"{len(candidates)}</span>"
            f'<span class="ov-info-icon" title="{_candidates_tip}">ℹ️</span></p>',
            unsafe_allow_html=True,
        )
        cand_display = candidates[show_cols].copy()
        cand_display.insert(0, "symbol", cand_display.index)
        cand_display["rank"] = cand_display["rank"].astype(int)
        cand_page = _ov_page_slice(cand_display, key="screen_candidates")
        st.markdown(
            _ov_table_html(
                cand_page,
                columns=["rank", "symbol"] + [c for c in show_cols if c != "rank"],
                sym_cols=["symbol"],
                num_fmt={**num_fmt, "rank": "{:.0f}"},
                badges={"rank": lambda v: "ov-badge-green" if v <= keep_zone_size else "ov-badge-red"},
            ),
            unsafe_allow_html=True,
        )
        _ov_pagination_controls(cand_display, key="screen_candidates")

    with st.expander("Full universe (including gate failures)"):
        gate_cols = ["trend_ok", "near_high_ok", "rsi_ok", "quality_ok", "quality_fails"]
        all_cols = gate_cols + show_cols
        all_cols = [c for c in all_cols if c in t.columns and c != "rank"]
        full_display = t[all_cols].copy()
        full_display.insert(0, "symbol", full_display.index)
        # ✓/✗ pill badges instead of literal "True"/"False" text, matching
        # the mockup.
        for c in ("trend_ok", "near_high_ok", "rsi_ok", "quality_ok"):
            if c in full_display.columns:
                full_display[c] = full_display[c].map({True: "✓", False: "✗"})
        _bool_badges = {
            c: {"✓": "ov-badge-green", "✗": "ov-badge-red"}
            for c in ("trend_ok", "near_high_ok", "rsi_ok", "quality_ok")
            if c in all_cols
        }
        full_page = _ov_page_slice(full_display, key="screen_full_universe")
        st.markdown(
            _ov_table_html(full_page, sym_cols=["symbol"], num_fmt=num_fmt, badges=_bool_badges), unsafe_allow_html=True
        )
        _ov_pagination_controls(full_display, key="screen_full_universe")

    with st.container(border=True, key="ov-card-screen-chart"):
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" '
            'style="background:var(--ov-purple);"></span>Chart a symbol</p>',
            unsafe_allow_html=True,
        )
        sym = st.selectbox("Chart a symbol", list(t.index), label_visibility="collapsed")
        if sym:
            df = kite_client.fetch_daily_candles(sym, days=config.STRATEGY["history_days"])
            if not df.empty:
                cfg = config.STRATEGY
                fig = go.Figure()
                fig.add_trace(
                    go.Candlestick(
                        x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"], name=sym
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=df.index, y=indicators.ema(df["close"], cfg["ema_fast"]), name="EMA50", line={"width": 1}
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=df.index, y=indicators.ema(df["close"], cfg["ema_slow"]), name="EMA200", line={"width": 1}
                    )
                )
                fig.update_layout(
                    height=500, xaxis_rangeslider_visible=False, margin={"l": 10, "r": 10, "t": 30, "b": 10}
                )
                st.plotly_chart(fig, width="stretch")

    with st.expander("🏭 Current sector rankings"):
        st.caption(
            "Today's relative strength (vs NIFTY 50, same lookback as the "
            "6-month momentum score) for every tracked sector index — "
            "separate from the Backtest page's sector bonus, this is just "
            "for browsing which sectors are currently strong. Own button "
            "since it needs its own ~35 index fetches on top of the "
            "candles already fetched by Run screen."
        )
        if st.button("Fetch current sector rankings"):
            with st.spinner("Fetching sector membership + index history..."):
                days = config.STRATEGY["history_days"]
                _membership, sector_candles = su.sector_membership_and_candles(config.UNIVERSE, days=days)
                bench_sec = kite_client.benchmark_candles(days)
                rank = su.sector_rs_asof(
                    sector_candles, bench_sec, dt.date.today(), config.STRATEGY["sector_rs_lookback_days"]
                )
            st.session_state["sector_rank"] = rank
            st.session_state["sector_rank_time"] = dt.datetime.now()
        if "sector_rank" in st.session_state:
            rt = st.session_state["sector_rank_time"]
            st.caption(f"Last fetched: {rt:%d %b %Y %H:%M}")
            _rank_series = st.session_state["sector_rank"].sort_values(ascending=False)
            _max_abs = float(_rank_series.abs().max()) or 1.0
            _sector_rows = []
            for _sector, _val in _rank_series.items():
                _pct_width = min(100.0, abs(_val) / _max_abs * 100)
                _color = "#1d9e75" if _val >= 0 else "#e24b4a"
                _cls = "ov-pos" if _val >= 0 else "ov-neg"
                _sector_rows.append(
                    f'<div class="ov-sector-row"><div class="ov-sector-head">'
                    f"<span>{html_lib.escape(str(_sector))}</span>"
                    f'<span class="ov-sym {_cls}">{_val:+.1f}</span></div>'
                    f'<div class="ov-sector-bar"><div class="ov-sector-fill" '
                    f'style="width:{_pct_width:.1f}%;background:{_color};"></div></div></div>'
                )
            st.markdown("".join(_sector_rows), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Page: Live Rebalance
# ---------------------------------------------------------------------------


def _with_day_item_status(result: dict) -> dict:
    """Overlays result's sells/buys/top_ups/stop_updates with EVERY item
    from EVERY run on the SAME CALENDAR DAY as result['run_time'] -- not
    just the single run_id that produced/loaded this result -- so the
    Proposed sells/buys/top-ups/stop-updates sections on the Live
    Rebalance page show the full day's activity (e.g. an early auto-
    execute run followed by a later manual re-scan that found nothing
    new) with each row's real status, instead of only the latest run in
    isolation and instead of executed/error/expired items silently
    disappearing. See get_rebalance_day_items(). Safe to call right after
    a fresh scan too: propose_rebalance() already persists via
    save_rebalance_run() before returning, so the DB is authoritative by
    the time this runs. Trade-off: loses any column that only ever
    existed in the in-memory propose_rebalance() result and was never
    persisted (e.g. 'rank') -- the buys table already degrades
    gracefully for that (builds its column list from whatever's actually
    present)."""
    run_time = result.get("run_time")
    if run_time is None:
        return result
    date_str = run_time.date().isoformat() if hasattr(run_time, "date") else str(run_time)[:10]
    result.update(state_db.get_rebalance_day_items(date_str))
    return result


def page_live_rebalance():
    auto_exec = bool(config.STRATEGY.get("auto_execute_trades", False))
    rebalance_job = get_background_job("rebalance_run")
    rebalance_running = rebalance_job is not None and not rebalance_job["done"]

    def _run_scan_now():
        fundamentals = st.session_state.get("value_scores")
        start_background_job(
            "rebalance_run",
            lr.propose_rebalance,
            available_cash,
            fundamentals=fundamentals,
            job_type="rebalance_scan",
            summarize_fn=lambda r: (
                f"{len(r['buys'])} buys, {len(r['sells'])} sells, {len(r['stop_updates'])} stop updates"
            ),
        )
        st.rerun()

    # Auto-execute mode still shows its status chip in the header (the
    # scan button stays further down as the manual-override path). Manual
    # mode drops the "Manual mode — review-first" label entirely and puts
    # the actual "Run today's scan" button in the header instead, since
    # that's the one thing this page's whole title bar exists to trigger.
    if auto_exec:
        _auto_exec_tip = html_lib.escape(
            "auto_execute_trades is ON — the scheduled daily scan places "
            "these sells/buys/top-ups as real orders automatically, with no "
            "confirmation step. The buttons below still work as a manual "
            "override for whatever's left (e.g. a manual 'Run today's scan'). "
            "Turn this off in Admin → Strategy configuration to go back to "
            "manual-only."
        )
        _hdr_l, _hdr_r = st.columns([5, 2])
        with _hdr_l:
            st.markdown(
                '<div class="ov-header" style="margin-bottom:0;">'
                '<div><span class="ov-h1">📡 Live Rebalance</span> '
                '<span class="ov-sub">· review, then execute</span></div>'
                "</div>",
                unsafe_allow_html=True,
            )
        with _hdr_r, st.container(key="lr_autoexec_header_row"):
            st.markdown(
                f'<span class="ov-info-icon" title="{_auto_exec_tip}">ℹ️</span>'
                '<span class="ov-chip ov-chip-amber">⚠ Auto-execute ON</span>',
                unsafe_allow_html=True,
            )
            if st.button("Run today's scan", type="primary", disabled=rebalance_running, key="lr_run_scan_autoexec"):
                _run_scan_now()
    else:
        _hdr_l, _hdr_r = st.columns([5, 2])
        with _hdr_l:
            st.markdown(
                '<div class="ov-header" style="margin-bottom:0;">'
                '<div><span class="ov-h1">📡 Live Rebalance</span> '
                '<span class="ov-sub">· review, then execute</span></div>'
                "</div>",
                unsafe_allow_html=True,
            )
        with _hdr_r:
            if st.button("Run today's scan", type="primary", disabled=rebalance_running, key="lr_run_scan_hdr"):
                _run_scan_now()

    if "rebalance_proposal" not in st.session_state:
        last_run = state_db.get_last_rebalance_run()
        if last_run is not None:
            # holdings is never persisted (see state_db.get_last_rebalance_run
            # -- it's a live snapshot, not historical), so always re-fetch it
            # fresh here regardless of when the underlying proposal ran.
            last_run["holdings"] = lr.get_live_holdings().reset_index().rename(columns={"tradingsymbol": "symbol"})
            st.session_state["rebalance_proposal"] = _with_day_item_status(last_run)

    if rebalance_running:
        st.info(f"⏳ Scan running since {rebalance_job['started_at']:%H:%M:%S} — safe to switch tabs.")

    @st.fragment(run_every="1s" if rebalance_running else None)
    def _rebalance_job_status():
        job = get_background_job("rebalance_run")
        if job is None:
            return
        if not job["done"]:
            frac, stage = job["progress"]
            st.progress(
                frac, text=f"{stage} — started {job['started_at']:%H:%M:%S}, keeps running even if you switch tabs"
            )
            return
        if job["error"]:
            st.error(f"Scan failed: {job['error']}")
        else:
            st.session_state["rebalance_proposal"] = _with_day_item_status(job["result"])
        clear_background_job("rebalance_run")
        st.rerun()

    _rebalance_job_status()

    if "rebalance_proposal" not in st.session_state:
        st.info("Click **Run today's scan** to generate a proposal.")
        return

    result = st.session_state["rebalance_proposal"]
    if rebalance_running:
        st.warning(
            "⏳ A new scan is running — actions below are locked until "
            "it finishes, so you can't execute against this now-stale "
            "proposal while a fresh one is being computed."
        )

    def _latest_per_symbol(df: pd.DataFrame) -> pd.DataFrame:
        """Collapses a day-aggregated sells/buys/top_ups/stop_updates table
        (see _with_day_item_status -- can have one row per symbol PER RUN
        today) down to one row per symbol: whichever run's row is most
        recent. save_rebalance_run() already guarantees at most one
        'proposed' row per symbol exists at a time (expires every prior
        proposed row the moment a new scan runs), so this only ever
        changes what's shown for a symbol whose most recent attempt
        already resolved (executed/error/expired) -- never hides a
        genuinely still-open proposal behind a stale one."""
        if df.empty or "run_time" not in df.columns:
            return df
        return (
            df.sort_values("run_time")
            .groupby("symbol", as_index=False)
            .last()
            .sort_values("run_time", ascending=False)
            .reset_index(drop=True)
        )

    for _key in ("sells", "buys", "top_ups", "stop_updates"):
        if _key in result:
            result[_key] = _latest_per_symbol(result[_key])

    def _pending(df: pd.DataFrame) -> pd.DataFrame:
        """The still-actionable (auto-selected) subset of a sells/buys/
        top_ups/stop_updates table -- these now carry every status (see
        _with_day_item_status), so counts/badges/what's pre-selected for
        Execute all need this rather than the raw row count. Only
        'proposed' rows are pre-selected -- an 'error' row needs an
        explicit manual pick (see _actionable below), never auto-retried."""
        return df[df["status"] == "proposed"] if "status" in df.columns else df

    def _actionable(df: pd.DataFrame) -> pd.DataFrame:
        """The full selectable set for a section's multiselect: 'proposed'
        (normal, pre-selected) PLUS 'error' (opt-in manual retry only --
        see _pending). 'executed'/'expired' rows are never selectable,
        there's nothing left to do with them."""
        return df[df["status"].isin(["proposed", "error"])] if "status" in df.columns else df

    _real_max_positions = config.STRATEGY["max_positions"]
    _real_target = result.get("target_per_slot") or 0
    _cash_pool = result.get("cash_pool") or 0
    _pending_sells = _pending(result["sells"])
    _pending_buys = _pending(result["buys"])
    st.markdown(
        '<div class="ov-grid-metrics">'
        + _ov_metric_html("Current holdings", str(len(result["holdings"])), "CNC positions", "", "blue")
        + _ov_metric_html(
            "Proposed sells",
            str(len(_pending_sells)),
            (_pending_sells.iloc[0]["symbol"] if not _pending_sells.empty else None),
            "",
            "red",
        )
        + _ov_metric_html(
            "Proposed buys",
            str(len(_pending_buys)),
            (_pending_buys.iloc[0]["symbol"] if not _pending_buys.empty else None),
            "",
            "green",
        )
        + _ov_metric_html(
            "Open slots after sells", str(result["open_slots"]), f"of {_real_max_positions} max", "", "purple"
        )
        + _ov_metric_html("Target / slot", f"₹{_real_target:,.0f}", "Equal weight", "", "teal")
        + _ov_metric_html("Cash pool", f"₹{_cash_pool:,.0f}", "incl. sell proceeds", "", "amber")
        + "</div>",
        unsafe_allow_html=True,
    )

    # cash_shortfall/target_per_slot/cash_pool are snapshotted once at
    # proposal time and never recomputed -- once every buy/top-up from
    # this proposal has actually executed (or there were none to begin
    # with), this message is describing a cash situation that's no
    # longer relevant to anything still actionable, so skip it entirely
    # rather than show a stale "buys below may be partial" next to an
    # empty buys table.
    still_actionable = not _pending_buys.empty or not _pending(result.get("top_ups", pd.DataFrame())).empty
    if still_actionable and result.get("cash_shortfall") is not None:
        target = result.get("target_per_slot") or 0
        pool = result.get("cash_pool") or 0
        shortfall = result.get("cash_shortfall") or 0
        if shortfall > 0:
            st.markdown(
                f'<div class="ov-alert">💰 <b>₹{shortfall:,.0f} more needed</b> to '
                f"fully equal-weight every open slot and under-target holding "
                f"(target ₹{target:,.0f}/slot, ₹{pool:,.0f} available including "
                "proposed sell proceeds) — buys below may be partial or fewer "
                "than ideal until more cash is added.</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="ov-alert ov-alert-success">✅ Enough cash '
                f"(₹{pool:,.0f} available including proposed sell proceeds) to "
                f"fully equal-weight every open slot and under-target holding at "
                f"₹{target:,.0f}/slot.</div>",
                unsafe_allow_html=True,
            )
        unsettled = result.get("unsettled_proceeds") or 0
        if unsettled:
            st.markdown(
                f'<div class="ov-alert ov-alert-info">ℹ️ ₹{unsettled:,.0f} of '
                "today's sell proceeds is from a same-day position or T1 (BTST) "
                "holding — already excluded from the available figure above, "
                "since Zerodha won't treat it as usable cash until that "
                "settlement cycle completes (next trading day for T1, the day "
                "after for a same-day sale).</div>",
                unsafe_allow_html=True,
            )

    with st.container(border=True, key="ov-card-lr-sells"):
        _keep_zone_size = (config.STRATEGY.get("max_positions") or 0) * 2
        st.markdown(
            '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
            '<span class="ov-dot" style="background:var(--ov-red);">'
            f'</span>Proposed sells <span class="ov-badge ov-badge-red">{len(_pending_sells)}</span>'
            f'<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
            f"Dropped out of the top-{_keep_zone_size} keep zone</span></p>",
            unsafe_allow_html=True,
        )
        if st.session_state.get("sell_exec_log"):
            st.success("Sell(s) executed — status below reflects the result.")
            for line in st.session_state["sell_exec_log"]:
                st.write(line)
            del st.session_state["sell_exec_log"]
        if not result["sells"].empty:
            _sells_display = result["sells"].copy()
            try:
                _ltp_map = kite_client.get_ltp(list(_sells_display["symbol"]))
                _sells_display["ltp"] = _sells_display["symbol"].map(_ltp_map)
            except Exception:
                _sells_display["ltp"] = pd.NA
            _sells_display["pnl"] = (_sells_display["ltp"] - _sells_display["avg_price"]) * _sells_display["qty"]
            # Rows can now come from several runs today (see
            # _with_day_item_status) -- show which run each came from so
            # two rows for the same symbol (e.g. re-proposed after an
            # earlier one expired) aren't just confusing duplicates.
            if "run_time" in _sells_display.columns:
                _sells_display["run_time"] = pd.to_datetime(_sells_display["run_time"]).dt.strftime("%d %b %H:%M")
            _sells_cols = [
                c
                for c in ["run_time", "symbol", "qty", "avg_price", "ltp", "pnl", "reason", "status"]
                if c in _sells_display.columns
            ]
            st.markdown(
                _ov_table_html(
                    _sells_display,
                    columns=_sells_cols,
                    sym_cols=["symbol"],
                    pnl_cols=["pnl"],
                    num_fmt={"qty": "{:.0f}", "avg_price": "₹{:.2f}", "ltp": "₹{:.2f}", "pnl": "₹{:+,.0f}"},
                    badges={
                        "status": {
                            "proposed": "ov-badge-amber",
                            "executed": "ov-badge-green",
                            "error": "ov-badge-red",
                            "expired": "ov-badge-gray",
                        }
                    },
                ),
                unsafe_allow_html=True,
            )
            _sells_actionable = _actionable(result["sells"])
            if not _sells_actionable.empty:
                _sells_status = _sells_actionable.set_index("symbol")["status"]
                selected_sells = st.multiselect(
                    "Select which to execute — error rows are offered for a manual retry but never auto-selected",
                    options=_sells_actionable["symbol"].tolist(),
                    default=_pending_sells["symbol"].tolist(),
                    format_func=lambda s: f"{s} ({_sells_status.get(s)})",
                    key="lr_sells_select",
                )
                st.caption(f"{len(selected_sells)} of {len(_sells_actionable)} selected")
                confirm_sell = st.checkbox(
                    "I confirm I want to execute the SELECTED sells at market", key="confirm_sell_all"
                )
                if st.button(
                    "Execute selected sells",
                    disabled=not confirm_sell or not selected_sells or rebalance_running,
                    use_container_width=True,
                    key="lr_execute_sells",
                ):
                    _to_execute = _sells_actionable[_sells_actionable["symbol"].isin(selected_sells)]
                    log, succeeded, failed = lr.execute_sells(_to_execute)
                    st.session_state["sell_exec_log"] = log
                    if succeeded:
                        # A sell just freed cash -- sweep any idle leftover
                        # into the cash-sweep instrument. No-ops when
                        # cash_sweep_enabled is off.
                        lr.sweep_idle_cash()
                    resolved = succeeded + list(failed)
                    if resolved:
                        result["open_slots"] = result.get("open_slots", 0) + len(succeeded)
                        state_db.mark_rebalance_sells_executed(result.get("run_id"), succeeded)
                        state_db.mark_rebalance_sells_failed(result.get("run_id"), failed)
                        state_db.set_rebalance_open_slots(result.get("run_id"), result["open_slots"])
                        # Re-read from state_db (already the source of truth after
                        # the marks above) rather than hand-patching this dict --
                        # keeps every already-resolved row visible with its real
                        # status instead of dropping it from the table.
                        st.session_state["rebalance_proposal"] = _with_day_item_status(result)
                    st.rerun()
            else:
                st.caption("All resolved — nothing left to execute here.")
        elif not result.get("is_rebalance_day", True):
            st.caption(
                f"Sell/keep-zone rule not evaluated today -- "
                f"'{result.get('rebalance_cadence', 'daily')}' cadence selected in "
                f"Admin, only checked on the first trading day of the month. "
                f"New buys still fill any already-open slot as usual."
            )
        else:
            st.caption("No current holdings fail the rebalance rule today.")

    with st.container(border=True, key="ov-card-lr-buys"):
        st.markdown(
            '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
            '<span class="ov-dot" style="background:var(--ov-green);">'
            f'</span>Proposed buys <span class="ov-badge ov-badge-green">{len(_pending_buys)}</span>'
            '<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
            "Sized off real available cash</span></p>",
            unsafe_allow_html=True,
        )
        if st.session_state.get("buy_exec_log"):
            st.success("Buy(s) executed — status below reflects the result.")
            for line in st.session_state["buy_exec_log"]:
                st.write(line)
            del st.session_state["buy_exec_log"]
        if not result["buys"].empty:
            # "rank" only ever exists on a just-completed scan's in-memory
            # result (never persisted to rebalance_buys -- see
            # _with_day_item_status) -- a proposal reloaded from state_db
            # won't have it, so build the column list from what's actually
            # present rather than assume.
            _buys_display = result["buys"].copy()
            _buys_display["amount"] = _buys_display["qty"] * _buys_display["price"]
            if "run_time" in _buys_display.columns:
                _buys_display["run_time"] = pd.to_datetime(_buys_display["run_time"]).dt.strftime("%d %b %H:%M")
            _buys_cols = [
                c
                for c in [
                    "run_time",
                    "symbol",
                    "rank",
                    "score",
                    "price",
                    "qty",
                    "amount",
                    "stop",
                    "fundamental_score",
                    "status",
                ]
                if c in _buys_display.columns
            ]
            st.markdown(
                _ov_table_html(
                    _buys_display,
                    columns=_buys_cols,
                    sym_cols=["symbol"],
                    num_fmt={
                        "rank": "{:.0f}",
                        "qty": "{:.0f}",
                        "price": "₹{:.2f}",
                        "amount": "₹{:,.0f}",
                        "stop": "₹{:.2f}",
                        "score": "{:.2f}",
                        "fundamental_score": "{:.1f}",
                    },
                    badges={
                        "status": {
                            "proposed": "ov-badge-amber",
                            "executed": "ov-badge-green",
                            "error": "ov-badge-red",
                            "expired": "ov-badge-gray",
                        }
                    },
                ),
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="ov-row"><span class="ov-card-meta">Total amount</span>'
                f'<span class="ov-sym">₹{_buys_display["amount"].sum():,.0f}</span></div>',
                unsafe_allow_html=True,
            )
            _buys_actionable = _actionable(result["buys"])
            if not _buys_actionable.empty:
                _buys_status = _buys_actionable.set_index("symbol")["status"]
                selected_buys = st.multiselect(
                    "Select which to execute — error rows are offered for a manual retry but never auto-selected",
                    options=_buys_actionable["symbol"].tolist(),
                    default=_pending_buys["symbol"].tolist(),
                    format_func=lambda s: f"{s} ({_buys_status.get(s)})",
                    key="lr_buys_select",
                )
                st.caption(f"{len(selected_buys)} of {len(_buys_actionable)} selected")
                place_gtt = st.checkbox("Also place a GTT stop-loss for each buy", value=True, key="rebal_gtt")
                confirm_buy = st.checkbox(
                    "I confirm I want to execute the SELECTED buys at market", key="confirm_buy_all"
                )
                if st.button(
                    "Execute selected buys",
                    disabled=not confirm_buy or not selected_buys or rebalance_running,
                    use_container_width=True,
                    key="lr_execute_buys",
                ):
                    _to_execute = _buys_actionable[_buys_actionable["symbol"].isin(selected_buys)]
                    # Redeem just enough of the cash-sweep instrument first
                    # if these buys need more than what's free as real
                    # cash. No-ops when cash_sweep_enabled is off.
                    lr.ensure_cash_for_buys(float((_to_execute["qty"] * _to_execute["price"]).sum()))
                    log, succeeded, failed = lr.execute_buys(_to_execute, place_gtt=place_gtt)
                    st.session_state["buy_exec_log"] = log
                    resolved = succeeded + list(failed)
                    if resolved:
                        result["open_slots"] = max(result.get("open_slots", 0) - len(succeeded), 0)
                        state_db.mark_rebalance_buys_executed(result.get("run_id"), succeeded)
                        state_db.mark_rebalance_buys_failed(result.get("run_id"), failed)
                        state_db.set_rebalance_open_slots(result.get("run_id"), result["open_slots"])
                        st.session_state["rebalance_proposal"] = _with_day_item_status(result)
                    st.rerun()
            else:
                st.caption("All resolved — nothing left to execute here.")
        else:
            st.caption("No open slots, or no candidates today.")

    top_ups = result.get("top_ups", pd.DataFrame())
    stop_updates = result.get("stop_updates", pd.DataFrame())
    _pending_topups = _pending(top_ups)
    col_topups, col_stops = st.columns(2)
    with col_topups, st.container(border=True, key="ov-card-lr-topups"):
        st.markdown(
            '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
            '<span class="ov-dot" style="background:var(--ov-blue);">'
            f'</span>Proposed top-ups <span class="ov-badge ov-badge-gray">{len(_pending_topups)}</span></p>',
            unsafe_allow_html=True,
        )
        if st.session_state.get("topup_exec_log"):
            st.success("Top-up(s) executed — status below reflects the result.")
            for line in st.session_state["topup_exec_log"]:
                st.write(line)
            del st.session_state["topup_exec_log"]
        if not top_ups.empty:
            st.caption(
                "Additional shares for positions you already hold that are below "
                "their equal-weight target, funded by cash left over after the "
                "buys above — the position's existing stop-loss carries over "
                "unchanged, only its GTT quantity gets updated to cover the new "
                "total."
            )
            _topups_display = top_ups.copy()
            _topups_display["amount"] = _topups_display["extra_qty"] * _topups_display["price"]
            if "run_time" in _topups_display.columns:
                _topups_display["run_time"] = pd.to_datetime(_topups_display["run_time"]).dt.strftime("%d %b %H:%M")
            _topups_cols = [
                c
                for c in ["run_time", "symbol", "extra_qty", "price", "amount", "gtt_trigger_id", "status"]
                if c in _topups_display.columns
            ]
            st.markdown(
                _ov_table_html(
                    _topups_display,
                    columns=_topups_cols,
                    sym_cols=["symbol"],
                    num_fmt={"extra_qty": "{:.0f}", "price": "₹{:.2f}", "amount": "₹{:,.0f}"},
                    badges={
                        "status": {
                            "proposed": "ov-badge-amber",
                            "executed": "ov-badge-green",
                            "error": "ov-badge-red",
                            "expired": "ov-badge-gray",
                        }
                    },
                ),
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="ov-row"><span class="ov-card-meta">Total amount</span>'
                f'<span class="ov-sym">₹{_topups_display["amount"].sum():,.0f}</span></div>',
                unsafe_allow_html=True,
            )
            _topups_actionable = _actionable(top_ups)
            if not _topups_actionable.empty:
                _topups_status = _topups_actionable.set_index("symbol")["status"]
                selected_topups = st.multiselect(
                    "Select which to execute — error rows are offered for a manual retry but never auto-selected",
                    options=_topups_actionable["symbol"].tolist(),
                    default=_pending_topups["symbol"].tolist(),
                    format_func=lambda s: f"{s} ({_topups_status.get(s)})",
                    key="lr_topups_select",
                )
                st.caption(f"{len(selected_topups)} of {len(_topups_actionable)} selected")
                confirm_topup = st.checkbox(
                    "I confirm I want to execute the SELECTED top-ups at market", key="confirm_topup_all"
                )
                if st.button(
                    "Execute selected top-ups",
                    disabled=not confirm_topup or not selected_topups or rebalance_running,
                    use_container_width=True,
                    key="lr_execute_topups",
                ):
                    _to_execute = _topups_actionable[_topups_actionable["symbol"].isin(selected_topups)]
                    # Redeem just enough of the cash-sweep instrument
                    # first if these top-ups need more than what's free
                    # as real cash. No-ops when cash_sweep_enabled is off.
                    lr.ensure_cash_for_buys(float((_to_execute["extra_qty"] * _to_execute["price"]).sum()))
                    log, succeeded, failed = lr.execute_top_ups(_to_execute)
                    st.session_state["topup_exec_log"] = log
                    resolved = succeeded + list(failed)
                    if resolved:
                        state_db.mark_rebalance_top_ups_executed(result.get("run_id"), succeeded)
                        state_db.mark_rebalance_top_ups_failed(result.get("run_id"), failed)
                        st.session_state["rebalance_proposal"] = _with_day_item_status(result)
                    st.rerun()
            else:
                st.caption("All resolved — nothing left to execute here.")
        else:
            st.caption("No under-target holdings, or no cash left over to top up with.")

    with col_stops, st.container(border=True, key="ov-card-lr-stops"):
        st.markdown(
            '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
            '<span class="ov-dot" style="background:var(--ov-amber);">'
            f"</span>Stop updates needing attention "
            f'<span class="ov-badge ov-badge-gray">{len(_pending(stop_updates))}</span></p>',
            unsafe_allow_html=True,
        )
        if st.session_state.get("stopupdate_exec_log"):
            st.success("Stop update(s) applied — status below reflects the result.")
            for line in st.session_state["stopupdate_exec_log"]:
                st.write(line)
            del st.session_state["stopupdate_exec_log"]
        _pending_stops = _pending(stop_updates)
        if not stop_updates.empty:
            st.caption("Ratchets auto-apply; only ones that couldn't (no active GTT / Kite error) land here.")
            _stops_display = stop_updates.copy()
            _stops_display["gtt_status"] = _stops_display["gtt_trigger_id"].apply(
                lambda v: "none active" if pd.isna(v) else "active"
            )
            if "run_time" in _stops_display.columns:
                _stops_display["run_time"] = pd.to_datetime(_stops_display["run_time"]).dt.strftime("%d %b %H:%M")
            _stops_cols = [
                c
                for c in ["run_time", "symbol", "current_stop", "recommended_stop", "gtt_status", "status"]
                if c in _stops_display.columns
            ]
            st.markdown(
                _ov_table_html(
                    _stops_display,
                    columns=_stops_cols,
                    sym_cols=["symbol"],
                    num_fmt={"current_stop": "₹{:.2f}", "recommended_stop": "₹{:.2f}"},
                    badges={
                        "gtt_status": {"active": "ov-badge-green", "none active": "ov-badge-red"},
                        "status": {
                            "proposed": "ov-badge-amber",
                            "executed": "ov-badge-green",
                            "error": "ov-badge-red",
                            "expired": "ov-badge-gray",
                        },
                    },
                ),
                unsafe_allow_html=True,
            )
            _stops_actionable = _actionable(stop_updates)
            if not _stops_actionable.empty:
                _stops_status = _stops_actionable.set_index("symbol")["status"]
                selected_stops = st.multiselect(
                    "Select which to apply — error rows are offered for a manual retry but never auto-selected",
                    options=_stops_actionable["symbol"].tolist(),
                    default=_pending_stops["symbol"].tolist(),
                    format_func=lambda s: f"{s} ({_stops_status.get(s)})",
                    key="lr_stops_select",
                )
                st.caption(f"{len(selected_stops)} of {len(_stops_actionable)} selected")
                confirm_stops = st.checkbox(
                    "I confirm I want to raise the SELECTED GTT stop-losses", key="confirm_stop_updates"
                )
                if st.button(
                    "Apply selected stop updates",
                    disabled=not confirm_stops or not selected_stops or rebalance_running,
                    use_container_width=True,
                    key="lr_apply_stops",
                ):
                    _to_apply = _stops_actionable[_stops_actionable["symbol"].isin(selected_stops)]
                    log = []
                    succeeded = []
                    failed = {}
                    for _, r in _to_apply.iterrows():
                        if pd.isna(r["gtt_trigger_id"]):
                            log.append(
                                f"⚠️ {r['symbol']}: no active GTT to update — place one manually first (Trade tab)."
                            )
                            failed[r["symbol"]] = "No active GTT to update"
                            continue
                        try:
                            ltp = kite_client.get_ltp([r["symbol"]])[r["symbol"]]
                            kite_client.modify_gtt_trigger(
                                int(r["gtt_trigger_id"]), r["symbol"], int(r["qty"]), r["recommended_stop"], ltp
                            )
                            # Only now does the recommended stop become the applied
                            # (real, broker-side) stop -- see apply_stop_update()'s
                            # docstring for why this must never happen earlier.
                            state_db.apply_stop_update(r["symbol"])
                            log.append(f"✅ {r['symbol']}: stop raised to ₹{r['recommended_stop']:.2f}")
                            succeeded.append(r["symbol"])
                        except Exception as e:
                            log.append(f"❌ {r['symbol']}: FAILED — {e}")
                            failed[r["symbol"]] = str(e)
                    st.session_state["stopupdate_exec_log"] = log
                    resolved = succeeded + list(failed)
                    if resolved:
                        state_db.mark_rebalance_stop_updates_executed(result.get("run_id"), succeeded)
                        state_db.mark_rebalance_stop_updates_failed(result.get("run_id"), failed)
                        st.session_state["rebalance_proposal"] = _with_day_item_status(result)
                    st.rerun()
            else:
                st.caption("All resolved — nothing left to apply here.")
        else:
            st.caption(
                "No trailing-stop increases needed attention today — "
                "either nothing ratcheted, or it all auto-applied cleanly."
            )

    with st.expander("🔮 What-if: preview equal-weight sizing"):
        st.caption(
            "Instant preview using the SAME sizing formula as the "
            "real proposal below (target/slot = total equity ÷ max "
            "positions, shortfall = slots needed × target − cash "
            "pool) — just with hypothetical inputs instead of the "
            "live config/balance. Doesn't re-run the screener, so it "
            "can't tell you which symbols would actually be picked "
            "at a different slot count, only how much cash each slot "
            "would need."
        )
        _total_equity = _real_target * _real_max_positions
        _held_value = _total_equity - available_cash
        _still_held_count = len(result["holdings"]) - len(result["sells"])

        wc1, wc2 = st.columns(2)
        with wc1:
            what_if_slots = st.slider(
                "Max positions", min_value=1, max_value=25, value=_real_max_positions, key="whatif_slots"
            )
        with wc2:
            what_if_cash = st.number_input(
                "Available cash (₹)", min_value=0.0, value=float(available_cash), step=1000.0, key="whatif_cash"
            )

        what_if_total_equity = what_if_cash + _held_value
        what_if_target = what_if_total_equity / what_if_slots if what_if_slots else 0.0
        what_if_open_slots = max(what_if_slots - _still_held_count, 0)
        what_if_cash_needed = what_if_open_slots * what_if_target
        what_if_shortfall = max(0.0, what_if_cash_needed - what_if_cash)

        st.markdown(
            '<div class="ov-grid-metrics">'
            + _ov_metric_html(
                "Target per slot",
                f"₹{what_if_target:,.0f}",
                (f"{what_if_target - _real_target:+,.0f} vs current" if _real_target else None),
                "ov-pos" if what_if_target >= _real_target else "ov-neg",
                "teal",
            )
            + _ov_metric_html("Open slots", str(what_if_open_slots), "after sells", "", "purple")
            + _ov_metric_html(
                "Cash shortfall",
                f"₹{what_if_shortfall:,.0f}" if what_if_shortfall else "₹0",
                "fully funded" if not what_if_shortfall else None,
                "",
                "green",
            )
            + "</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Page: Positions & Trade
# ---------------------------------------------------------------------------


def page_positions_trade():
    cfg = config.STRATEGY

    hdr_l, hdr_r = st.columns([2, 3])
    with hdr_l:
        st.markdown(
            '<div class="ov-header" style="margin-bottom:0;">'
            '<div><span class="ov-h1">💼 Positions, Holdings &amp; Trade</span></div></div>',
            unsafe_allow_html=True,
        )
    with hdr_r, st.container(key="pt_refresh_row"):
        # A separate "Auto-refresh" label div next to the control kept
        # landing in the wrong visual position however the flex CSS
        # was tuned -- the widget's OWN native label (rendered above
        # it) is unambiguous and needs no CSS guesswork to place
        # correctly, at the cost of sitting above instead of beside.
        refresh_choice = st.segmented_control(
            "Auto-refresh",
            ["Off", "10s", "30s", "1m", "5m"],
            default="30s",
            key="pt_refresh_interval",
            required=True,
            help="Only the positions/holdings tables below refresh on this timer -- "
            "the rest of this page (square-off, orders, trade forms) isn't "
            "affected, so nothing you're typing gets reset by it.",
        )
    run_every = None if refresh_choice == "Off" else refresh_choice

    # Corporate-action review -- live_rebalance.detect_corporate_actions()
    # (run daily as part of the scheduled scan) flags a symbol whose real
    # Kite qty no longer matches our own positions.qty, the signature of a
    # stock split or bonus issue. Shown at the very top, above everything
    # else, since a stale GTT stop-loss is a real risk to a live position.
    # Deliberately confirm-first, never automatic -- the same qty mismatch
    # could also mean you bought more of this symbol manually outside the
    # app, which is NOT a split and would corrupt entry_price if the
    # split math were applied to it, so a human needs to actually judge
    # which case this is before anything gets touched.
    _pending_corp_actions = state_db.get_corporate_action_flags(status="pending")
    if not _pending_corp_actions.empty:
        with st.container(border=True, key="ov-card-corp-action"):
            st.markdown(
                '<p class="ov-card-title"><span class="ov-dot" '
                'style="background:var(--ov-coral);"></span>⚠️ Possible stock split / '
                f'bonus detected <span class="ov-badge ov-badge-amber">'
                f"{len(_pending_corp_actions)}</span></p>",
                unsafe_allow_html=True,
            )
            st.caption(
                "Your real broker quantity for these no longer matches what this app "
                "has on file, with no buy/sell/top-up on record to explain it -- usually "
                "a split or bonus issue, but could also mean you bought more of it "
                "manually outside the app (which is NOT a split, and applying split math "
                "to that would corrupt the entry price). Check the ratio makes sense "
                "before confirming -- a clean 2.0× is a 1:1 bonus, 1.5× is 3:2, etc."
            )
            for _, _f in _pending_corp_actions.iterrows():
                _ratio = float(_f["ratio"])
                _new_entry = float(_f["old_entry_price"]) / _ratio
                _new_stop = float(_f["old_current_stop"]) / _ratio
                with st.container(border=True, key=f"corp_action_{_f['id']}"):
                    cac1, cac2 = st.columns([2, 1])
                    with cac1:
                        st.markdown(
                            f"**{_f['symbol']}** — {int(_f['our_qty'])} → "
                            f"{int(_f['live_qty'])} units (×{_ratio:.4f})  \n"
                            f"Entry price: ₹{_f['old_entry_price']:.2f} → ₹{_new_entry:.2f} · "
                            f"Stop: ₹{_f['old_current_stop']:.2f} → ₹{_new_stop:.2f}"
                            + (
                                f" · GTT {int(_f['old_gtt_trigger_id'])} will be updated to match"
                                if pd.notna(_f["old_gtt_trigger_id"])
                                else " · no GTT on file"
                            )
                        )
                    with cac2:
                        cb1, cb2 = st.columns(2)
                        if cb1.button(
                            "Confirm", key=f"corp_confirm_{_f['id']}", type="primary", use_container_width=True
                        ):
                            _result = lr.apply_corporate_action_adjustment(int(_f["id"]))
                            if _result.get("gtt") and "FAILED" in str(_result["gtt"]):
                                st.warning(f"Position/trade records fixed, but the GTT push failed: {_result['gtt']}")
                            else:
                                st.success(f"{_f['symbol']} adjusted.")
                            st.rerun()
                        if cb2.button(
                            "Dismiss",
                            key=f"corp_dismiss_{_f['id']}",
                            use_container_width=True,
                            help="Use this if it wasn't actually a split -- e.g. you bought more shares manually.",
                        ):
                            state_db.resolve_corporate_action_flag(int(_f["id"]), "dismissed")
                            st.rerun()

    # Own small fragment (not the big orders/holdings one below) so this
    # timestamp still ticks with the same run_every, but can render
    # directly under the segmented control in the header instead of at
    # the bottom of the orders/holdings cards.
    @st.fragment(run_every=run_every)
    def _refresh_status():
        st.markdown(
            '<p class="ov-card-meta" style="text-align:right;margin:2px 0 14px;font-size:10px;">'
            f"Last refreshed {dt.datetime.now():%H:%M:%S}"
            + (f" · auto-refreshing every {refresh_choice}" if run_every else "")
            + "</p>",
            unsafe_allow_html=True,
        )

    with hdr_r:
        _refresh_status()

    @st.fragment(run_every=run_every)
    def _live_holdings():
        _sweep_sym = cfg.get("cash_sweep_symbol", "LIQUIDCASE")
        _all_hold = kite_client.get_holdings()
        _cash_row = _all_hold[_all_hold["tradingsymbol"] == _sweep_sym] if not _all_hold.empty else _all_hold

        with st.container(border=True, key="ov-card-pt-holdings"):
            st.markdown(
                '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
                '<span class="ov-dot" '
                'style="background:var(--ov-purple);"></span>Holdings (CNC)</p>',
                unsafe_allow_html=True,
            )
            live_hold = _all_hold[_all_hold["tradingsymbol"] != _sweep_sym] if not _all_hold.empty else _all_hold
            if live_hold.empty:
                st.caption("No holdings.")
            else:
                live_hold = live_hold.copy()
                live_hold["pnl_pct"] = ((live_hold["last_price"] / live_hold["average_price"]) - 1) * 100
                live_hold["invested_capital"] = live_hold["quantity"] * live_hold["average_price"]
                live_hold["current_capital"] = live_hold["quantity"] * live_hold["last_price"]
                st.markdown(
                    _ov_table_html(
                        live_hold[
                            [
                                "tradingsymbol",
                                "quantity",
                                "average_price",
                                "last_price",
                                "invested_capital",
                                "current_capital",
                                "pnl",
                                "pnl_pct",
                            ]
                        ],
                        sym_cols=["tradingsymbol"],
                        pnl_cols=["pnl", "pnl_pct"],
                        num_fmt={
                            "quantity": "{:.0f}",
                            "average_price": "₹{:.2f}",
                            "last_price": "₹{:.2f}",
                            "invested_capital": "₹{:,.0f}",
                            "current_capital": "₹{:,.0f}",
                            "pnl": "{:+,.0f}",
                            "pnl_pct": "{:+.2f}%",
                        },
                        arrow_cols={"current_capital": ("current_capital", "invested_capital", True)},
                    ),
                    unsafe_allow_html=True,
                )
                _hold_pnl = float(live_hold["pnl"].sum())
                _hold_pnl_cls = "ov-pos" if _hold_pnl >= 0 else "ov-neg"
                st.markdown(
                    f'<div class="ov-row"><span class="ov-card-meta">Total holdings P&amp;L</span>'
                    f'<span class="ov-sym {_hold_pnl_cls}">₹{_hold_pnl:+,.0f}</span></div>',
                    unsafe_allow_html=True,
                )

        # Separate from the momentum-stock holdings above -- idle cash
        # parked in the cash-sweep instrument isn't a swing position (no
        # stop-loss, doesn't count toward max_positions), so it gets its
        # own small card instead of being mixed into "Holdings (CNC)".
        # Shown whenever the feature is on, or a leftover balance still
        # exists after turning it off.
        if cfg.get("cash_sweep_enabled", False) or not _cash_row.empty:
            try:
                _avail_margin = kite_client.get_margins()["equity"]["available"]["live_balance"]
            except Exception:
                _avail_margin = None
            with st.container(border=True, key="ov-card-pt-cash"):
                st.markdown(
                    '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
                    '<span class="ov-dot" style="background:var(--ov-teal);"></span>'
                    "Cash</p>",
                    unsafe_allow_html=True,
                )
                if _avail_margin is not None:
                    st.markdown(
                        f'<div class="ov-row"><span class="ov-card-meta">Available margin</span>'
                        f'<span class="ov-sym">₹{_avail_margin:,.2f}</span></div>',
                        unsafe_allow_html=True,
                    )
                if _cash_row.empty:
                    st.caption(f"No idle cash currently parked in {_sweep_sym}.")
                else:
                    _r = _cash_row.iloc[0]
                    _cur_val = float(_r["quantity"]) * float(_r["last_price"])
                    st.markdown(
                        f'<p class="ov-card-meta" style="margin:10px 0 2px 0;">{_sweep_sym}</p>'
                        f'<div class="ov-row"><span class="ov-card-meta">Units</span>'
                        f'<span class="ov-sym">{int(_r["quantity"])}</span></div>'
                        f'<div class="ov-row"><span class="ov-card-meta">Avg. price</span>'
                        f'<span class="ov-sym">₹{float(_r["average_price"]):.2f}</span></div>'
                        f'<div class="ov-row"><span class="ov-card-meta">Current value</span>'
                        f'<span class="ov-sym">₹{_cur_val:,.0f}</span></div>'
                        f'<div class="ov-row"><span class="ov-card-meta">P&amp;L</span>'
                        f'<span class="ov-sym {"ov-pos" if float(_r["pnl"]) >= 0 else "ov-neg"}">'
                        f"₹{float(_r['pnl']):+,.0f}</span></div>",
                        unsafe_allow_html=True,
                    )
                    if _avail_margin is not None:
                        _total_cash = _avail_margin + _cur_val
                        st.markdown(
                            f'<div class="ov-row" style="border-top:1px solid var(--ov-border);'
                            f'margin-top:8px;padding-top:8px;">'
                            f'<span class="ov-card-meta"><b>Total cash</b></span>'
                            f'<span class="ov-sym"><b>₹{_total_cash:,.2f}</b></span></div>',
                            unsafe_allow_html=True,
                        )

    @st.fragment(run_every=run_every)
    def _live_orders():
        with st.container(border=True, key="ov-card-pt-orders"):
            _orders_tip = html_lib.escape(
                "Every order placed today, enriched with the resulting "
                "position's live LTP/P&L where it's still open -- open "
                "positions and today's orders showed almost entirely "
                "overlapping symbols/qty as separate tables, so this is "
                "one combined view instead of two near-duplicates."
            )
            st.markdown(
                '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
                '<span class="ov-dot" style="background:var(--ov-blue);">'
                "</span>Today's orders &amp; positions"
                f'<span class="ov-info-icon" title="{_orders_tip}">ℹ️</span></p>',
                unsafe_allow_html=True,
            )
            orders = kite_client.get_orders()
            live_pos = kite_client.get_positions()
            if orders.empty:
                st.caption("No orders today.")
            else:
                pos_by_symbol = {}
                if not live_pos.empty:
                    for _, r in live_pos[live_pos["quantity"] != 0].iterrows():
                        pos_by_symbol[r["tradingsymbol"]] = {
                            "current_qty": r["quantity"],
                            "ltp": r["last_price"],
                            "pnl": r["pnl"],
                            "product": r["product"],
                        }
                display = orders[
                    ["order_timestamp", "tradingsymbol", "transaction_type", "quantity", "average_price", "status"]
                ].copy()
                display["current_qty"] = display["tradingsymbol"].map(
                    lambda s: pos_by_symbol.get(s, {}).get("current_qty")
                )
                display["ltp"] = display["tradingsymbol"].map(lambda s: pos_by_symbol.get(s, {}).get("ltp"))
                display["pnl"] = display["tradingsymbol"].map(lambda s: pos_by_symbol.get(s, {}).get("pnl"))
                display["product"] = display["tradingsymbol"].map(lambda s: pos_by_symbol.get(s, {}).get("product"))
                st.markdown(
                    _ov_table_html(
                        display,
                        sym_cols=["tradingsymbol"],
                        pnl_cols=["pnl"],
                        num_fmt={
                            "quantity": "{:.0f}",
                            "average_price": "₹{:.2f}",
                            "current_qty": "{:.0f}",
                            "ltp": "₹{:.2f}",
                        },
                        badges={
                            "transaction_type": lambda v: "ov-badge-green" if v == "BUY" else "ov-badge-red",
                            "status": _ov_order_status_cls,
                        },
                    ),
                    unsafe_allow_html=True,
                )
                total_pnl = live_pos[live_pos["quantity"] != 0]["pnl"].sum() if not live_pos.empty else 0.0
                _pnl_cls = "ov-pos" if total_pnl >= 0 else "ov-neg"
                st.markdown(
                    f'<div class="ov-row"><span class="ov-card-meta">Total position P&amp;L</span>'
                    f'<span class="ov-sym {_pnl_cls}">₹{total_pnl:+,.0f}</span></div>',
                    unsafe_allow_html=True,
                )

    _live_holdings()

    # Separate fetch for the sections below (square-off, stop-loss, orders) --
    # these don't live inside the auto-refreshing fragment above, since their
    # widgets/forms shouldn't get reset every refresh tick; a second cheap
    # positions/holdings call here keeps them independent of that cadence.
    pos = kite_client.get_positions()
    hold = kite_client.get_holdings()

    _sweep_sym = cfg.get("cash_sweep_symbol", "LIQUIDCASE")
    all_syms = []
    if not pos.empty:
        # > 0, not != 0 -- a same-day SELL leaves a NEGATIVE "day"
        # quantity here (settlement-lag artifact, nets to 0 against the
        # holding overnight), not a real short (long-only CNC swing
        # trading) -- see merged_holdings()'s identical fix for the full
        # story. Without this, a symbol sold entirely TODAY still showed
        # up as "unprotected, needs a stop-loss" even though it's not
        # actually held anymore and there was never a GTT to place or
        # delete for it.
        all_syms += list(pos[pos["quantity"] > 0]["tradingsymbol"])
    if not hold.empty:
        all_syms += list(hold[hold["quantity"] > 0]["tradingsymbol"])
    # Exclude the cash-sweep instrument -- it isn't a momentum swing
    # position, so it has no stop-loss concept and shouldn't appear as
    # "unprotected" here.
    all_syms = sorted(set(all_syms) - {_sweep_sym})

    col_orders, col_gtt = st.columns(2)
    with col_orders:
        _live_orders()

    with col_gtt, st.container(border=True, key="ov-card-pt-gtt"):
        st.markdown(
            '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
            '<span class="ov-dot" '
            'style="background:var(--ov-red);"></span> GTT / Stop-Loss Management'
            '<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
            "Straight from Kite — the source of truth</span></p>",
            unsafe_allow_html=True,
            help="The one place for GTT visibility and actions: every current "
            "position/holding, its live GTT status straight from Kite "
            "(the source of truth, not just this app's own tracking), "
            "and -- for anything unprotected -- the action to place one. "
            "Computes the same ATR-based stop this app always uses for a "
            "position bought outside its own buy flow (e.g. placed "
            "directly on Kite), and backfills this app's own bookkeeping "
            "so future trailing-stop updates pick it up too.",
        )

        try:
            active_gtts = kite_client.get_active_gtts()
            gtt_by_symbol = {}
            if not active_gtts.empty and "condition" in active_gtts.columns:
                for _, g in active_gtts.iterrows():
                    cond = g.get("condition") or {}
                    gsym = cond.get("tradingsymbol") if isinstance(cond, dict) else None
                    if not gsym:
                        continue
                    trigger_vals = cond.get("trigger_values") if isinstance(cond, dict) else None
                    gtt_by_symbol[gsym] = {
                        "trigger_price": trigger_vals[0] if trigger_vals else None,
                        "updated_at": g.get("updated_at"),
                    }
        except Exception as e:
            st.warning(f"Could not fetch GTTs from Kite: {e}")
            gtt_by_symbol = {}

        gtt_symbols = set(gtt_by_symbol)
        gtt_rows = []
        for sym in all_syms:
            g = gtt_by_symbol.get(sym)
            _updated_raw = g["updated_at"] if g else None
            _updated_fmt = None
            if _updated_raw:
                try:
                    _updated_fmt = pd.to_datetime(_updated_raw).strftime("%d %b")
                except Exception:
                    _updated_fmt = str(_updated_raw)
            gtt_rows.append(
                {
                    "symbol": sym,
                    "gtt_active": "active" if g else "none",
                    "trigger_price": g["trigger_price"] if g else None,
                    "updated_at": _updated_fmt,
                }
            )
        gtt_table = pd.DataFrame(gtt_rows)
        if not gtt_table.empty:
            st.markdown(
                _ov_table_html(
                    gtt_table.sort_values("symbol"),
                    sym_cols=["symbol"],
                    num_fmt={"trigger_price": "₹{:.2f}"},
                    badges={"gtt_active": {"active": "ov-badge-green", "none": "ov-badge-red"}},
                ),
                unsafe_allow_html=True,
            )

        unprotected_syms = [s for s in all_syms if s not in gtt_symbols]

        if not unprotected_syms:
            st.markdown(
                '<div class="ov-alert ov-alert-success">✓ Every current position/holding has an active GTT.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.warning(f"{len(unprotected_syms)} unprotected: {', '.join(unprotected_syms)} — place a stop-loss below.")
            sl_symbol = st.selectbox("Symbol", unprotected_syms, key="manual_sl_symbol")

            sl_qty, sl_avg_price = 0, 0.0
            if not pos.empty and sl_symbol in pos["tradingsymbol"].values:
                r = pos[pos["tradingsymbol"] == sl_symbol].iloc[0]
                sl_qty, sl_avg_price = int(r["quantity"]), float(r["average_price"])
            elif not hold.empty and sl_symbol in hold["tradingsymbol"].values:
                r = hold[hold["tradingsymbol"] == sl_symbol].iloc[0]
                sl_qty, sl_avg_price = int(r["quantity"]), float(r["average_price"])

            try:
                sl_ltp = kite_client.get_ltp([sl_symbol])[sl_symbol]
                sl_df = kite_client.fetch_daily_candles(sl_symbol, days=120)
                sl_atr = float(indicators.atr(sl_df, cfg["atr_period"]).iloc[-1])
                sl_stop = sl_ltp - cfg["atr_stop_multiple"] * sl_atr
            except Exception as e:
                st.warning(f"Couldn't fetch live data: {e}")
                sl_ltp, sl_stop = 0.0, 0.0

            st.markdown(
                '<div class="ov-grid-metrics">'
                + _ov_metric_html("Quantity", str(sl_qty), None, "", "blue")
                + _ov_metric_html("LTP", f"₹{sl_ltp:,.2f}", None, "", "red")
                + _ov_metric_html(
                    "ATR stop",
                    f"₹{sl_stop:,.2f}",
                    f"{cfg['atr_stop_multiple']}× ATR({cfg['atr_period']})",
                    "",
                    "purple",
                )
                + "</div>",
                unsafe_allow_html=True,
            )

            sl_confirm = st.checkbox("I confirm this GTT stop-loss", key="manual_sl_confirm")
            if st.button(
                "Place stop-loss",
                type="primary",
                disabled=not sl_confirm or sl_qty == 0 or sl_stop <= 0,
                key="manual_sl_place",
                use_container_width=True,
            ):
                try:
                    gtt_id = kite_client.place_gtt_stoploss(sl_symbol, sl_qty, sl_stop, sl_ltp)
                except Exception as e:
                    st.error(f"GTT placement failed: {e}")
                else:
                    state_db.upsert_manual_position(sl_symbol, sl_avg_price, sl_qty, sl_stop, gtt_id)
                    st.success(f"GTT stop-loss placed: trigger {gtt_id} at ₹{sl_stop:,.1f}")
                    st.rerun()

    with st.container(border=True, key="ov-card-pt-order"):
        # The right-hand subtitle needs qty/ltp/side, which aren't known
        # until after the form widgets below run -- render into this
        # placeholder later instead of a static line up front.
        _order_title_ph = st.empty()
        _order_tip = html_lib.escape(
            "Sizing uses your ATR stop so every BUY risks the same % of "
            "capital. Pick SELL on something you currently hold to square "
            "off the whole position at market in one click."
        )

        symbol_choices = sorted(set(all_syms) | set(config.UNIVERSE))
        col1, col2, col3 = st.columns(3)
        with col1:
            symbol = st.selectbox("Symbol", symbol_choices, key="trade_symbol")
            side = st.segmented_control("Side", ["BUY", "SELL"], default="BUY", key="trade_side", required=True)

        held_qty, _held_avg_price = 0, 0.0
        if not pos.empty and symbol in pos["tradingsymbol"].values:
            r = pos[pos["tradingsymbol"] == symbol].iloc[0]
            held_qty, _held_avg_price = int(r["quantity"]), float(r["average_price"])
        elif not hold.empty and symbol in hold["tradingsymbol"].values:
            r = hold[hold["tradingsymbol"] == symbol].iloc[0]
            held_qty, _held_avg_price = int(r["quantity"]), float(r["average_price"])

        square_off_mode = False
        if side == "SELL" and held_qty > 0:
            square_off_mode = st.checkbox(
                f"Square off entire position ({held_qty} shares at market)", value=True, key="trade_square_off"
            )

        with col2:
            capital = st.number_input(
                "Capital for sizing (₹)",
                value=float(available_cash),
                step=10000.0,
                key="trade_capital",
                disabled=square_off_mode,
            )
            order_type = st.segmented_control(
                "Order type",
                ["MARKET", "LIMIT"],
                default="MARKET",
                key="trade_order_type",
                disabled=square_off_mode,
                required=True,
            )
            limit_price = (
                st.number_input("Limit price", value=0.0, step=0.05, key="trade_limit")
                if (order_type == "LIMIT" and not square_off_mode)
                else None
            )

        try:
            ltp = kite_client.get_ltp([symbol])[symbol]
            df = kite_client.fetch_daily_candles(symbol, days=120)
            atr_now = float(indicators.atr(df, cfg["atr_period"]).iloc[-1])
            stop = ltp - cfg["atr_stop_multiple"] * atr_now
            suggested_qty = screener.position_size(capital, ltp, stop)
        except Exception as e:
            st.warning(f"Couldn't fetch live data: {e}")
            ltp, stop, suggested_qty = 0.0, 0.0, 0

        with col3:
            st.markdown(
                '<div class="ov-grid-metrics">'
                + _ov_metric_html("LTP", f"₹{ltp:,.2f}", None, "", "blue")
                + _ov_metric_html("ATR stop", f"₹{stop:,.2f}", None, "", "red")
                + "</div>",
                unsafe_allow_html=True,
            )
            if square_off_mode:
                qty = held_qty
                st.markdown(
                    '<div class="ov-grid-metrics">'
                    + _ov_metric_html("Quantity", str(qty), None, "", "purple")
                    + "</div>",
                    unsafe_allow_html=True,
                )
            else:
                default_qty = held_qty if (side == "SELL" and held_qty > 0) else int(suggested_qty)
                qty = st.number_input(
                    "Quantity",
                    value=default_qty,
                    min_value=0,
                    help=f"Suggested for {cfg['risk_per_trade_pct']}% risk"
                    if side == "BUY"
                    else "Currently held quantity",
                    key="trade_qty",
                )

        place_gtt = False
        if side == "BUY" and not square_off_mode:
            place_gtt = st.checkbox("Also place GTT stop-loss at the ATR stop", value=True, key="trade_place_gtt")

        confirm = st.checkbox(
            f"I confirm I want to close my entire {symbol} position at market"
            if square_off_mode
            else "I confirm this order",
            key="trade_confirm",
        )

        if square_off_mode:
            _preview_bold = f"SELL {qty} × {symbol} at market (square-off)"
            _preview_rest = f" ≈ ₹{qty * ltp:,.0f}"
        else:
            est_value = qty * ltp
            _preview_bold = f"{side} {qty} × {symbol}"
            _preview_rest = f" ≈ ₹{est_value:,.0f} ({order_type}{f' @ ₹{limit_price}' if limit_price else ''})" + (
                f" + GTT SL at ₹{stop:,.1f}" if place_gtt else ""
            )
        _order_title_ph.markdown(
            '<p class="ov-card-title"><span class="ov-dot" '
            'style="background:var(--ov-green);"></span>Place an order'
            f'<span class="ov-info-icon" title="{_order_tip}">ℹ️</span></p>',
            unsafe_allow_html=True,
        )

        if st.button(
            "Square off" if square_off_mode else "Execute order",
            type="primary",
            disabled=not confirm or qty == 0,
            key="trade_execute",
            use_container_width=True,
        ):
            if square_off_mode:
                try:
                    order_id = kite_client.square_off_position(symbol)
                    st.success(f"Square-off order placed: {order_id}")
                    try:
                        exit_ltp = kite_client.get_ltp([symbol])[symbol]
                    except Exception:
                        exit_ltp = None
                    state_db.close_trade(symbol, exit_ltp, "manual_square_off")
                    state_db.close_position(symbol, exit_ltp)
                    # This just freed cash -- sweep any idle leftover into
                    # the cash-sweep instrument. No-ops when
                    # cash_sweep_enabled is off.
                    lr.sweep_idle_cash()
                    # A stale GTT left pointing at a position you no longer
                    # hold can trigger and attempt to sell shares that aren't
                    # there, or just confusingly linger in the Kite GTT list.
                    tracked_pos = state_db.get_open_positions().get(symbol)
                    gtt_id = tracked_pos.get("gtt_trigger_id") if tracked_pos else None
                    if gtt_id:
                        try:
                            kite_client.delete_gtt(int(gtt_id))
                            st.success(f"GTT {gtt_id} deleted")
                        except Exception as e:
                            st.warning(f"⚠️ GTT delete failed: {e} — remove it manually in Kite or re-check here.")
                except Exception as e:
                    st.error(f"Order failed: {e}")
            else:
                if side == "BUY":
                    # Redeem just enough of the cash-sweep instrument first
                    # if this buy needs more than what's free as real cash.
                    # No-ops when cash_sweep_enabled is off.
                    lr.ensure_cash_for_buys(float(qty) * float(limit_price or ltp))
                try:
                    oid = kite_client.place_order(symbol, qty, side, order_type=order_type, price=limit_price)
                except Exception as e:
                    st.error(f"Order failed: {e}")
                else:
                    st.success(f"Order placed: {oid}")
                    if side == "SELL":
                        # This just freed cash -- sweep any idle leftover.
                        # No-ops when cash_sweep_enabled is off.
                        lr.sweep_idle_cash()
                    if side == "BUY":
                        gtt_id = None
                        if place_gtt:
                            try:
                                gtt_id = kite_client.place_gtt_stoploss(symbol, qty, stop, ltp)
                                st.success(f"GTT stop-loss placed: trigger {gtt_id} at ₹{stop:,.1f}")
                            except Exception as e:
                                st.warning(
                                    f"⚠️ Buy succeeded but GTT stop-loss FAILED: {e} "
                                    "(no stop-loss in place — check the GTT / "
                                    "Stop-Loss Management section below)"
                                )
                        # Recorded even when the GTT failed (gtt_id=None), same
                        # reasoning as the Live Rebalance buy flow.
                        position_id = state_db.record_new_position(symbol, float(ltp), int(qty), float(stop), gtt_id)
                        # No screener row here (this is a manually-picked symbol, not
                        # a candidate from the scan) -- entry snapshot is just
                        # price/qty/stop, same as record_new_position itself gets.
                        state_db.record_trade_entry(
                            symbol,
                            float(ltp),
                            int(qty),
                            float(stop),
                            snapshot={"entry_reason": "Manually placed order (Trade tab), not from the automated scan"},
                            position_id=position_id,
                        )

        st.markdown(
            f'<div class="ov-alert ov-alert-info">ℹ️ Order preview: <b>{_preview_bold}</b>{_preview_rest}</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Page: Backtest
# ---------------------------------------------------------------------------


def _run_backtest_job(
    range_mode,
    years,
    start_date,
    end_date,
    use_fundamentals,
    run_cfg,
    bt_capital,
    rebalance_cadence_v,
    progress_cb=None,
):
    """Runs in a background thread via start_background_job -- everything
    the old synchronous button handler did (load candles, load fundamentals
    history, run the backtest, cache the result), just with progress
    reporting threaded through both slow steps instead of an indeterminate
    spinner. Candle loading gets 0-40% of the bar, the simulation itself
    gets the remaining 40-100% -- a rough split, not measured, but close
    enough that the bar never looks stuck for long."""

    def report(stage, frac):
        if progress_cb:
            progress_cb(stage, frac)

    if range_mode == "Custom dates":
        days = (dt.date.today() - start_date).days + 400
        candles_bt, bench_bt = bt.load_candles_cached(
            config.UNIVERSE, days, end_date=end_date, progress_cb=lambda s, f: report(s, f * 0.4)
        )
        sim_start_date = start_date
    else:
        days = int(years * 365) + 400
        candles_bt, bench_bt = bt.load_candles_cached(
            config.UNIVERSE, days, progress_cb=lambda s, f: report(s, f * 0.4)
        )
        # Same reasoning as the Custom-dates branch's sim_start_date: the
        # warmup-days skip alone only approximately lands `years` back
        # from today (it depends on exactly how much candle history was
        # fetched), so without this a "5 years" run could actually
        # simulate/trade a bit outside that window.
        sim_start_date = dt.date.today() - dt.timedelta(days=int(years * 365))

    fundamentals_history = None
    if use_fundamentals and os.path.exists(FUNDAMENTALS_HISTORY_CACHE):
        fundamentals_history = pd.read_pickle(FUNDAMENTALS_HISTORY_CACHE)["history"]

    # Only fetched when the sector bonus OR the sector diversification cap
    # is actually on (~21 index candle fetches, ~15-30s) -- bt.run_backtest()
    # treats both None (both features off) as byte-identical to never
    # having sector data at all, so there's no reason to pay for the fetch
    # otherwise.
    sector_candles = None
    sector_membership = None
    if run_cfg.get("sector_bonus_weight", 0.0) > 0 or run_cfg.get("sector_diversification_enabled", False):
        report("Fetching sector index data...", 0.42)
        sector_membership, sector_candles = su.sector_membership_and_candles(config.UNIVERSE, days=days, verbose=False)

    # Only fetched when the weekly/monthly confirmation gate OR the
    # overhead-resistance tilt is on -- both need far more history than
    # this run's own candles_bt window usually has (weekly/monthly's
    # 200-bar EMA needs ~16.7 years; resistance zones need
    # resistance_zone_lookback_years, 5 by default). Cached separately and
    # incrementally (see bt.load_long_history_cached's docstring) so this
    # is only slow the very first time, not on every run.
    long_candles = None
    if run_cfg.get("weekly_monthly_gate_enabled", False) or run_cfg.get("resistance_zone_weight", 0.0) > 0:
        long_candles = bt.load_long_history_cached(
            config.UNIVERSE, end_date=end_date, progress_cb=lambda s, f: report(s, 0.44 + f * 0.05)
        )

    _rebalance_code = {"daily": "D", "weekly": "W", "monthly": "MS"}.get(rebalance_cadence_v, "MS")
    res = bt.run_backtest(
        candles_bt,
        bench_bt,
        run_cfg,
        initial_capital=bt_capital,
        rebalance=_rebalance_code,
        fundamentals_history=fundamentals_history,
        sector_candles=sector_candles,
        sector_membership=sector_membership,
        long_candles=long_candles,
        start_date=sim_start_date,
        progress_cb=lambda s, f: report(s, 0.4 + f * 0.6),
        track_daily_positions=True,
    )
    run_time = dt.datetime.now()
    os.makedirs("cache", exist_ok=True)
    run_meta = {
        "range_mode": range_mode,
        "years": years,
        "start_date": start_date,
        "end_date": end_date,
        "bt_capital": bt_capital,
        "rebalance_cadence": rebalance_cadence_v,
        "use_fundamentals": use_fundamentals,
    }
    result = {"result": res, "bench": bench_bt, "run_time": run_time, "cfg": run_cfg, "run_meta": run_meta}
    pd.to_pickle(result, BACKTEST_CACHE)
    return result


def _strategy_config_diff(live_cfg: dict, new_cfg: dict, keys) -> list[tuple[str, object, object]]:
    """[(key, live_value, new_value), ...] for keys where they differ, used
    by "Apply to live"'s confirmation panel. Float-tolerant: near_high_
    threshold and similar percent fields round-trip through *100/100 in
    both the Admin and Backtest widgets, which can leave float noise
    (0.8500000000000001 vs 0.85) that would otherwise show up as a fake
    pending change."""
    out = []
    for k in keys:
        old, new = live_cfg.get(k), new_cfg.get(k)
        if isinstance(old, float) or isinstance(new, float):
            if old is not None and new is not None and round(float(old), 6) == round(float(new), 6):
                continue
        elif old == new:
            continue
        out.append((k, old, new))
    return out


def page_backtest():
    backtest_job = get_background_job("backtest_run")
    backtest_running = backtest_job is not None and not backtest_job["done"]

    # While a backtest is running, every field below should show and stay
    # locked to whatever was actually SUBMITTED for this run, not silently
    # revert to a fresh default. A run can take 15-50+ minutes -- long
    # enough to outlive the browser tab's own session (closing the browser,
    # switching away, or just a network blip is enough), and st.session_
    # state is per-session, not persisted across that. backtest_job["meta"]
    # lives on the process-global job registry instead (see background_
    # jobs.start_background_job's docstring), so it survives a session
    # reset even though every widget's own state doesn't -- reading form
    # values from there instead of the widgets' own value= defaults while
    # locked is what actually fixes "values reset to default" rather than
    # just disabling the (already-wrong) displayed values.
    _bt_snapshot = (backtest_job.get("meta") or {}) if backtest_job else {}
    _bt_locked = backtest_running and bool(_bt_snapshot)

    def _bt_val(key, computed_default):
        return _bt_snapshot.get(key, computed_default) if _bt_locked else computed_default

    _backtest_tip = html_lib.escape(
        "Replays the exact screener logic point-in-time with monthly "
        "rebalancing (any slot freed by a stop gets redeployed immediately, "
        "not just at the next rebalance), daily ATR-stop checks, and "
        "transaction costs. Defaults below match the current LIVE strategy "
        "(config.STRATEGY) exactly: fundamental quality gate on, trailing "
        "stop on, the equal-weight allocator with cross-slot borrowing. "
        "(The sector relative-strength bonus was tested here too -- "
        "including together with the equal-weight allocator -- and "
        "removed: it lost on CAGR/Sharpe at every weight tried, with worse "
        "drawdown too, so there's no free lunch even in trade for safety.) "
        "Today's universe implies some survivorship bias regardless -- "
        "treat parameter-sensitivity comparisons as more reliable than "
        "absolute returns."
    )
    st.markdown(
        '<div class="ov-header" style="margin-bottom:0;">'
        '<div><span class="ov-h1">🧪 Backtest</span> '
        '<span class="ov-sub">calendar-entry momentum system</span>'
        f'<span class="ov-info-icon" title="{_backtest_tip}">ℹ️</span></div></div>',
        unsafe_allow_html=True,
    )
    _bt_hdr_spacer, _bt_hdr_r1, _bt_hdr_r2, _bt_hdr_r3 = st.columns([5, 2, 1.2, 1.2])
    _build_fh_clicked = _bt_hdr_r1.button(
        "Build/Refresh fundamentals history", key="bt_build_fh_hdr", disabled=backtest_running
    )
    _run_backtest_clicked = _bt_hdr_r2.button(
        "Run backtest", type="primary", key="bt_run_hdr", disabled=backtest_running
    )
    _stop_backtest_clicked = _bt_hdr_r3.button("⏹️ Stop backtest", key="bt_stop_hdr", disabled=not backtest_running)
    if _stop_backtest_clicked:
        cancel_background_job("backtest_run")
        st.toast("Stopping backtest — this can take a few seconds to take effect.", icon="⏹️")

    if "bt_result" not in st.session_state and os.path.exists(BACKTEST_CACHE):
        _cached_bt = pd.read_pickle(BACKTEST_CACHE)
        st.session_state["bt_result"] = _cached_bt["result"]
        st.session_state["bt_bench"] = _cached_bt["bench"]
        st.session_state["bt_run_time"] = _cached_bt["run_time"]
        st.session_state["bt_is_cached"] = True
        st.session_state["bt_cfg"] = _cached_bt.get("cfg")
        st.session_state["bt_run_meta"] = _cached_bt.get("run_meta")

    _bt_run_time_hdr = st.session_state.get("bt_run_time")
    if _bt_run_time_hdr is not None:
        _bt_cached_note_hdr = (
            " 📁 (from cache — click 'Run backtest' to refresh)" if st.session_state.get("bt_is_cached") else ""
        )
        _bt_run_meta = f"Last run: {_bt_run_time_hdr:%d %b %Y %H:%M}{_bt_cached_note_hdr}"
    else:
        _bt_run_meta = "Not run yet"

    with st.container(border=True, key="ov-card-bt-config"):
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" '
            'style="background:var(--ov-blue);"></span>Run configuration'
            f'<span class="ov-card-meta" style="font-weight:400;margin-left:auto;">'
            f"{_bt_run_meta}</span></p>",
            unsafe_allow_html=True,
        )

        rc1, rc2, rc3, rc4 = st.columns([1.3, 1.6, 1.1, 1.1])
        with rc1:
            range_mode = st.segmented_control(
                "Date range",
                ["Trailing years", "Custom dates"],
                default=_bt_val("range_mode", "Trailing years"),
                key="bt_range_mode",
                required=True,
                disabled=_bt_locked,
            )
        if range_mode == "Trailing years":
            with rc2:
                years = st.slider(
                    "Years of history",
                    1.0,
                    5.0,
                    _bt_val("years", 3.0),
                    0.5,
                    disabled=_bt_locked,
                    help="Up to 5 years supported via chunked Kite "
                    "fetches (Kite's historical API caps a single "
                    "request at ~2000 days).",
                )
            start_date, end_date = None, None
        else:
            with rc2:
                rc2a, rc2b = st.columns(2)
                # Streamlit deletes a widget's own auto-managed state if it
                # isn't rendered on a given script run (documented
                # behavior, confirmed via a headless AppTest simulation --
                # this is true regardless of whether the widget has an
                # explicit key=, that alone does NOT fix it) -- since these
                # two date_inputs only render while range_mode == "Custom
                # dates", switching to "Trailing years" and back silently
                # reset them to a freshly-recomputed default (today - 3
                # years for start_date), discarding whatever custom range
                # you'd actually picked. Mirror each widget's value into a
                # plain (non-widget-managed) session_state slot every
                # render, and seed value= from THAT instead of a fresh
                # computation -- a plain dict entry survives the widget
                # being unmounted, so a later remount re-seeds from your
                # last real choice instead of silently reverting.
                if "bt_custom_start_date_saved" not in st.session_state:
                    st.session_state["bt_custom_start_date_saved"] = dt.date.today() - dt.timedelta(days=3 * 365)
                if "bt_custom_end_date_saved" not in st.session_state:
                    st.session_state["bt_custom_end_date_saved"] = dt.date.today()
                start_date = rc2a.date_input(
                    "Start date",
                    value=_bt_val("start_date", st.session_state["bt_custom_start_date_saved"]),
                    max_value=dt.date.today(),
                    key="bt_custom_start_date",
                    disabled=_bt_locked,
                )
                end_date = rc2b.date_input(
                    "End date",
                    value=_bt_val("end_date", st.session_state["bt_custom_end_date_saved"]),
                    max_value=dt.date.today(),
                    key="bt_custom_end_date",
                    disabled=_bt_locked,
                )
                if not _bt_locked:
                    st.session_state["bt_custom_start_date_saved"] = start_date
                    st.session_state["bt_custom_end_date_saved"] = end_date
            years = None
        with rc3:
            bt_capital = st.number_input(
                "Starting capital (₹)", value=_bt_val("bt_capital", 1_000_000.0), step=100000.0, disabled=_bt_locked
            )
        with rc4:
            bt_max_positions = st.number_input(
                "Max open positions",
                min_value=1,
                max_value=30,
                value=_bt_val("max_positions", int(config.STRATEGY["max_positions"])),
                step=1,
                disabled=_bt_locked,
                help="Backtest-only override (config.STRATEGY['max_positions'] "
                "is 10 live) -- more slots means more diversification but "
                "smaller equal-weight targets per slot; fewer slots "
                "concentrates capital in higher-conviction picks. Not "
                "itself an A/B-tuned edge parameter the way the ones below "
                "are, just a portfolio-construction choice to experiment "
                "with.",
            )

        st.divider()
        _hist_available = os.path.exists(FUNDAMENTALS_HISTORY_CACHE)
        _hist_badge_color = "var(--ov-green-d)" if _hist_available else "var(--ov-red-d)"
        _hist_badge_text = "AVAILABLE" if _hist_available else "NOT AVAILABLE"
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" '
            'style="background:var(--ov-purple);"></span>🎯 Strategy parameters — '
            "tested &amp; approved"
            f'<span class="ov-card-meta" style="font-weight:700;margin-left:auto;'
            f'color:{_hist_badge_color};">'
            f"Fundamentals Build History - {_hist_badge_text}</span></p>",
            unsafe_allow_html=True,
        )

        def _ov_muted(text):
            st.markdown(
                f'<p class="ov-muted" style="margin:10px 0 2px;text-transform:none;">{text}</p>', unsafe_allow_html=True
            )

        _ov_muted("Trade management")
        use_mad_stop = st.checkbox(
            "Use MAD Volatility Trail stop instead of ATR",
            key="bt_use_mad_stop",
            value=_bt_val("mad_stop_enabled", bool(config.STRATEGY.get("mad_stop_enabled", False))),
            disabled=_bt_locked,
            help="OFF by default. Replaces BOTH the initial and trailing stop below "
            "with the MAD trail's own one-sided ratcheting lower band (median + "
            "MAD-scaled bands, ATR floor) -- falls back to the ATR stop/trailing "
            "settings below automatically whenever the trail isn't a sensible "
            "support for a given entry (not in a bull MAD-regime, or the band "
            "sits above price), so the ATR fields still matter even with this "
            "on. A 5.6yr PDF-config backtest (regime filter ON) found the "
            "default params here raised CAGR 38.65%->40.37% and shrank max "
            "drawdown -30.67%->-28.81% at once, verified against this exact "
            "production engine -- the strongest, most consistent stop-placement "
            "result tested so far. Still worth re-verifying against your own "
            "config before relying on it live.",
        )
        if use_mad_stop:
            mad1, mad2, mad3, mad4 = st.columns(4)
            with mad1:
                mad_med_len_v = st.number_input(
                    "Median length",
                    min_value=5,
                    max_value=100,
                    value=_bt_val("mad_stop_med_len", int(config.STRATEGY.get("mad_stop_med_len", 21))),
                    step=1,
                    disabled=_bt_locked,
                    help="Rolling window for the trail's median center line.",
                )
            with mad2:
                mad_mad_len_v = st.number_input(
                    "MAD length",
                    min_value=5,
                    max_value=100,
                    value=_bt_val("mad_stop_mad_len", int(config.STRATEGY.get("mad_stop_mad_len", 21))),
                    step=1,
                    disabled=_bt_locked,
                    help="Rolling window for the median-absolute-deviation band width.",
                )
            with mad3:
                mad_dev_factor_v = st.number_input(
                    "Deviation factor",
                    min_value=0.5,
                    max_value=5.0,
                    value=_bt_val("mad_stop_dev_factor", float(config.STRATEGY.get("mad_stop_dev_factor", 2.0))),
                    step=0.1,
                    disabled=_bt_locked,
                    help="MAD band half-width multiplier -- wider band = looser stop.",
                )
            with mad4:
                mad_atr_floor_mult_v = st.number_input(
                    "ATR floor ×",
                    min_value=0.5,
                    max_value=5.0,
                    value=_bt_val(
                        "mad_stop_atr_floor_mult", float(config.STRATEGY.get("mad_stop_atr_floor_mult", 2.0))
                    ),
                    step=0.1,
                    disabled=_bt_locked,
                    help="Floors the band width at this × ATR(14) so it never gets "
                    "unrealistically tight in a low-volatility lull.",
                )
        else:
            mad_med_len_v = config.STRATEGY.get("mad_stop_med_len", 21)
            mad_mad_len_v = config.STRATEGY.get("mad_stop_mad_len", 21)
            mad_dev_factor_v = config.STRATEGY.get("mad_stop_dev_factor", 2.0)
            mad_atr_floor_mult_v = config.STRATEGY.get("mad_stop_atr_floor_mult", 2.0)

        tm1, tm2, tm3, tm4 = st.columns(4)
        with tm1:
            atr_stop_multiple_v = st.number_input(
                "Initial stop (× ATR)",
                min_value=0.5,
                max_value=10.0,
                value=_bt_val("atr_stop_multiple", float(config.STRATEGY["atr_stop_multiple"])),
                step=0.1,
                disabled=_bt_locked,
            )
        with tm2:
            ts1, ts2 = st.columns([1, 1])
            with ts1:
                use_trailing = st.checkbox(
                    "Trailing stop",
                    value=_bt_val("trailing_stop_enabled", bool(config.STRATEGY["trailing_stop_enabled"])),
                    key="bt_use_trailing",
                    disabled=_bt_locked,
                    help="LIVE default is ON. Ratchets each position's stop up to "
                    "highest_close_since_entry - multiple*ATR as it gains, "
                    "never back down.",
                )
            with ts2:
                trailing_mult_v = st.number_input(
                    "ATR multiple",
                    min_value=0.5,
                    max_value=10.0,
                    value=_bt_val("trailing_atr_multiple", float(config.STRATEGY["trailing_atr_multiple"])),
                    step=0.25,
                    disabled=(not use_trailing) or _bt_locked,
                    help="A 5-year sweep found an inverted-U peaking at 4.0x (the "
                    "live default): CAGR 24.30% vs baseline 22.51%, Sharpe 1.73 "
                    "vs 1.50, max drawdown -14.37% vs -18.06%.",
                )
        with tm3:
            risk_per_trade_pct_v = st.number_input(
                "Risk per trade (% of capital)",
                min_value=0.1,
                max_value=10.0,
                value=_bt_val("risk_per_trade_pct", float(config.STRATEGY["risk_per_trade_pct"])),
                step=0.1,
                disabled=_bt_locked,
            )
        with tm4:
            rebalance_cadence_v = st.segmented_control(
                "Rebalance cadence",
                ["daily", "weekly", "monthly"],
                default=_bt_val("rebalance_cadence", config.STRATEGY.get("rebalance_cadence", "daily")),
                key="bt_rebalance_cadence",
                disabled=_bt_locked,
                help="All three mirror the LIVE Admin setting exactly -- "
                "'daily' re-checks the sell/keep-zone rule every trading "
                "day (matches the live default); 'weekly' only on the "
                "last trading day of each week (Friday, or the prior "
                "trading day if Friday is a market holiday); 'monthly' "
                "only on the first trading day of each month. Buys/"
                "top-ups always fill open slots daily regardless of "
                "which is chosen -- only the sell decision's frequency "
                "changes.",
            )

        _ov_muted("Technical indicator")
        ti1, ti2, ti3 = st.columns(3)
        with ti1:
            rsi_min_v = st.number_input(
                "RSI min",
                min_value=0.0,
                max_value=100.0,
                value=_bt_val("rsi_min", float(config.STRATEGY["rsi_min"])),
                step=0.01,
                format="%.2f",
                disabled=_bt_locked,
                help="Momentum names trade 45-80 in this system's regime; below this is not yet in an uptrend.",
            )
        with ti2:
            rsi_max_v = st.number_input(
                "RSI max",
                min_value=0.0,
                max_value=100.0,
                value=_bt_val("rsi_max", float(config.STRATEGY["rsi_max"])),
                step=0.01,
                format="%.2f",
                disabled=_bt_locked,
                help="A 5-year A/B (max_positions=4) found raising this 78->80 "
                "improved CAGR 7.36->8.15%, Sharpe 1.14->1.25 -- re-verify "
                "any further move against that same baseline, not just "
                "eyeballing one run.",
            )
        with ti3:
            ema_fast_v = st.number_input(
                "EMA (fast)",
                min_value=5,
                max_value=100,
                value=_bt_val("ema_fast", int(config.STRATEGY["ema_fast"])),
                step=1,
                disabled=_bt_locked,
            )
        ti4, ti5, ti6 = st.columns(3)
        with ti4:
            ema_slow_v = st.number_input(
                "EMA (slow)",
                min_value=50,
                max_value=400,
                value=_bt_val("ema_slow", int(config.STRATEGY["ema_slow"])),
                step=1,
                disabled=_bt_locked,
            )
        with ti5:
            mom_lookback_short_v = st.number_input(
                "Momentum lookback — short (days)",
                min_value=5,
                max_value=252,
                value=_bt_val("mom_lookback_days_short", int(config.STRATEGY["mom_lookback_days_short"])),
                step=1,
                disabled=_bt_locked,
            )
        with ti6:
            mom_lookback_long_v = st.number_input(
                "Momentum lookback — long (days)",
                min_value=5,
                max_value=504,
                value=_bt_val("mom_lookback_days_long", int(config.STRATEGY["mom_lookback_days_long"])),
                step=1,
                disabled=_bt_locked,
            )
        ti7, ti8 = st.columns(2)
        with ti7:
            skip_recent_days_v = st.number_input(
                "Skip most recent (days)",
                min_value=0,
                max_value=30,
                value=_bt_val("skip_recent_days", int(config.STRATEGY["skip_recent_days"])),
                step=1,
                disabled=_bt_locked,
            )
        with ti8:
            history_days_v = st.number_input(
                "Candle history fetched (days)",
                min_value=300,
                max_value=3000,
                value=_bt_val("history_days", int(config.STRATEGY["history_days"])),
                step=100,
                disabled=_bt_locked,
            )
        ti9, ti10 = st.columns([1, 1])
        with ti9:
            use_rsi_exit_gate = st.checkbox(
                "Separate exit RSI ceiling",
                key="bt_use_rsi_exit_gate",
                value=_bt_val("rsi_exit_gate_enabled", bool(config.STRATEGY.get("rsi_exit_gate_enabled", False))),
                disabled=_bt_locked,
                help="OFF by default and NOT the live behavior. When on, a "
                "held position whose only failing gate is the entry-band "
                "RSI max above stays held (instead of being force-sold) "
                "as long as RSI is still under the separate ceiling to "
                "the right — lets a hot winner keep running instead of "
                "selling the moment it crosses the entry ceiling. Note: "
                "this exact idea was already A/B tested once and made "
                "every metric worse — re-testing here against current "
                "data, not assumed to flip that result.",
            )
        with ti10:
            rsi_exit_max_v = st.number_input(
                "Exit RSI ceiling",
                min_value=0.0,
                max_value=100.0,
                value=_bt_val("rsi_exit_max", float(config.STRATEGY.get("rsi_exit_max", config.STRATEGY["rsi_max"]))),
                step=1.0,
                format="%.2f",
                disabled=(not use_rsi_exit_gate) or _bt_locked,
            )
        ti11, _ti12 = st.columns([1, 2])
        with ti11:
            use_wm_rsi_gate = st.checkbox(
                "Weekly/monthly EMA trend gate",
                key="bt_use_wm_rsi_gate",
                value=_bt_val(
                    "weekly_monthly_gate_enabled", bool(config.STRATEGY.get("weekly_monthly_gate_enabled", False))
                ),
                disabled=_bt_locked,
                help="OFF by default and NOT the live behavior. Extra entry "
                "gate on top of the daily checks above: weekly close "
                "must be above its own 200-EMA, AND monthly close above "
                "its own 200-EMA (each falls back to a 50-EMA when there "
                "isn't enough resampled history for 200 yet). Higher-"
                "timeframe confirmation that the trend isn't just a "
                "short-term daily blip. Simplified to EMA-only (no "
                "weekly/monthly RSI requirement) after real-run data "
                "showed the RSI leg added excessive rebalance-exit "
                "churn -- a held position only needed one of the (then "
                "four) stacked conditions to wobble near its threshold "
                "to get force-sold. Needs deep (~16-year) history per "
                "symbol, fetched and cached separately the first time "
                "this is checked (slow, one-time) and updated "
                "incrementally after that (fast) -- but the gate itself "
                "stays meaningfully slower than everything else on this "
                "page even after that, since it re-resamples that deep "
                "history from scratch every rebalance day (unlike the "
                "daily indicators, this can't be safely precomputed "
                "without risking lookahead). Untested — verify from "
                "here before considering for live.",
            )

        _ov_muted("Scanner param")
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            ew1, ew2 = st.columns([1, 1])
            with ew1:
                use_equal_weight = st.checkbox(
                    "Equal-weight allocator",
                    value=_bt_val(
                        "advanced_equal_weight_sizing", bool(config.STRATEGY["advanced_equal_weight_sizing"])
                    ),
                    key="bt_use_equal_weight",
                    disabled=_bt_locked,
                    help="LIVE default is ON. Sizes the whole day's buys in one "
                    "pass -- cross-slot borrowing within tolerance, partial "
                    "fill on shortfall, hard-stop-not-substitute, top-up of "
                    "under-target holdings -- instead of one-symbol-at-a-time "
                    "greedy sizing.",
                )
            with ew2:
                equal_weight_tolerance_v = st.number_input(
                    "Tolerance",
                    min_value=0.0,
                    max_value=1.0,
                    value=_bt_val("equal_weight_tolerance_pct", float(config.STRATEGY["equal_weight_tolerance_pct"])),
                    step=0.01,
                    format="%.2f",
                    disabled=(not use_equal_weight) or _bt_locked,
                    help="A 5-year A/B found 0.20 (the live default) beats the "
                    "original one-at-a-time fill on every metric at once: CAGR "
                    "43.06->44.39%, Sharpe 1.64->1.67, max drawdown "
                    "-20.30->-19.58%, profit factor 2.10->2.12.",
                )
            use_capital_equal_weight = st.checkbox(
                "Capital-weighted sizing (uncheck for risk-based)",
                key="bt_use_capital_equal_weight",
                value=_bt_val(
                    "capital_equal_weight_sizing", bool(config.STRATEGY.get("capital_equal_weight_sizing", True))
                ),
                disabled=_bt_locked,
                help="ON by default, matches live. Sizes each position off "
                "capital/portfolio value (the allocator above, or the "
                "one-at-a-time fallback when it's off). Uncheck to size "
                "off risk instead: risk_per_trade_pct of capital, "
                "position width = (entry - stop) -- can come out "
                "arbitrarily small on modest capital combined with a "
                "wide ATR stop (e.g. 1-2 share positions that don't "
                "grow with your account size). Off by default for "
                "exactly that reason; verify here before switching live.",
            )
        with sc2:
            use_fundamentals = st.checkbox(
                "Fundamental gate",
                value=_bt_val("fundamental_gate_enabled", bool(config.STRATEGY["fundamental_gate_enabled"])),
                key="bt_use_fundamentals",
                disabled=_bt_locked,
                help="This is the LIVE default (config.STRATEGY['fundamental_gate_"
                "enabled']=True) -- uncheck only to see the pure-technical "
                "baseline it was A/B'd against. Uses each filing's real "
                "broadcast timestamp to only count what was actually public "
                "knowledge as of each rebalance date -- not today's "
                "fundamentals applied retroactively. Needs a fundamentals "
                "history built first (top-right button) -- without one, "
                "this checkbox has no effect regardless of its state.",
            )
        with sc3:
            fundamental_bonus_weight_v = st.number_input(
                "Fundamental bonus weight",
                min_value=0.0,
                max_value=3.0,
                value=_bt_val("fundamental_bonus_weight", float(config.STRATEGY["fundamental_bonus_weight"])),
                step=0.1,
                disabled=(not use_fundamentals) or _bt_locked,
                help="Tilts ranking toward higher-quality gate-passers (on top "
                "of the gate itself, which only excludes/includes). A "
                "5-year sweep found an inverted-U peaking at 0.5 (the live "
                "default): CAGR 43.70->43.03% at 0.5, Sharpe 1.62->1.64, "
                "max drawdown improves -24.61->-20.30% -- anything above "
                "0.5 is a clear net negative.",
            )
        sc4, sc5, sc6 = st.columns(3)
        with sc4:
            min_fundamental_score_v = st.number_input(
                "Min fundamental score",
                min_value=0.0,
                max_value=100.0,
                value=_bt_val("min_fundamental_score", float(config.STRATEGY["min_fundamental_score"])),
                step=1.0,
                disabled=_bt_locked,
                help="NOT independently A/B-tuned -- config.py calls 50 (the "
                "live default) 'a rough average-or-better bar, tune to "
                "taste.' Only the gate's on/off status and the bonus "
                "weight above have documented A/B history; this threshold "
                "itself has never been swept, so treat any result here as "
                "a first look, not a verified finding. Stays editable "
                "regardless of the gate checkbox above -- unlike the bonus "
                "weight, this is just a plain threshold value with no "
                "other side effect when the gate is off, so there's no "
                "reason to grey it out.",
            )
        with sc5:
            near_high_threshold_v = st.number_input(
                "52-week-high proximity (%)",
                min_value=50.0,
                max_value=100.0,
                value=_bt_val("near_high_threshold", float(config.STRATEGY["near_high_threshold"])) * 100,
                step=1.0,
                disabled=_bt_locked,
                help="Price must be at least this % of its 52-week high to qualify.",
            )
        with sc6:
            sector_bonus_weight_v = st.number_input(
                "Sector bonus weight",
                min_value=0.0,
                max_value=1.0,
                value=_bt_val("sector_bonus_weight", float(config.STRATEGY["sector_bonus_weight"])),
                step=0.05,
                disabled=_bt_locked,
                help="0 = off (recommended) -- re-tested with the equal-weight "
                "allocator specifically: loses on CAGR and Sharpe at every "
                "weight, and drawdown gets worse too, so there's no "
                "risk/reward trade-off to make here.",
            )
        sc7, sc8, sc9 = st.columns([1, 1, 1])
        with sc7:
            use_sector_diversification = st.checkbox(
                "Sector diversification cap",
                key="bt_use_sector_diversification",
                value=_bt_val(
                    "sector_diversification_enabled", bool(config.STRATEGY.get("sector_diversification_enabled", False))
                ),
                disabled=_bt_locked,
                help="OFF by default and NOT the live behavior. Unlike the bonus "
                "above (a ranking tilt that can still leave a portfolio "
                "stacked into one hot sector), this is a hard constraint: "
                "a stock only qualifies if its best-matching sector GROUP "
                "is currently among the top N strongest (right), AND no "
                "single group can hold more than the position cap (right) "
                "at once -- enforced at buy time, never forces an exit. "
                "Grouped, not raw index names: NSE tracks several "
                "overlapping sector indices for the same real industry "
                "(e.g. 4 different healthcare-flavored ones) -- capping "
                "by raw name alone let a real test portfolio end up 100% "
                "one industry since each variant got its own independent "
                "allowance, so this groups them first (see "
                "sector_universe.SECTOR_INDUSTRY_GROUPS) and caps the "
                "group instead. Untested — verify from here before "
                "considering for live.",
            )
        with sc8:
            top_n_sectors_v = st.number_input(
                "Top N sectors",
                min_value=1,
                max_value=10,
                value=_bt_val("top_n_sectors", int(config.STRATEGY.get("top_n_sectors", 3))),
                step=1,
                disabled=(not use_sector_diversification) or _bt_locked,
            )
        with sc9:
            max_positions_per_sector_v = st.number_input(
                "Max positions / sector",
                min_value=1,
                max_value=10,
                value=_bt_val("max_positions_per_sector", int(config.STRATEGY.get("max_positions_per_sector", 3))),
                step=1,
                disabled=(not use_sector_diversification) or _bt_locked,
            )
        use_sector_composite = st.checkbox(
            "Use composite sector score (RS + 52w-high + breadth) instead of RS alone",
            key="bt_use_sector_composite",
            value=_bt_val(
                "sector_composite_score_enabled", bool(config.STRATEGY.get("sector_composite_score_enabled", False))
            ),
            disabled=(not use_sector_diversification) or _bt_locked,
            help="Only affects which sectors count as 'top N' above -- OFF "
            "ranks sectors on relative strength alone (the original "
            "behavior); ON blends in two more signals, each research-"
            "backed: the sector index's own 52-week-high proximity "
            "(George & Hwang 2004 -- predicts continuation better than "
            "past returns alone) and breadth, i.e. what % of the "
            "sector's own stocks are themselves passing the technical "
            "gates (IBD/O'Neil 'Group Relative Strength' methodology -- "
            "a sector whose RS is carried by one or two outliers is a "
            "weaker signal than one with broad participation). "
            "Untested — A/B against RS-alone from here first.",
        )

        resistance_zone_weight_v = st.number_input(
            "Resistance zone weight",
            min_value=0.0,
            max_value=1.0,
            value=_bt_val("resistance_zone_weight", float(config.STRATEGY.get("resistance_zone_weight", 0.0))),
            step=0.05,
            disabled=_bt_locked,
            help="0 = off. Tilts ranking toward stocks with more clean room "
            "before the nearest strong multi-year price zone above them "
            "-- a level swing-touched repeatedly in the past (the last "
            "5 years, receding), which can act as latent overhead "
            "supply and cap a rally even when momentum/trend look fine "
            "at entry. A stock right underneath a zone that's been "
            "touched many times scores worse than one with the same "
            "momentum but open air above it. Untested — verify from "
            "here before considering for live.",
        )

        rg1, rg2 = st.columns(2)
        with rg1:
            use_regime_filter = st.checkbox(
                "Market regime filter",
                key="bt_use_regime_filter",
                value=_bt_val("regime_filter_enabled", bool(config.STRATEGY.get("regime_filter_enabled", False))),
                disabled=_bt_locked,
                help="OFF by default. When NIFTY 50's own close is below its "
                "200 EMA, caps how many NEW positions may open to "
                "max_positions x the multiplier (right) -- never force-"
                "sells an existing position purely because the regime "
                "flipped, same 'blocks new entries only' rule as the "
                "sector diversification cap. A real 5-year A/B (core "
                "strategy, sector/resistance-zone/fundamental features "
                "off) improved every headline metric at once -- CAGR "
                "41.73%->42.86%, Sharpe 1.58->1.69, max drawdown "
                "-28.26%->-24.05%, win rate 43.6%->44.6% -- but wasn't "
                "uniform year to year: 2026 YTD was worse with it ON "
                "(-5.51% vs -2.16%), every other year flat-to-better. "
                "Verify against your own fuller config (sector bonus, "
                "diversification, resistance zone together) before "
                "considering for live.",
            )
        with rg2:
            regime_position_multiplier_v = st.number_input(
                "Regime position multiplier",
                min_value=0.1,
                max_value=1.0,
                value=_bt_val(
                    "regime_position_multiplier", float(config.STRATEGY.get("regime_position_multiplier", 0.5))
                ),
                step=0.05,
                disabled=(not use_regime_filter) or _bt_locked,
                help="Fraction of max_positions allowed while NIFTY is below "
                "its 200 EMA -- 0.5 means half the normal slot count "
                "(and, with equal-weight sizing, roughly half the "
                "capital deployed, since each filled slot is still "
                "sized off the full max_positions).",
            )

        cf1, cf2 = st.columns(2)
        with cf1:
            entry_confirm_days_v = st.number_input(
                "Entry confirmation (consecutive rebalance events)",
                min_value=0,
                max_value=10,
                value=_bt_val("entry_confirm_days", int(config.STRATEGY.get("entry_confirm_days", 0) or 0)),
                step=1,
                key="bt_entry_confirm_days",
                disabled=_bt_locked,
                help="0 = OFF (default). Requires a stock to have stayed in the "
                "confirm-pool (right) for this many CONSECUTIVE rebalance "
                "events before a NEW buy is allowed -- filters out one-event "
                "'wonder' ranks that reverse right after qualifying. Never "
                "affects sells. TESTED AND NOT RECOMMENDED: a 5.6yr PDF-style "
                "config backtest (2021-2026, regime filter already ON) found "
                "0 -> 2 made every headline metric worse at once -- CAGR "
                "38.65%->37.26%, Sharpe 1.64->1.60, max drawdown "
                "-30.67%->-33.10% -- despite a small win-rate lift. Left here "
                "as a re-testable toggle in case a different config responds "
                "differently, not because it's expected to help.",
            )
        with cf2:
            entry_confirm_pool_size_v = st.number_input(
                "Confirm-pool size",
                min_value=1,
                max_value=100,
                value=_bt_val(
                    "entry_confirm_pool_size",
                    int(config.STRATEGY.get("entry_confirm_pool_size") or (bt_max_positions * 2)),
                ),
                step=1,
                disabled=(entry_confirm_days_v == 0) or _bt_locked,
                key="bt_entry_confirm_pool_size",
                help="How many top-scored candidates count as the confirm-pool "
                "each rebalance -- defaults to 2x portfolio size (e.g. "
                "top-20 for a 10-position portfolio, same convention as the "
                "sell-side keep zone).",
            )

        st.caption(
            "No per-trade cost is modeled — Zerodha charges no brokerage "
            "on equity delivery (CNC). Statutory costs (STT, stamp duty, "
            "exchange/SEBI charges) still apply in reality (~5-7 bps round "
            "trip) but aren't broker-specific; use `--cost-bps` on the CLI "
            "if you want a more conservative run that includes them."
        )

        if _build_fh_clicked:
            bar = st.progress(0.0, text="Starting...")
            history = fa.build_fundamentals_history(
                config.UNIVERSE, n_years=5, progress_cb=lambda s, f: bar.progress(f, text=s)
            )
            bar.empty()
            os.makedirs("cache", exist_ok=True)
            pd.to_pickle({"history": history, "run_time": dt.datetime.now()}, FUNDAMENTALS_HISTORY_CACHE)
            st.rerun()

    run_disabled = range_mode == "Custom dates" and start_date >= end_date
    if run_disabled:
        st.error("Start date must be before end date.")

    if _run_backtest_clicked and not run_disabled:
        # Always built fresh from the live config + every control above, so
        # the backtest that actually runs can never silently diverge from
        # what's shown on screen (previously run_cfg stayed None -- falling
        # back to config.STRATEGY untouched -- unless sector was checked).
        run_cfg = dict(config.STRATEGY)
        run_cfg["max_positions"] = int(bt_max_positions)
        run_cfg["rsi_min"] = rsi_min_v
        run_cfg["rsi_max"] = rsi_max_v
        run_cfg["trailing_stop_enabled"] = use_trailing
        run_cfg["trailing_atr_multiple"] = trailing_mult_v
        run_cfg["advanced_equal_weight_sizing"] = use_equal_weight
        run_cfg["capital_equal_weight_sizing"] = use_capital_equal_weight
        run_cfg["equal_weight_tolerance_pct"] = equal_weight_tolerance_v
        # fundamental_gate_enabled is set explicitly too, even though the
        # gate is already a no-op without fundamentals_history (see
        # use_fundamentals above) -- this keeps run_cfg an honest mirror of
        # every control on screen rather than relying on that side channel.
        run_cfg["fundamental_gate_enabled"] = use_fundamentals
        run_cfg["fundamental_bonus_weight"] = fundamental_bonus_weight_v
        run_cfg["min_fundamental_score"] = min_fundamental_score_v
        run_cfg["mom_lookback_days_short"] = int(mom_lookback_short_v)
        run_cfg["mom_lookback_days_long"] = int(mom_lookback_long_v)
        run_cfg["skip_recent_days"] = int(skip_recent_days_v)
        run_cfg["rsi_exit_gate_enabled"] = use_rsi_exit_gate
        run_cfg["rsi_exit_max"] = float(rsi_exit_max_v)
        run_cfg["weekly_monthly_gate_enabled"] = use_wm_rsi_gate
        run_cfg["near_high_threshold"] = float(near_high_threshold_v) / 100
        run_cfg["ema_fast"] = int(ema_fast_v)
        run_cfg["ema_slow"] = int(ema_slow_v)
        run_cfg["atr_stop_multiple"] = float(atr_stop_multiple_v)
        run_cfg["mad_stop_enabled"] = use_mad_stop
        run_cfg["mad_stop_med_len"] = int(mad_med_len_v)
        run_cfg["mad_stop_mad_len"] = int(mad_mad_len_v)
        run_cfg["mad_stop_dev_factor"] = float(mad_dev_factor_v)
        run_cfg["mad_stop_atr_floor_mult"] = float(mad_atr_floor_mult_v)
        run_cfg["risk_per_trade_pct"] = float(risk_per_trade_pct_v)
        run_cfg["sector_bonus_weight"] = float(sector_bonus_weight_v)
        run_cfg["sector_diversification_enabled"] = use_sector_diversification
        run_cfg["top_n_sectors"] = int(top_n_sectors_v)
        run_cfg["max_positions_per_sector"] = int(max_positions_per_sector_v)
        run_cfg["sector_composite_score_enabled"] = use_sector_composite
        run_cfg["resistance_zone_weight"] = float(resistance_zone_weight_v)
        run_cfg["regime_filter_enabled"] = use_regime_filter
        run_cfg["regime_position_multiplier"] = float(regime_position_multiplier_v)
        run_cfg["entry_confirm_days"] = int(entry_confirm_days_v)
        run_cfg["entry_confirm_pool_size"] = int(entry_confirm_pool_size_v)
        run_cfg["history_days"] = int(history_days_v)
        run_cfg["rebalance_cadence"] = rebalance_cadence_v
        # Keeps this block honest against config.BACKTEST_TUNABLE_KEYS (the
        # allow-list "Apply to live" pushes from) -- if a new widget is added
        # here without adding its key to that tuple too, this trips instead
        # of the two silently drifting apart.
        assert all(k in run_cfg for k in config.BACKTEST_TUNABLE_KEYS)
        # Snapshot of every value actually submitted, keyed the same as
        # run_cfg (plus the handful of fields run_cfg doesn't carry:
        # date-range mode and the starting capital) -- read back by _bt_val
        # above while this job is running/locked, so the form shows and
        # stays on exactly what was submitted even if the browser session
        # resets mid-run. See start_background_job's meta= docstring.
        bt_meta = dict(run_cfg)
        bt_meta.update(
            {
                "range_mode": range_mode,
                "years": years,
                "start_date": start_date,
                "end_date": end_date,
                "bt_capital": bt_capital,
            }
        )
        start_background_job(
            "backtest_run",
            _run_backtest_job,
            range_mode,
            years,
            start_date,
            end_date,
            use_fundamentals,
            run_cfg,
            bt_capital,
            rebalance_cadence_v,
            job_type="backtest_run",
            meta=bt_meta,
            summarize_fn=lambda r: (
                f"CAGR {r['result']['metrics'].get('CAGR %', '?')}%, Sharpe {r['result']['metrics'].get('Sharpe', '?')}"
            ),
        )
        st.rerun()

    if backtest_running:
        st.info(
            f"⏳ Backtest running since {backtest_job['started_at']:%H:%M:%S} "
            "— safe to switch tabs or close the browser, it keeps running "
            "server-side; come back to this page any time to see progress."
        )

    @st.fragment(run_every="1s" if backtest_running else None)
    def _backtest_job_status():
        job = get_background_job("backtest_run")
        if job is None:
            return
        if not job["done"]:
            frac, stage = job["progress"]
            st.progress(frac, text=f"{stage} — started {job['started_at']:%H:%M:%S}")
            return
        if job.get("cancelled"):
            st.warning("⏹️ Backtest stopped.")
        elif job["error"]:
            st.error(f"Backtest failed: {job['error']}")
        else:
            result = job["result"]
            st.session_state["bt_result"] = result["result"]
            st.session_state["bt_bench"] = result["bench"]
            st.session_state["bt_run_time"] = result["run_time"]
            st.session_state["bt_is_cached"] = False
            st.session_state["bt_cfg"] = result.get("cfg")
            st.session_state["bt_run_meta"] = result.get("run_meta")
        # Every explicitly-keyed form widget above (checkboxes/segmented_
        # controls/date_inputs that carry key="bt_...") has an entry in
        # st.session_state by now, from whichever render last happened
        # while this job was running/locked. Streamlit's rule for a keyed
        # widget is that once session_state[key] exists, a freshly-passed
        # value=/default= on a LATER render is silently ignored -- only
        # the widget's own prior session-state value is used. Without
        # this, the form's next render (backtest_running now False,
        # _bt_locked False, disabled= correctly flips back off) would
        # still SHOW every keyed field frozen at whatever it was during
        # the run, not the freshly-editable value= being passed -- which
        # is exactly "form stays non-editable after the run finishes",
        # even though it's no longer actually disabled. Deleting these
        # keys forces Streamlit to re-seed each one fresh from its
        # value=/default= on the very next render, for every completion
        # path (success, cancelled, or error), not just success.
        for _k in (
            "bt_range_mode",
            "bt_custom_start_date",
            "bt_custom_end_date",
            "bt_use_mad_stop",
            "bt_use_trailing",
            "bt_rebalance_cadence",
            "bt_use_rsi_exit_gate",
            "bt_use_wm_rsi_gate",
            "bt_use_equal_weight",
            "bt_use_capital_equal_weight",
            "bt_use_fundamentals",
            "bt_use_sector_diversification",
            "bt_use_sector_composite",
            "bt_use_regime_filter",
            "bt_entry_confirm_days",
            "bt_entry_confirm_pool_size",
        ):
            st.session_state.pop(_k, None)
        clear_background_job("backtest_run")
        st.rerun()

    _backtest_job_status()

    if "bt_result" not in st.session_state:
        st.info("Click **Run backtest** to simulate on real Kite data.")
        return

    res = st.session_state["bt_result"]
    eq = res["equity_curve"]
    bench_bt = st.session_state["bt_bench"]

    nifty = bench_bt["close"].reindex(eq.index).ffill()

    _bt_cfg = st.session_state.get("bt_cfg")
    _bt_meta = st.session_state.get("bt_run_meta") or {}
    with st.expander("⚙️ Parameters used for this run", expanded=False):
        if not _bt_cfg:
            st.caption(
                "This result was cached before parameter tracking was added — re-run the backtest to record its config."
            )
        else:
            if _bt_meta.get("range_mode") == "Custom dates":
                _range_txt = f"{_bt_meta.get('start_date')} → {_bt_meta.get('end_date')}"
            else:
                _range_txt = f"{_bt_meta.get('years')} years trailing"
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Date range", _range_txt)
            p2.metric("Starting capital", f"₹{_bt_meta.get('bt_capital', 0):,.0f}")
            p3.metric("Max positions", _bt_cfg.get("max_positions"))
            p4.metric("Rebalance cadence", _bt_cfg.get("rebalance_cadence"))

            st.caption("Trade management")
            t1, t2, t3, t4 = st.columns(4)
            t1.metric("Initial stop (× ATR)", _bt_cfg.get("atr_stop_multiple"))
            _trail = "ON" if _bt_cfg.get("trailing_stop_enabled") else "OFF"
            t2.metric("Trailing stop", f"{_trail} ({_bt_cfg.get('trailing_atr_multiple')}×)")
            t3.metric("Risk per trade (%)", _bt_cfg.get("risk_per_trade_pct"))
            t4.metric("History fetched (days)", _bt_cfg.get("history_days"))

            st.caption("Technical indicator")
            i1, i2, i3, i4 = st.columns(4)
            i1.metric("RSI range", f"{_bt_cfg.get('rsi_min')}–{_bt_cfg.get('rsi_max')}")
            i2.metric("EMA fast/slow", f"{_bt_cfg.get('ema_fast')}/{_bt_cfg.get('ema_slow')}")
            i3.metric(
                "Momentum lookback",
                f"{_bt_cfg.get('mom_lookback_days_short')}/{_bt_cfg.get('mom_lookback_days_long')}d",
            )
            i4.metric("Skip most recent (days)", _bt_cfg.get("skip_recent_days"))
            _rsi_exit = "ON" if _bt_cfg.get("rsi_exit_gate_enabled") else "OFF"
            st.metric("Exit RSI ceiling", f"{_rsi_exit} ({_bt_cfg.get('rsi_exit_max')})")
            _wm_rsi = "ON" if _bt_cfg.get("weekly_monthly_gate_enabled") else "OFF"
            st.metric("Weekly/monthly EMA trend gate", f"{_wm_rsi} (price>200EMA on both)")

            st.caption("Scanner param")
            s1, s2, s3, s4 = st.columns(4)
            _ew = "ON" if _bt_cfg.get("advanced_equal_weight_sizing") else "OFF"
            s1.metric("Equal-weight allocator", f"{_ew} (tol {_bt_cfg.get('equal_weight_tolerance_pct')})")
            _fg = "ON" if _bt_cfg.get("fundamental_gate_enabled") else "OFF"
            s2.metric("Fundamental gate", _fg)
            s3.metric("Fundamental bonus weight", _bt_cfg.get("fundamental_bonus_weight"))
            s4.metric("Min fundamental score", _bt_cfg.get("min_fundamental_score"))
            s5, s6, s7, s8 = st.columns(4)
            s5.metric("52w-high proximity (%)", f"{_bt_cfg.get('near_high_threshold', 0) * 100:.0f}")
            s6.metric("Sector bonus weight", _bt_cfg.get("sector_bonus_weight"))
            _sd = "ON" if _bt_cfg.get("sector_diversification_enabled") else "OFF"
            _sc = "composite" if _bt_cfg.get("sector_composite_score_enabled") else "RS-only"
            s7.metric(
                "Sector diversification",
                f"{_sd} (top {_bt_cfg.get('top_n_sectors')}, "
                f"max {_bt_cfg.get('max_positions_per_sector')}/sector, {_sc})",
            )
            s8.metric("Resistance zone weight", _bt_cfg.get("resistance_zone_weight", 0.0))
            _rg = "ON" if _bt_cfg.get("regime_filter_enabled") else "OFF"
            st.metric(
                "Market regime filter",
                f"{_rg} (x{_bt_cfg.get('regime_position_multiplier', 0.5)} "
                f"positions when NIFTY < {_bt_cfg.get('regime_ema_period', 200)}EMA)",
            )
            _ecd = _bt_cfg.get("entry_confirm_days", 0)
            _ec = f"{_ecd}d (pool {_bt_cfg.get('entry_confirm_pool_size')})" if _ecd else "OFF"
            st.metric("Entry confirmation", _ec)
            _ms = "ON" if _bt_cfg.get("mad_stop_enabled") else "OFF"
            st.metric(
                "MAD trail stop",
                f"{_ms} (med={_bt_cfg.get('mad_stop_med_len')}, "
                f"mad={_bt_cfg.get('mad_stop_mad_len')}, "
                f"dev={_bt_cfg.get('mad_stop_dev_factor')}, "
                f"floor×={_bt_cfg.get('mad_stop_atr_floor_mult')})",
            )

    if _bt_cfg:
        with st.expander("🚀 Apply this run's config to live", expanded=False):
            _live_diff = _strategy_config_diff(config.STRATEGY, _bt_cfg, config.BACKTEST_TUNABLE_KEYS)
            if not _live_diff:
                st.info("Live config already matches this run's settings — nothing to apply.")
            else:
                st.caption(
                    "This only updates the parameters the next Live "
                    "Rebalance run (scheduled or manual) will use — it "
                    "does not run a scan or place any trade. Go to the "
                    "Live Rebalance tab to actually run/execute one."
                )
                _diff_rows = [
                    {"Parameter": k, "Live now": str(old), "Would become": str(new)} for k, old, new in _live_diff
                ]
                st.dataframe(pd.DataFrame(_diff_rows), hide_index=True, use_container_width=True)
                _confirm_apply_live = st.checkbox(
                    f"I confirm I want to push these {len(_live_diff)} "
                    "changed parameter(s) to the LIVE strategy config",
                    key="bt_confirm_apply_live",
                )
                if st.button(
                    "🚀 Apply to live", type="primary", disabled=not _confirm_apply_live, key="bt_apply_live_btn"
                ):
                    _live_updates = {k: new for k, old, new in _live_diff}
                    state_db.update_strategy_config(_live_updates)
                    config.STRATEGY.update(_live_updates)
                    st.success(
                        f"Applied {len(_live_updates)} parameter(s) to "
                        "live — takes effect on the next scheduled or "
                        "manual rebalance run (no restart needed)."
                    )
                    st.rerun()

    with st.container(border=True, key="ov-card-bt-pdf"):
        pdf_col1, pdf_col2 = st.columns([3, 2])
        with pdf_col1:
            st.markdown(
                "**📄 PDF report** — config used, summary metrics, "
                "equity/drawdown charts, year-by-year table, and the "
                "full trade list for this result, all in one file."
            )
        with pdf_col2:
            if st.button("Generate PDF report", key="bt_gen_pdf", width="stretch"):
                with st.spinner("Building PDF..."):
                    st.session_state["bt_pdf_bytes"] = backtest_report.build_pdf(
                        res, bench_bt, _bt_cfg or {}, _bt_meta or {}, _bt_run_time_hdr
                    )
                    st.session_state["bt_pdf_run_time"] = _bt_run_time_hdr
            if st.session_state.get("bt_pdf_run_time") == _bt_run_time_hdr and "bt_pdf_bytes" in st.session_state:
                st.download_button(
                    "⬇️ Download PDF",
                    st.session_state["bt_pdf_bytes"],
                    f"backtest_report_{_bt_run_time_hdr:%Y%m%d_%H%M}.pdf",
                    mime="application/pdf",
                    key="bt_dl_pdf",
                    width="stretch",
                )

    with st.container(border=True, key="ov-card-bt-equity"):
        eq_fig = go.Figure()
        eq_fig.add_trace(
            go.Scatter(
                x=eq.index,
                y=eq / eq.iloc[0] * 100,
                name="Strategy",
                mode="lines",
                line={"color": "#16a34a", "width": 2},
                hovertemplate="%{y:.1f}<extra>Strategy</extra>",
            )
        )
        eq_fig.add_trace(
            go.Scatter(
                x=nifty.index,
                y=nifty / nifty.iloc[0] * 100,
                name="NIFTY 50",
                mode="lines",
                line={"color": "#6b7280", "width": 1.5, "dash": "dot"},
                hovertemplate="%{y:.1f}<extra>NIFTY 50</extra>",
            )
        )
        eq_fig.update_layout(
            title={"text": "Backtest equity curve — growth of ₹100", "x": 0, "xanchor": "left"},
            height=420,
            margin={"l": 10, "r": 10, "t": 60, "b": 10},
            hovermode="x unified",
            yaxis={"title": "Growth of 100"},
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0},
        )
        st.plotly_chart(eq_fig, width="stretch")

    _m = res["metrics"]
    _total_ret = (res["final_capital"] / eq.iloc[0] - 1) * 100
    _cagr = _m.get("CAGR %")
    _maxdd = _m.get("Max drawdown %")
    st.markdown(
        '<div class="ov-grid-metrics">'
        + _ov_metric_html(
            "Final capital",
            f"₹{res['final_capital']:,.0f}",
            f"{_total_ret:+.1f}% total",
            "ov-pos" if _total_ret >= 0 else "ov-neg",
            "green",
        )
        + _ov_metric_html(
            "CAGR",
            f"{_cagr:.1f}%" if _cagr is not None else "—",
            None,
            "ov-pos" if (_cagr or 0) >= 0 else "ov-neg",
            "green",
            "ov-pos" if (_cagr or 0) >= 0 else "ov-neg",
        )
        + _ov_metric_html("Sharpe", f"{_m.get('Sharpe', '—')}", "daily, annualized", "", "blue")
        + _ov_metric_html(
            "Max drawdown",
            f"{_maxdd:.1f}%" if _maxdd is not None else "—",
            f"NIFTY {_m.get('NIFTY CAGR %', '—')}% CAGR",
            "",
            "coral",
        )
        + _ov_metric_html("Win rate", f"{_m.get('Win rate %', '—')}%", f"{_m.get('Trades', '—')} trades", "", "purple")
        + _ov_metric_html("Profit factor", f"{_m.get('Profit factor', '—')}", "gross win/loss", "", "teal")
        + _ov_metric_html("Open at end", str(len(res["open_positions"])), "not force-sold", "", "amber")
        + "</div>",
        unsafe_allow_html=True,
    )

    with st.expander("Full metrics table"):
        _metrics_df = pd.DataFrame({"Value": res["metrics"]})
        _metrics_df.insert(0, "Metric", _metrics_df.index)
        st.markdown(_ov_table_html(_metrics_df), unsafe_allow_html=True)

    dd = (eq / eq.cummax() - 1) * 100
    with st.container(border=True, key="ov-card-bt-drawdown"):
        dd_fig = go.Figure()
        dd_fig.add_trace(
            go.Scatter(
                x=dd.index,
                y=dd,
                name="Drawdown %",
                mode="lines",
                line={"color": "#dc2626", "width": 1.5},
                fill="tozeroy",
                fillcolor="rgba(220,38,38,0.15)",
                hovertemplate="%{y:.1f}%<extra>Drawdown</extra>",
            )
        )
        dd_fig.update_layout(
            title={"text": "Drawdown from peak", "x": 0, "xanchor": "left"},
            height=260,
            margin={"l": 10, "r": 10, "t": 50, "b": 10},
            yaxis={"title": "Drawdown %"},
            showlegend=False,
        )
        st.plotly_chart(dd_fig, width="stretch")

    yp = bt.yearly_performance(eq, bench_bt, res["trades"])
    yc1, yc2 = st.columns([2, 3])
    with yc1, st.container(border=True, key="ov-card-bt-yearly"):
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" '
            'style="background:var(--ov-teal);"></span>Year-by-year performance</p>',
            unsafe_allow_html=True,
        )
        yp_display = yp.copy()
        yp_display.insert(0, "Year", yp_display.index.astype(str))
        st.markdown(
            _ov_table_html(
                yp_display,
                sym_cols=["Year"],
                pnl_cols=["Strategy %", "Alpha %"],
                num_fmt={"NIFTY %": "{:+.2f}", "Win rate %": "{:.1f}"},
            ),
            unsafe_allow_html=True,
        )
    with yc2, st.container(border=True, key="ov-card-bt-yearly-bar"):
        bar_fig = go.Figure()
        bar_colors = ["#16a34a" if v >= 0 else "#dc2626" for v in yp["Strategy %"]]
        bar_fig.add_trace(
            go.Bar(
                x=yp.index.astype(str),
                y=yp["Strategy %"],
                name="Strategy %",
                marker_color=bar_colors,
                hovertemplate="%{y:.1f}%<extra>Strategy</extra>",
            )
        )
        bar_fig.add_trace(
            go.Bar(
                x=yp.index.astype(str),
                y=yp["NIFTY %"],
                name="NIFTY %",
                marker_color="#9ca3af",
                hovertemplate="%{y:.1f}%<extra>NIFTY 50</extra>",
            )
        )
        bar_fig.update_layout(
            title={"text": "Strategy vs NIFTY by year", "x": 0, "xanchor": "left"},
            height=350,
            margin={"l": 10, "r": 10, "t": 50, "b": 10},
            barmode="group",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0},
        )
        st.plotly_chart(bar_fig, width="stretch")

    if not res["open_positions"].empty:
        with st.expander(f"Open positions at period end ({len(res['open_positions'])})", expanded=True):
            st.caption(
                "Still held when the backtest's date range ran out — "
                "not force-sold. Unrealized P&L is marked to the last "
                "available close, not an actual exit."
            )
            op = res["open_positions"].copy()
            op["entry_date"] = pd.to_datetime(op["entry_date"]).dt.date.astype(str)
            st.markdown(
                _ov_table_html(
                    op.sort_values("unrealized_pnl", ascending=False),
                    sym_cols=["symbol"],
                    pnl_cols=["unrealized_pnl", "unrealized_ret_pct"],
                    num_fmt={"entry_price": "₹{:.2f}", "current_price": "₹{:.2f}", "stop": "₹{:.2f}", "qty": "{:.0f}"},
                ),
                unsafe_allow_html=True,
            )

    _daily_pos = res.get("daily_positions")
    if _daily_pos is not None and not _daily_pos.empty:
        with st.expander("📅 Open positions on a specific date", expanded=True):
            st.caption(
                "Reconstructed from the actual simulated state on that day "
                "(real entry price/qty/stop, real close price) -- not an "
                "approximation, and not limited to the final-day snapshot "
                "above."
            )
            _dp_dates = pd.to_datetime(_daily_pos["date"]).dt.date
            _dp_min, _dp_max = _dp_dates.min(), _dp_dates.max()
            query_date = st.date_input(
                "Date", value=_dp_max, min_value=_dp_min, max_value=_dp_max, key="bt_daily_pos_query_date"
            )
            day_rows = _daily_pos[_dp_dates == query_date]
            if day_rows.empty:
                st.info(
                    f"No open positions on {query_date} in this run (either "
                    "flat that day, or not a simulated trading day)."
                )
            else:
                dpd = day_rows.drop(columns=["date"]).copy()
                dpd["entry_date"] = pd.to_datetime(dpd["entry_date"]).dt.date.astype(str)
                st.markdown(
                    _ov_table_html(
                        dpd.sort_values("unrealized_pnl", ascending=False),
                        sym_cols=["symbol"],
                        pnl_cols=["unrealized_pnl", "unrealized_ret_pct"],
                        num_fmt={
                            "entry_price": "₹{:.2f}",
                            "current_price": "₹{:.2f}",
                            "stop": "₹{:.2f}",
                            "qty": "{:.0f}",
                        },
                    ),
                    unsafe_allow_html=True,
                )
    elif "daily_positions" not in res:
        st.caption(
            "📁 Position-on-a-date lookup isn't available for this cached "
            "run (older format) — re-run the backtest to use it."
        )

    tr = res["trades"].copy()
    if not tr.empty:
        with st.container(border=True, key="ov-card-bt-closed"):
            st.markdown(
                '<p class="ov-card-title"><span class="ov-dot" '
                'style="background:var(--ov-coral);"></span>All closed trades</p>',
                unsafe_allow_html=True,
            )
            tr["entry_date"] = pd.to_datetime(tr["entry_date"]).dt.date
            tr["exit_date"] = pd.to_datetime(tr["exit_date"]).dt.date

            f1, f2, f3 = st.columns(3)
            with f1:
                sym_filter = st.multiselect("Symbol", sorted(tr["symbol"].unique()), key="tr_sym_filter")
            with f2:
                reason_filter = st.multiselect("Exit reason", sorted(tr["reason"].unique()), key="tr_reason_filter")
            with f3:
                outcome_filter = st.selectbox("Outcome", ["All", "Wins only", "Losses only"], key="tr_outcome_filter")

            filtered = tr
            if sym_filter:
                filtered = filtered[filtered["symbol"].isin(sym_filter)]
            if reason_filter:
                filtered = filtered[filtered["reason"].isin(reason_filter)]
            if outcome_filter == "Wins only":
                filtered = filtered[filtered["pnl"] > 0]
            elif outcome_filter == "Losses only":
                filtered = filtered[filtered["pnl"] <= 0]

            st.caption(f"Showing {len(filtered)} of {len(tr)} trades")
            filtered_sorted = filtered.sort_values("entry_date", ascending=False)
            filtered_page = _ov_page_slice(filtered_sorted, key="bt_closed", page_size=20)
            st.markdown(
                _ov_table_html(
                    filtered_page,
                    sym_cols=["symbol"],
                    pnl_cols=["pnl", "ret_pct"],
                    num_fmt={"entry_price": "₹{:.2f}", "exit_price": "₹{:.2f}"},
                    badges={"reason": lambda v: "ov-badge-red" if v == "stop_hit" else "ov-badge-gray"},
                ),
                unsafe_allow_html=True,
            )
            _ov_pagination_controls(filtered_sorted, key="bt_closed", page_size=20)
            st.download_button(
                "Download trades CSV (filtered view)", filtered.to_csv(index=False), "backtest_trades.csv"
            )


# ---------------------------------------------------------------------------
# Page: Fundamentals (Value Score)
# ---------------------------------------------------------------------------


def page_fundamentals():
    if "value_scores" not in st.session_state and os.path.exists(VALUE_SCORE_CACHE):
        st.session_state["value_scores"] = pd.read_pickle(VALUE_SCORE_CACHE)
        st.session_state["value_scores_is_cached"] = True

    _last_scan_bit = ""
    if st.session_state.get("value_scores_is_cached"):
        age = dt.datetime.now() - dt.datetime.fromtimestamp(os.path.getmtime(VALUE_SCORE_CACHE))
        _last_scan_bit = f" · last scan {age.total_seconds() / 3600:.1f}h ago"

    hdr_l, hdr_r = st.columns([3, 2])
    with hdr_l:
        st.markdown(
            '<div class="ov-header" style="margin-bottom:0;">'
            '<div><span class="ov-h1">📊 Fundamentals</span> '
            '<span class="ov-sub">· primary-source value score</span></div></div>',
            unsafe_allow_html=True,
        )
        st.caption("0-100 from audited XBRL filings — no scraping, no LLM" + _last_scan_bit)
    with hdr_r, st.container(key="fund_scan_row"):
        with st.popover("ℹ️"):
            st.markdown(
                "**Sector-aware scoring.** Banks and NBFCs file under "
                "structurally different XBRL taxonomies — banks don't tag "
                "Revenue/Equity/Current Assets at all, and general-company "
                "thresholds would flag every healthy NBFC as over-levered "
                "(NBFCs run 3-6x leverage by design). Each symbol is routed "
                "to the rubric matching what its filings actually contain: "
                "**general** (ROE, D/E, Current Ratio, FCF, Revenue CAGR, "
                "PEG), **banking** (ROE, ROA, NIM proxy, Gross/Net NPA, "
                "Advances growth), or **nbfc** (ROE, ROA, D/E, Loan growth "
                "— also covers AMCs per NSE's own filing classification). "
                "Insurers aren't covered yet — their key metrics "
                "(persistency, embedded value, solvency ratio) aren't "
                "reliably XBRL-tagged. Balance-sheet ratios only refresh "
                "once a year (audited annual filing). Missing sub-metrics "
                "are dropped, not faked — check a row's missing pillars "
                "before trusting a high total score."
            )
        _run_value_scan_clicked = st.button("Run value score scan", type="primary")

    _existing_scores = st.session_state.get("value_scores")
    _rubrics_present = sorted(_existing_scores["rubric"].dropna().unique()) if _existing_scores is not None else []

    with st.container(border=True, key="ov-card-fund-filters"):
        v1, v2, v3, v4 = st.columns(4)
        with v1:
            max_syms_v = st.slider(
                "Symbols to scan",
                10,
                len(config.UNIVERSE),
                len(config.UNIVERSE),
                step=1,
                key="value_scan_n",
                help="~0.3s/symbol + XBRL download time",
            )
        with v2:
            n_years_v = st.slider("Years of annual history", 2, 5, 3, key="value_scan_years")
        with v3:
            st.markdown(
                '<p style="font-size:11px;font-weight:500;color:var(--ov-text-muted);margin:0 0 4px;">PEG input</p>',
                unsafe_allow_html=True,
            )
            use_price = st.checkbox(
                "Use live price",
                value=True,
                key="value_scan_price",
                help="Uses today's live price for PEG instead of the price as of the filing date.",
            )
        with v4:
            sector = st.selectbox(
                "Filter by sector",
                ["All", *_rubrics_present],
                key="fund_sector_filter",
                help="Each sector uses a different rubric with different metrics — "
                "filtering keeps the table to the columns that actually apply.",
            )

        if _run_value_scan_clicked:
            bar = st.progress(0.0, text="Starting...")
            result = fa.fno_value_scan(
                config.UNIVERSE[:max_syms_v],
                n_years=n_years_v,
                use_live_price=use_price,
                progress_cb=lambda s, f: bar.progress(f, text=s),
            )
            bar.empty()
            st.session_state["value_scores"] = result
            st.session_state["value_scores_is_cached"] = False
            os.makedirs("cache", exist_ok=True)
            result.to_pickle(VALUE_SCORE_CACHE)
            st.markdown(
                '<div class="ov-alert ov-alert-success">✓ Scan complete — '
                f"{int(result['total_score'].notna().sum())}/{len(result)} scored."
                "</div>",
                unsafe_allow_html=True,
            )

    # Column labels for this page's tables live in the module-level
    # COLUMN_LABELS dict (near pnl_style/readable_df) alongside every other
    # page's, rather than a local copy here.

    # DECISION-relevant headline metrics only — excludes the 0-5 pillar
    # averages and sub-scores, which explain HOW a score was computed, not
    # WHAT to decide on (see the "Score breakdown" expander for that).
    RUBRIC_HEADLINE_COLS = {
        "general": ["roe", "debt_to_equity", "current_ratio", "revenue_cagr_pct", "fcf_yoy_pct", "peg"],
        "banking": ["roe", "roa", "nim_proxy_pct", "gross_npa_pct", "net_npa_pct", "advances_yoy_pct", "pat_yoy_pct"],
        "nbfc": ["roe", "roa", "debt_to_equity", "loan_yoy_pct", "pat_yoy_pct"],
        "general_insurance": [
            "roe",
            "roa",
            "combined_ratio_pct",
            "incurred_claim_ratio_pct",
            "premium_yoy_pct",
            "pat_yoy_pct",
        ],
        "life_insurance": ["roe", "premium_yoy_pct", "pat_yoy_pct"],
    }

    if "value_scores" not in st.session_state:
        st.info("Click **Run value score scan** to fetch XBRL filings and score the universe.")
        return
    vdf = st.session_state["value_scores"].copy()

    if sector == "All":
        shown = vdf
        seen_cols, numeric_cols = set(), []
        for rubric_cols in RUBRIC_HEADLINE_COLS.values():
            for c in rubric_cols:
                if c not in seen_cols and c in vdf.columns:
                    seen_cols.add(c)
                    numeric_cols.append(c)
    else:
        shown = vdf[vdf["rubric"] == sector]
        numeric_cols = [c for c in RUBRIC_HEADLINE_COLS.get(sector, []) if c in vdf.columns]

    def _pillar_coverage(row) -> str:
        """ "3/3", "1/2", etc -- pillars actually scored vs the rubric's
        full pillar count (scored + missing combined). A row can hit
        total_score=100 on a single available pillar (see
        _aggregate_pillars' "missing data lowers confidence, not the
        score" design) -- this is the caveat that travels with the score
        itself, not just in the separate incomplete-rows expander below,
        so a thin 100 can't be mistaken for a fully-graded one at a
        glance."""
        mp = row.get("missing_pillars") or []
        if not isinstance(mp, (list, tuple)):
            mp = []
        if "unsupported_taxonomy" in mp:
            return "Unsupported sector"
        if "error" in mp:
            return "Fetch error"
        ps = row.get("pillar_scores")
        ok = len(ps) if isinstance(ps, dict) else 0
        total = ok + len(mp)
        return f"{ok}/{total}" if total else "—"

    # Incomplete-pillar rows are demoted below every fully-scored row
    # (never let a thin, few-pillar 100 outrank a genuinely complete
    # assessment) -- ranked by total_score within each of those two
    # groups, same as before.
    shown = shown.copy()
    shown["pillar_coverage"] = shown.apply(_pillar_coverage, axis=1)
    shown["_incomplete"] = shown["missing_pillars"].apply(bool)
    shown = shown.sort_values(["_incomplete", "total_score"], ascending=[True, False])

    show_cols = ["total_score", "pillar_coverage", "rubric", *numeric_cols, "fiscal_year_end"]
    show_cols = [c for c in show_cols if c in shown.columns]

    with st.container(border=True, key="ov-card-fund-ranked"):
        st.markdown(
            '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
            '<span class="ov-dot" style="background:var(--ov-teal);">'
            f'</span>Ranked <span class="ov-badge ov-badge-gray">'
            f"{shown['total_score'].notna().sum()} / {len(shown)} scored</span>"
            f"{f' · {sector}' if sector != 'All' else ''}</p>",
            unsafe_allow_html=True,
        )
        fmt = dict.fromkeys(numeric_cols, "{:.2f}")
        rubric_badge = {
            "general": "ov-badge-purple",
            "banking": "ov-badge-blue",
            "nbfc": "ov-badge-pink",
            "general_insurance": "ov-badge-gray",
            "life_insurance": "ov-badge-gray",
        }

        def _score_badge_cls(v):
            return "ov-badge-green" if v >= 60 else "ov-badge-amber" if v >= 40 else "ov-badge-red"

        def _coverage_badge_cls(v):
            if v in ("Unsupported sector", "Fetch error"):
                return "ov-badge-red"
            if isinstance(v, str) and "/" in v:
                try:
                    ok, total = (int(x) for x in v.split("/"))
                except ValueError:
                    return "ov-badge-gray"
                return "ov-badge-gray" if total in (0, ok) else "ov-badge-amber"
            return "ov-badge-gray"

        shown_display = shown[show_cols].copy()
        shown_display.insert(0, "symbol", shown_display.index)
        if "total_score" in shown_display.columns:
            shown_display["total_score"] = shown_display["total_score"].apply(
                lambda v: round(v, 1) if pd.notna(v) else v
            )
        shown_page = _ov_page_slice(shown_display, key="fund_ranked")
        st.markdown(
            _ov_table_html(
                shown_page,
                sym_cols=["symbol"],
                num_fmt=fmt,
                badges={
                    "rubric": rubric_badge,
                    "total_score": _score_badge_cls,
                    "pillar_coverage": _coverage_badge_cls,
                },
            ),
            unsafe_allow_html=True,
        )
        _ov_pagination_controls(shown_display, key="fund_ranked")

    def _bucket_badge(v):
        try:
            n = float(v)
        except (TypeError, ValueError):
            return "ov-badge-gray"
        return "ov-badge-green" if n >= 4 else "ov-badge-amber" if n >= 2 else "ov-badge-red"

    col_score, col_buckets = st.columns(2)
    with col_score, st.container(border=True, key="ov-card-fund-breakdown"):
        bd1, bd2, bd3 = st.columns([1.9, 1.6, 2.5])
        with bd1:
            st.markdown(
                '<p class="ov-card-title" style="margin-bottom:0;border-bottom:0px solid var(--ov-border);">'
                '<span class="ov-dot" style="background:var(--ov-purple);"></span>'
                "Score breakdown</p>",
                unsafe_allow_html=True,
            )
        with bd2:
            sym_choice = st.selectbox(
                "Symbol", list(shown.index), key="value_score_detail_sym", label_visibility="collapsed"
            )
        if sym_choice:
            row = shown.loc[sym_choice]
            with bd3:
                st.markdown(
                    f'<p class="ov-card-meta" style="text-align:right;margin:6px 0 0;'
                    f'font-size:10px;font-weight:700;color:var(--ov-purple-d);">'
                    f"{row.get('rubric')} rubric · score {row.get('total_score')} · "
                    f"FY {row.get('fiscal_year_end', '—')}</p>",
                    unsafe_allow_html=True,
                )
            st.markdown(
                '<p class="ov-muted" style="margin-top:10px;font-size:10px;">Pillar scores (0-5)</p>',
                unsafe_allow_html=True,
            )
            pillar_scores = row.get("pillar_scores") or {}
            _pillar_rows = []
            for k, v in pillar_scores.items():
                _pct = min(100.0, max(0.0, float(v) / 5 * 100))
                _color = "#1d9e75" if v >= 4 else "#ef9f27" if v >= 2 else "#e24b4a"
                _pillar_rows.append(
                    '<div class="ov-sector-row"><div class="ov-sector-head">'
                    f"<span>{html_lib.escape(k.replace('_', ' ').title())}</span>"
                    f'<span class="ov-sym">{v:.1f}</span></div>'
                    f'<div class="ov-sector-bar"><div class="ov-sector-fill" '
                    f'style="width:{_pct:.1f}%;background:{_color};"></div></div></div>'
                )
            st.markdown("".join(_pillar_rows), unsafe_allow_html=True)
            if row.get("missing_pillars"):
                st.markdown(
                    f'<div class="ov-alert">Excluded from total (no data): {", ".join(row["missing_pillars"])}</div>',
                    unsafe_allow_html=True,
                )

    with col_buckets, st.container(border=True, key="ov-card-fund-buckets"):
        st.markdown(
            '<p class="ov-card-title" style="border-bottom:0px solid var(--ov-border);">'
            '<span class="ov-dot" '
            'style="background:var(--ov-teal);"></span>Sub-metric buckets (0-5)</p>',
            unsafe_allow_html=True,
        )
        if sym_choice:
            sub_scores = row.get("sub_scores") or {}
            sub_df = pd.DataFrame([{"Metric": k.replace("_", " ").title(), "Bucket": v} for k, v in sub_scores.items()])
            st.markdown(_ov_table_html(sub_df, badges={"Bucket": _bucket_badge}), unsafe_allow_html=True)

    incomplete = shown[shown["missing_pillars"].apply(bool)]
    with st.expander(f"Rows with incomplete data ({len(incomplete)})"):
        _incomplete_tip = html_lib.escape(
            "A pillar is excluded from the total (not defaulted) when "
            "none of its sub-metrics are available — usually means "
            "fewer than 2 years of annual filings are retrievable via "
            "NSE's endpoint for this name, or (for "
            "'unsupported_taxonomy') the sector isn't covered by any "
            "rubric yet."
        )
        st.markdown(
            f'<span class="ov-info-icon" title="{_incomplete_tip}">ℹ️ Why rows land here</span>', unsafe_allow_html=True
        )
        inc_cols = [*show_cols, "missing_pillars"]
        inc_display = incomplete[inc_cols].copy()
        inc_display.insert(0, "symbol", inc_display.index)
        inc_display["missing_pillars"] = inc_display["missing_pillars"].apply(
            lambda ps: ", ".join(ps) if isinstance(ps, (list, tuple)) else ps
        )
        st.markdown(_ov_table_html(inc_display, sym_cols=["symbol"]), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Page: Job Log
# ---------------------------------------------------------------------------

JOB_TYPES = ["rebalance_scan", "gap_check", "fundamentals_refresh", "screen_run", "backtest_run"]

# Mirrors deploy/vps/systemd/*.timer's OnCalendar schedules -- kept in sync
# by hand, not read from systemd itself (this dashboard process has no
# visibility into the VPS's timer state). weekdays: 0=Mon..6=Sun.
# screen_run/backtest_run have no entry -- both are manual-only buttons
# (Screener's "Run screen", Backtest's "Run backtest"), never scheduled.
_JOB_SCHEDULES = {
    "rebalance_scan": ([0, 1, 2, 3, 4], 14, 45),
    "gap_check": ([0, 1, 2, 3, 4], 9, 16),
    "fundamentals_refresh": ([0], 8, 0),
}


def _next_scheduled_run(job_type: str, now: dt.datetime | None = None) -> dt.datetime | None:
    """Next occurrence of job_type's systemd timer schedule, skipping NSE
    trading holidays (nse_holidays.py) on top of the timer's own weekday
    filter -- the timer itself fires on every Mon-Fri regardless of NSE
    holidays (systemd has no notion of them), so this is a display-only
    projection of when the job would next do something meaningful, not a
    claim about exactly when systemd will next invoke the service. None
    for a manual-only job type (no entry in _JOB_SCHEDULES)."""
    now = now or dt.datetime.now()
    sched = _JOB_SCHEDULES.get(job_type)
    if sched is None:
        return None
    weekdays, hour, minute = sched
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for _ in range(21):  # far enough to clear a holiday cluster + a weekly schedule
        if (
            candidate.weekday() in weekdays
            and candidate > now
            and not nse_holidays.is_trading_holiday(candidate.date())
        ):
            return candidate
        candidate = (candidate + dt.timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return None


def _format_next_run(job_type: str, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    nxt = _next_scheduled_run(job_type, now)
    if nxt is None:
        return "Manual only -- no schedule"
    if nxt.date() == now.date():
        when = f"today {nxt:%H:%M}"
    elif nxt.date() == (now + dt.timedelta(days=1)).date():
        when = f"tomorrow {nxt:%H:%M}"
    else:
        when = f"{nxt:%a %d %b} {nxt:%H:%M}"
    return f"Next: {when}"


def page_job_log():
    _joblog_tip = html_lib.escape(
        "Every scheduled job (systemd timers on the VPS) and manual "
        "background-job button writes a row here -- answers \"did today's "
        'jobs actually run" without SSH-ing in to read raw logs.'
    )
    st.markdown(
        '<div class="ov-header"><div><span class="ov-h1">🗂️ Job Log</span>'
        f'<span class="ov-info-icon" title="{_joblog_tip}">ℹ️</span></div></div>',
        unsafe_allow_html=True,
    )

    _job_tones = {"success": "green", "failed": "red", "running": "amber"}
    _job_cards = []
    for jt in JOB_TYPES:
        last = state_db.get_last_job_run(jt)
        label = COLUMN_LABELS.get(jt, jt)
        next_run_line = _format_next_run(jt)
        if last is None:
            _job_cards.append(_ov_metric_html(label, "never run", next_run_line, "", "coral"))
            continue
        started = dt.datetime.fromisoformat(last["started_at"])
        age_hr = (dt.datetime.now() - started).total_seconds() / 3600
        badge = {"success": "✅", "failed": "❌", "running": "⏳"}.get(last["status"], "❓")
        # error_message stores the FULL traceback (real debugging value in
        # the DB/expander below) -- but a raw multi-hundred-line dump in
        # this compact metric card is unreadable. A traceback's last
        # non-empty line is always "ExceptionType: message", so that alone
        # is what shows here; the full detail is one click away below.
        _err_msg = last.get("error_message") or ""
        _err_last_line = _err_msg.strip().splitlines()[-1] if _err_msg.strip() else ""
        note = last.get("summary") or _err_last_line
        note = f"{note}<br>{next_run_line}" if note else next_run_line
        _job_cards.append(
            _ov_metric_html(
                label,
                f"{badge} {age_hr:.1f}h ago",
                note,
                "ov-neg" if last["status"] == "failed" else "",
                _job_tones.get(last["status"], "coral"),
            )
        )
    st.markdown(f'<div class="ov-grid-metrics">{"".join(_job_cards)}</div>', unsafe_allow_html=True)

    st.divider()
    with st.container(border=True, key="ov-card-joblog-history"):
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" style="background:var(--ov-blue);"></span>History</p>',
            unsafe_allow_html=True,
        )
        f1, f2, f3 = st.columns(3)
        with f1:
            type_filter = st.multiselect("Job type", JOB_TYPES, key="jl_type_filter")
        with f2:
            status_filter = st.multiselect("Status", ["success", "failed", "running"], key="jl_status_filter")
        with f3:
            since_date = st.date_input("Since", value=dt.date.today() - dt.timedelta(days=30), key="jl_since")

        runs = state_db.get_job_runs(since=since_date.isoformat(), limit=1000)
        if type_filter:
            runs = runs[runs["job_type"].isin(type_filter)]
        if status_filter:
            runs = runs[runs["status"].isin(status_filter)]

        st.caption(f"Showing {len(runs)} run(s)")
        if runs.empty:
            st.info("No job runs match these filters.")
            return

        # error_message holds the FULL traceback (real value in the
        # "full error detail" expander below) -- dumping that raw into a
        # table cell blew up that row's height/width for every failed
        # run. Same last-non-empty-line truncation as the quick-glance
        # cards above; summary already stays blank on a failed run
        # (finish_job_run() only ever sets one or the other), so this
        # only ever fills in where summary was empty.
        _display_runs = runs.drop(columns=["id", "error_message"]).copy()
        _display_runs["summary"] = runs.apply(
            lambda r: (
                r["summary"]
                or (
                    str(r["error_message"]).strip().splitlines()[-1]
                    if pd.notna(r["error_message"]) and str(r["error_message"]).strip()
                    else ""
                )
            ),
            axis=1,
        )
        _display_page = _ov_page_slice(_display_runs, key="joblog_history", page_size=20)
        st.markdown(
            _ov_table_html(
                _display_page,
                num_fmt={"duration_sec": "{:.1f}s"},
                badges={
                    "status": {"success": "ov-badge-green", "failed": "ov-badge-red", "running": "ov-badge-amber"},
                    "trigger_type": {"scheduled": "ov-badge-blue", "manual": "ov-badge-purple"},
                },
            ),
            unsafe_allow_html=True,
        )
        _ov_pagination_controls(_display_runs, key="joblog_history", page_size=20)

    failed = runs[runs["status"] == "failed"]
    if not failed.empty:
        with st.expander(f"Failed runs -- full error detail ({len(failed)})"):
            for _, r in failed.iterrows():
                st.markdown(f"**{r['job_type']}** at {r['started_at']}")
                st.code(r["error_message"] or "(no error message captured)")


# ---------------------------------------------------------------------------
# Page: Rebalance History
# ---------------------------------------------------------------------------


def page_rebalance_history():
    _rh_tip = html_lib.escape(
        "Every sell/buy/top-up/stop-update ever proposed, across every "
        "rebalance run. Lifecycle: proposed -> executed | error (attempted, "
        "failed -- reason recorded) | expired (superseded by a newer scan "
        "before ever being acted on). Nothing here is ever deleted -- this "
        "is the full audit trail, not just what's currently pending (see "
        "Live Rebalance for that)."
    )
    st.markdown(
        '<div class="ov-header"><div><span class="ov-h1">📜 Rebalance History</span>'
        f'<span class="ov-info-icon" title="{_rh_tip}">ℹ️</span></div>'
        '<div class="ov-chips"><span class="ov-chip ov-chip-muted">proposed → '
        "executed | error | expired</span></div></div>",
        unsafe_allow_html=True,
    )

    with st.container(border=True, key="ov-card-rh-history"):
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            action_filter = st.multiselect("Action", ["sell", "buy", "top_up", "stop_update"], key="rh_action_filter")
        with f2:
            status_filter = st.multiselect(
                "Status", ["proposed", "executed", "error", "expired"], key="rh_status_filter"
            )
        with f3:
            symbol_filter = st.text_input("Symbol (exact)", key="rh_symbol_filter")
        with f4:
            since_date = st.date_input("Since", value=dt.date.today() - dt.timedelta(days=30), key="rh_since")

        hist = state_db.get_rebalance_history(
            status=status_filter or None,
            action_type=action_filter or None,
            symbol=symbol_filter.strip() or None,
            since=since_date.isoformat(),
            limit=1000,
        )

        st.caption(f"Showing {len(hist)} item(s)")
        if hist.empty:
            st.info("No rebalance items match these filters.")
            return

        st.markdown(
            _ov_table_html(
                hist.drop(columns=["error_message"]),
                sym_cols=["symbol"],
                num_fmt={"qty": "{:.0f}", "price": "₹{:.2f}"},
                badges={
                    "action_type": {
                        "sell": "ov-badge-red",
                        "buy": "ov-badge-green",
                        "top_up": "ov-badge-blue",
                        "stop_update": "ov-badge-purple",
                    },
                    "status": {
                        "proposed": "ov-badge-amber",
                        "executed": "ov-badge-green",
                        "error": "ov-badge-red",
                        "expired": "ov-badge-gray",
                    },
                },
            ),
            unsafe_allow_html=True,
        )

    errors = hist[hist["status"] == "error"]
    if not errors.empty:
        with st.expander(f"Errors — full detail ({len(errors)})"):
            for _, r in errors.iterrows():
                st.markdown(f"**{r['symbol']}** ({r['action_type']}) — run at {r['run_time']}")
                st.code(r["error_message"] or "(no error message captured)")


def _exit_type_label(reason) -> str:
    """Collapses a trades row's raw exit_reason into a short, scannable
    category for the Tradebook's separate Exit type column/filter -- the
    original exit_reason column/text is left untouched, this is additive.
    Only four kinds of value are ever actually written (state_db.close_trade()'s
    call sites): screener.sell_check()'s two long rank/gate-drop
    explanations (rebalance sells), and three fixed internal keys
    (gap_down_stop, manual_square_off, gtt_fill_or_external -- the last
    covers BOTH a GTT stop-loss firing silently at the broker and a
    manual sell made directly on Kite outside this app; the two can't be
    told apart from Kite's API, see reconciled_positions()'s own
    docstring). The full original text is unaffected in the downloaded
    CSV, which is built from the untransformed trades data."""
    if reason is None or (isinstance(reason, float) and pd.isna(reason)):
        return "—"
    reason = str(reason)
    fixed = {
        "gap_down_stop": "Stop (gap-down)",
        "manual_square_off": "Manual",
        "gtt_fill_or_external": "GTT / External",
    }
    if reason in fixed:
        return fixed[reason]
    if reason.startswith(("dropped out of top", "failed a technical gate")):
        return "Rebalance"
    # Unrecognized value (future/legacy data) -- show something readable
    # rather than silently mislabeling it one of the categories above.
    return reason.replace("_", " ").title() if "_" in reason and " " not in reason else reason


_EXIT_TYPE_BADGES = {
    "Rebalance": "ov-badge-blue",
    "Stop (gap-down)": "ov-badge-red",
    "GTT / External": "ov-badge-purple",
    "Manual": "ov-badge-gray",
}


# ---------------------------------------------------------------------------
# Page: Intraday Dashboard ("DaysLowVolumnBreakout" strategy)
# ---------------------------------------------------------------------------

_INTRADAY_EVENT_BADGES = {
    "signal_formed": "ov-badge-amber",
    "expired": "ov-badge-gray",
    "re_signaled": "ov-badge-amber",
    "invalidated": "ov-badge-gray",
    "triggered": "ov-badge-green",
    "target": "ov-badge-green",
    # ema5_trail_exit: kept for historical legs recorded before v5.4's
    # §5i.2 removed EMA5 from the trail decision -- no new leg will ever
    # be this type again, but old ones must still render correctly.
    "ema5_trail_exit": "ov-badge-green",
    "ema10_trail_exit": "ov-badge-green",
    # v5.4 §5b -- the runner's breakeven exit is neither a real win nor a
    # real loss (fills at entry, costs-only P&L) -- gray like the other
    # "wash/neutral" statuses, distinct from stop's red and a real exit's
    # green.
    "breakeven": "ov-badge-gray",
    # v5.4 §5i.3 -- always a losing exit by construction (only ever
    # checked/fired when the entry candle's own close already breached
    # the stop), same red as a normal stop.
    "entry_candle_close": "ov-badge-red",
    "stop": "ov-badge-red",
    "squareoff": "ov-badge-blue",
}

LIVE_TICK_STALE_SECONDS = 20  # fall back to a REST quote if the feed goes quiet this long


@st.cache_resource(show_spinner=False)
def _get_dashboard_ticker() -> live_ticker.LiveTicker:
    """One persistent WebSocket ticker for the whole Streamlit server
    process, NOT recreated on every rerun -- st.cache_resource is the
    idiom for exactly this (a resource that should survive Streamlit's
    own rerun-on-every-interaction model). mode="quote" so each tick
    carries ohlc.close, needed for the day-change % shown alongside
    every live price here (plain mode="ltp", what the intraday engine
    itself uses, has no ohlc). Starts with no tokens subscribed --
    _ensure_subscribed() below adds them lazily as symbols become
    relevant (NIFTY 50 up front; candidates/sectors once known)."""
    return live_ticker.LiveTicker({}, mode="quote")


def _ensure_subscribed(ticker: live_ticker.LiveTicker, symbols: list[str]) -> None:
    """Adds any of `symbols` not already subscribed (resolved via
    kite_client's equity or index instrument map, whichever has it) and
    connects the ticker on first real use -- st.cache_resource means
    this only actually does anything the first time a given symbol is
    requested across the whole process's lifetime, not on every rerun."""
    new_tokens = {}
    for sym in symbols:
        if sym in ticker.token_by_symbol:
            continue
        try:
            tok = kite_client.instrument_map().get(sym) or kite_client.index_instrument_map().get(sym)
        except Exception:
            tok = None
        if tok is not None:
            new_tokens[tok] = sym
    if new_tokens:
        ticker.add_tokens(new_tokens)
    if not ticker.started and ticker.tokens:
        ticker.start(timeout=8.0)


def _live_price_and_change(ticker: live_ticker.LiveTicker, symbol: str) -> tuple[float | None, float | None]:
    """Prefers a fresh live tick; falls back to a one-off REST quote if
    the feed hasn't produced a tick for this symbol yet (e.g. right
    after subscribing, or a stale/reconnecting feed) -- so a quiet patch
    in the feed can't leave the dashboard showing nothing."""
    token = ticker.token_by_symbol.get(symbol)
    if token is not None:
        age = ticker.last_tick_age(token)
        if age is not None and age <= LIVE_TICK_STALE_SECONDS:
            return ticker.get_ltp_and_change(token)
    try:
        q = kite_client.get_quote_with_change([symbol]).get(symbol)
    except Exception:
        q = None
    return (q["last_price"], q["change_pct"]) if q else (None, None)


_INTRADAY_CHART_WARMUP_DAYS = 45  # enough for EMA21 to have converged well
# past its 21-bar min_periods without paying EMA_WARMUP_DAYS=120's full
# fetch cost for what's purely a visual reference line here, not a
# trading decision (see intraday_strategy.ema21()'s own continuous-
# series requirement -- this chart still respects it, just with a
# shorter, display-only warmup window).


# TradingView-style palette -- more saturated/higher-contrast than the
# earlier plain green/red, distinct from the ov-pos/ov-neg colors used
# elsewhere on the page so the chart doesn't visually blend into the
# surrounding metric text.
_CHART_UP, _CHART_DOWN = "#26a69a", "#ef5350"


@st.cache_data(ttl=15, show_spinner=False)
def _cached_intraday_hist(symbol: str, days: int) -> pd.DataFrame:
    """Historical 5-min candles are a real Kite REST call, unlike the LTP
    reads elsewhere on this page which just read the WebSocket ticker's
    in-memory tick cache (free). Caching this for a short TTL is what
    lets _render_chart_and_tradebook_section() rerun once a second (to
    keep the live-tick candle as fresh as every other live price on this
    page) without turning that into one Kite historical-data call per
    second per open chart -- cache_data is shared across all sessions on
    this server process, so concurrent viewers don't multiply the calls
    either. Nothing about the actual current candle depends on this --
    that part is always built fresh from the live ticker, never cached."""
    return kite_client.fetch_intraday_candles(symbol, days=days, interval="5minute")


def _build_intraday_candle_figure(
    symbol: str,
    direction: str,
    today: dt.date,
    first_low: float | None,
    first_high: float | None,
    sig: dict | None,
    pos: dict | None,
    live_candle: dict | None = None,
) -> go.Figure | None:
    """5-min candlestick + volume for `symbol`'s session today, with the
    strategy's own decision levels overlaid -- EMA21 (continuous line),
    the 09:15 first-candle low/high (Spec v2 §3.2 step 1b), and either
    the active signal's breakout trigger + would-be stop, or the real
    entry/stop/target once a position is open. Returns None if no candle
    data is available yet (e.g. called before 09:15).

    live_candle: optional {"open","high","low","close","volume"} for the
    CURRENTLY FORMING 5-min bar, built tick-by-tick by the caller from
    live LTP (see _render_chart_and_tradebook_section()) -- Kite's
    historical API only ever returns CLOSED candles, so without this the
    chart visibly stalls for up to 5 minutes at a time instead of moving
    with the live price."""
    try:
        hist = _cached_intraday_hist(symbol, _INTRADAY_CHART_WARMUP_DAYS)
    except Exception:
        return None
    if hist.empty:
        return None
    ema21_series = istrat.ema21(hist["close"])
    today_candles = hist[hist.index.normalize() == pd.Timestamp(today)]
    if today_candles.empty and live_candle is None:
        return None

    plot_df = today_candles
    ema21_today = ema21_series.reindex(today_candles.index)
    if live_candle is not None:
        live_ts = pd.Timestamp(live_candle["ts"])
        live_row = pd.DataFrame(
            [
                {
                    "open": live_candle["open"],
                    "high": live_candle["high"],
                    "low": live_candle["low"],
                    "close": live_candle["close"],
                    "volume": live_candle["volume"],
                }
            ],
            index=[live_ts],
        )
        plot_df = pd.concat([today_candles[today_candles.index != live_ts], live_row]).sort_index()
        # EMA21 "as of now" for the live bar -- close enough for a moving
        # visual reference (this is display-only, never a trading
        # decision): continue the series forward using the live close.
        #
        # .get(live_ts) on a Series can return a Series (not a scalar!)
        # if live_ts happens to be duplicated in the reindexed result --
        # a real race right at candle close, where Kite's historical API
        # may already carry this exact boundary as a closed candle while
        # this function's caller still treats it as "live" (confirmed
        # live 2026-09-18: a stray Series here poisoned the y-range
        # min()/max() below with "truth value of a Series is ambiguous").
        # Selecting .iloc[-1] after filtering to just this timestamp's
        # row(s) guarantees a plain scalar either way.
        _ema_reindexed = ema21_series.reindex(hist.index.append(pd.Index([live_ts]))).ffill()
        _ema_at_live_ts = _ema_reindexed[_ema_reindexed.index == live_ts]
        _live_ema = float(_ema_at_live_ts.iloc[-1]) if not _ema_at_live_ts.empty else None
        ema21_today = pd.concat(
            [ema21_today[ema21_today.index != live_ts], pd.Series([_live_ema], index=[live_ts])]
        ).sort_index()

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(
        go.Candlestick(
            x=plot_df.index,
            open=plot_df["open"],
            high=plot_df["high"],
            low=plot_df["low"],
            close=plot_df["close"],
            name=symbol,
            increasing_line_color=_CHART_UP,
            decreasing_line_color=_CHART_DOWN,
            increasing_fillcolor=_CHART_UP,
            decreasing_fillcolor=_CHART_DOWN,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=plot_df.index, y=ema21_today, mode="lines", name="EMA21", line={"color": "#7b3294", "width": 1.5}),
        row=1,
        col=1,
    )
    if "volume" in plot_df.columns:
        vol_colors = [
            _CHART_UP if c >= o else _CHART_DOWN for o, c in zip(plot_df["open"], plot_df["close"], strict=False)
        ]
        fig.add_trace(
            go.Bar(x=plot_df.index, y=plot_df["volume"], marker_color=vol_colors, opacity=0.6, name="Volume"),
            row=2,
            col=1,
        )

    _level_values = []

    def _hline(y, color, label, dash="dot"):
        if y is not None and pd.notna(y):
            fig.add_hline(
                y=float(y),
                line_color=color,
                line_dash=dash,
                line_width=1.25,
                annotation_text=label,
                annotation_position="right",
                annotation_font_size=10,
                row=1,
                col=1,
            )
            _level_values.append(float(y))

    _hline(first_low, "#9e9e9e", "09:15 low")
    _hline(first_high, "#9e9e9e", "09:15 high")
    if pos is not None:
        # Entry marked as an arrow ON the actual entry candle (not a
        # line stretched across the whole day) -- stop/target stay as
        # dotted reference lines at the real price level, since those
        # ARE prices the position is still exposed to for the rest of
        # the day, unlike entry which is a one-time past event.
        _is_long = direction == istrat.LONG
        fig.add_annotation(
            x=pd.Timestamp(pos["entry_time"]),
            y=float(pos["entry_price"]),
            xref="x",
            yref="y",
            text="entry",
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowwidth=1.5,
            arrowcolor="#2166ac",
            ax=0,
            ay=28 if _is_long else -28,
            font={"size": 10, "color": "#2166ac"},
            bgcolor="rgba(255,255,255,0.85)",
            row=1,
            col=1,
        )
        _level_values.append(float(pos["entry_price"]))
        _hline(pos["stop_price"], _CHART_DOWN, "stop", dash="dot")
        _hline(pos["target_price"], _CHART_UP, "target", dash="dot")
    elif sig is not None:
        # Signal candle's own high/low -- shown as a shaded box spanning
        # just that ONE candle's x-range, not full-width hlines, since
        # signal_high/signal_low sit only ~5% of ATR away from the
        # trigger/stop-if-triggered levels below and would collide with
        # their labels if drawn the same way. A box also directly answers
        # the v5 gated-2nd-candle rule's own question (spec S2): did the
        # next candle's high/low stay CONTAINED within this box, or did
        # it poke outside without triggering -- that visual containment
        # is exactly what the color+volume+range gate is checking.
        _sig_ts = pd.Timestamp(sig["signal_time"])
        fig.add_shape(
            type="rect",
            xref="x",
            yref="y",
            x0=_sig_ts,
            x1=_sig_ts + pd.Timedelta(minutes=5),
            y0=sig["signal_low"],
            y1=sig["signal_high"],
            fillcolor="rgba(92,107,192,0.15)",
            line={"color": "#5c6bc0", "width": 1.25},
            row=1,
            col=1,
        )
        fig.add_annotation(
            x=_sig_ts + pd.Timedelta(minutes=5),
            y=sig["signal_high"],
            xref="x",
            yref="y",
            text="signal candle",
            showarrow=False,
            font={"size": 9, "color": "#5c6bc0"},
            xanchor="left",
            yanchor="bottom",
            row=1,
            col=1,
        )
        _level_values.append(float(sig["signal_high"]))
        _level_values.append(float(sig["signal_low"]))

        # Trigger / stop-if-triggered stay as full-width hlines (unlike
        # the signal box, these matter for the ENTIRE rest of the window,
        # not just one candle) -- "trigger" and "stop if triggered" are
        # the two levels that actually matter for what happens next,
        # kept visually distinct from each other and from the box above.
        buf = sig["signal_atr"] * istrat.ATR_PCT_BUFFER
        if direction == istrat.LONG:
            trigger, would_be_stop = sig["signal_high"] + buf, sig["signal_low"] - buf
        else:
            trigger, would_be_stop = sig["signal_low"] - buf, sig["signal_high"] + buf
        _hline(trigger, "#e6a817", "entry trigger", dash="dash")
        _hline(would_be_stop, _CHART_DOWN, "stop if triggered", dash="dot")

    fig.update_layout(
        height=460,
        margin={"l": 10, "r": 70, "t": 20, "b": 10},
        showlegend=False,
        plot_bgcolor="white",
        paper_bgcolor="white",
        bargap=0.15,
        # Without this, every 15s auto-refresh hands Plotly a brand-new
        # figure and it forgets any zoom/pan the user just did. Keying
        # it on the symbol (not a constant) means switching the chart
        # dropdown still resets to a fresh full-day view.
        uirevision=symbol,
    )
    fig.update_xaxes(rangeslider_visible=False, showgrid=True, gridcolor="#eeeeee", row=1, col=1)
    fig.update_xaxes(showgrid=False, row=2, col=1)
    # STICKY y-range instead of Plotly's default autorange -- autorange
    # recomputes the tightest possible bounds on EVERY call, so a live
    # tick nudging the still-forming candle's high/low by even a few
    # paise shifted the whole visible price scale, making every candle
    # appear to jump/redraw each second even though only that one
    # candle's data actually changed (uirevision only preserves a
    # user's own manual zoom, it doesn't stop autorange from
    # recomputing on new data). Cached in session_state per symbol/day
    # and only ever WIDENED, never recentered/shrunk, the same ratchet
    # idea as the MAD trail stop -- so the axis, and hence the whole
    # chart, only actually moves when price genuinely approaches the
    # edge of the current range, not on every tick's tiny wiggle.
    _price_values = pd.concat([plot_df["high"], plot_df["low"], ema21_today]).dropna()
    if _level_values:
        _price_values = pd.concat([_price_values, pd.Series(_level_values)])
    # Defensive: coerce to plain numeric and drop anything that doesn't
    # convert cleanly, so a stray non-scalar value sneaking in here some
    # other way degrades to "skip the fixed range for this tick" rather
    # than crashing the whole chart (this is display-only sizing, never
    # a trading decision -- safe to just fall back).
    _price_values = pd.to_numeric(_price_values, errors="coerce").dropna()
    if not _price_values.empty:
        _pmin, _pmax = float(_price_values.min()), float(_price_values.max())
        _pad = max((_pmax - _pmin) * 0.10, _pmax * 0.005, 0.5)
        _range_key = f"_intraday_chart_yrange_{symbol}_{today}"
        _stored = st.session_state.get(_range_key)
        if _stored is None or _pmin - _pad < _stored[0] or _pmax + _pad > _stored[1]:
            _stored = [
                min(_pmin - _pad, _stored[0]) if _stored else _pmin - _pad,
                max(_pmax + _pad, _stored[1]) if _stored else _pmax + _pad,
            ]
            st.session_state[_range_key] = _stored
        fig.update_yaxes(range=_stored, row=1, col=1)
    fig.update_yaxes(title_text="Price (₹)", showgrid=True, gridcolor="#eeeeee", row=1, col=1)
    fig.update_yaxes(title_text="Vol", showgrid=False, row=2, col=1)
    return fig


def page_intraday_dashboard():
    _mode = "live" if config.STRATEGY.get("intraday_live_enabled", False) else "paper"
    _tip = html_lib.escape(
        "The DaysLowVolumnBreakout intraday strategy (v5.4 §5i, paper-trading "
        "trial of the disputed top-5 finding -- see the v5.4 spec §0) -- "
        "day-bias from NIFTY 50 breadth, a top-5 F&O momentum candidate pool "
        "(only 2 trade slots/day) with a 09:15 overnight-gap filter "
        "(candidates gapping >5% from prior close are skipped, backfilled from "
        "the next-best ranked candidate), a low-volume pullback signal (09:25 "
        "window) gated one-sided (§5i.1: the signal candle's own body must not "
        "have broken the 09:20/09:25 range on the trade's own side), a "
        "genuinely real-time gated-2-candle breakout entry (only a price-cross "
        "fires entry; color/volume/range only ever gate whether an already-"
        "closed candle gets a 2nd chance), a lower-volume re-signal that can "
        "happen at most once per signal, sector confirmation gate. Exit: the "
        "original stop protects the whole position until the first half books; "
        "on touching the 1:2R target the first half is not sold there but "
        "deferred and trailed on EMA10 (§5i.2 -- EMA5 is no longer consulted), "
        "sold on the first candle closing through it (filled at the next "
        "candle's open); once that half books, the runner's stop moves to "
        "breakeven (§5b, entry price) instead of the original stop; the rest "
        "squares off at 15:10. Paper mode simulates every fill with zero real "
        "orders; switching to live is a separate, deliberate step (Admin)."
    )
    _mode_badge = (
        '<span class="ov-badge ov-badge-red">🔴 LIVE</span>'
        if _mode == "live"
        else '<span class="ov-badge ov-badge-blue">📝 PAPER</span>'
    )
    st.markdown(
        f'<div class="ov-header"><div><span class="ov-h1">⚡ Intraday Dashboard</span>'
        f'<span class="ov-info-icon" title="{_tip}">ℹ️</span></div>'
        f'<div class="ov-chips">{_mode_badge}'
        f'<span class="ov-chip ov-chip-muted">{dt.date.today():%d %b %Y}</span></div></div>',
        unsafe_allow_html=True,
    )

    today = dt.date.today().isoformat()
    cap = idb.get_capital(_mode)

    # --- Capital / P&L strip -------------------------------------------------
    legs_today = idb.get_legs(date=today, mode=_mode)
    today_pnl = float(legs_today["net_pnl"].sum()) if not legs_today.empty else 0.0
    current_capital = cap["current_capital"] if cap else None
    cum_pnl = (current_capital - cap["starting_capital"]) if cap else None
    metrics = [
        _ov_metric_html(
            "Capital (compounding)",
            f"₹{current_capital:,.0f}" if current_capital is not None else "—",
            f"started at ₹{cap['starting_capital']:,.0f}" if cap else "not seeded yet",
        ),
        _ov_metric_html(
            "Today's P&L",
            f"₹{today_pnl:+,.2f}" if legs_today is not None else "—",
            f"{len(legs_today)} leg(s) closed today" if not legs_today.empty else "nothing closed yet",
            value_cls=("ov-pos" if today_pnl >= 0 else "ov-neg"),
        ),
        _ov_metric_html(
            "Cumulative P&L",
            f"₹{cum_pnl:+,.2f}" if cum_pnl is not None else "—",
            "since inception",
            value_cls=("ov-pos" if (cum_pnl or 0) >= 0 else "ov-neg"),
        ),
    ]
    st.markdown(f'<div class="ov-grid-metrics">{"".join(metrics)}</div>', unsafe_allow_html=True)

    st.divider()

    # 3s, not 1s -- this fragment rebuilds the candidate table via
    # st.markdown(html, unsafe_allow_html=True), which always replaces the
    # ENTIRE table's DOM in one shot (there's no per-cell patching for raw
    # HTML the way st.plotly_chart can diff a keyed component) -- at 1s
    # that read as the whole table flickering every second just to move a
    # couple of LTP/% digits. 3s keeps prices reasonably fresh for a
    # decision-support table (the actual trading logic reacts via the
    # engine process's own live tick feed, independent of what this page
    # visually shows) while cutting both the flicker and the per-candidate
    # DB query load by roughly 3x.
    @st.fragment(run_every="3s" if _is_market_hours() else None)
    def _render_live_section():
        # `day` MUST be fetched here, every rerun -- not once outside this
        # fragment -- or it goes stale the moment intraday_days first gets
        # its row written at 09:30: a page loaded/left open before that
        # (day=None captured once) would keep rendering with day=None
        # forever after, even as `candidates` below (fetched fresh inside
        # the fragment) starts returning real rows -- crashing the sector-
        # gate display's `day["day_bias"]` lookup with day=None (confirmed
        # live 2026-09-17, right around today's own 09:30 selection).
        day = idb.get_day(today)
        # Persistent WebSocket ticker for this whole server process (see
        # _get_dashboard_ticker()) -- NIFTY 50 is always wanted; candidates/
        # sectors get subscribed below once known, each only actually
        # triggering a new subscription the first time it's seen. Without
        # this whole section living inside a fragment, ticks would update
        # the ticker's in-memory cache correctly but the PAGE itself would
        # never re-render to show it -- Streamlit only reruns on user
        # interaction otherwise, so the price would look frozen even
        # though the underlying feed was live the whole time (confirmed
        # live 2026-09-15).
        ticker = _get_dashboard_ticker()
        _ensure_subscribed(ticker, ["NIFTY 50"])

        # --- NIFTY 50: price + both breadth numbers -----------------------------
        col_nifty, col_bias = st.columns(2)
        with col_nifty, st.container(border=True, key="ov-card-intraday-nifty"):
            st.markdown(
                '<p class="ov-card-title"><span class="ov-dot" style="background:var(--ov-blue);"></span>NIFTY 50</p>',
                unsafe_allow_html=True,
            )
            nifty_price, nifty_chg = _live_price_and_change(ticker, "NIFTY 50")
            try:
                live_ad = imkt.fetch_advance_decline("NIFTY 50")
            except Exception:
                live_ad = None
            c1, c2 = st.columns(2)
            if nifty_price is not None:
                c1.metric(
                    "Current price", f"₹{nifty_price:,.2f}", f"{nifty_chg:+.2f}%" if nifty_chg is not None else None
                )
            else:
                c1.metric("Current price", "—")
            if live_ad:
                c2.metric(
                    "NSE live A/D (whole day)",
                    f"{live_ad['advances']} / {live_ad['declines']}",
                    help="NSE's own live, continuously-updating breadth (advancers/decliners "
                    "vs previous close, as of right now) -- informational only, NOT what "
                    "today's day-bias was computed from. Compare against \"Code A/D "
                    '(first-15m)" on the card to the right, same advancers/decliners '
                    "format -- the two measure genuinely different windows (whole day so "
                    "far vs. frozen at 09:30), so they're expected to differ, sometimes "
                    "substantially, especially later in the day.",
                )
            else:
                c2.metric("NSE live A/D (whole day)", "—")

        with col_bias, st.container(border=True, key="ov-card-intraday-bias"):
            st.markdown(
                '<p class="ov-card-title"><span class="ov-dot" style="background:var(--ov-purple);">'
                "</span>Today's day-bias (locked at 09:30)</p>",
                unsafe_allow_html=True,
            )
            if day is None:
                st.info("No selection recorded yet today -- the engine runs this once, at 09:30.")
            elif day["day_bias"] is None:
                _adv, _dec = day.get("advancers"), day.get("decliners")
                _ad_text = f" ({int(_adv)} / {int(_dec)})" if pd.notna(_adv) and pd.notna(_dec) else ""
                st.warning(
                    f"⚠️ No trade today -- NIFTY 50 first-15-min ratio was "
                    f"{day['nifty_ratio']:.2f}{_ad_text} (needs >{istrat.BIAS_RATIO_LONG_MIN} "
                    f"for LONG or <{istrat.BIAS_RATIO_SHORT_MAX} for SHORT)."
                )
            else:
                bias_tone = "green" if day["day_bias"] == "LONG" else "red"
                bias_cls = "ov-pos" if day["day_bias"] == "LONG" else "ov-neg"
                _bias_box = _ov_metric_html("Day bias", day["day_bias"], tone=bias_tone, value_cls=bias_cls)
                _ratio_box = _ov_metric_html("Ratio", f"{day['nifty_ratio']:.2f}")
                # Same advancers/decliners format as the NSE live A/D box
                # on the NIFTY 50 card to the left, so the two can be
                # diffed at a glance -- these measure different windows
                # (frozen at 09:30 vs continuously updating), so they're
                # expected to differ, not a sign either one is wrong.
                _adv, _dec = day.get("advancers"), day.get("decliners")
                _ad_val = f"{int(_adv)} / {int(_dec)}" if pd.notna(_adv) and pd.notna(_dec) else "—"
                _code_ad_box = _ov_metric_html("Code A/D (first-15m, @09:30)", _ad_val)
                st.markdown(
                    f'<div class="ov-grid-metrics">{_bias_box}{_ratio_box}{_code_ad_box}</div>', unsafe_allow_html=True
                )

        # --- Today's candidates (v5.4: top-5 pool + gap filter, 2 trade slots) ---
        st.markdown(
            '<p class="ov-card-title" style="margin-top:16px;"><span class="ov-dot" '
            f'style="background:var(--ov-teal);"></span>Today\'s candidates '
            f'<span class="ov-card-meta">(top-{istrat.TOP_N_CANDIDATES} pool, '
            f"{istrat.MAX_TRADES_PER_DAY} trade slots)</span></p>",
            unsafe_allow_html=True,
        )
        candidates = idb.get_candidates(today)
        if candidates.empty:
            st.info("No candidates selected yet today.")
        else:
            # v3 Spec §4 -- only MAX_TRADES_PER_DAY of the pool ever actually
            # trade (first to confirm, in rank order on ties); this counts
            # real positions opened today, not just candidates evaluated.
            _today_positions = idb.get_positions(date=today, mode=_mode)
            _slots_filled = int(_today_positions["symbol"].nunique()) if not _today_positions.empty else 0
            _slots_cls = "ov-pos" if _slots_filled < istrat.MAX_TRADES_PER_DAY else "ov-neg"
            st.markdown(
                f'<p class="ov-card-meta">Trade slots: '
                f'<span class="{_slots_cls}">{_slots_filled}/{istrat.MAX_TRADES_PER_DAY} filled</span></p>',
                unsafe_allow_html=True,
            )

            _ensure_subscribed(ticker, list(candidates["symbol"]))
            # A compact data table (one row per candidate, fixed columns) --
            # a card grid can't help but vary in height/content per card
            # (a "Position open" state has 4x the numbers a plain "No
            # signal yet" one does), which read as inconsistent no matter
            # how the cards themselves were tightened. A table's rows are
            # structurally uniform regardless of content, matching a
            # standard broker "Market Watch" panel.
            _table_rows = []
            for _, c in candidates.iterrows():
                cand_price, cand_chg = _live_price_and_change(ticker, c["symbol"])
                sector = c.get("sector")
                if pd.isna(sector):
                    sector = None

                sig = idb.get_active_signal(today, c["symbol"])
                open_pos = idb.get_open_positions(date=today, mode=_mode)
                open_pos = open_pos[open_pos["symbol"] == c["symbol"]]
                _p = open_pos.iloc[0] if not open_pos.empty else None
                state, detail = "No signal yet", ""
                if _p is not None:
                    state = "Position open"
                    detail = (
                        f"Entry ₹{_p['entry_price']:.2f} / Stop ₹{_p['stop_price']:.2f} / "
                        f"Target ₹{_p['target_price']:.2f} / Qty "
                        f"{int(_p['qty_remaining'])}/{int(_p['qty'])}"
                    )
                    # v5.2 EMA-trail: once the 1:2R target is touched the
                    # first-half booking is deferred and trailed -- surface
                    # that instead of leaving "Target" looking untouched.
                    if (
                        pd.notna(_p.get("target_touch_time"))
                        and pd.notna(_p.get("trail_ema"))
                        and int(_p["qty_remaining"]) == int(_p["qty"])
                    ):
                        detail += (
                            f" · target touched {pd.Timestamp(_p['target_touch_time']):%H:%M}, "
                            f"trailing EMA{int(_p['trail_ema'])} "
                            f"(1st half sells on a close through it)"
                        )
                elif sig is not None:
                    _buf = sig["signal_atr"] * istrat.ATR_PCT_BUFFER
                    _proj_entry = (
                        sig["signal_high"] + _buf
                        if day and day["day_bias"] == istrat.LONG
                        else sig["signal_low"] - _buf
                    )
                    # The sector gate is only ENFORCED at the moment a
                    # breakout actually triggers (_open_position_from_
                    # trigger()) -- the engine keeps tracking/forming
                    # signals for every candidate regardless of its sector
                    # outcome, resolved once at 09:30, and only rejects it
                    # right at the trigger instant (candidate "status" in
                    # the DB only flips to sector_gate_failed then, not
                    # now). So a candidate can sit here showing "Signal
                    # active" even though its own gate column already says
                    # FAIL -- without calling that out, it looks like a
                    # live, actionable setup when any trigger it produces
                    # will actually be silently rejected.
                    if c.get("sector_gate_pass") is False:
                        state = "Signal active (sector already failed)"
                        detail = (
                            f"H/L ₹{sig['signal_high']:.2f}/₹{sig['signal_low']:.2f} → would-be "
                            f"entry ₹{_proj_entry:.2f} -- won't open, sector gate already failed"
                        )
                    else:
                        state = "Signal active"
                        detail = (
                            f"H/L ₹{sig['signal_high']:.2f}/₹{sig['signal_low']:.2f} → entry "
                            f"₹{_proj_entry:.2f} · formed {pd.Timestamp(sig['signal_time']):%H:%M}"
                        )
                else:
                    all_positions_today = idb.get_positions(date=today, mode=_mode)
                    sym_positions = (
                        all_positions_today[all_positions_today["symbol"] == c["symbol"]]
                        if not all_positions_today.empty
                        else all_positions_today
                    )
                    if not sym_positions.empty and (sym_positions["status"] == "closed").all():
                        state = "Day closed"
                    elif c.get("status") == "invalidated":
                        state, detail = "Invalidated", "EMA21 / first-candle gate fired"
                    elif c.get("status") == "sector_gate_failed":
                        _sr = c.get("sector_ratio")
                        # A sector ratio can legitimately be infinite (zero
                        # decliners among its constituents, see
                        # intraday_market.compute_first15_breadth()'s own
                        # docstring) -- ".2f" on float("inf") literally
                        # prints the string "inf", so special-case it
                        # rather than let that leak into the UI.
                        if pd.isna(_sr):
                            _sr_text = "no data"
                        elif math.isinf(_sr):
                            _sr_text = "∞"
                        else:
                            _sr_text = f"{_sr:.2f}"
                        state = "Sector gate failed"
                        detail = f"Triggered, ratio {_sr_text} didn't confirm"
                    elif c.get("status") == "day_slots_filled":
                        state, detail = "Slots filled", "Other candidates confirmed first"
                    elif dt.datetime.now().time() > istrat.NEW_SIGNAL_CUTOFF:
                        state, detail = "No signal formed", f"Search closed {istrat.NEW_SIGNAL_CUTOFF:%H:%M}"

                _sgp = c.get("sector_gate_pass")
                _sr = c.get("sector_ratio")
                if pd.notna(_sgp) and day is not None:
                    _verdict = "PASS" if _sgp else "FAIL"
                    if pd.isna(_sr):
                        gate = f"{_verdict} —"
                    elif math.isinf(_sr):
                        # Zero decliners among the sector's constituents --
                        # a genuinely infinite ratio (compute_first15_
                        # breadth()'s own documented behavior), not a bug;
                        # ".2f" would otherwise print the literal "inf".
                        gate = f"{_verdict} ∞"
                    else:
                        gate = f"{_verdict} {_sr:.2f}"
                else:
                    gate = "—"

                _gap = c.get("gap_pct")
                _table_rows.append(
                    {
                        "cand_rank": int(c["rank"]),
                        "symbol": c["symbol"],
                        "cand_sector": sector or "—",
                        "ret_first15_pct": float(c["ret_first15_pct"]),
                        "gap_pct": float(_gap) if pd.notna(_gap) else float("nan"),
                        "ltp": cand_price if cand_price is not None else float("nan"),
                        "chg_pct": cand_chg if cand_chg is not None else float("nan"),
                        "gate": gate,
                        "state": state,
                        "detail": detail or "—",
                    }
                )

            _tdf = pd.DataFrame(_table_rows)
            st.markdown(
                _ov_table_html(
                    _tdf,
                    columns=[
                        "cand_rank",
                        "symbol",
                        "cand_sector",
                        "ret_first15_pct",
                        "gap_pct",
                        "ltp",
                        "chg_pct",
                        "gate",
                        "state",
                        "detail",
                    ],
                    sym_cols=["symbol"],
                    pnl_cols=["ret_first15_pct", "chg_pct"],
                    num_fmt={
                        "ret_first15_pct": "{:+.2f}%",
                        "gap_pct": "{:+.2f}%",
                        "ltp": "₹{:,.2f}",
                        "chg_pct": "{:+.2f}%",
                    },
                    badges={
                        "gate": lambda v: (
                            "ov-badge-green"
                            if v.startswith("PASS")
                            else "ov-badge-red"
                            if v.startswith("FAIL")
                            else "ov-badge-gray"
                        ),
                        "state": {
                            "Position open": "ov-badge-green",
                            "Signal active": "ov-badge-amber",
                            "Signal active (sector already failed)": "ov-badge-gray",
                            "Invalidated": "ov-badge-red",
                            "Sector gate failed": "ov-badge-red",
                            "Day closed": "ov-badge-gray",
                            "Slots filled": "ov-badge-gray",
                            "No signal formed": "ov-badge-gray",
                            "No signal yet": "ov-badge-gray",
                        },
                    },
                ),
                unsafe_allow_html=True,
            )

    _render_live_section()

    # --- Live chart + today's trade book -------------------------------------
    # 3s, not 1s -- Streamlit visually highlights/pulses a fragment's
    # ENTIRE bounding box on every one of its reruns (its own built-in
    # signal that a background update just happened), independent of how
    # efficiently the content inside actually updates. At 1s that read as
    # the whole chart card pulsing continuously, on top of (not fixed by)
    # the plotly key= and sticky y-range work, which only control what
    # happens to the chart's OWN content during a rerun, not whether the
    # fragment reruns in the first place. 3s (matching the candidate
    # table's own cadence) keeps the still-forming candle reasonably live
    # while cutting that visible pulse rate by a third.
    @st.fragment(run_every="3s" if _is_market_hours() else None)
    def _render_chart_and_tradebook_section():
        # Fetched fresh here, not read from the sibling _render_live_
        # section()'s own `day` -- that's a local variable scoped to
        # THAT function's own closure, not visible to this one, even
        # though both are nested inside page_intraday_dashboard() (confirmed
        # live: "name 'day' is not defined"). Same freshness rationale as
        # that function's own fetch: don't let this go stale across reruns.
        day = idb.get_day(today)
        _cands_now = idb.get_candidates(today)
        if _cands_now.empty:
            return
        _open_now = idb.get_open_positions(date=today, mode=_mode)
        # v5.4: TOP_N_CANDIDATES (5) no longer equals MAX_TRADES_PER_DAY
        # (still 2) -- up to 5 candidates get scanned, but only ever 2
        # can hold a position. Fixed 2-wide side-by-side charts (v5.3's
        # layout) doesn't fit that anymore. Split instead: any OPEN
        # POSITION (there are at most 2, by construction) always gets
        # its own dedicated chart, since that's the most actionable
        # thing on the page; a separate dropdown below covers whichever
        # of the day's other (not-yet/never-traded) candidates you want
        # to watch, without needing up to 5 permanently-visible panels.
        _syms = list(_cands_now["symbol"])
        _open_syms = list(_open_now["symbol"]) if not _open_now.empty else []
        _watch_syms = [s for s in _syms if s not in _open_syms]
        _ticker = _get_dashboard_ticker()
        _ensure_subscribed(_ticker, _syms)
        _direction = day["day_bias"] if day is not None else istrat.LONG

        def _render_one_chart(sym: str) -> None:
            with st.container(border=True, key=f"ov-card-intraday-chart-{sym}"):
                st.markdown(f'<p class="ov-card-title">{html_lib.escape(sym)}</p>', unsafe_allow_html=True)
                _sel_sig = idb.get_active_signal(today, sym)
                _sel_pos_df = _open_now[_open_now["symbol"] == sym] if not _open_now.empty else _open_now
                _sel_pos = _sel_pos_df.iloc[0].to_dict() if not _sel_pos_df.empty else None

                # Live, tick-by-tick current (still-forming) candle -- Kite's
                # historical API only ever returns CLOSED 5-min bars, so
                # without this the chart visibly freezes for up to 5 minutes
                # at a stretch instead of moving with the live price. Tracked
                # in session_state (persists across this fragment's own
                # reruns, keyed per symbol), reset the moment a new 5-min
                # window starts.
                _ltp, _ = _live_price_and_change(_ticker, sym)
                _now = dt.datetime.now()
                _cur_boundary = _now.replace(second=0, microsecond=0) - dt.timedelta(minutes=_now.minute % 5)
                _live_key = f"_intraday_live_candle_{sym}_{today}"
                _live_state = st.session_state.get(_live_key)
                _live_candle = None
                if _ltp is not None and _is_market_hours():
                    if _live_state is None or _live_state["boundary"] != _cur_boundary:
                        _live_state = {
                            "boundary": _cur_boundary,
                            "open": _ltp,
                            "high": _ltp,
                            "low": _ltp,
                            "close": _ltp,
                        }
                    else:
                        _live_state["high"] = max(_live_state["high"], _ltp)
                        _live_state["low"] = min(_live_state["low"], _ltp)
                        _live_state["close"] = _ltp
                    st.session_state[_live_key] = _live_state
                    _live_candle = {
                        "ts": _cur_boundary,
                        "open": _live_state["open"],
                        "high": _live_state["high"],
                        "low": _live_state["low"],
                        "close": _live_state["close"],
                        "volume": float("nan"),
                    }

                # first_low/first_high (the 09:15 first-candle gate reference)
                # only ever lives in the live engine's own in-memory tracker,
                # never persisted to the DB -- this dashboard process has no
                # way to read it, so those two overlay lines are skipped for
                # now (EMA21/signal/entry/stop/target still all render).
                fig = _build_intraday_candle_figure(
                    sym,
                    _direction,
                    today,
                    first_low=None,
                    first_high=None,
                    sig=_sel_sig,
                    pos=_sel_pos,
                    live_candle=_live_candle,
                )
                if fig is not None:
                    # A stable key is what lets Streamlit reuse the SAME
                    # chart component across reruns instead of tearing it
                    # down and remounting a brand-new one every tick --
                    # without it, each rerun's new Figure object gets
                    # treated as a new component instance, so the WHOLE
                    # chart visibly redraws from scratch instead of
                    # Plotly's own react()-based diff just moving the
                    # current candle/EMA point.
                    st.plotly_chart(
                        fig,
                        width="stretch",
                        key=f"intraday_chart_{sym}",
                        config={"displayModeBar": True, "scrollZoom": True},
                    )
                else:
                    st.info(f"No candle data yet for {sym} today.")

        if _open_syms:
            st.markdown('<p class="ov-card-meta">Open position(s)</p>', unsafe_allow_html=True)
            _pos_cols = st.columns(len(_open_syms))
            for _col, _sym in zip(_pos_cols, _open_syms, strict=False):
                with _col:
                    _render_one_chart(_sym)

        if _watch_syms:
            st.markdown(
                f'<p class="ov-card-meta">Watch another candidate '
                f"({len(_watch_syms)} of today's top-{istrat.TOP_N_CANDIDATES} not currently open)</p>",
                unsafe_allow_html=True,
            )
            _watch_default = st.session_state.get("intraday_watch_symbol")
            _watch_idx = _watch_syms.index(_watch_default) if _watch_default in _watch_syms else 0
            _watch_sel = st.selectbox(
                "Chart", _watch_syms, index=_watch_idx, key="intraday_watch_symbol", label_visibility="collapsed"
            )
            _render_one_chart(_watch_sel)
        elif not _open_syms:
            st.info("No candidates today.")

        with st.container(border=True, key="ov-card-intraday-tb"):
            st.markdown(
                '<p class="ov-card-title"><span class="ov-dot" style="background:var(--ov-purple);">'
                "</span>Today's trade book</p>",
                unsafe_allow_html=True,
            )
            _legs_today = idb.get_legs(date=today, mode=_mode)
            if _legs_today.empty and _open_now.empty:
                st.caption("No trades yet today.")
            else:
                _pnl_today = float(_legs_today["net_pnl"].sum()) if not _legs_today.empty else 0.0
                st.markdown(
                    f'<p class="ov-card-meta">Net P&amp;L today: '
                    f'<span class="{"ov-pos" if _pnl_today >= 0 else "ov-neg"}">'
                    f"₹{_pnl_today:+,.2f}</span></p>",
                    unsafe_allow_html=True,
                )
                if not _legs_today.empty:
                    _tb_show = _legs_today.sort_values("exit_time", ascending=False).head(10)
                    st.markdown(
                        _ov_table_html(
                            _tb_show,
                            columns=["symbol", "leg_type", "qty", "exit_price", "net_pnl"],
                            sym_cols=["symbol"],
                            pnl_cols=["net_pnl"],
                            num_fmt={"exit_price": "₹{:,.2f}", "qty": "{:.0f}"},
                            badges={"leg_type": _INTRADAY_EVENT_BADGES},
                        ),
                        unsafe_allow_html=True,
                    )
                if not _open_now.empty:
                    st.markdown('<p class="ov-card-meta">Open position(s), live</p>', unsafe_allow_html=True)
                    _ensure_subscribed(_ticker, list(_open_now["symbol"]))
                    _open_rows = []
                    for _, _p in _open_now.iterrows():
                        _p_ltp, _ = _live_price_and_change(_ticker, _p["symbol"])
                        _p_dir_sign = 1.0 if _p["direction"] == istrat.LONG else -1.0
                        if _p_ltp is not None:
                            _p_chg_pct = (_p_ltp - _p["entry_price"]) / _p["entry_price"] * 100.0 * _p_dir_sign
                            _p_upnl = (_p_ltp - _p["entry_price"]) * _p["qty_remaining"] * _p_dir_sign
                        else:
                            _p_chg_pct, _p_upnl = float("nan"), float("nan")
                        _open_rows.append(
                            {
                                "symbol": _p["symbol"],
                                "direction": _p["direction"],
                                "entry_price": _p["entry_price"],
                                "ltp": _p_ltp,
                                "chg_pct": _p_chg_pct,
                                "qty_remaining": _p["qty_remaining"],
                                "upnl": _p_upnl,
                            }
                        )
                    _open_df = pd.DataFrame(_open_rows)
                    st.markdown(
                        _ov_table_html(
                            _open_df,
                            columns=["symbol", "direction", "entry_price", "ltp", "chg_pct", "qty_remaining", "upnl"],
                            sym_cols=["symbol"],
                            pnl_cols=["chg_pct", "upnl"],
                            num_fmt={
                                "entry_price": "₹{:,.2f}",
                                "ltp": "₹{:,.2f}",
                                "chg_pct": "{:+.2f}%",
                                "qty_remaining": "{:.0f}",
                                "upnl": "₹{:+,.2f}",
                            },
                            badges={"direction": {"LONG": "ov-badge-green", "SHORT": "ov-badge-red"}},
                            na_rep="—",
                        ),
                        unsafe_allow_html=True,
                    )
            st.page_link(page_intraday_tradebook_p, label="View full tradebook →", icon="📒")

    _render_chart_and_tradebook_section()

    # --- Event timeline -------------------------------------------------------
    st.markdown(
        '<p class="ov-card-title" style="margin-top:16px;"><span class="ov-dot" '
        'style="background:var(--ov-amber);"></span>Today\'s events</p>',
        unsafe_allow_html=True,
    )
    sigs = idb.get_signals(today)
    poss = idb.get_positions(date=today, mode=_mode)
    legs = idb.get_legs(date=today, mode=_mode)
    events = []
    # "active" has no event badge of its own -- falls back to
    # "signal_formed" (a signal record simply exists, still being
    # watched). Every other status (expired / re_signaled / triggered /
    # invalidated) is shown as itself.
    _sig_status_to_event = {
        "expired": "expired",
        "re_signaled": "re_signaled",
        "triggered": "triggered",
        "invalidated": "invalidated",
    }
    for _, s in sigs.iterrows():
        events.append(
            {
                "time": s["signal_time"],
                "symbol": s["symbol"],
                "event": _sig_status_to_event.get(s["status"], "signal_formed"),
                "detail": f"high ₹{s['signal_high']:.2f} / low ₹{s['signal_low']:.2f}",
            }
        )
    for _, p in poss.iterrows():
        events.append(
            {
                "time": p["entry_time"],
                "symbol": p["symbol"],
                "event": "triggered",
                "detail": f"{p['direction']} qty {int(p['qty'])} @ ₹{p['entry_price']:.2f} "
                f"-- stop ₹{p['stop_price']:.2f}, target ₹{p['target_price']:.2f}",
            }
        )
    for _, l in legs.iterrows():
        events.append(
            {
                "time": l["exit_time"],
                "symbol": l["symbol"],
                "event": l["leg_type"],
                "detail": f"qty {int(l['qty'])} @ ₹{l['exit_price']:.2f} (₹{l['net_pnl']:+,.2f})",
            }
        )
    if events:
        ev_df = pd.DataFrame(events).sort_values("time")
        st.markdown(
            _ov_table_html(
                ev_df,
                columns=["time", "symbol", "event", "detail"],
                sym_cols=["symbol"],
                badges={"event": _INTRADAY_EVENT_BADGES},
            ),
            unsafe_allow_html=True,
        )
    else:
        st.caption("Nothing has happened yet today.")


# ---------------------------------------------------------------------------
# Page: Intraday Tradebook
# ---------------------------------------------------------------------------


def page_intraday_tradebook():
    _tip = html_lib.escape(
        "Every intraday position this strategy has opened, split into its "
        "exit legs (target half + 15:10 runner half, or a single stop leg) "
        "-- separate from the momentum strategy's own Tradebook."
    )
    st.markdown(
        '<div class="ov-header"><div><span class="ov-h1">📒 Intraday Tradebook</span>'
        f'<span class="ov-info-icon" title="{_tip}">ℹ️</span></div></div>',
        unsafe_allow_html=True,
    )

    f1, f2 = st.columns(2)
    with f1:
        mode_filter = st.selectbox("Mode", ["paper", "live"], key="intraday_tb_mode")
    with f2:
        since = st.date_input("Since", value=dt.date.today() - dt.timedelta(days=30), key="intraday_tb_since")

    positions = idb.get_positions(mode=mode_filter)
    if not positions.empty:
        positions = positions[positions["date"] >= since.isoformat()]
    if positions.empty:
        st.info(f"No {mode_filter} positions recorded yet.")
        return

    closed = positions[positions["status"] == "closed"]
    legs_all = idb.get_legs(mode=mode_filter)
    legs_all = legs_all[legs_all["date"] >= since.isoformat()] if not legs_all.empty else legs_all
    total_pnl = float(legs_all["net_pnl"].sum()) if not legs_all.empty else 0.0
    win_rate = (100 * (legs_all["net_pnl"] > 0).mean()) if not legs_all.empty else float("nan")

    metrics = [
        _ov_metric_html("Positions", str(len(positions)), f"{len(closed)} closed"),
        _ov_metric_html("Legs", str(len(legs_all)), "target + stop/squareoff exits"),
        _ov_metric_html("Net P&L", f"₹{total_pnl:+,.2f}", None, value_cls=("ov-pos" if total_pnl >= 0 else "ov-neg")),
        _ov_metric_html("Win rate (legs)", f"{win_rate:.0f}%" if pd.notna(win_rate) else "—", None),
    ]
    st.markdown(f'<div class="ov-grid-metrics">{"".join(metrics)}</div>', unsafe_allow_html=True)
    st.divider()

    display = (
        legs_all.merge(
            positions[["id", "signal_time"]].rename(columns={"id": "position_id"}), on="position_id", how="left"
        )
        if not legs_all.empty
        else legs_all
    )
    if display.empty:
        st.info("No legs recorded in this window.")
        return
    display = display.sort_values("exit_time", ascending=False)
    show_cols = [
        "date",
        "symbol",
        "direction",
        "entry_time",
        "entry_price",
        "leg_type",
        "qty",
        "exit_time",
        "exit_price",
        "gross_pnl",
        "costs",
        "net_pnl",
    ]
    show_cols = [c for c in show_cols if c in display.columns]
    page = _ov_page_slice(display, key="intraday_tb", page_size=20)
    st.markdown(
        _ov_table_html(
            page,
            columns=show_cols,
            sym_cols=["symbol"],
            pnl_cols=["gross_pnl", "net_pnl"],
            num_fmt={
                "entry_price": "₹{:,.2f}",
                "exit_price": "₹{:,.2f}",
                "gross_pnl": "₹{:+,.2f}",
                "costs": "₹{:,.2f}",
                "qty": "{:.0f}",
            },
            badges={
                "leg_type": _INTRADAY_EVENT_BADGES,
                "direction": {"LONG": "ov-badge-green", "SHORT": "ov-badge-red"},
            },
        ),
        unsafe_allow_html=True,
    )
    _ov_pagination_controls(display, key="intraday_tb", page_size=20)


# ---------------------------------------------------------------------------
# Page: Tradebook
# ---------------------------------------------------------------------------


def page_tradebook():
    _tb_tip = html_lib.escape(
        "Every trade this app has opened, with its entry-time "
        "technical/fundamental snapshot and a real exit reason -- separate "
        "from the Positions & Trade page's live view, meant for "
        "historical/analytics use."
    )
    st.markdown(
        '<div class="ov-header"><div><span class="ov-h1">📒 Positional Tradebook</span>'
        f'<span class="ov-info-icon" title="{_tb_tip}">ℹ️</span></div></div>',
        unsafe_allow_html=True,
    )

    trades = state_db.get_trades()
    if trades.empty:
        st.info("No trades recorded yet.")
        return

    closed = trades[trades["status"] == "closed"]
    if not closed.empty:
        wins = closed[closed["realized_pnl"] > 0]
        win_rate = (
            100 * len(wins) / len(closed[closed["realized_pnl"].notna()])
            if closed["realized_pnl"].notna().any()
            else float("nan")
        )
        total_realized = float(closed["realized_pnl"].sum())
        best = closed["realized_ret_pct"].max()
        worst = closed["realized_ret_pct"].min()
        open_count = len(trades[trades["status"] == "open"])
        st.markdown(
            '<div class="ov-grid-metrics">'
            + _ov_metric_html(
                "Win rate",
                f"{win_rate:.1f}%" if win_rate == win_rate else "—",
                f"of {closed['realized_pnl'].notna().sum()} closed",
                "",
                "green",
            )
            + _ov_metric_html(
                "Avg holding days",
                f"{closed['holding_days'].mean():.0f}" if closed["holding_days"].notna().any() else "—",
                "closed trades",
                "",
                "blue",
            )
            + _ov_metric_html(
                "Total realized P&L",
                f"₹{total_realized:+,.0f}",
                "since inception",
                "ov-pos" if total_realized >= 0 else "ov-neg",
                "green",
                "ov-pos" if total_realized >= 0 else "ov-neg",
            )
            + _ov_metric_html(
                "Best / worst",
                f"{best:+.1f}% / {worst:+.1f}%" if pd.notna(best) else "—",
                "per trade return",
                "",
                "purple",
            )
            + _ov_metric_html("Open trades", str(open_count), "live now", "", "teal")
            + "</div>",
            unsafe_allow_html=True,
        )

    st.divider()
    with st.container(border=True, key="ov-card-tb-history"):
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            sym_filter = st.multiselect("Symbol", sorted(trades["symbol"].unique()), key="tb_sym_filter")
        with f2:
            status_filter = st.multiselect("Status", ["open", "closed"], key="tb_status_filter")
        with f3:
            reason_types = sorted(trades["exit_reason"].dropna().map(_exit_type_label).unique())
            reason_filter = st.multiselect("Exit type", reason_types, key="tb_reason_filter")
        with f4:
            since_date = st.date_input("Entered since", value=dt.date.today() - dt.timedelta(days=365), key="tb_since")

        filtered = trades[trades["entry_date"] >= since_date.isoformat()]
        if sym_filter:
            filtered = filtered[filtered["symbol"].isin(sym_filter)]
        if status_filter:
            filtered = filtered[filtered["status"].isin(status_filter)]
        if reason_filter:
            filtered = filtered[filtered["exit_reason"].map(_exit_type_label).isin(reason_filter)]

        st.caption(f"Showing {len(filtered)} of {len(trades)} trades")
        _priority_cols = [
            "symbol",
            "entry_date",
            "entry_price",
            "qty",
            "initial_stop",
            "latest_recommended_stop",
            "exit_date",
            "exit_type",
            "exit_price",
            "realized_pnl",
            "realized_ret_pct",
            "holding_days",
        ]
        display_df = filtered.copy()
        if "exit_reason" in display_df.columns:
            display_df["exit_type"] = display_df["exit_reason"].map(_exit_type_label)
        _remaining_cols = [
            c for c in display_df.columns if c not in ("id", "position_id", "status") and c not in _priority_cols
        ]
        display_cols = ["status"] + [c for c in _priority_cols if c in display_df.columns] + _remaining_cols
        st.markdown(
            _ov_table_html(
                display_df[display_cols],
                sym_cols=["symbol"],
                pnl_cols=["realized_pnl", "realized_ret_pct"],
                num_fmt={
                    "entry_price": "₹{:.2f}",
                    "exit_price": "₹{:.2f}",
                    "initial_stop": "₹{:.2f}",
                    "latest_recommended_stop": "₹{:.2f}",
                    "entry_score": "{:.2f}",
                    "entry_rsi": "{:.1f}",
                    "entry_pct_52w_high": "{:.2f}",
                    "entry_vol_expansion": "{:.2f}",
                    "entry_fundamental_score": "{:.1f}",
                },
                badges={
                    "status": {"open": "ov-badge-green", "closed": "ov-badge-gray"},
                    "exit_type": _EXIT_TYPE_BADGES,
                },
            ),
            unsafe_allow_html=True,
        )
        st.download_button("Download tradebook CSV (filtered view)", filtered.to_csv(index=False), "tradebook.csv")

    st.divider()
    with st.container(border=True, key="ov-card-tb-chart"):
        st.markdown(
            '<p class="ov-card-title"><span class="ov-dot" style="background:var(--ov-purple);"></span>Trade chart</p>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Open positions: the amber line is your REAL applied-stop "
            "history (state_db's daily stop-check log -- exactly what live "
            "computed and applied each day, whether MAD or ATR-based -- "
            "same mechanism as the Live Rebalance page). Closed trades: "
            "shown with a plain ATR-based simulated stop line for "
            "readability, regardless of what was actually enabled while "
            "the trade was live. A symbol traded more than once shows "
            "every occurrence, starting from its first entry in the "
            "tradebook."
        )
        if filtered.empty:
            st.info("No trades match the filters above to chart.")
        else:
            _include_closed = st.checkbox(
                "Include closed trades in the dropdown",
                value=False,
                key="tb_chart_include_closed",
                help="Off by default so the list stays short and focused on what "
                "you're actually holding -- check this to also browse the "
                "chart for a symbol whose trades have all closed.",
            )
            _chart_pool = filtered if _include_closed else filtered[filtered["status"] == "open"]
            _chart_syms = sorted(_chart_pool["symbol"].unique())
            if not _chart_syms:
                st.info(
                    "No open trades match the filters above."
                    + ("" if _include_closed else " Check 'Include closed trades' above to browse closed ones.")
                )
                st.stop()
            _sym_sel = st.selectbox("Symbol", _chart_syms, key="tb_chart_sym")

            _sym_trades = trades[trades["symbol"] == _sym_sel].sort_values("entry_date")
            _first_entry = pd.Timestamp(_sym_trades["entry_date"].iloc[0])
            _any_open = (_sym_trades["status"] == "open").any()
            _last_relevant = (
                pd.Timestamp(dt.date.today()) if _any_open else pd.Timestamp(_sym_trades["exit_date"].max())
            )
            _fetch_end = _last_relevant.date()

            # load_long_history_cached, not load_candles_cached: the plain
            # cache is sized to whatever `days` a call asks for and fully
            # re-fetches once stale, so a different (often larger) window
            # per symbol here kept missing that cache and paying a live
            # Kite fetch every time. The long-history cache is a fixed
            # ~16.7yr depth per symbol, incremental (only the missing gap
            # is fetched), and shared with the weekly/monthly-gate feature
            # -- always covers a trade's own entry date, no re-fetch churn.
            with st.spinner(
                f"Loading {_sym_sel} candles... (first time for this "
                f"symbol can take up to a minute; instant after that)"
            ):
                _candles = bt.load_long_history_cached([_sym_sel], end_date=_fetch_end)
            _df = _candles.get(_sym_sel)

            # If we're charting through today and the market's actually open
            # right now, the day's cached candle can be hours stale (the
            # long-history cache only fetches once the gap is non-zero, so
            # once today's row exists it's never touched again this run) --
            # patch it with a live LTP so "today" reflects the current
            # price, not whatever it was at the day's first fetch.
            if _df is not None and not _df.empty and _fetch_end == dt.date.today():
                _now = dt.datetime.now()
                _market_open = nse_holidays.is_trading_day(_now.date()) and dt.time(9, 15) <= _now.time() <= dt.time(
                    15, 30
                )
                if _market_open:
                    try:
                        _ltp = kite_client.get_ltp([_sym_sel]).get(_sym_sel)
                    except Exception:
                        _ltp = None
                    if _ltp is not None:
                        _df = _df.copy()
                        _today_ts = pd.Timestamp(dt.date.today())
                        if _today_ts in _df.index:
                            _df.loc[_today_ts, "high"] = max(_df.loc[_today_ts, "high"], _ltp)
                            _df.loc[_today_ts, "low"] = min(_df.loc[_today_ts, "low"], _ltp)
                            _df.loc[_today_ts, "close"] = _ltp
                        else:
                            _df.loc[_today_ts] = {"open": _ltp, "high": _ltp, "low": _ltp, "close": _ltp, "volume": 0}
                            _df = _df.sort_index()

            if _df is None or _df.empty:
                st.warning(f"No candle data available for {_sym_sel}.")
            else:
                _default_start = min(_first_entry, _last_relevant - pd.Timedelta(days=365))
                _min_bound = min(_default_start, pd.Timestamp(_df.index.min())).date()
                _max_bound = _last_relevant.date()
                # Keyed by symbol + max_bound (today, or the trade's exit
                # date) so switching symbols -- or the same symbol on a new
                # day -- gets a fresh widget instead of Streamlit silently
                # reusing a stale value= from days ago in a long-lived
                # browser session (date_input's value= is only honored on
                # a key's FIRST render, never on later reruns).
                _range_key = f"{_sym_sel}_{_max_bound.isoformat()}"
                c1, c2 = st.columns(2)
                with c1:
                    _range_start = st.date_input(
                        "From",
                        value=_default_start.date(),
                        min_value=_min_bound,
                        max_value=_max_bound,
                        key=f"tb_chart_from_{_range_key}",
                    )
                with c2:
                    _range_end = st.date_input(
                        "To",
                        value=_max_bound,
                        min_value=_min_bound,
                        max_value=_max_bound,
                        key=f"tb_chart_to_{_range_key}",
                    )

                # For now (per explicit request): open positions show only
                # the REAL applied-stop history (state_db's daily log) --
                # that line already reflects whatever's actually live (MAD
                # or ATR), so a separate simulated "recommended" line is
                # dropped to keep it a single source of truth. Closed
                # trades always get the plain ATR-based simulated line,
                # regardless of whether MAD was enabled while they were
                # live -- keeps historical trades simple to read.
                _cfg_atr_only = dict(config.STRATEGY)
                _cfg_atr_only["mad_stop_enabled"] = False

                _trade_list = []
                for _, _tr in _sym_trades.iterrows():
                    _entry_date = pd.Timestamp(_tr["entry_date"])
                    _is_open = _tr["status"] == "open"
                    _exit_date = (
                        pd.Timestamp(_tr["exit_date"]) if not _is_open and pd.notna(_tr.get("exit_date")) else None
                    )

                    _real_history = None
                    if _is_open:
                        _pos_id = _tr.get("position_id")
                        if pd.notna(_pos_id):
                            _log = state_db.get_stop_update_log(int(_pos_id))
                            _rh = trade_chart.build_real_stop_history(
                                _log, _entry_date, float(_tr["initial_stop"]), exit_date=None
                            )
                            if _rh is not None:
                                _real_history = _rh[["applied"]]

                    _overlay = trade_chart.build_trade_overlay(
                        _df, _cfg_atr_only, _entry_date, float(_tr["entry_price"]), exit_date=_exit_date
                    )
                    _trade_list.append(
                        {
                            "entry_date": _entry_date,
                            "entry_price": float(_tr["entry_price"]),
                            "exit_date": _exit_date,
                            "exit_price": (
                                float(_tr["exit_price"])
                                if _exit_date is not None and pd.notna(_tr.get("exit_price"))
                                else None
                            ),
                            "overlay": _overlay,
                            "real_history": _real_history,
                        }
                    )

                _n = len(_trade_list)
                st.markdown(
                    f"**{_sym_sel}** — {_n} trade{'s' if _n != 1 else ''} since {_first_entry.date()}"
                    if _n > 1
                    else f"**{_sym_sel}** — entry {_first_entry.date()}"
                )
                fig = trade_chart.build_symbol_figure(
                    _sym_sel, _df, _trade_list, chart_start=_range_start, chart_end=_range_end
                )
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": True, "scrollZoom": True})


# ---------------------------------------------------------------------------
# Page: Guide ("how this app actually works")
# ---------------------------------------------------------------------------

_GUIDE_CSS = """
<style>
.guide-hero {
    border-radius: 18px; padding: 32px 36px; margin-bottom: 20px;
    background: linear-gradient(135deg, var(--ov-blue-d) 0%, var(--ov-purple-d) 55%, var(--ov-pink-d) 100%);
    color: #fff; position: relative; overflow: hidden;
}
.guide-hero h1 { font-size: 28px; margin: 0 0 6px 0; font-weight: 800; letter-spacing: -0.02em; }
.guide-hero p { font-size: 15px; margin: 0; opacity: 0.92; max-width: 640px; line-height: 1.55; }
.guide-stats { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
.guide-stat {
    background: rgba(255,255,255,0.14); border: 1px solid rgba(255,255,255,0.25);
    border-radius: 10px; padding: 8px 14px; font-size: 12.5px; backdrop-filter: blur(2px);
}
.guide-stat b { font-size: 14px; display: block; }
.guide-toc {
    display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 22px 0;
}
.guide-toc a {
    text-decoration: none; font-size: 12.5px; font-weight: 600; padding: 7px 13px;
    border-radius: 999px; background: var(--ov-surface-2); border: 1px solid var(--ov-border);
    color: var(--ov-text-secondary);
}
.guide-toc a:hover { border-color: var(--ov-border-strong); color: var(--ov-text-primary); }
.guide-section { margin-bottom: 8px; }
.guide-section h2 {
    font-size: 19px; font-weight: 800; margin: 0 0 4px 0; display: flex;
    align-items: center; gap: 9px; letter-spacing: -0.01em;
}
.guide-section .sub { color: var(--ov-text-muted); font-size: 13px; margin: 0 0 14px 0; }
.guide-icon {
    width: 30px; height: 30px; border-radius: 9px; display: inline-flex;
    align-items: center; justify-content: center; font-size: 15px; flex-shrink: 0;
}
.guide-flow { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 6px 0 18px 0; }
.guide-flow-step {
    background: var(--ov-surface-2); border: 1px solid var(--ov-border); border-radius: 10px;
    padding: 9px 13px; font-size: 12.5px; font-weight: 700; color: var(--ov-text-primary);
    text-align: center; line-height: 1.3;
}
.guide-flow-step span { display: block; font-size: 10.5px; font-weight: 500; color: var(--ov-text-muted); margin-top: 1px; }
.guide-flow-arrow { color: var(--ov-text-muted); font-size: 15px; }
.guide-card {
    background: var(--ov-surface-2); border: 1px solid var(--ov-border); border-radius: 12px;
    padding: 14px 16px; margin-bottom: 10px;
}
.guide-card h4 { margin: 0 0 6px 0; font-size: 13.5px; font-weight: 700; }
.guide-card p, .guide-card li { font-size: 12.8px; color: var(--ov-text-secondary); line-height: 1.55; margin: 0 0 4px 0; }
.guide-grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; }
.guide-grid3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
.guide-formula {
    font-family: 'SF Mono', Consolas, monospace; background: var(--ov-surface-1);
    border: 1px dashed var(--ov-border-strong); border-radius: 10px; padding: 12px 15px;
    font-size: 12.5px; margin: 8px 0 14px 0; color: var(--ov-text-primary); line-height: 1.7;
}
.guide-weights { display: flex; flex-direction: column; gap: 6px; margin: 10px 0 16px 0; }
.guide-weight-row { display: flex; align-items: center; gap: 10px; font-size: 12px; }
.guide-weight-label { width: 168px; flex-shrink: 0; color: var(--ov-text-secondary); font-weight: 600; }
.guide-weight-bar-bg { flex: 1; background: var(--ov-surface-1); border-radius: 6px; height: 16px; overflow: hidden; }
.guide-weight-bar { height: 100%; border-radius: 6px; }
.guide-weight-pct { width: 38px; text-align: right; font-weight: 700; font-size: 12px; }
table.guide-table { width: 100%; border-collapse: collapse; font-size: 12.5px; margin: 6px 0 18px 0; }
table.guide-table th {
    text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em;
    color: var(--ov-text-muted); padding: 6px 10px; border-bottom: 1px solid var(--ov-border-strong);
}
table.guide-table td { padding: 8px 10px; border-bottom: 1px solid var(--ov-border); color: var(--ov-text-secondary); vertical-align: top; }
table.guide-table td:first-child { color: var(--ov-text-primary); font-weight: 600; white-space: nowrap; }
.guide-pill { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 10.5px; font-weight: 700; }
.guide-pages-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }
.guide-page-card { border: 1px solid var(--ov-border); border-radius: 12px; padding: 12px 14px; background: var(--ov-surface-2); }
.guide-page-card .icon { font-size: 18px; }
.guide-page-card h5 { margin: 4px 0 3px 0; font-size: 13px; font-weight: 700; }
.guide-page-card p { margin: 0; font-size: 12px; color: var(--ov-text-muted); line-height: 1.5; }
</style>
"""


def _guide_section(icon: str, color: str, title: str, subtitle: str, anchor: str) -> str:
    return (
        f'<div class="guide-section" id="{anchor}">'
        f'<h2><span class="guide-icon" style="background:var(--ov-{color}-l);'
        f'color:var(--ov-{color}-d);">{icon}</span>{html_lib.escape(title)}</h2>'
        f'<p class="sub">{html_lib.escape(subtitle)}</p>'
    )


def _guide_flow(steps: list[tuple[str, str]]) -> str:
    """steps: list of (label, sublabel)."""
    parts = ['<div class="guide-flow">']
    for i, (label, sub) in enumerate(steps):
        if i:
            parts.append('<span class="guide-flow-arrow">➜</span>')
        parts.append(f'<div class="guide-flow-step">{html_lib.escape(label)}<span>{html_lib.escape(sub)}</span></div>')
    parts.append("</div>")
    return "".join(parts)


def page_guide():
    st.markdown(_GUIDE_CSS, unsafe_allow_html=True)
    cfg = config.STRATEGY
    stop_mode = (
        "MAD Volatility Trail"
        if cfg.get("mad_stop_enabled")
        else "ATR Trailing"
        if cfg.get("trailing_stop_enabled")
        else "Fixed ATR"
    )
    sizing_mode = (
        "Equal-weight (advanced allocator)"
        if cfg.get("capital_equal_weight_sizing", False) and cfg.get("advanced_equal_weight_sizing", True)
        else "Equal-weight (simple)"
        if cfg.get("capital_equal_weight_sizing", False)
        else "Risk-based (% of capital)"
    )

    st.markdown(
        '<div class="guide-hero"><h1>📘 How This System Works</h1>'
        "<p>A momentum-driven, rules-based swing-trading engine for NSE F&amp;O stocks — "
        "it ranks the whole eligible universe every day, only ever buys a stock that clears "
        "a stack of technical and fundamental checks, sizes and protects every position "
        "automatically, and rebalances on a schedule you control. Everything below reflects "
        "the exact logic actually running right now, pulled live from your current settings.</p>"
        '<div class="guide-stats">'
        f'<div class="guide-stat"><b>{len(config.UNIVERSE)}</b>stocks in universe</div>'
        f'<div class="guide-stat"><b>{cfg.get("max_positions", 10)}</b>max positions</div>'
        f'<div class="guide-stat"><b>{cfg.get("rebalance_cadence", "daily").title()}</b>rebalance cadence</div>'
        f'<div class="guide-stat"><b>{stop_mode}</b>stop mechanism</div>'
        f'<div class="guide-stat"><b>{sizing_mode}</b>position sizing</div>'
        "</div></div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="guide-toc">'
        '<a href="#g-bigpicture">🗺️ The big picture</a>'
        '<a href="#g-selection">🎯 How a stock earns its spot</a>'
        '<a href="#g-protect">🛡️ Protecting what you own</a>'
        '<a href="#g-rhythm">📅 The daily rhythm</a>'
        '<a href="#g-safety">🚨 Execution &amp; safety nets</a>'
        '<a href="#g-cash">💰 Cash management</a>'
        '<a href="#g-pages">🧭 Tour of every page</a>'
        "</div>",
        unsafe_allow_html=True,
    )

    # ---- The big picture -------------------------------------------------
    st.markdown(
        _guide_section(
            "🗺️",
            "blue",
            "The big picture",
            anchor="g-bigpicture",
            subtitle="One stock's entire journey through the system, start to finish.",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        _guide_flow(
            [
                ("Universe", f"~{len(config.UNIVERSE)} F&O stocks"),
                ("Technical gates", "trend, RSI, 52w-high"),
                ("Fundamental gate", "XBRL value score"),
                ("Score & rank", "momentum + tilts"),
                ("Sector cap", "diversification"),
                ("Size & buy", "equal-weight/risk"),
                ("Hold & protect", "stop ratchets up"),
                ("Sell", "rebalance / stop / manual"),
                ("Ledger", "charges, XIRR, tradebook"),
            ]
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:12.8px;color:var(--ov-text-muted);margin-top:-8px;">'
        "Every box above is a real, separate decision this app makes — the sections below walk "
        "through each one with the exact formulas and thresholds in use today.</p></div>",
        unsafe_allow_html=True,
    )

    # ---- Selection ---------------------------------------------------
    st.markdown(
        _guide_section(
            "🎯",
            "green",
            "How a stock earns its spot",
            anchor="g-selection",
            subtitle="From ~200 F&O-eligible stocks down to a ranked shortlist.",
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="guide-card"><h4>1. The universe</h4>'
        f"<p>Every stock eligible for F&amp;O trading on NSE (fetched from NSE's own "
        f"underlying-instruments list, refreshed weekly), filtered to only symbols "
        f"actually tradable via Kite, minus anything you've manually skipped in Admin. "
        f"That's <b>{len(config.UNIVERSE)} stocks</b> right now.</p></div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="guide-card"><h4>2. Technical gates — every one must pass</h4>'
        "<p>A stock failing ANY gate below is dropped entirely, not just scored lower.</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<table class="guide-table"><tr><th>Gate</th><th>Condition</th><th>Default</th></tr>'
        "<tr><td>Trend structure</td><td>Price above both EMAs, and the fast EMA itself rising</td>"
        f"<td>EMA {int(cfg.get('ema_fast', 50))} / EMA {int(cfg.get('ema_slow', 200))}</td></tr>"
        "<tr><td>Near 52-week high</td><td>Price is at least this % of its 52-week high</td>"
        f"<td>{cfg.get('near_high_threshold', 0.85) * 100:.0f}%</td></tr>"
        "<tr><td>RSI band</td><td>14-day RSI inside this range — strong but not overheated</td>"
        f"<td>{cfg.get('rsi_min', 45)}–{cfg.get('rsi_max', 80)}</td></tr>"
        "<tr><td>Weekly/monthly trend</td><td>Price above its own weekly AND monthly EMA(200) — a higher-timeframe confirmation</td>"
        f"<td>{'ON' if cfg.get('weekly_monthly_gate_enabled') else 'off'}</td></tr>"
        "<tr><td>Fundamental quality</td><td>Fundamental value score at or above the minimum (stocks with no data pass through)</td>"
        f"<td>{'ON, min ' + str(cfg.get('min_fundamental_score', 50)) if cfg.get('fundamental_gate_enabled') else 'off'}</td></tr>"
        "<tr><td>Sector diversification</td><td>Stock's sector must be among the currently-strongest sector groups</td>"
        f"<td>{'ON, top ' + str(cfg.get('top_n_sectors', 3)) if cfg.get('sector_diversification_enabled') else 'off'}</td></tr>"
        "</table></div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="guide-card"><h4>3. Momentum score — ranks everyone who passed the gates</h4>'
        "<p>Every gate-passer gets one score, each ingredient converted to a Z-score "
        "(how many standard deviations above/below the AVERAGE stock in today's universe) "
        "before weighting, so a raw number in % or ratio terms never dominates just because "
        "of its units:</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="guide-weights">'
        '<div class="guide-weight-row"><div class="guide-weight-label">6-month relative strength</div>'
        '<div class="guide-weight-bar-bg"><div class="guide-weight-bar" style="width:40%;background:var(--ov-blue);"></div></div>'
        '<div class="guide-weight-pct">40%</div></div>'
        '<div class="guide-weight-row"><div class="guide-weight-label">3-month relative strength</div>'
        '<div class="guide-weight-bar-bg"><div class="guide-weight-bar" style="width:25%;background:var(--ov-teal);"></div></div>'
        '<div class="guide-weight-pct">25%</div></div>'
        '<div class="guide-weight-row"><div class="guide-weight-label">52-week-high proximity</div>'
        '<div class="guide-weight-bar-bg"><div class="guide-weight-bar" style="width:20%;background:var(--ov-purple);"></div></div>'
        '<div class="guide-weight-pct">20%</div></div>'
        '<div class="guide-weight-row"><div class="guide-weight-label">Volume expansion</div>'
        '<div class="guide-weight-bar-bg"><div class="guide-weight-bar" style="width:15%;background:var(--ov-amber);"></div></div>'
        '<div class="guide-weight-pct">15%</div></div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class=\"guide-formula\">relative strength = stock's own return − NIFTY 50's return, over the same window<br>"
        "52w-high proximity = today's close ÷ highest close in the last 252 trading days<br>"
        "volume expansion = (avg. volume, last 20 days) ÷ (avg. volume, last 60 days)<br>"
        "score = 0.40·Z(RS 6mo) + 0.25·Z(RS 3mo) + 0.20·Z(52w-high %) + 0.15·Z(vol. expansion)</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:12.5px;color:var(--ov-text-muted);">Optional add-on tilts (each off unless '
        "you've enabled it in Admin) nudge the same score up or down without ever excluding a stock on "
        "their own: a <b>fundamental-quality tilt</b> ("
        f"{cfg.get('fundamental_bonus_weight', 0.5)} × Z-score of fundamental value score), a "
        f"<b>sector-strength tilt</b> ({cfg.get('sector_bonus_weight', 0.0)} × Z-score of the stock's "
        "sector's own relative strength vs NIFTY), and a <b>resistance-clearance tilt</b> "
        f"({cfg.get('resistance_zone_weight', 0.0)} × Z-score of room-to-run before the next chart "
        "resistance level).</p></div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="guide-card"><h4>4. Fundamental value score — 0 to 100, sector-aware</h4>'
        "<p>Pulled from companies' own primary-source XBRL regulatory filings (no scraping, "
        "no AI guessing) — routed to one of five rubrics by the company's actual sector, since "
        '"good" numbers mean different things for a bank vs a manufacturer:</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="guide-grid3">'
        '<div class="guide-card"><h4>General companies</h4><ul>'
        "<li>Profitability — ROE, net margin, free cash flow growth</li>"
        "<li>Financial health — Debt/Equity, Current Ratio</li>"
        "<li>Growth &amp; valuation — Revenue CAGR, PEG ratio</li></ul></div>"
        '<div class="guide-card"><h4>Banks</h4><ul>'
        "<li>Profitability — ROE, ROA, net interest margin</li>"
        "<li>Asset quality — Gross/Net NPA % (lower is better)</li>"
        "<li>Growth — Advances growth, profit growth</li></ul></div>"
        '<div class="guide-card"><h4>NBFCs &amp; AMCs</h4><ul>'
        "<li>Profitability — ROE, ROA</li>"
        "<li>Leverage — Debt/Equity, judged on an NBFC-appropriate scale (3–6× is normal by design)</li>"
        "<li>Growth — Loan-book growth, profit growth</li></ul></div>"
        '<div class="guide-card"><h4>General insurers</h4><ul>'
        "<li>Profitability — ROE, ROA</li>"
        "<li>Underwriting — Combined ratio, claim ratio (lower is better)</li>"
        "<li>Growth — Gross premium growth, profit growth</li></ul></div>"
        '<div class="guide-card"><h4>Life insurers</h4><ul>'
        "<li>Profitability — ROE</li>"
        "<li>Growth — Net premium growth, profit growth</li></ul></div>"
        '<div class="guide-card"><h4>How the 0–100 comes together</h4>'
        "<p>Each metric is bucketed 0–5, averaged within its pillar, pillars averaged together "
        "and rescaled to 100. A pillar with no data available is simply left out rather than "
        "guessed at — missing data lowers confidence, never the score itself.</p></div>"
        "</div></div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="guide-card"><h4>5. Sector strength &amp; diversification</h4>'
        "<p>Every stock is mapped to its real NSE sector index (not a rough heatmap guess). "
        "A sector's own relative strength is measured the exact same way a stock's is — "
        "its index's return vs NIFTY's. When diversification is on, only stocks from the "
        f"top {cfg.get('top_n_sectors', 3)} strongest sector groups are eligible to buy at all, "
        f"and no more than {cfg.get('max_positions_per_sector', 3)} positions are ever held in "
        "the same sector group at once — this only ever blocks a NEW purchase, it never forces "
        "out a position you already hold.</p></div></div>",
        unsafe_allow_html=True,
    )

    # ---- Protecting what you own ------------------------------------
    st.markdown(
        _guide_section(
            "🛡️",
            "red",
            "Protecting what you own",
            anchor="g-protect",
            subtitle="How much of each stock you buy, and what keeps a loser from running away.",
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="guide-card"><h4>Position sizing</h4>'
        f"<p>Currently: <b>{sizing_mode}</b>. In equal-weight mode, every position targets an equal "
        'slice of your total equity (capital ÷ max positions) — the "advanced" allocator can let a '
        "pricier top-ranked stock borrow a little headroom from a not-yet-filled lower-ranked slot, "
        "buys a partial size rather than skipping outright when cash is tight, and tops up any "
        "existing under-sized position with leftover cash. Risk-based mode instead sizes every "
        "buy so that a stop-loss hit would only cost a fixed % of your capital, regardless of "
        "the stock's price.</p></div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<table class="guide-table"><tr><th>Stop mechanism</th><th>How it works</th><th>Currently</th></tr>'
        "<tr><td>Fixed ATR</td><td>Set once at entry: price − 2.5× ATR(14). Never moves.</td>"
        f'<td><span class="guide-pill" style="background:var(--ov-blue-l);color:var(--ov-blue-d);">'
        f"{'active' if stop_mode == 'Fixed ATR' else 'available'}</span></td></tr>"
        "<tr><td>ATR trailing (chandelier)</td><td>Every day: highest close since entry − 4× ATR(14). "
        "Only ever moves UP, never down.</td>"
        f'<td><span class="guide-pill" style="background:var(--ov-green-l);color:var(--ov-green-d);">'
        f"{'active' if stop_mode == 'ATR Trailing' else 'available'}</span></td></tr>"
        "<tr><td>MAD volatility trail</td><td>A rolling median ± a volatility-scaled band (median "
        "absolute deviation, floored by ATR) that ratchets up with price in an uptrend — adapts to "
        "each stock's own volatility instead of one fixed multiple.</td>"
        f'<td><span class="guide-pill" style="background:var(--ov-purple-l);color:var(--ov-purple-d);">'
        f"{'active' if stop_mode == 'MAD Volatility Trail' else 'available'}</span></td></tr>"
        "</table>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:12.5px;color:var(--ov-text-muted);">Whichever mechanism is active, the same '
        "rule always applies: a stop can only ever tighten, never loosen — a quieter/lower candidate value "
        "on any given day is simply ignored.</p></div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="guide-card"><h4>Market regime filter</h4>'
        f"<p>{'Currently ON' if cfg.get('regime_filter_enabled') else 'Currently off'} — when NIFTY 50 "
        f"closes below its own {cfg.get('regime_ema_period', 200)}-day EMA, the number of positions "
        f"allowed to be open at once is cut "
        f"to {int(cfg.get('regime_position_multiplier', 0.5) * 100)}% (rounded, minimum 1). This caps "
        "<b>how many</b> positions can be open, not how much capital goes into each one — money that "
        "isn't deployed into a blocked slot simply sits in cash rather than being spread thicker "
        "across fewer stocks, and no existing holding is ever force-sold by this filter alone.</p>"
        "</div></div>",
        unsafe_allow_html=True,
    )

    # ---- The daily rhythm --------------------------------------------
    st.markdown(
        _guide_section(
            "📅",
            "amber",
            "The daily rhythm",
            anchor="g-rhythm",
            subtitle="What runs every trading day, on autopilot, and when.",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="guide-card"><h4>Every single trading day, regardless of cadence</h4>'
        "<ul><li>Every held position's stop is recalculated and ratcheted up if warranted</li>"
        "<li>Any open slot (freed by a stop-loss or otherwise) gets filled from the current watchlist</li>"
        "<li>Under-sized existing positions get topped up if cash allows</li>"
        "<li>Any due recurring charge (e.g. quarterly Demat AMC) is posted to the Ledger</li></ul></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="guide-card"><h4>Only on a rebalance day</h4>'
        f"<p>Cadence is currently set to <b>{cfg.get('rebalance_cadence', 'daily').title()}</b> — "
        '"Weekly" checks only on each week\'s last trading day, "Monthly" only on each month\'s '
        "first trading day. Only ONE decision is gated by this: whether to re-rank the whole universe "
        "and sell anything that dropped out of the top ranks or broke its trend — everything in the "
        "box above still runs every single day no matter what.</p></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<table class="guide-table"><tr><th>Time (IST)</th><th>Job</th><th>What it does</th></tr>'
        "<tr><td>07:00</td><td>Token check</td><td>Confirms the broker login is valid before the market opens</td></tr>"
        "<tr><td>09:16</td><td>Gap-down check</td><td>Safety net — market-sells anything that gapped straight through its stop overnight</td></tr>"
        "<tr><td>Mon 08:00</td><td>Fundamentals refresh</td><td>Re-pulls XBRL filings and recomputes every stock's value score</td></tr>"
        "<tr><td>14:55</td><td>Rebalance scan</td><td>The main daily decision — sells, buys, top-ups, stop updates</td></tr>"
        "<tr><td>14:56</td><td>Paper trade scan</td><td>A fully separate, isolated simulation — never touches real money</td></tr>"
        "<tr><td>15:31</td><td>Exit-price correction</td><td>Swaps today's approximate exit prices for the real fill prices from the broker</td></tr>"
        "</table></div>",
        unsafe_allow_html=True,
    )

    # ---- Execution & safety nets ---------------------------------------
    st.markdown(
        _guide_section(
            "🚨",
            "coral",
            "Execution & safety nets",
            anchor="g-safety",
            subtitle="What's automatic, what needs your click, and what catches the unexpected.",
        ),
        unsafe_allow_html=True,
    )
    _pending_corp_actions_n = 0
    with contextlib.suppress(Exception):
        _pending_corp_actions_n = len(state_db.get_corporate_action_flags(status="pending"))
    st.markdown(
        '<div class="guide-grid3">'
        '<div class="guide-card"><h4>Auto-execute trades</h4>'
        f"<p>{'ON' if cfg.get('auto_execute_trades') else 'Off'} — when on, the scheduled 14:55 scan places "
        "its proposed sells/buys/top-ups as real orders with no confirmation click. The dashboard's own "
        "\"Run today's scan\" button never auto-places orders regardless of this setting — it's always "
        "review-first.</p></div>"
        '<div class="guide-card"><h4>Auto-apply stop updates</h4>'
        f"<p>{'ON' if cfg.get('auto_apply_stop_updates', True) else 'Off'} — whenever a stop genuinely "
        "ratchets up, the new stop is pushed straight to the broker's GTT order automatically. Low-risk by "
        "design: this can only ever tighten protection, never place a new order or loosen an existing one.</p></div>"
        '<div class="guide-card"><h4>Gap-down safety net</h4>'
        "<p>A GTT's own triggered order is a limit order, which can go unfilled if a stock gaps hard through "
        "its stop overnight. Each morning at 09:16 this checks for exactly that and fires an immediate market "
        "sell instead — the one place this app places a real order with no human in the loop by design.</p></div>"
        '<div class="guide-card"><h4>Catching a silent exit</h4>'
        "<p>If a GTT stop-loss fires at the broker, or you sell something manually outside this app, nothing "
        "tells this app directly. Instead, every scan compares its own records against your REAL broker "
        'holdings — anything missing gets marked closed and logged, tagged "GTT / External" since the two '
        "can't be told apart from the broker's API alone.</p></div>"
        '<div class="guide-card"><h4>Exit-price accuracy</h4>'
        "<p>The moment a position closes, its exit price is only an estimate (the last traded price at the "
        "moment this app noticed). At 15:31 each day, a dedicated pass fetches the broker's own real order "
        "book and corrects every trade that closed that day to its true average fill price.</p></div>"
        '<div class="guide-card"><h4>Split / bonus detection</h4>'
        "<p>Checked once daily: if a held stock's real broker quantity no longer matches what's on file, "
        "with nothing this app did to explain it, that's flagged for review on Positions &amp; Trade — a "
        "split or bonus changes qty and price together without any order this app placed, which would "
        "otherwise silently leave the stop-loss GTT pointing at stale numbers. Deliberately "
        "<b>confirm-first, never automatic</b>: the same mismatch could also mean shares were bought "
        "manually outside the app, which isn't a split at all."
        + (f"<br><b>{_pending_corp_actions_n} pending review right now.</b>" if _pending_corp_actions_n else "")
        + "</p></div>"
        "</div></div>",
        unsafe_allow_html=True,
    )

    # ---- Cash management ------------------------------------------------
    st.markdown(
        _guide_section(
            "💰",
            "teal",
            "Cash management",
            anchor="g-cash",
            subtitle="Keeping idle capital working, and the small recurring costs of actually trading — both tracked automatically.",
        ),
        unsafe_allow_html=True,
    )
    _sweep_qty, _sweep_value = (0, 0.0)
    if cfg.get("cash_sweep_enabled", False):
        with contextlib.suppress(Exception):
            _sweep_qty, _sweep_value = lr.get_cash_sweep_holding(cfg)
    st.markdown(
        '<div class="guide-grid3">'
        '<div class="guide-card"><h4>Idle cash sweep</h4>'
        f"<p>{'Currently ON' if cfg.get('cash_sweep_enabled') else 'Currently off'} — uninvested cash is "
        f"automatically parked in <b>{cfg.get('cash_sweep_symbol', 'LIQUIDCASE')}</b>, a liquid-fund ETF, so "
        "it earns interest instead of sitting idle — swept in after every rebalance run, gap-down sell, or "
        "manual trade, no minimum amount (buying it carries no DP charge). Whenever a new buy needs more "
        "cash than what's free, just enough gets automatically redeemed back first to cover the gap — the "
        "real DP charge applies there, since that IS a sell. It's never counted as one of your momentum "
        'positions, and its value is folded into "Cash" everywhere on the Overview page so nothing looks '
        "like it went missing."
        + (f"<br><b>Currently parked: {_sweep_qty} units, ₹{_sweep_value:,.0f}</b>" if _sweep_qty else "")
        + "</p></div>"
        '<div class="guide-card"><h4>DP charges</h4>'
        f"<p>Your depository charges ₹{cfg.get('dp_charge_per_scrip', 15.34):.2f} per stock, per day you "
        "sell it — this app logs that automatically to the Ledger the moment any position actually closes, "
        "no matter which of the exit paths above caused it, so it's never forgotten.</p></div>"
        '<div class="guide-card"><h4>Recurring charges</h4>'
        "<p>Fixed, calendar-scheduled costs like quarterly Demat AMC — defined once on the Ledger page "
        "(amount, cadence, next due date), then posted automatically every time they come due, correctly "
        "anchored to the same day of the month cycle after cycle.</p></div>"
        "</div></div>",
        unsafe_allow_html=True,
    )

    # ---- Pages tour -------------------------------------------------
    st.markdown(
        _guide_section(
            "🧭",
            "pink",
            "Tour of every page",
            anchor="g-pages",
            subtitle="What each tab in the sidebar actually shows you.",
        ),
        unsafe_allow_html=True,
    )
    _pages_tour = [
        (
            "🏠",
            "Positional Dashboard",
            "Your portfolio at a glance — equity curve, today's snapshot, live holdings summary.",
        ),
        (
            "⚡",
            "Intraday Dashboard",
            "The DaysLowVolumnBreakout intraday strategy — NIFTY breadth, today's candidates, live signal/position state.",
        ),
        (
            "📡",
            "Live Rebalance",
            "Today's proposed sells/buys/top-ups/stop-updates — review and execute, or watch auto-execute run.",
        ),
        ("💼", "Positions & Trade", "Your real, live broker holdings and intraday positions, plus manual order entry."),
        ("🔍", "Screener", "The full ranked universe — every gate, every score, browsable and chartable on demand."),
        (
            "📊",
            "Fundamentals",
            "The XBRL-based value-score scan across the universe, with the rubric behind every number.",
        ),
        ("⚙️", "Admin", "Every strategy setting in one form — stop mechanism, sizing, gates, automation toggles."),
        ("💰", "Ledger", "Deposits/withdrawals for accurate XIRR, plus DP charges and recurring costs."),
        (
            "📒",
            "Positional Tradebook",
            "Every trade this app has ever opened, with its entry snapshot, real exit type, and live P&L.",
        ),
        (
            "📒",
            "Intraday Tradebook",
            "Every intraday position's target/stop/squareoff legs, with realized P&L and cost breakdown.",
        ),
        ("🗂️", "Job Log", "Status and history of every scheduled and manual job — did today's scan actually run?"),
        ("📜", "Rebalance History", "The full audit trail of every sell/buy/top-up/stop-update ever proposed."),
        ("🧪", "Backtest", "Run the exact same engine against history to test a change before trusting it live."),
    ]
    st.markdown(
        '<div class="guide-pages-grid">'
        + "".join(
            f'<div class="guide-page-card"><span class="icon">{icon}</span>'
            f"<h5>{html_lib.escape(name)}</h5><p>{html_lib.escape(desc)}</p></div>"
            for icon, name, desc in _pages_tour
        )
        + "</div></div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="text-align:center;color:var(--ov-text-muted);font-size:12px;padding:24px 0 8px 0;">'
        "Every number on this page is read live from your current configuration — change a setting in "
        "Admin, and this page reflects it the next time you open it.</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

page_cockpit_p = st.Page(page_cockpit, title="Positional Dashboard", icon="🏠")
page_screener_p = st.Page(page_screener, title="Screener", icon="🔍")
page_live_rebalance_p = st.Page(page_live_rebalance, title="Live Rebalance", icon="📡")
page_positions_trade_p = st.Page(page_positions_trade, title="Positions & Trade", icon="💼")
page_backtest_p = st.Page(page_backtest, title="Backtest", icon="🧪")
page_fundamentals_p = st.Page(page_fundamentals, title="Fundamentals", icon="📊")
page_tradebook_p = st.Page(page_tradebook, title="Positional Tradebook", icon="📒")
page_job_log_p = st.Page(page_job_log, title="Job Log", icon="🗂️")
page_rebalance_history_p = st.Page(page_rebalance_history, title="Rebalance History", icon="📜")
page_ledger_p = st.Page(page_ledger, title="Ledger", icon="💰")
page_admin_p = st.Page(page_admin, title="Admin", icon="⚙️")
page_guide_p = st.Page(page_guide, title="Guide", icon="📘")
page_intraday_dashboard_p = st.Page(page_intraday_dashboard, title="Intraday Dashboard", icon="⚡", default=True)
page_intraday_tradebook_p = st.Page(page_intraday_tradebook, title="Intraday Tradebook", icon="📒")

# Injected before the sidebar (not per-page) so every page -- not just
# Overview, where this design system started -- gets the same compact
# card/badge/table look, and so the sidebar CSS below applies immediately.
st.markdown(_OVERVIEW_CSS, unsafe_allow_html=True)

with st.sidebar:
    # Flat, always-visible tabs grouped under a plain small-caps label --
    # matches the mockup's .side-label/.tab exactly (no collapse behavior
    # there at all), which an st.expander could never fully look like no
    # matter how much its border/background got stripped via CSS (it still
    # carries its own chevron/toggle chrome). st.navigation itself runs
    # with position="hidden" below so routing/query-params/current-page
    # tracking keep working exactly as before, just with no visible
    # built-in widget -- this whole block is just the visible menu.
    st.markdown('<p class="ov-side-label">Learn</p>', unsafe_allow_html=True)
    st.page_link(page_guide_p)

    st.markdown('<p class="ov-side-label">Trading</p>', unsafe_allow_html=True)
    st.page_link(page_intraday_dashboard_p)
    st.page_link(page_cockpit_p)
    st.page_link(page_live_rebalance_p)
    st.page_link(page_positions_trade_p)
    st.page_link(page_screener_p)
    st.page_link(page_fundamentals_p)
    st.page_link(page_admin_p)
    st.page_link(page_ledger_p)

    st.markdown('<p class="ov-side-label">Audit Trail</p>', unsafe_allow_html=True)
    st.page_link(page_tradebook_p)
    st.page_link(page_intraday_tradebook_p)
    st.page_link(page_job_log_p)
    st.page_link(page_rebalance_history_p)

    st.markdown('<p class="ov-side-label">Testing</p>', unsafe_allow_html=True)
    st.page_link(page_backtest_p)

    # Streamlit gives the current page's link no stable DOM marker (just an
    # unstable emotion class with a faint default tint), so CSS alone can't
    # paint the mockup's active-tab pill. Stamp aria-current="page" on the
    # link whose href matches the URL; the CSS above keys off it. A one-shot
    # script is not enough -- React re-renders the sidebar links right after
    # this script runs and wipes the attribute -- so a MutationObserver
    # (installed once per browser session) re-stamps after every re-render.
    # Watching childList only, not attributes, so its own setAttribute calls
    # can't re-trigger it in a loop.
    st.html(
        """<script>
        (function(){
          function mark(){
            const links = document.querySelectorAll(
              '[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]');
            const path = location.pathname.replace(/\\/+$/, "");
            links.forEach(a => {
              const href = (a.getAttribute("href") || "").split("?")[0];
              const active = href === "" ? (path === "" || path === "/")
                                         : path.endsWith("/" + href);
              if (active) a.setAttribute("aria-current", "page");
              else if (a.hasAttribute("aria-current")) a.removeAttribute("aria-current");
            });
          }
          mark();
          if (!window.__ovNavMarker) {
            // Body-wide childList observer: navigating pages re-renders the
            // MAIN area but often leaves the sidebar links untouched, so a
            // sidebar-scoped observer never fires and the pill stays on the
            // old page. Any rerun mutates the body somewhere; mark() is two
            // cheap queries over ~10 links. history hooks catch the URL
            // change itself (Streamlit navigates via pushState, no popstate).
            window.__ovNavMarker = new MutationObserver(mark);
            window.__ovNavMarker.observe(document.body, {childList: true, subtree: true});
            const push = history.pushState.bind(history);
            history.pushState = function(){ push.apply(null, arguments); setTimeout(mark, 0); };
            const repl = history.replaceState.bind(history);
            history.replaceState = function(){ repl.apply(null, arguments); setTimeout(mark, 0); };
            window.addEventListener("popstate", () => setTimeout(mark, 0));
          }
        })();
        </script>""",
        unsafe_allow_javascript=True,
    )

    st.divider()
    if st.button("LOGOUT →", key="ov_logout"):
        state_db.delete_remember_token(st.context.cookies.get("remember_token", ""))
        st.session_state["dashboard_authenticated"] = False
        st.html(
            '<script>document.cookie = "remember_token=; max-age=0; path=/; Secure";</script>',
            unsafe_allow_javascript=True,
        )
        st.rerun()

# Global brandbar -- shown above every page's own content, matching the
# mockup's .brandbar (which sits above the tabpanes, not inside any one of
# them). Available cash / pending actions / universe size used to live in
# the sidebar; moved here to match the reference design exactly.
n_skipped = len(config.UNIVERSE_RAW) - len(config.UNIVERSE)
skipped_note = f" ({n_skipped} skipped)" if n_skipped else ""
_last_run = state_db.get_last_rebalance_run()
_n_pending = 0
if _last_run is not None:
    _n_pending = len(_last_run["sells"]) + len(_last_run["buys"]) + len(_last_run.get("stop_updates", pd.DataFrame()))
_pending_chip = (
    f'<span class="ov-chip ov-chip-danger">🔴 {_n_pending} action(s) pending</span>'
    if _n_pending
    else '<span class="ov-chip ov-chip-success">✅ No actions pending</span>'
)
_scan_chip_g = f"📅 Last scan {_last_run['run_time']:%d %b %H:%M}" if _last_run is not None else "📅 No scan run yet"
_open_slots = len(state_db.get_open_positions())
_logo_uri = _sidebar_logo_data_uri()
_logo_html = (
    f'<img src="{_logo_uri}" class="ov-topbar-logo" alt="KK Trading System">'
    if _logo_uri
    else '<div class="ov-brand">🚀 KK Trading System <span class="ov-sub">Calendar-entry momentum</span></div>'
)
# Splitting logo/chips/sync across st.columns() kept fighting the flex
# ratios (logo overlapping chips, chips wrapping early depending on
# window width) no matter how the flex-basis/shrink was tuned. Back to
# ONE markdown call for logo+chips (the original, proven .ov-header
# space-between layout -- logo left, chips right, never had this problem
# before the sync icon was added). The Sync button is a real widget that
# can't be flattened into that HTML string, so instead of sharing a flex
# row with the chips at all, it's taken OUT of the normal flow entirely
# via absolute positioning against this container (position:relative on
# .st-key-ov-topbar) -- it can't overlap or squeeze anything else because
# it no longer participates in anyone else's layout math.
with st.container(key="ov-topbar"):
    st.markdown(
        '<div class="ov-header" style="margin-bottom:0;">'
        f"{_logo_html}"
        '<div class="ov-chips">'
        f"{_pending_chip}"
        f'<span class="ov-chip ov-chip-accent">{_scan_chip_g}</span>'
        f'<span class="ov-chip ov-chip-success">Slots {_open_slots}/'
        f"{config.STRATEGY['max_positions']}</span>"
        f'<span class="ov-chip ov-chip-accent">F&amp;O universe: {len(config.UNIVERSE_RAW)} stocks'
        f"{skipped_note} · {dt.date.today():%d %b %Y}</span>"
        "</div></div>",
        unsafe_allow_html=True,
    )
    _sync_icon_uri = _asset_data_uri("synch.png")
    if _sync_icon_uri:
        # _OVERVIEW_CSS (injected once, module-level, earlier in this
        # same script run) already styles .st-key-ov_sync button as a
        # small text button -- this second <style> tag lands later in
        # the DOM, so on equal specificity it wins without needing to
        # touch that shared block just for this one icon swap.
        st.markdown(
            "<style>.st-key-ov_sync button {"
            f"background-image:url('{_sync_icon_uri}'); background-size:18px 18px; "
            "background-repeat:no-repeat; background-position:center; "
            "color:transparent !important; font-size:0 !important; "
            "width:30px !important; height:30px !important; padding:0 !important; "
            "min-width:0 !important; border-radius:50% !important;"
            "}</style>",
            unsafe_allow_html=True,
        )
    if st.button("Sync", key="ov_sync"):
        st.rerun()

nav = st.navigation(
    [
        page_cockpit_p,
        page_live_rebalance_p,
        page_positions_trade_p,
        page_screener_p,
        page_fundamentals_p,
        page_tradebook_p,
        page_job_log_p,
        page_rebalance_history_p,
        page_backtest_p,
        page_admin_p,
        page_ledger_p,
        page_guide_p,
        page_intraday_dashboard_p,
        page_intraday_tradebook_p,
    ],
    position="hidden",
)
nav.run()
