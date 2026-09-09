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
analysis/volatility_surface.py
──────────────────────────────
IV Smile and Term Structure analysis.

IV Smile: IV across strikes for a given expiry (the skew).
Term Structure: ATM IV across expiries (contango/backwardation).

Usage:
    iv-smile NIFTY
    iv-term NIFTY
"""


from typing import Optional

import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()


# ── Skew & Term Structure Classification ─────────────────────


def classify_skew(otm_put_iv: float, atm_iv: float, otm_call_iv: float) -> str:
    """Classify the IV smile shape."""
    put_skew = otm_put_iv - atm_iv
    call_skew = otm_call_iv - atm_iv

    if put_skew > 3.0 and put_skew > call_skew + 2.0:
        return "PUT_SKEW"  # Crash protection premium — market fears downside
    if call_skew > 3.0 and call_skew > put_skew + 2.0:
        return "CALL_SKEW"  # Rally expectation — market fears missing upside
    return "SYMMETRIC"  # Normal smile — balanced expectations


def classify_term_structure(near_iv: float, far_iv: float) -> str:
    """Classify IV term structure."""
    diff = far_iv - near_iv
    if diff > 1.5:
        return "CONTANGO"  # Normal — far expiry IV higher
    if diff < -1.5:
        return "BACKWARDATION"  # Event risk — near expiry IV higher (unusual)
    return "FLAT"


# ── IV Smile Computation ────────────────────────────────────


def compute_iv_smile(underlying: str, expiry: str | None = None) -> pd.DataFrame | None:
    """
    Compute IV across strikes for a given expiry.

    Returns DataFrame with columns: strike, ce_iv, pe_iv, moneyness.
    Returns None if data unavailable.
    """
    try:
        from market.options import get_options_chain
        from market.quotes import get_ltp

        chain = get_options_chain(underlying, expiry)
        if not chain:
            return None

        spot = get_ltp(f"NSE:{underlying}")
        if spot <= 0:
            return None

        # Build strike → IV mapping
        strikes = {}
        for c in chain:
            s = c.strike
            if s not in strikes:
                strikes[s] = {"strike": s, "ce_iv": None, "pe_iv": None}

            iv_val = c.iv
            # If IV not in chain, try computing from premium
            if (iv_val is None or iv_val <= 0) and c.last_price > 0:
                try:
                    from analysis.options import compute_greeks

                    exp_str = c.expiry or expiry
                    if exp_str:
                        g = compute_greeks(spot, s, exp_str, c.option_type, c.last_price)
                        iv_val = g.iv_pct if g.iv_pct > 0 else None
                except Exception:
                    pass

            if c.option_type == "CE":
                strikes[s]["ce_iv"] = iv_val
            else:
                strikes[s]["pe_iv"] = iv_val

        if not strikes:
            return None

        df = pd.DataFrame(sorted(strikes.values(), key=lambda x: x["strike"]))
        df["moneyness"] = ((df["strike"] - spot) / spot * 100).round(1)
        return df

    except Exception:
        return None


def compute_iv_term_structure(underlying: str) -> pd.DataFrame | None:
    """
    Compute ATM IV across multiple expiries.

    Returns DataFrame with columns: expiry, dte, atm_strike, ce_iv, pe_iv.
    """
    try:
        from market.options import get_atm_strike, get_expiries, get_options_chain
        from market.quotes import get_ltp

        spot = get_ltp(f"NSE:{underlying}")
        expiries = get_expiries(underlying)
        if not expiries or spot <= 0:
            return None

        rows = []
        for exp in expiries[:5]:  # first 5 expiries
            chain = get_options_chain(underlying, exp)
            if not chain:
                continue

            atm = get_atm_strike(underlying, spot)
            ce_iv = None
            pe_iv = None

            for c in chain:
                if c.strike == atm:
                    iv = c.iv
                    if (iv is None or iv <= 0) and c.last_price > 0:
                        try:
                            from analysis.options import compute_greeks

                            g = compute_greeks(spot, atm, exp, c.option_type, c.last_price)
                            iv = g.iv_pct
                        except Exception:
                            pass
                    if c.option_type == "CE":
                        ce_iv = iv
                    else:
                        pe_iv = iv

            if ce_iv or pe_iv:
                from analysis.options import _dte_days

                rows.append(
                    {
                        "expiry": exp,
                        "dte": _dte_days(exp),
                        "atm_strike": atm,
                        "ce_iv": ce_iv,
                        "pe_iv": pe_iv,
                    }
                )

        return pd.DataFrame(rows) if rows else None
    except Exception:
        return None


def print_iv_smile(underlying: str, expiry: str | None = None) -> None:
    """Display IV smile as Rich table."""
    df = compute_iv_smile(underlying, expiry)
    if df is None or df.empty:
        console.print("[dim]IV smile data unavailable.[/dim]")
        return

    table = Table(title=f"IV Smile — {underlying}")
    table.add_column("Strike", justify="right", style="bold")
    table.add_column("CE IV%", justify="right")
    table.add_column("PE IV%", justify="right")
    table.add_column("Moneyness", justify="right", style="dim")

    for _, row in df.iterrows():
        table.add_row(
            f"{row['strike']:,.0f}",
            f"{row['ce_iv']:.1f}%" if pd.notna(row.get("ce_iv")) and row["ce_iv"] else "—",
            f"{row['pe_iv']:.1f}%" if pd.notna(row.get("pe_iv")) and row["pe_iv"] else "—",
            f"{row['moneyness']:+.1f}%",
        )

    console.print(table)

    # Classify skew
    valid = df.dropna(subset=["ce_iv", "pe_iv"])
    if len(valid) >= 3:
        atm_idx = valid["moneyness"].abs().idxmin()
        atm_iv = valid.loc[atm_idx, "pe_iv"] or valid.loc[atm_idx, "ce_iv"] or 0
        otm_put = valid[valid["moneyness"] < -3]["pe_iv"].mean() if len(valid[valid["moneyness"] < -3]) else atm_iv
        otm_call = valid[valid["moneyness"] > 3]["ce_iv"].mean() if len(valid[valid["moneyness"] > 3]) else atm_iv
        skew = classify_skew(otm_put, atm_iv, otm_call)
        console.print(f"  Skew: [bold]{skew}[/bold]")
