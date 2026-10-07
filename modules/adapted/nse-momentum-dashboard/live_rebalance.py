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
Stage 1 of live automation: propose today's rebalance (sells + buys) by
running the exact same screener pipeline used live and in the backtest,
diffing it against your ACTUAL broker holdings.

propose_rebalance() itself only ever computes a proposal -- it never
places an order. Execution is a separate, explicit step: either the
dashboard's manual "Execute all .../Apply..." buttons (config.STRATEGY
["auto_execute_trades"]=False, the default), or main()'s own
auto-execute block right after computing the proposal
(auto_execute_trades=True) -- both routes call the exact same
execute_sells()/execute_buys()/execute_top_ups() functions below, so
manual and automated execution can never drift apart. Meant to be run
once a day, either from the dashboard's Live Rebalance page or scheduled
externally (systemd timer / cron / Windows Task Scheduler) via
`python live_rebalance.py`.

check_gap_down_stops()/main_gap_check() and trailing-stop ratchets
(compute_stop_updates(), config.STRATEGY["auto_apply_stop_updates"],
True by default) are automated regardless of auto_execute_trades --
both are lower-risk, one-directional actions (an immediate market sell
to guarantee an exit, or tightening an existing stop) that don't carry
the same new-capital-deployment risk a full auto-execute does.

Why sells can lag a day: the rebalance rule (200 EMA / rank) is only ever
evaluated when this runs, so if you don't run it on a given day, a stock
that broke down that day won't be flagged until you next run it. Stops are
NOT covered here if you placed a GTT stop-loss at entry (kite_client.
place_gtt_stoploss) -- that already protects you intraday without needing
this job to run. This job only proposes the rebalance-rule exits/entries.
"""

import contextlib
import datetime as dt
import math
import os

import kite_client
import nse_holidays
import pandas as pd
import screener
import state_db

import config
import indicators

LOG_PATH = os.path.join("cache", "live_rebalance_log.txt")


def _trailing_stop_candidate(
    df: pd.DataFrame, highest_close: float, atr_now: float, cfg: dict
) -> float | None:
    """The ongoing ratchet's candidate stop -- the ATR chandelier formula,
    unless mad_stop_enabled, in which case the MAD volatility trail's own
    current lower band takes over (same precedence as backtest.py's
    trailing-ratchet block and indicators._suggested_stop's initial-stop
    fallback). compute_stop_updates()'s caller already enforces "ratchet
    up only" via `if new_stop <= pos["current_stop"]: continue`,
    regardless of which formula computed this candidate -- MAD's own
    one-sided-rise property doesn't need separate handling here. Deferred
    import: mad_trail_strategy imports indicators at module level; safe
    as a call-time import since both are already fully loaded by the
    time this runs.

    Returns None when there's no ratchet candidate to apply this run --
    matches backtest.py's own day-loop exactly (backtest.py:955-972):
    `if mad_stop_enabled: ... (no regime check, no ATR fallback -- just
    skip this symbol this run if the MAD value isn't available) elif
    trailing_stop_enabled: ...` (no else). Note this deliberately differs
    from indicators._suggested_stop()'s INITIAL-stop logic, which DOES
    check MAD's regime (you don't want to enter a brand-new position
    anchored to a currently-bearish trail value) -- for an ALREADY-HELD
    position's ongoing ratchet, backtest just tries the current lower
    band regardless of regime, relying on the "only rise" comparison in
    the caller to naturally protect against ratcheting down. Previously
    this always computed the ATR formula regardless of trailing_stop_
    enabled's value, silently ignoring that toggle, and (a separate bug)
    added a regime check + ATR fallback for the MAD case that backtest.py
    doesn't actually have."""
    if cfg.get("mad_stop_enabled", False):
        import mad_trail_strategy

        mad_cfg = mad_trail_strategy.cfg_from_strategy(cfg)
        mad_df = mad_trail_strategy.precompute_mad_trail(df, mad_cfg)
        if mad_df.empty:
            return None
        last = mad_df.iloc[-1]
        return None if pd.isna(last["lower"]) else float(last["lower"])
    if not cfg.get("trailing_stop_enabled", False):
        return None
    return highest_close - cfg["trailing_atr_multiple"] * atr_now


def compute_stop_updates(held_symbols: set[str], cfg: dict) -> list[dict]:
    """Recomputes each held position's trailing stop using the exact same
    formula as backtest.py's step 1b (highest_close_since_entry -
    trailing_atr_multiple*ATR, ratchet up only) -- so live and backtest
    logic can never quietly drift apart. highest_close/atr bookkeeping is
    persisted back to state_db every run a ratchet CANDIDATE exists
    (whether or not it actually ratchets this run) -- skipped entirely
    for a symbol only when neither mad_stop_enabled nor trailing_stop_
    enabled is on (see _trailing_stop_candidate's None case), matching
    backtest.py having no ratchet mechanism active at all in that state.

    cfg["auto_apply_stop_updates"] (True by default): when a stop
    genuinely ratchets, immediately pushes it to the real broker GTT
    (kite_client.modify_gtt_trigger + state_db.apply_stop_update) -- same
    automation level as the gap-down safety check, since raising a stop
    is a one-directional, low-risk action (it only ever tightens risk,
    never loosens it or places a new order). Shared by both the scheduled
    daily job and the dashboard's manual "Run today's scan" button, since
    this function is common to both.

    Returns only the updates that still need YOUR attention: auto-apply
    was off, there's no active GTT to push to (needs one placed manually
    first), or the modify_gtt_trigger call itself failed (network/API
    error) -- each such row carries an "apply_error" explaining why.
    A successfully auto-applied update is NOT included here; it's already
    done."""
    stale = state_db.get_stale_open_symbols(held_symbols)
    exit_prices = kite_client.get_ltp(stale) if stale else {}
    positions = state_db.reconciled_positions(held_symbols, exit_prices)
    auto_apply = cfg.get("auto_apply_stop_updates", True)
    updates = []
    for sym, pos in positions.items():
        try:
            df = kite_client.fetch_daily_candles(sym, days=300)
        except Exception:
            continue
        if df.empty:
            continue
        today_close = float(df["close"].iloc[-1])
        highest_close = max(pos["highest_close"], today_close)
        atr_now = float(indicators.atr(df, cfg["atr_period"]).iloc[-1])
        new_stop = _trailing_stop_candidate(df, highest_close, atr_now, cfg)
        if new_stop is None:
            continue  # neither mad_stop nor trailing_stop is enabled (or
            # MAD has no value yet) -- nothing to log or apply
        # Round to paisa precision before comparing/storing/sending to Kite.
        # The MAD trail recomputes from scratch over the full price history
        # every run, so two consecutive days can land a few millionths of a
        # rupee apart for what's really the same value -- that noise used
        # to pass the raw-float "> current_stop" check as a genuine ratchet,
        # then Kite's own modify_gtt_trigger call (which compares at real
        # currency precision) rejected it outright: "No changes detected.
        # Modify the trigger parameters before submitting." (hit live on
        # SONACOMS, 2026-09-01: current_stop=771.3750740681 vs a freshly
        # computed 771.375075941754 -- both round to the same Rs.771.38).
        new_stop = round(new_stop, 2)
        state_db.update_position_stop(sym, highest_close, atr_now, new_stop)
        if new_stop <= round(pos["current_stop"], 2):
            continue  # no ratchet this run -- nothing to apply or report

        entry = {
            "symbol": sym,
            "qty": pos["qty"],
            "current_stop": round(pos["current_stop"], 2),
            "recommended_stop": round(new_stop, 2),
            "gtt_trigger_id": pos.get("gtt_trigger_id"),
        }
        gtt_id = pos.get("gtt_trigger_id")
        if not auto_apply:
            updates.append(entry)
            continue
        if not gtt_id:
            entry["apply_error"] = "no active GTT to update -- place one manually (Trade tab)"
            updates.append(entry)
            continue
        try:
            ltp = kite_client.get_ltp([sym])[sym]
            kite_client.modify_gtt_trigger(int(gtt_id), sym, int(pos["qty"]), new_stop, ltp)
            state_db.apply_stop_update(sym)
        except Exception as e:
            entry["apply_error"] = str(e)
            updates.append(entry)
    return updates


