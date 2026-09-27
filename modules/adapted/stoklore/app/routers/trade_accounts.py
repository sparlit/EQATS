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


from fastapi import APIRouter, HTTPException

from app.core import db, trade_context
from app.schemas import TradeAccountRequest

router = APIRouter(tags=["trade-accounts"])

ACCOUNT_KINDS = {"journal", "paper"}


def _validate_spike(req):
    """A multiple below 1 flags every bar as a spike, and a zero/negative lookback scans nothing -
    both make the stored reading meaningless rather than merely odd, so they're rejected here.

    The upper bound is real, not cosmetic: only 100 bars are ever fetched per trade and the scan
    needs 20 of them behind its window for the baseline, so a larger lookback would quietly scan
    fewer bars than it was told to. Rejecting it here is the only place that can say so."""
    if req.vol_spike_multiple < 1:
        raise HTTPException(status_code=422, detail="volume spike multiple must be at least 1")
    if not 1 <= req.vol_spike_lookback <= trade_context.MAX_SPIKE_LOOKBACK:
        raise HTTPException(
            status_code=422,
            detail=f"volume spike lookback must be 1-{trade_context.MAX_SPIKE_LOOKBACK} bars",
        )
    # None is "off"; 0 would mean "remind me after no losses at all", which is a dialog that never
    # closes rather than a setting.
    if req.loss_streak_alert is not None and req.loss_streak_alert < 1:
        raise HTTPException(status_code=422, detail="loss streak reminder must be at least 1 trade")


@router.get("/api/trade-accounts")
def trade_accounts(kind: str = "journal"):
    """`kind` defaults to journal so existing callers are unaffected. The two kinds never mix in
    one list - a paper account showing up in the journal's account picker would let a hand-logged
    trade be filed against a simulated wallet."""
    if kind not in ACCOUNT_KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {sorted(ACCOUNT_KINDS)}")
    return db.list_trade_accounts(kind=kind)


@router.post("/api/trade-accounts")
def create_trade_account(req: TradeAccountRequest, kind: str = "journal"):
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="account name is required")
    _validate_spike(req)
    if kind not in ACCOUNT_KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {sorted(ACCOUNT_KINDS)}")
    account_id = db.create_trade_account(
        req.name.strip(),
        req.strategy,
        req.strategy_explanation,
        req.opening_balance,
        req.max_position_size,
        req.max_position_size_type,
        req.max_position_count,
        kind=kind,
        settings=req.settings(),
    )
    return {"id": account_id}


@router.put("/api/trade-accounts/{account_id}")
def update_trade_account(account_id: int, req: TradeAccountRequest):
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="account name is required")
    _validate_spike(req)
    db.update_trade_account(
        account_id,
        req.name.strip(),
        req.strategy,
        req.strategy_explanation,
        req.opening_balance,
        req.max_position_size,
        req.max_position_size_type,
        req.max_position_count,
        settings=req.settings(),
    )
    return {"ok": True}


@router.delete("/api/trade-accounts/{account_id}")
def delete_trade_account(account_id: int):
    # Closed trades survive an account deletion (manual_trades.account_id is ON DELETE SET NULL,
    # so journal history is never destroyed) - but paper_positions is ON DELETE CASCADE, because a
    # simulated open position means nothing without the wallet it belongs to. That asymmetry would
    # make this endpoint silently discard live positions, so it refuses instead and says how many.
    open_positions = db.list_paper_positions(account_id)
    if open_positions:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(open_positions)} open paper position(s) on this account - close them first. "
                "Deleting the account would discard them."
            ),
        )
    db.delete_trade_account(account_id)
    return {"ok": True}