def get_live_holdings() -> pd.DataFrame:
    """Combined CNC holdings + any same-day positions, one row per symbol
    (qty, avg entry price), indexed by tradingsymbol. Delivery momentum
    swings mostly live in holdings; positions covers a same-day buy before
    it settles into holdings overnight.

    Deliberately excludes the idle-cash-sweep instrument (config.STRATEGY
    ["cash_sweep_symbol"], e.g. LIQUIDCASE) -- it isn't a momentum swing
    position and must never count toward max_positions, sector caps, or
    the sell-check loop. Its value is added back separately wherever
    total capital is computed -- see get_cash_sweep_holding() and its
    callers in propose_rebalance()."""
    frames = []
    pos = kite_client.get_positions()
    if not pos.empty and "quantity" in pos.columns:
        # > 0, not != 0 -- a same-day SELL of an existing holding leaves a
        # NEGATIVE "day" quantity here (the settlement-lag leg, nets to 0
        # against the holding overnight), not a real short (long-only CNC
        # swing trading). Including it phantom-counted a fully-sold symbol
        # as still held with a negative qty -- confirmed live 2026-08-04,
        # a same-day SONACOMS sell left it appearing "held" again on the
        # very next page refresh after execute_sells() ran.
        p = pos[pos["quantity"] > 0][["tradingsymbol", "quantity", "average_price"]]
        frames.append(p)
    hold = kite_client.get_holdings()
    if not hold.empty and "quantity" in hold.columns:
        h = hold[hold["quantity"] > 0][["tradingsymbol", "quantity", "average_price"]]
        frames.append(h)
    if not frames:
        return pd.DataFrame(columns=["quantity", "average_price"])
    combined = pd.concat(frames, ignore_index=True)
    sweep_sym = config.STRATEGY.get("cash_sweep_symbol", "LIQUIDCASE")
    combined = combined[combined["tradingsymbol"] != sweep_sym]
    if combined.empty:
        return pd.DataFrame(columns=["quantity", "average_price"])
    combined["cost"] = combined["quantity"] * combined["average_price"]
    grouped = combined.groupby("tradingsymbol").agg(
        quantity=("quantity", "sum"), cost=("cost", "sum")
    )
    grouped["average_price"] = grouped["cost"] / grouped["quantity"]
    return grouped[["quantity", "average_price"]]


def detect_corporate_actions() -> list[dict]:
    """Compares our stored positions.qty against Kite's REAL held qty for
    every open position -- a mismatch that isn't explained by anything
    this app did itself (no buy/sell/top-up went through our own code to
    change it) is the signature of a stock split or bonus issue: the
    exchange changed the qty and price at the broker without any order
    this app placed, silently invalidating our own entry_price/
    current_stop/highest_close AND the real GTT stop-loss order (still
    referencing the pre-split qty/price).

    Read-only and safe to run automatically every day: this only detects
    and persists a 'pending' flag (state_db.corporate_action_flags) for
    review -- it never touches the positions/trades tables or the real
    GTT itself. See apply_corporate_action_adjustment() for the actual
    (user-confirmed) fix. Idempotent -- won't create a second pending
    flag for a symbol that already has one outstanding.

    Returns the flags newly inserted this run (empty list if nothing
    changed or reconciliation itself failed)."""
    try:
        held = get_live_holdings()
    except Exception:
        return []
    our_positions = state_db.get_open_positions()
    new_flags = []
    for sym, pos in our_positions.items():
        if sym not in held.index:
            continue  # fully exited -- reconciled_positions()'s job, not this
        live_qty = int(held.loc[sym, "quantity"])
        our_qty = int(pos["qty"])
        if live_qty == our_qty or our_qty <= 0 or live_qty <= 0:
            continue
        if state_db.has_pending_corporate_action_flag(sym):
            continue  # already flagged, awaiting review -- don't duplicate
        ratio = live_qty / our_qty
        state_db.insert_corporate_action_flag(
            sym,
            pos.get("id"),
            our_qty,
            live_qty,
            ratio,
            float(pos["entry_price"]),
            float(pos["current_stop"]),
            float(pos["highest_close"]),
            pos.get("gtt_trigger_id"),
        )
        new_flags.append({"symbol": sym, "our_qty": our_qty, "live_qty": live_qty, "ratio": ratio})
    return new_flags


def apply_corporate_action_adjustment(flag_id: int) -> dict:
    """User-confirmed fix for one detect_corporate_actions() flag:
    rescales entry_price/current_stop/highest_close by 1/ratio (qty went
    up by `ratio`, so per-share price must have gone down by the same
    factor for total position value to be unchanged -- the whole point of
    a split/bonus), updates qty to the real live qty, applies the same
    rescale to the matching open trades row so P&L stays correct at exit,
    and pushes the corrected qty/trigger price to the real GTT if one was
    on file. Marks the flag 'applied' once the position/trade bookkeeping
    is fixed, even if the GTT push itself fails (that's the more
    time-sensitive fix) -- the result dict says exactly what happened."""
    flags = state_db.get_corporate_action_flags(status=None)
    match = flags[flags["id"] == flag_id]
    if match.empty:
        return {"error": f"No such flag: {flag_id}"}
    f = match.iloc[0]
    if f["status"] != "pending":
        return {"error": f"Flag {flag_id} is already {f['status']}"}

    ratio = float(f["ratio"])
    new_entry_price = float(f["old_entry_price"]) / ratio
    new_current_stop = float(f["old_current_stop"]) / ratio
    new_highest_close = float(f["old_highest_close"]) / ratio
    new_qty = int(f["live_qty"])
    sym = f["symbol"]

    if f["position_id"] is not None and not pd.isna(f["position_id"]):
        state_db.apply_corporate_action_to_position(
            int(f["position_id"]), new_qty, new_entry_price, new_current_stop, new_highest_close
        )
    state_db.apply_corporate_action_to_trade(sym, new_qty, new_entry_price, new_current_stop)

    gtt_result = None
    gtt_id = f["old_gtt_trigger_id"]
    if gtt_id is not None and not pd.isna(gtt_id):
        try:
            ltp = kite_client.get_ltp([sym])[sym]
            kite_client.modify_gtt_trigger(int(gtt_id), sym, new_qty, new_current_stop, ltp)
            gtt_result = "updated"
        except Exception as e:
            gtt_result = f"FAILED -- {e} -- update or replace this GTT manually"

    state_db.resolve_corporate_action_flag(flag_id, "applied")
    return {
        "symbol": sym,
        "ratio": ratio,
        "new_qty": new_qty,
        "new_entry_price": round(new_entry_price, 2),
        "new_current_stop": round(new_current_stop, 2),
        "gtt": gtt_result,
    }


def get_cash_sweep_holding(cfg: dict | None = None) -> tuple[int, float]:
    """Real qty + current market value of the idle-cash-sweep instrument
    actually held right now, queried fresh from Kite -- never tracked in
    our own positions table (it isn't a momentum trade, see
    cash_sweep_log's own comment in state_db.py). Returns (0, 0.0) on any
    lookup failure or if nothing is held, never raises."""
    cfg = cfg or config.STRATEGY
    sym = cfg.get("cash_sweep_symbol", "LIQUIDCASE")
    try:
        qty = 0
        for df in (kite_client.get_holdings(), kite_client.get_positions()):
            if not df.empty and "tradingsymbol" in df.columns:
                rows = df[(df["tradingsymbol"] == sym) & (df["quantity"] > 0)]
                qty += int(rows["quantity"].sum())
        if qty <= 0:
            return 0, 0.0
        ltp = kite_client.get_ltp([sym])[sym]
        return qty, round(qty * ltp, 2)
    except Exception:
        return 0, 0.0


def compute_portfolio_value(cfg: dict | None = None) -> dict:
    """Canonical 'what's my total portfolio value right now' calc --
    available cash + real momentum-stock holdings at current price +
    whatever's parked in the cash-sweep instrument. The SAME basis
    dashboard.py's page_cockpit() logs from on every page visit, factored
    out here so the scheduled exit-price-correction job can log a daily
    snapshot too (see main_exit_price_correction()) without a second,
    separately-maintained copy of "how do I total this up" -- exactly
    the kind of drift that let the cash-sweep instrument get double-
    counted in three different places earlier before each was fixed.
    Reuses get_live_holdings() (already excludes the cash-sweep symbol)
    rather than re-deriving that exclusion a third time.

    Returns {"portfolio_value", "invested_amount", "holdings_value"},
    all 0.0 on any lookup failure -- callers should treat an all-zero
    result as "couldn't compute today, skip logging" rather than a real
    reading, same guard page_cockpit() already applies."""
    cfg = cfg or config.STRATEGY
    try:
        available_cash = kite_client.get_margins()["equity"]["available"]["live_balance"]
    except Exception:
        return {"portfolio_value": 0.0, "invested_amount": 0.0, "holdings_value": 0.0}

    held = get_live_holdings()
    invested_amount = 0.0
    holdings_value = 0.0
    if not held.empty:
        try:
            ltps = kite_client.get_ltp(list(held.index))
        except Exception:
            ltps = {}
        invested_amount = float((held["quantity"] * held["average_price"]).sum())
        holdings_value = float(
            sum(
                qty * ltps.get(sym, avg_price)
                for sym, qty, avg_price in zip(
                    held.index, held["quantity"], held["average_price"], strict=False
                )
            )
        )

    cash_sweep_value = (
        get_cash_sweep_holding(cfg)[1] if cfg.get("cash_sweep_enabled", False) else 0.0
    )
    return {
        "portfolio_value": available_cash + holdings_value + cash_sweep_value,
        "invested_amount": invested_amount,
        "holdings_value": holdings_value,
    }


# Same reasoning as sweep_idle_cash()'s CASH_SWEEP_BUFFER, applied the
# other direction: ensure_cash_for_buys() used to redeem EXACTLY the
# calculated shortfall, no margin -- confirmed live 2026-09-11, NYKAA's
# buy was rejected ("Add 43.19") minutes after an Rs.8,758 shortfall
# redemption that should have covered it, purely because the real
# available-cash figure drifted a few rupees between this check and the
# actual buy order landing (LTP tick, rounding). With 700+ units of
# LIQUIDCASE typically held (~Rs.80k+), redeeming a bit extra costs
# nothing -- any leftover gets swept straight back in by sweep_idle_cash()
# later in the same run, exactly as it already does today.
CASH_SHORTFALL_BUFFER = 1000.0


def ensure_cash_for_buys(needed: float, cfg: dict | None = None) -> dict | None:
    """Call right before placing real buy/top-up orders: if today's total
    buy cost exceeds real available cash, redeems the cash-sweep
    instrument first (a real SELL order, so the usual DP charge applies --
    unlike buying it) to close the gap, plus CASH_SHORTFALL_BUFFER extra
    margin so a small price/rounding drift between this check and the
    actual buy order doesn't still leave it short. Kite's own order
    rejection remains the final safety net if even that's not enough. No-
    ops (returns None) when cash_sweep_enabled is off, cash is already
    sufficient, or nothing is actually held to redeem."""
    cfg = cfg or config.STRATEGY
    if not cfg.get("cash_sweep_enabled", False) or needed <= 0:
        return None
    sym = cfg.get("cash_sweep_symbol", "LIQUIDCASE")
    try:
        margins = kite_client.get_margins()
        available_cash = margins["equity"]["available"]["live_balance"]
    except Exception:
        return None
    shortfall = needed - available_cash
    if shortfall <= 0:
        return None
    qty_held, _ = get_cash_sweep_holding(cfg)
    if qty_held <= 0:
        return None
    try:
        ltp = kite_client.get_ltp([sym])[sym]
    except Exception:
        return None
    qty_to_sell = min(qty_held, math.ceil((shortfall + CASH_SHORTFALL_BUFFER) / ltp))
    if qty_to_sell <= 0:
        return None
    try:
        oid = kite_client.place_order(sym, qty_to_sell, "SELL")
    except Exception as e:
        return {"action": "redeem", "symbol": sym, "error": str(e)}
    amount = round(qty_to_sell * ltp, 2)
    today = dt.date.today().isoformat()
    state_db.record_cash_sweep(
        today,
        "sell",
        sym,
        qty_to_sell,
        ltp,
        amount,
        f"Redeemed to cover a Rs.{shortfall:,.0f} cash shortfall for today's buys "
        f"(+Rs.{CASH_SHORTFALL_BUFFER:,.0f} buffer)",
        oid,
    )
    dp_charge = cfg.get("dp_charge_per_scrip", 0.0)
    if dp_charge > 0:
        state_db.record_cash_flow(today, -dp_charge, f"DP charge -- {sym} sold")
    return {
        "action": "redeem",
        "symbol": sym,
        "qty": qty_to_sell,
        "price": ltp,
        "amount": amount,
        "order_id": oid,
    }


def sweep_idle_cash(cfg: dict | None = None) -> dict | None:
    """Call after any cash-affecting action settles (a rebalance run, a
    gap-down sell, a manual trade): parks whatever real cash is currently
    idle into the cash-sweep instrument. Buying it carries no DP charge
    (that's only ever levied on a sell), so there's no minimum -- every
    idle rupee that can afford at least 1 unit gets swept. No-ops when
    cash_sweep_enabled is off or cash can't afford even 1 unit."""
    cfg = cfg or config.STRATEGY
    if not cfg.get("cash_sweep_enabled", False):
        return None
    sym = cfg.get("cash_sweep_symbol", "LIQUIDCASE")
    try:
        margins = kite_client.get_margins()
        available_cash = margins["equity"]["available"]["live_balance"]
        ltp = kite_client.get_ltp([sym])[sym]
    except Exception:
        return None
    # Small safety buffer: get_margins()'s "available" figure can be a
    # hair optimistic right after a same-day sell (its proceeds haven't
    # actually SETTLED yet -- T+1 -- even though this call already shows
    # them as available), so sweeping the FULL reported amount can get
    # the buy order rejected outright by Kite's own real-time margin
    # check. Hit live 2026-09-04: reported available Rs.76,119 moments
    # after a SONACOMS sale, real order rejected needing Rs.336 more.
    # Held-back cash just gets swept the next run instead of lost.
    CASH_SWEEP_BUFFER = 1000.0
    qty_to_buy = int(max(available_cash - CASH_SWEEP_BUFFER, 0) // ltp) if ltp > 0 else 0
    if qty_to_buy <= 0:
        return None
    try:
        oid = kite_client.place_order(sym, qty_to_buy, "BUY")
    except Exception as e:
        return {"action": "sweep", "symbol": sym, "error": str(e)}
    amount = round(qty_to_buy * ltp, 2)
    today = dt.date.today().isoformat()
    state_db.record_cash_sweep(today, "buy", sym, qty_to_buy, ltp, amount, "Swept idle cash", oid)
    return {
        "action": "sweep",
        "symbol": sym,
        "qty": qty_to_buy,
        "price": ltp,
        "amount": amount,
        "order_id": oid,
    }


def get_unsettled_quantities() -> dict[str, int]:
    """Per-symbol quantity that would NOT yield usable cash today if sold --
    same-day CNC positions (bought today, shows in kite_client.get_positions()
    until it settles into holdings overnight) plus T1 holdings
    (kite_client.get_holdings()'s t1_quantity -- bought yesterday, settlement
    completes the day after that). Zerodha credits a SOLD, already-settled
    (T0) holding's proceeds as usable margin the same day; a same-day
    position or T1 holding's sale proceeds only become usable once that
    settlement cycle finishes -- this is what propose_rebalance() checks
    before counting a proposed sell's proceeds toward today's buying
    power (the "T1/BTST" case). get_holdings() itself folds t1_quantity
    into quantity for DISPLAY purposes (see its docstring) -- the raw
    t1_quantity column is still present on the DataFrame it returns, just
    not documented as something callers should look at; this is the one
    place that does."""
    unsettled: dict[str, int] = {}
    pos = kite_client.get_positions()
    if not pos.empty and "quantity" in pos.columns:
        for _, r in pos[pos["quantity"] > 0].iterrows():
            sym = r["tradingsymbol"]
            unsettled[sym] = unsettled.get(sym, 0) + int(r["quantity"])
    hold = kite_client.get_holdings()
    if not hold.empty and "t1_quantity" in hold.columns:
        for _, r in hold[hold["t1_quantity"] > 0].iterrows():
            sym = r["tradingsymbol"]
            unsettled[sym] = unsettled.get(sym, 0) + int(r["t1_quantity"])
    return unsettled


def _holdings_value(held: pd.DataFrame, ranked: pd.DataFrame) -> float:
    """Current mark-to-market value of held positions -- held's own
    average_price is COST basis, not current price, so this isn't just
    (quantity * average_price). Reuses ranked's already-fetched price where
    the held symbol appears there (the common case); falls back to a fresh
    LTP fetch only for the rest (delisted from F&O, gate failures, etc.),
    and to cost basis as a last resort if even that fails."""
    if held.empty:
        return 0.0
    prices = {sym: float(ranked.loc[sym, "price"]) for sym in held.index if sym in ranked.index}
    missing = [sym for sym in held.index if sym not in prices]
    if missing:
        with contextlib.suppress(Exception):
            prices.update(kite_client.get_ltp(missing))
    return float(
        sum(
            held.loc[sym, "quantity"] * prices.get(sym, held.loc[sym, "average_price"])
            for sym in held.index
        )
    )


def propose_rebalance(
    available_cash: float,
    cfg: dict | None = None,
    fundamentals: pd.DataFrame | None = None,
    progress_cb=None,
) -> dict:
    """Returns {"run_time", "sells", "buys", "holdings", "open_slots"}.
    Nothing here executes an order -- see module docstring."""

    def report(stage, frac):
        if progress_cb:
            progress_cb(stage, frac)

    cfg = dict(cfg or config.STRATEGY)

    report("Loading current holdings...", 0.05)
    held = get_live_holdings()

    # Idle-cash sweep (cash_sweep_enabled): treat whatever's currently
    # parked in the cash-sweep instrument as spendable capital for SIZING
    # purposes -- otherwise the strategy would systematically undersize
    # buys just because some capital happens to be earning interest
    # instead of sitting as raw cash. Actually turning that theoretical
    # availability into real cash (redeeming it) only happens at EXECUTION
    # time, right before real buy orders go out -- see
    # ensure_cash_for_buys(), called from main()/the dashboard's manual
    # Execute buttons. 0.0 whenever the feature is off, byte-identical to
    # before this existed.
    cash_sweep_value = (
        get_cash_sweep_holding(cfg)[1] if cfg.get("cash_sweep_enabled", False) else 0.0
    )

    # Market regime filter (backtest.py:817, 926-929): when NIFTY's own
    # close is below its own regime_ema_period EMA, caps how many NEW
    # positions may open to max_positions * regime_position_multiplier --
    # never force-sells anything, and the SIZING denominator (target_
    # per_slot/allocate_equal_weight_buys' max_positions below) stays the
    # full, unreduced cfg["max_positions"] throughout, exactly matching
    # backtest's two-variable split (a regime-halved slot count leaves the
    # unused capital in cash, not redistributed into fewer/larger
    # positions). Off by default -- effective_max_positions == max_
    # positions whenever this is off, byte-identical to before this
    # existed. Fetches its own cheap NIFTY copy rather than threading one
    # out of screener.run_screen() below, to avoid changing that
    # function's return contract for its other two callers.
    effective_max_positions = cfg["max_positions"]
    if cfg.get("regime_filter_enabled", False):
        bench_regime = kite_client.benchmark_candles(cfg["history_days"])
        regime_ema = indicators.ema(bench_regime["close"], cfg.get("regime_ema_period", 200))
        regime_ok = bool(bench_regime["close"].iloc[-1] > regime_ema.iloc[-1])
        if not regime_ok:
            effective_max_positions = max(
                1, int(cfg["max_positions"] * cfg.get("regime_position_multiplier", 0.5))
            )

    report("Scanning universe (screener pipeline)...", 0.10)
    ranked = screener.run_screen(
        with_fundamentals=True,
        fundamentals=fundamentals,
        progress_cb=lambda s, f: report(s, 0.10 + f * 0.7),
    )

    # Cache the same ranked table the Screener page's own "Run screen"
    # button computes -- a rebalance run already does this full scan
    # internally, so caching it here too means the Screener page shows
    # this run's fresh data without a second, redundant universe fetch.
    os.makedirs("cache", exist_ok=True)
    ranked.to_pickle(screener.SCREEN_CACHE)

    candidates = ranked[ranked["all_gates"]]
    keep_zone = set(candidates.head(cfg["max_positions"] * 2).index)

    # ---- Sells: same rebalance rule as the backtest (200 EMA / rank) ----
    # Gated by cfg["rebalance_cadence"]: "daily" (default) evaluates this
    # every run; "weekly" only on the last trading day of the ISO week
    # (nse_holidays.is_week_end_trading_day); "monthly" only on the first
    # trading day of the month (nse_holidays.is_month_start_trading_day) --
    # same definitions backtest.py's weekly/monthly rb_dates use. Buys/
    # top-ups below are NOT gated by this -- a slot that's already open
    # (from an earlier sell, or just fewer than max_positions currently
    # held) still gets filled today regardless of cadence, matching
    # backtest.py's own daily slot-fill-from-watchlist behavior.
    report("Checking held positions against the rebalance rule...", 0.85)
    _cadence = cfg.get("rebalance_cadence", "daily")
    if _cadence == "daily":
        is_rebalance_day = True
    elif _cadence == "weekly":
        is_rebalance_day = nse_holidays.is_week_end_trading_day(dt.date.today())
    else:  # "monthly" (and any unrecognized value, same fallback as before)
        is_rebalance_day = nse_holidays.is_month_start_trading_day(dt.date.today())
    sells = []
    if is_rebalance_day:
        for sym, row in held.iterrows():
            reason = screener.sell_check(
                sym, ranked, candidates, keep_zone, cfg["max_positions"], cfg
            )
            if reason:
                sells.append(
                    {
                        "symbol": sym,
                        "qty": int(row["quantity"]),
                        "avg_price": float(row["average_price"]),
                        "reason": reason,
                    }
                )
    sells_df = pd.DataFrame(sells)

    # ---- Buys: fill slots opened up by the sells above ----
    report("Sizing new candidates...", 0.92)
    sold_syms = set(sells_df["symbol"]) if not sells_df.empty else set()
    still_held = set(held.index) - sold_syms
    open_slots = max(effective_max_positions - len(still_held), 0)

    # Total portfolio value (cash + everything held, current prices, plus
    # whatever's parked in the cash sweep instrument -- see the comment at
    # this function's top) -- the equal-weight denominator, unchanged
    # either sizing mode.
    total_equity = available_cash + _holdings_value(held, ranked) + cash_sweep_value
    target_per_slot = total_equity / cfg["max_positions"]

    # Sell proceeds use each symbol's CURRENT price (from the screener,
    # today's close), not the cost-basis avg_price the sells table
    # displays -- avg_price would understate/overstate what's actually
    # about to come back as cash. Only the SETTLED portion of each sale
    # counts toward today's usable pool -- a same-day position or T1
    # holding (bought yesterday, BTST) still needs its own settlement
    # cycle before Zerodha treats its sale proceeds as usable margin; see
    # get_unsettled_quantities()'s docstring.
    unsettled_qtys = get_unsettled_quantities()
    sell_proceeds = 0.0
    unsettled_proceeds = 0.0
    for sym, qty, avg_price in zip(
        sells_df.get("symbol", []),
        sells_df.get("qty", []),
        sells_df.get("avg_price", []),
        strict=False,
    ):
        price = float(ranked.loc[sym, "price"]) if sym in ranked.index else avg_price
        unsettled_qty = min(qty, unsettled_qtys.get(sym, 0))
        settled_qty = qty - unsettled_qty
        sell_proceeds += price * settled_qty
        unsettled_proceeds += price * unsettled_qty
    cash_pool = available_cash + sell_proceeds + cash_sweep_value

    # Sector diversification cap (backtest.py:521-557, _apply_sector_cap)
    # -- filters which NEW-entry candidates are even eligible before any
    # of the three sizing paths below run, counting current sector-group
    # occupancy from `still_held` first (same as backtest counting from
    # its in-memory `positions`). Never touches already-held symbols --
    # no forced exit, only blocks new entries into an already-at-cap
    # group. No-op (returns the input unchanged) whenever sector_
    # diversification_enabled is off or "sector_group" wasn't attached
    # to `ranked` this run (screener.run_screen() only attaches it when
    # sector_bonus_weight/sector_diversification_enabled fetched sector
    # data) -- byte-identical to before this existed in that case.
    # Deferred import: backtest.py already imports screener at module
    # level, so importing backtest here at call-time avoids a circular
    # import.
    import backtest as bt

    new_candidate_order = [sym for sym in candidates.index if sym not in still_held]
    capped_new_candidates = set(bt._apply_sector_cap(new_candidate_order, still_held, ranked, cfg))

    # Entry confirmation (backtest.py:1009-1020) -- requires a stock to
    # have stayed in the confirm-pool (top entry_confirm_pool_size
    # candidates by score) for entry_confirm_days CONSECUTIVE rebalance
    # events before a NEW buy is allowed. Only gates NEW entries --
    # keep_zone/sell_check above are unaffected, same "blocks new entries
    # only" philosophy as the regime filter and sector cap. Streak state
    # is persisted (state_db.entry_confirm_streak) since live has no
    # day-loop to hold it in memory across separate runs -- updated only
    # on an actual rebalance day (same is_rebalance_day gate the sell
    # rule above uses, matching backtest's "updated only inside the
    # monthly-rebalance block"), and only once per calendar day even if
    # called again (state_db.update_entry_confirm_streaks' own
    # idempotency guard) -- a manual "Run today's scan" re-click can't
    # double-increment every streak. entry_confirm_days=0 (default) skips
    # this block entirely: zero new queries, zero new writes,
    # byte-identical to before this existed.
    confirm_days = cfg.get("entry_confirm_days", 0)
    if confirm_days:
        confirm_pool_size = cfg.get("entry_confirm_pool_size") or cfg["max_positions"] * 2
        confirm_syms_now = set(candidates.head(confirm_pool_size).index)
        if is_rebalance_day:
            state_db.update_entry_confirm_streaks(confirm_syms_now, dt.date.today().isoformat())
        streaks = state_db.get_entry_confirm_streaks()
        capped_new_candidates = {
            sym for sym in capped_new_candidates if streaks.get(sym, 0) >= confirm_days
        }

    buys = []
    top_ups = []
    open_positions_now = state_db.get_open_positions()
    if not cfg.get("capital_equal_weight_sizing", True):
        # Risk-based path: screener.position_size() sizes off risk_per_
        # trade_pct of capital between entry and stop, instead of capital/
        # portfolio value -- the exact function backtest.py calls in the
        # same cfg state (backtest.py:873), now available live behind this
        # explicit opt-in. Default True (capital-weighted) reproduces
        # today's behavior exactly; only this branch changes when someone
        # deliberately switches it off. No top-up concept here, matching
        # backtest.py's own try_enter()/position_size() scope -- top-ups
        # are an equal-weight-allocator-only feature.
        remaining_cash = available_cash
        for sym, row in candidates.iterrows():
            if len(still_held) + len(buys) >= effective_max_positions:
                break
            if sym in still_held or sym not in capped_new_candidates:
                continue
            price = float(row["price"])
            stop = float(row["suggested_stop"])
            qty = screener.position_size(total_equity, price, stop, cfg)
            qty = min(qty, int(remaining_cash / price)) if price > 0 else 0
            if qty <= 0:
                continue
            remaining_cash -= qty * price
            fscore = row.get("fundamental_score")
            fscore = None if pd.isna(fscore) else round(float(fscore), 1)
            rank = candidates.index.get_loc(sym) + 1
            reason = (
                f"Ranked #{rank} of {len(candidates)} momentum candidates "
                f"(score {row['score']:.2f}); RSI {row['rsi']:.0f}, "
                f"{row['pct_52w_high'] * 100:.0f}% of 52w high, "
                f"vol expansion {row['vol_expansion']:.2f}x; risk-based sizing"
            )
            if fscore is not None:
                reason += f"; fundamental score {fscore:.0f}/100"
            buys.append(
                {
                    "symbol": sym,
                    "qty": qty,
                    "price": round(price, 2),
                    "stop": round(stop, 2),
                    "score": float(row["score"]),
                    "rank": rank,
                    "rsi": float(row["rsi"]),
                    "pct_52w_high": float(row["pct_52w_high"]),
                    "vol_expansion": float(row["vol_expansion"]),
                    "fundamental_score": fscore,
                    "fundamental_rubric": row.get("fundamental_rubric"),
                    "reason": reason,
                }
            )
    elif cfg.get("advanced_equal_weight_sizing", True):
        # New candidates (not held), rank order, plus held-but-still-
        # gate-passing symbols (eligible for topping up, not for a fresh
        # entry -- allocate_equal_weight_buys() filters that itself).
        new_candidate_syms = [
            sym
            for sym in candidates.index
            if sym not in still_held and sym in capped_new_candidates
        ]
        held_still_candidates = [sym for sym in candidates.index if sym in still_held]
        allocator_syms = new_candidate_syms + held_still_candidates
        prices = {sym: float(candidates.loc[sym, "price"]) for sym in allocator_syms}
        held_info = {
            sym: (int(held.loc[sym, "quantity"]), prices[sym]) for sym in held_still_candidates
        }
        alloc = screener.allocate_equal_weight_buys(
            allocator_syms,
            prices,
            held_info,
            cash_pool=cash_pool,
            total_equity=total_equity,
            max_positions=cfg["max_positions"],
            tolerance_pct=cfg.get("equal_weight_tolerance_pct", 0.20),
        )

        for sym, (qty, size_reason) in alloc["new_buys"].items():
            if len(still_held) + len(buys) >= effective_max_positions:
                break  # regime filter -- allocator sized off the full
                # max_positions above, this is what actually caps
                # how many of its proposed buys get taken today
            row = candidates.loc[sym]
            price = float(row["price"])
            stop = float(row["suggested_stop"])
            fscore = row.get("fundamental_score")
            fscore = None if pd.isna(fscore) else round(float(fscore), 1)
            rank = candidates.index.get_loc(sym) + 1
            reason = (
                f"Ranked #{rank} of {len(candidates)} momentum candidates "
                f"(score {row['score']:.2f}); RSI {row['rsi']:.0f}, "
                f"{row['pct_52w_high'] * 100:.0f}% of 52w high, "
                f"vol expansion {row['vol_expansion']:.2f}x"
            )
            if fscore is not None:
                reason += f"; fundamental score {fscore:.0f}/100"
            if size_reason:
                reason += f" -- {size_reason}"
            buys.append(
                {
                    "symbol": sym,
                    "qty": qty,
                    "price": round(price, 2),
                    "stop": round(stop, 2),
                    "score": float(row["score"]),
                    "rank": rank,
                    "rsi": float(row["rsi"]),
                    "pct_52w_high": float(row["pct_52w_high"]),
                    "vol_expansion": float(row["vol_expansion"]),
                    "fundamental_score": fscore,
                    "fundamental_rubric": row.get("fundamental_rubric"),
                    "reason": reason,
                }
            )
        for sym, extra_qty in alloc["top_ups"].items():
            pos = open_positions_now.get(sym)
            top_ups.append(
                {
                    "symbol": sym,
                    "extra_qty": extra_qty,
                    "price": round(prices[sym], 2),
                    "gtt_trigger_id": pos.get("gtt_trigger_id") if pos else None,
                }
            )
    elif open_slots > 0:
        # Rollback path: original one-symbol-at-a-time greedy fill.
        remaining_cash = available_cash
        for sym, row in candidates.iterrows():
            if len(buys) >= open_slots:
                break
            if sym in still_held or sym not in capped_new_candidates:
                continue
            price = float(row["price"])
            stop = float(row["suggested_stop"])
            slots_remaining = open_slots - len(buys)
            qty = screener.capital_position_size(
                total_equity, remaining_cash, price, slots_remaining, cfg["max_positions"]
            )
            if qty <= 0:
                continue
            remaining_cash -= qty * price
            fscore = row.get("fundamental_score")
            fscore = None if pd.isna(fscore) else round(float(fscore), 1)
            rank = candidates.index.get_loc(sym) + 1
            reason = (
                f"Ranked #{rank} of {len(candidates)} momentum candidates "
                f"(score {row['score']:.2f}); RSI {row['rsi']:.0f}, "
                f"{row['pct_52w_high'] * 100:.0f}% of 52w high, "
                f"vol expansion {row['vol_expansion']:.2f}x"
            )
            if fscore is not None:
                reason += f"; fundamental score {fscore:.0f}/100"
            buys.append(
                {
                    "symbol": sym,
                    "qty": qty,
                    "price": round(price, 2),
                    "stop": round(stop, 2),
                    "score": float(row["score"]),
                    "rank": rank,
                    "rsi": float(row["rsi"]),
                    "pct_52w_high": float(row["pct_52w_high"]),
                    "vol_expansion": float(row["vol_expansion"]),
                    "fundamental_score": fscore,
                    "fundamental_rubric": row.get("fundamental_rubric"),
                    "reason": reason,
                }
            )
    buys_df = pd.DataFrame(buys)
    top_ups_df = pd.DataFrame(top_ups)

    # How much MORE cash would be needed to fully equal-weight every open
    # slot and every under-target held position at once -- shown on the
    # UI so you know exactly how much to add, rather than silently getting
    # partial fills or a stopped proposal with no explanation.
    cash_needed = open_slots * target_per_slot
    for sym in still_held:
        if sym in candidates.index:
            current_value = float(held.loc[sym, "quantity"]) * float(candidates.loc[sym, "price"])
            if current_value < target_per_slot:
                cash_needed += target_per_slot - current_value
    cash_shortfall = max(0.0, cash_needed - cash_pool)

    # ---- Trailing-stop updates: recommend, never modify a live GTT here.
    # Uses currently ACTUALLY held symbols, not "still_held" (which already
    # subtracts today's proposed-but-not-yet-executed sells) -- a position
    # you haven't gotten around to selling yet still needs its stop tracked.
    report("Checking trailing-stop levels...", 0.97)
    stop_updates = compute_stop_updates(set(held.index), cfg)
    stop_updates_df = pd.DataFrame(stop_updates)

    report("Done", 1.0)
    result = {
        "run_time": dt.datetime.now(),
        "sells": sells_df,
        "buys": buys_df,
        "top_ups": top_ups_df,
        "stop_updates": stop_updates_df,
        "holdings": held.reset_index().rename(columns={"tradingsymbol": "symbol"}),
        "is_rebalance_day": is_rebalance_day,
        "rebalance_cadence": cfg.get("rebalance_cadence", "daily"),
        "open_slots": open_slots,
        "screen_candidates": len(ranked),
        "screen_gate_passers": int(ranked["all_gates"].sum()),
        "target_per_slot": round(target_per_slot, 2),
        "cash_pool": round(cash_pool, 2),
        "cash_needed_for_full_equal_weight": round(cash_needed, 2),
        "cash_shortfall": round(cash_shortfall, 2),
        "unsettled_proceeds": round(unsettled_proceeds, 2),
    }
    result["run_id"] = state_db.save_rebalance_run(result)
    return result


# ---------------------------------------------------------------------------
# Execution -- shared between the dashboard's manual "Execute all ..."
# buttons and main()'s auto-execute path (config.STRATEGY
# ["auto_execute_trades"]), so the two can never quietly drift apart.
# Each returns a list of human-readable log lines.
# ---------------------------------------------------------------------------


def execute_sells(sells_df: pd.DataFrame) -> tuple[list[str], list[str], dict[str, str]]:
    """Market-sells every row (the rebalance rule's exits), closes the
    tradebook entry with the reason already computed (previously
    discarded the moment the order fired), and deletes any stale GTT left
    pointing at the now-closed position -- same cleanup
    check_gap_down_stops() already does for its own auto-sells. Returns
    (log_lines, succeeded_symbols, failed_symbols_with_error_message)."""
    log, succeeded, failed = [], [], {}
    for _, r in sells_df.iterrows():
        try:
            oid = kite_client.square_off_position(r["symbol"])
            log.append(f"✅ {r['symbol']}: order {oid}")
            try:
                ltp = kite_client.get_ltp([r["symbol"]])[r["symbol"]]
            except Exception:
                ltp = None
            state_db.close_trade(r["symbol"], ltp, r["reason"])
            pos = state_db.get_open_positions().get(r["symbol"])
            state_db.close_position(r["symbol"], ltp)
            gtt_id = pos.get("gtt_trigger_id") if pos else None
            if gtt_id:
                try:
                    kite_client.delete_gtt(int(gtt_id))
                    log.append(f"   GTT {gtt_id} deleted")
                except Exception as e:
                    log.append(f"   ⚠️ GTT delete failed: {e} — remove it manually")
            succeeded.append(r["symbol"])
        except Exception as e:
            log.append(f"❌ {r['symbol']}: FAILED — {e}")
            failed[r["symbol"]] = str(e)
    return log, succeeded, failed


def execute_buys(
    buys_df: pd.DataFrame, place_gtt: bool = True
) -> tuple[list[str], list[str], dict[str, str]]:
    """Market-buys every row (new candidates filling open slots), places a
    GTT stop-loss at the sizing-time stop unless place_gtt=False, and
    seeds this app's own trailing-stop bookkeeping + tradebook entry
    (entry-time technical/fundamental snapshot, already on the row).
    Returns (log_lines, succeeded_symbols, failed_symbols_with_error_message)."""
    log, succeeded, failed = [], [], {}
    for _, r in buys_df.iterrows():
        try:
            oid = kite_client.place_order(r["symbol"], int(r["qty"]), "BUY")
        except Exception as e:
            log.append(f"❌ {r['symbol']}: BUY FAILED — {e}")
            failed[r["symbol"]] = str(e)
            continue
        succeeded.append(r["symbol"])
        msg = f"✅ {r['symbol']}: order {oid}"
        gtt_id = None
        if place_gtt:
            try:
                gtt_id = kite_client.place_gtt_stoploss(
                    r["symbol"], int(r["qty"]), r["stop"], r["price"]
                )
                msg += f", GTT {gtt_id} @ ₹{r['stop']:.1f}"
            except Exception as e:
                msg += f" — ⚠️ BUY SUCCEEDED but GTT FAILED: {e} (no stop-loss in place)"
        position_id = state_db.record_new_position(
            r["symbol"], float(r["price"]), int(r["qty"]), float(r["stop"]), gtt_id
        )
        state_db.record_trade_entry(
            r["symbol"],
            float(r["price"]),
            int(r["qty"]),
            float(r["stop"]),
            snapshot={
                "score": r.get("score"),
                "rsi": r.get("rsi"),
                "pct_52w_high": r.get("pct_52w_high"),
                "vol_expansion": r.get("vol_expansion"),
                "fundamental_score": r.get("fundamental_score"),
                "entry_reason": r.get("reason"),
            },
            position_id=position_id,
        )
        log.append(msg)
    return log, succeeded, failed


def execute_top_ups(top_ups_df: pd.DataFrame) -> tuple[list[str], list[str], dict[str, str]]:
    """Buys the extra shares for each under-target existing holding, and
    updates its GTT to cover the new total quantity at the same stop
    price (the stop itself never changes here -- only quantity). Returns
    (log_lines, succeeded_symbols, failed_symbols_with_error_message)."""
    log, succeeded, failed = [], [], {}
    for _, r in top_ups_df.iterrows():
        try:
            oid = kite_client.place_order(r["symbol"], int(r["extra_qty"]), "BUY")
        except Exception as e:
            log.append(f"❌ {r['symbol']}: BUY FAILED — {e}")
            failed[r["symbol"]] = str(e)
            continue
        succeeded.append(r["symbol"])
        msg = f"✅ {r['symbol']}: order {oid} (+{int(r['extra_qty'])})"
        gtt_id = r.get("gtt_trigger_id")
        if pd.notna(gtt_id):
            try:
                pos = state_db.get_open_positions().get(r["symbol"])
                new_total_qty = (pos["qty"] + int(r["extra_qty"])) if pos else int(r["extra_qty"])
                ltp = kite_client.get_ltp([r["symbol"]])[r["symbol"]]
                kite_client.modify_gtt_trigger(
                    int(gtt_id),
                    r["symbol"],
                    new_total_qty,
                    pos["current_stop"] if pos else float(r["price"]),
                    ltp,
                )
                msg += f", GTT updated to qty {new_total_qty}"
            except Exception as e:
                msg += (
                    f" — ⚠️ BUY SUCCEEDED but GTT quantity update FAILED: "
                    f"{e} (existing GTT still only covers the old quantity)"
                )
        else:
            msg += " — ⚠️ no existing GTT to update (position may be unprotected)"
        state_db.top_up_trade(r["symbol"], int(r["extra_qty"]), float(r["price"]))
        log.append(msg)
    return log, succeeded, failed


def check_gap_down_stops() -> list[dict]:
    """Morning safety net -- meant to run once, shortly after market open.

    kite_client.place_gtt_stoploss's triggered order is a LIMIT sell at
    trigger_price*0.995, not a market order. That's fine for an ordinary
    intraday stop hit, but if a stock gaps down hard overnight -- opening
    already well below the stop -- the GTT still "triggers" (LTP crossed the
    threshold) but the resulting limit order can sit unfilled if the market
    price has already gapped past it, leaving the position open with no
    actual exit. This checks every open position's LTP against its tracked
    stop and, for anything already through it, places an immediate MARKET
    sell (via kite_client.square_off_position, the same call the dashboard's
    manual Square-off button uses) to guarantee an exit, then deletes the
    now-stale GTT so it can't also sit there confusingly pointed at a
    position that no longer exists.

    A real race exists here: the GTT's OWN trigger can fire on the exact
    same gap moments before this scheduled check runs (both react to the
    same market-open LTP crossing the stop). When that happens the
    position is already flat by the time this runs -- square_off_position()
    correctly returns None in that case (see its own docstring for the
    2026-09-09 incident this guards against: an earlier version of that
    function misread the resulting negative same-day CNC quantity as a
    short needing a buy-cover, and bought the just-sold position straight
    back). That's reflected here as already_closed=True, not folded into
    the same shape as a real sell, so the caller's log line can say so
    plainly instead of claiming "market SELL order None".

    This is the one place in this module that places a real order
    automatically, without a human confirmation step -- deliberately, since
    the whole point is to react before a human could realistically check
    and confirm; propose_rebalance()/main() stay proposal-only everywhere
    else.

    Returns one {"symbol", "qty", "stop", "ltp", "order_id", "gtt_deleted",
    "already_closed", "error"} dict per position that was gapped below its
    stop (empty list if nothing needed exiting)."""
    positions = state_db.get_open_positions()
    if not positions:
        return []

    try:
        ltps = kite_client.get_ltp(list(positions.keys()))
    except Exception as e:
        return [{"symbol": None, "error": f"Could not fetch LTPs: {e}"}]

    gtts = kite_client.get_active_gtts()
    gtt_by_symbol = {}
    if not gtts.empty and "condition" in gtts.columns:
        for _, row in gtts.iterrows():
            cond = row["condition"]
            sym = cond.get("tradingsymbol") if isinstance(cond, dict) else None
            if sym:
                gtt_by_symbol[sym] = row["id"]

    actions = []
    still_held = set(positions.keys())
    for sym, pos in positions.items():
        ltp = ltps.get(sym)
        if ltp is None or ltp > pos["current_stop"]:
            continue  # not gapped below stop -- nothing to do

        action = {
            "symbol": sym,
            "qty": pos["qty"],
            "stop": pos["current_stop"],
            "ltp": ltp,
            "order_id": None,
            "gtt_deleted": False,
            "already_closed": False,
            "error": None,
        }
        try:
            order_id = kite_client.square_off_position(sym)
        except Exception as e:
            action["error"] = f"Market sell FAILED: {e}"
            actions.append(action)
            continue
        if order_id is None:
            # Already flat -- the GTT's own trigger almost certainly fired
            # on this same gap moments before this scheduled check ran.
            # Nothing to sell; just reconcile our own bookkeeping to match
            # reality instead of leaving a stale "open" row.
            action["already_closed"] = True
        else:
            action["order_id"] = order_id
        still_held.discard(sym)
        state_db.close_trade(sym, ltp, "gap_down_stop")

        gtt_id = gtt_by_symbol.get(sym)
        if gtt_id:
            try:
                kite_client.delete_gtt(gtt_id)
                action["gtt_deleted"] = True
            except Exception as e:
                action["error"] = f"Sold OK but GTT delete failed: {e}"

        actions.append(action)

    if actions:
        exit_prices = {a["symbol"]: a["ltp"] for a in actions if a.get("order_id")}
        state_db.reconciled_positions(still_held, exit_prices)

    return actions


def main_gap_check():
    """Headless entry point for check_gap_down_stops() -- e.g. from
    trading_service.py's scheduler, shortly after market open. Logs to the
    same LOG_PATH as main()'s rebalance scan, since both are automated runs
    with no console to watch. Also wrapped in state_db.job_run() -- see its
    docstring -- so the Job Log page has a persisted, filterable record on
    top of the plain-text tail log.

    No-ops on an NSE trading holiday (nse_holidays.py) -- the systemd timer
    itself has no notion of holidays and fires on every Mon-Fri regardless,
    but there's nothing to check on a day the market never opened. Doesn't
    create a job_run row for a skipped day, same reasoning as main() below:
    the Job Log's "last run" should reflect the last day this genuinely
    tried to do something, not a misleading no-op entry."""
    if not nse_holidays.is_trading_day(dt.date.today()):
        print(
            f"{dt.datetime.now():%d %b %Y %H:%M:%S} Skipping gap-check -- NSE holiday or weekend."
        )
        return
    os.makedirs("cache", exist_ok=True)
    log_lines = [
        f"\n{'=' * 60}\n{dt.datetime.now():%d %b %Y %H:%M:%S} (gap-down check)\n{'=' * 60}"
    ]

    def log(msg=""):
        print(msg)
        log_lines.append(msg)

    with state_db.job_run("gap_check", "scheduled") as jr:
        try:
            actions = check_gap_down_stops()
        except Exception as e:
            log(f"FAILED -- {e}")
            with open(LOG_PATH, "a") as f:
                f.write("\n".join(log_lines) + "\n")
            raise

        if not actions:
            log("No positions gapped below their stop.")
        for a in actions:
            if a.get("error") and a.get("order_id") is None and not a.get("already_closed"):
                log(f"⚠️ {a['symbol']}: {a['error']}")
            elif a.get("already_closed"):
                log(
                    f"🔴 {a['symbol']}: gapped to ₹{a['ltp']:.2f} (stop ₹{a['stop']:.2f}) -- "
                    f"already closed (GTT fired first, nothing left to sell), "
                    f"GTT deleted: {a['gtt_deleted']}"
                    + (f" -- {a['error']}" if a.get("error") else "")
                )
            else:
                log(
                    f"🔴 {a['symbol']}: gapped to ₹{a['ltp']:.2f} (stop ₹{a['stop']:.2f}) -- "
                    f"market SELL order {a['order_id']}, GTT deleted: {a['gtt_deleted']}"
                    + (f" -- {a['error']}" if a.get("error") else "")
                )
        # A gap-down sell frees cash immediately -- sweep any idle leftover
        # into the cash-sweep instrument the same run. No-ops when
        # cash_sweep_enabled is off or nothing actually sold.
        if actions:
            sweep_result = sweep_idle_cash()
            if sweep_result:
                log(f"💰 Cash sweep: {sweep_result}")
        with open(LOG_PATH, "a") as f:
            f.write("\n".join(log_lines) + "\n")
        jr["summary"] = (
            f"{len(actions)} gap action(s)" if actions else "no positions gapped below stop"
        )


def correct_todays_exit_prices() -> list[str]:
    """End-of-day correction pass, meant to run once shortly after market
    close (~15:31 IST): replaces today's closed trades' exit_price -- an
    LTP-at-detection-time APPROXIMATION every close_trade() call site uses,
    since Kite's order-placement response never includes the real fill
    price -- with the REAL average fill price from Kite's own order book
    (kite_client.get_orders()), the only source of truth for what actually
    executed. Applies uniformly to every trade that closed today,
    regardless of which path closed it (rebalance sell, gap-down stop, or
    a GTT/external fill caught by reconciled_positions()) -- no need to
    distinguish which; Kite's real trade book is strictly more accurate
    than any LTP guess either way.

    Same-day only: kite.orders() only ever returns TODAY's order book, so
    a day this doesn't run, the accurate price is gone for good -- this
    must be scheduled to run every trading day, not something to catch up
    later.

    If a symbol has more than one COMPLETE sell fill today (rare -- e.g. a
    same-day round trip), aggregates a quantity-weighted average across all
    of them and applies that single blended price to every trades row that
    closed for that symbol today -- an approximation for that edge case,
    not a per-order match.

    Returns a log line per symbol actually corrected."""
    today = dt.date.today().isoformat()
    try:
        orders = kite_client.get_orders()
    except Exception as e:
        return [f"Exit-price correction skipped -- Kite orders fetch failed: {e}"]
    if orders.empty:
        return []

    sells = orders[(orders["transaction_type"] == "SELL") & (orders["status"] == "COMPLETE")].copy()
    if sells.empty:
        return []
    qty_col = "filled_quantity" if "filled_quantity" in sells.columns else "quantity"
    sells["_qty"] = sells[qty_col].astype(float)
    sells = sells[sells["_qty"] > 0]
    if sells.empty:
        return []

    log = []
    for sym, grp in sells.groupby("tradingsymbol"):
        total_qty = grp["_qty"].sum()
        avg_price = float((grp["average_price"] * grp["_qty"]).sum() / total_qty)
        n = state_db.correct_trade_exit_price(sym, today, avg_price)
        if n:
            log.append(
                f"{sym}: exit_price corrected to Rs.{avg_price:.2f} "
                f"from Kite's real order book ({n} row(s))"
            )
    return log


def main_exit_price_correction():
    """Headless entry point for correct_todays_exit_prices() -- run once
    shortly after market close (~15:31 IST). Logs to the same LOG_PATH as
    every other automated run, and wrapped in state_db.job_run() so the
    Job Log page has a persisted record. No-ops on an NSE trading holiday,
    same reasoning as main()/main_gap_check()."""
    if not nse_holidays.is_trading_day(dt.date.today()):
        print(
            f"{dt.datetime.now():%d %b %Y %H:%M:%S} Skipping exit-price "
            f"correction -- NSE holiday or weekend."
        )
        return
    os.makedirs("cache", exist_ok=True)
    log_lines = [
        f"\n{'=' * 60}\n{dt.datetime.now():%d %b %Y %H:%M:%S} (exit-price correction)\n{'=' * 60}"
    ]

    def log(msg=""):
        print(msg)
        log_lines.append(msg)

    with state_db.job_run("exit_price_correction", "scheduled") as jr:
        try:
            corrected = correct_todays_exit_prices()
        except Exception as e:
            log(f"FAILED -- {e}")
            with open(LOG_PATH, "a") as f:
                f.write("\n".join(log_lines) + "\n")
            raise

        if not corrected:
            log("No sell fills today to reconcile (or nothing needed correcting).")
        for line in corrected:
            log(line)

        # Daily equity snapshot -- guarantees one gets logged every trading
        # day regardless of whether the Overview page is ever visited (the
        # ONLY other place this gets written), run once here at a
        # controlled, post-market-close time rather than depending on
        # whichever page load happens to be last. A same-day Overview
        # visit later still overwrites this with its own fresher read --
        # both compute the same way (compute_portfolio_value() vs.
        # page_cockpit()'s equivalent), so they should agree within a
        # few rupees of live price movement between the two reads.
        snapshot = compute_portfolio_value()
        if snapshot["portfolio_value"] > 0:
            state_db.log_equity_snapshot(
                snapshot["portfolio_value"], snapshot["invested_amount"], snapshot["holdings_value"]
            )
            log(f"\nEquity snapshot logged: Rs.{snapshot['portfolio_value']:,.2f}")
        else:
            log(
                "\nEquity snapshot skipped -- couldn't compute a valid portfolio value "
                "(Kite connection issue)."
            )

        # Job Log retention -- keep only the last 30 days so job_runs
        # doesn't grow unbounded. Run once here, daily, alongside the
        # other end-of-day maintenance in this job.
        pruned = state_db.prune_job_runs(days=30)
        if pruned:
            log(f"Job Log: pruned {pruned} run(s) older than 30 days.")

        with open(LOG_PATH, "a") as f:
            f.write("\n".join(log_lines) + "\n")
        jr["summary"] = (
            f"{len(corrected)} symbol(s) corrected" if corrected else "nothing to correct"
        )


def main():
    """Run headless, e.g. from Windows Task Scheduler -- see README's
    "Scheduled scan" section. Every run appends a timestamped block to
    LOG_PATH regardless of outcome (including a Kite-auth failure), since a
    scheduled run has no console to watch -- this is the only record of
    whether today's run happened and what it found. Also wrapped in
    state_db.job_run() -- see its docstring -- so the Job Log page has a
    persisted, filterable record on top of the plain-text tail log; a
    Kite-auth failure now also propagates (after logging) instead of
    silently returning, so the systemd unit itself shows failed too.

    No-ops on an NSE trading holiday (nse_holidays.py) -- see
    main_gap_check()'s docstring for why this doesn't create a job_run
    row for a skipped day."""
    if not nse_holidays.is_trading_day(dt.date.today()):
        print(
            f"{dt.datetime.now():%d %b %Y %H:%M:%S} Skipping rebalance scan -- "
            f"NSE holiday or weekend."
        )
        return

    # Recurring charges (e.g. quarterly Demat AMC) -- checked once per
    # scheduled run, independent of the Kite connection below, so a
    # due charge still gets logged even on a day the rebalance scan itself
    # fails. Never raises: a bookkeeping miss shouldn't block the real
    # scan.
    try:
        for line in state_db.post_due_recurring_charges():
            print(f"{dt.datetime.now():%d %b %Y %H:%M:%S} {line}")
    except Exception as e:
        print(f"{dt.datetime.now():%d %b %Y %H:%M:%S} Recurring-charge check failed: {e}")

    os.makedirs("cache", exist_ok=True)
    log_lines = [f"\n{'=' * 60}\n{dt.datetime.now():%d %b %Y %H:%M:%S}\n{'=' * 60}"]

    def log(msg=""):
        print(msg)
        log_lines.append(msg)

    with state_db.job_run("rebalance_scan", "scheduled") as jr:
        try:
            margins = kite_client.get_margins()
            available_cash = margins["equity"]["available"]["live_balance"]
        except Exception as e:
            log(f"FAILED -- Kite connection failed (token may have expired): {e}")
            log(
                "Refresh the token (python kite_client.py login / token <request_token>) "
                "before the next scheduled run, or run manually from the dashboard."
            )
            state_db.save_rebalance_failure(str(e))
            with open(LOG_PATH, "a") as f:
                f.write("\n".join(log_lines) + "\n")
            raise

        # Corporate-action detection (stock split / bonus issue) -- purely
        # read-only, just flags a mismatch for manual review on the
        # Positions & Trade page; never touches the positions/trades
        # tables or the real GTT itself (see
        # apply_corporate_action_adjustment()). Never raises: a detection
        # miss shouldn't block the real scan.
        try:
            for flag in detect_corporate_actions():
                log(
                    f"⚠️ Possible split/bonus detected: {flag['symbol']} "
                    f"{flag['our_qty']} → {flag['live_qty']} units "
                    f"(×{flag['ratio']:.4f}) -- review on Positions & Trade"
                )
        except Exception as e:
            log(f"Corporate-action check failed: {e}")

        def cb(stage, frac):
            pass  # progress bar text is meaningless in a headless/logged run

        result = propose_rebalance(available_cash, progress_cb=cb)

        log(f"Rebalance proposal ({result['run_time']:%d %b %Y %H:%M})")
        log(f"Open slots: {result['open_slots']}")
        log("\n-- Proposed SELLS --")
        log(result["sells"].to_string(index=False) if not result["sells"].empty else "(none)")
        log("\n-- Proposed BUYS --")
        log(result["buys"].to_string(index=False) if not result["buys"].empty else "(none)")
        log("\n-- Proposed TOP-UPS --")
        log(result["top_ups"].to_string(index=False) if not result["top_ups"].empty else "(none)")
        log("\n-- Trailing-stop updates needing attention (auto-apply failed or no GTT) --")
        log(
            result["stop_updates"].to_string(index=False)
            if not result["stop_updates"].empty
            else "(none -- everything that ratcheted today applied cleanly)"
        )
        log(
            f"\nEqual-weight target: Rs.{result['target_per_slot']:,.0f}/slot, "
            f"Rs.{result['cash_pool']:,.0f} available (cash + proposed sell proceeds)"
        )
        if result["unsettled_proceeds"] > 0:
            log(
                f"Rs.{result['unsettled_proceeds']:,.0f} of today's sell proceeds is "
                "from a same-day position or T1 (BTST) holding -- not usable until "
                "settlement completes (excluded from the available figure above)."
            )
        if result["cash_shortfall"] > 0:
            log(
                f"SHORTFALL: Rs.{result['cash_shortfall']:,.0f} more needed to fully "
                "equal-weight every open slot and under-target holding"
            )
        else:
            log("Sufficient cash to fully equal-weight every open slot and under-target holding.")
        log(f"\nSaved to {state_db.DB_PATH}")
        if config.STRATEGY.get("auto_execute_trades", False):
            log("\n-- Auto-executing trades (auto_execute_trades=True) --")
            run_id = result.get("run_id")
            open_slots = result["open_slots"]
            if not result["sells"].empty:
                sell_log, sold, sell_failed = execute_sells(result["sells"])
                log("\n".join(sell_log))
                state_db.mark_rebalance_sells_executed(run_id, sold)
                state_db.mark_rebalance_sells_failed(run_id, sell_failed)
                open_slots += len(sold)
            # Idle-cash sweep: redeem just enough of the cash-sweep
            # instrument BEFORE placing real buy/top-up orders, if today's
            # total buy cost needs more than what's free as real cash --
            # see ensure_cash_for_buys()'s own docstring. No-ops entirely
            # when cash_sweep_enabled is off.
            buy_cost = (
                float((result["buys"]["qty"] * result["buys"]["price"]).sum())
                if not result["buys"].empty
                else 0.0
            )
            topup_cost = (
                float((result["top_ups"]["extra_qty"] * result["top_ups"]["price"]).sum())
                if not result["top_ups"].empty
                else 0.0
            )
            sweep_action = ensure_cash_for_buys(buy_cost + topup_cost)
            if sweep_action:
                log(f"\n💰 Cash sweep: {sweep_action}")
            if not result["buys"].empty:
                buy_log, bought, buy_failed = execute_buys(result["buys"])
                log("\n".join(buy_log))
                state_db.mark_rebalance_buys_executed(run_id, bought)
                state_db.mark_rebalance_buys_failed(run_id, buy_failed)
                open_slots = max(open_slots - len(bought), 0)
            if not result["top_ups"].empty:
                topup_log, topped_up, topup_failed = execute_top_ups(result["top_ups"])
                log("\n".join(topup_log))
                state_db.mark_rebalance_top_ups_executed(run_id, topped_up)
                state_db.mark_rebalance_top_ups_failed(run_id, topup_failed)
            state_db.set_rebalance_open_slots(run_id, open_slots)
            # Sweep whatever's left over back into the cash-sweep
            # instrument once everything above has settled -- no-ops when
            # cash_sweep_enabled is off.
            sweep_result = sweep_idle_cash()
            if sweep_result:
                log(f"💰 Cash sweep: {sweep_result}")
            log("\nTrades executed automatically -- see the log above for each order.")
        else:
            log(
                "Nothing was placed or modified -- review and execute/apply manually "
                "in the dashboard's Live Rebalance page or the Trade tab."
            )
        with open(LOG_PATH, "a") as f:
            f.write("\n".join(log_lines) + "\n")
        jr["summary"] = (
            f"{len(result['buys'])} buys, {len(result['sells'])} sells, "
            f"{len(result['stop_updates'])} stop updates"
        )

    # propose_rebalance() already ran the full screener pipeline and cached
    # it to screener.SCREEN_CACHE above -- log this as its own screen_run
    # entry too (not folded into the rebalance_scan entry above) so the Job
    # Log's "last run" for screen_run also reflects this time, even though
    # no separate screener pass actually happened.
    sr_id = state_db.start_job_run("screen_run", "scheduled")
    state_db.finish_job_run(
        sr_id,
        "success",
        summary=(
            f"{result['screen_candidates']} candidates "
            f"({result['screen_gate_passers']} passing all gates) -- "
            "refreshed alongside the rebalance scan"
        ),
    )


if __name__ == "__main__":
    import sys

    if "--gap-check" in sys.argv:
        main_gap_check()
    elif "--correct-exit-prices" in sys.argv:
        main_exit_price_correction()
    else:
        main()
