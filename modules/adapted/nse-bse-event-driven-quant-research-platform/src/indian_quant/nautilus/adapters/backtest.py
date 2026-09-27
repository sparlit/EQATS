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


"""Backtest runner: catalog -> engine -> strategy -> deterministic report."""


import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from indian_quant.nautilus.adapters.fees import IndiaDeliveryFeeModel
from indian_quant.nautilus.data.catalog import CatalogBridge
from indian_quant.strategies.sma_cross import SmaCross, SmaCrossConfig
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FillModel
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig
from nautilus_trader.model.currencies import INR
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money

if TYPE_CHECKING:
    import pandas as pd
    from indian_quant.config.settings import Settings


@dataclass
class BacktestResult:
    run_id: str
    instrument_id: str
    n_fills: int
    fills: pd.DataFrame
    positions: pd.DataFrame
    account: pd.DataFrame
    config: dict = field(default_factory=dict)


class BacktestRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run_sma_cross(
        self,
        *,
        symbol: str,
        timeframe: str = "1d",
        fast: int = 10,
        slow: int = 30,
        trade_size: int = 100,
    ) -> BacktestResult:
        bridge = CatalogBridge(self.settings.catalog_dir)
        instruments = bridge.read_instruments()
        if not instruments:
            msg = f"catalog at {bridge.catalog_path} has no instruments; run scripts/sync_catalog.py first"
            raise RuntimeError(msg)
        target_symbol = symbol.upper()
        instrument = next((i for i in instruments if str(i.id.symbol).upper() == target_symbol), None)
        if instrument is None:
            msg = f"instrument {symbol} not in catalog"
            raise KeyError(msg)

        venue_str = str(instrument.id.venue)
        nautilus_instrument_id = str(instrument.id)

        bars = bridge.read_bars(nautilus_instrument_id, timeframe)
        if not bars:
            msg = f"no bars for {instrument.id} in catalog"
            raise RuntimeError(msg)

        config = SmaCrossConfig(
            instrument_id=nautilus_instrument_id,
            bar_type=str(bars[0].bar_type),
            fast=fast,
            slow=slow,
            trade_size=trade_size,
        )

        bt = self.settings.backtest
        risk_kwargs: dict = {
            "max_order_submit_rate": bt.risk_max_order_submit_rate,
            "max_order_modify_rate": bt.risk_max_order_modify_rate,
            "bypass": bt.risk_bypass,
        }
        if bt.risk_max_notional_per_order:
            risk_kwargs["max_notional_per_order"] = bt.risk_max_notional_per_order
        engine = BacktestEngine(config=BacktestEngineConfig(risk_engine=RiskEngineConfig(**risk_kwargs)))
        fill_model = FillModel(prob_fill_on_limit=1.0)
        bt = self.settings.backtest
        fee_model = IndiaDeliveryFeeModel(
            brokerage_bps=bt.brokerage_bps,
            stt_sell_bps=bt.stt_sell_bps,
            stamp_buy_bps=bt.stamp_buy_bps,
            flat_fee_per_order=bt.flat_fee_per_order,
        )
        engine.add_venue(
            venue=Venue(venue_str),
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            starting_balances=[Money(round(self.settings.backtest.starting_balance_inr), INR)],
            bar_execution=True,
            fill_model=fill_model,
            fee_model=fee_model,
        )
        engine.add_instrument(instrument)
        engine.add_data(bars)
        engine.add_strategy(SmaCross(config))
        engine.run()

        fills = engine.trader.generate_order_fills_report()
        positions = engine.trader.generate_positions_report()
        account = engine.trader.generate_account_report(Venue(venue_str))

        run_config = {
            "symbol": target_symbol,
            "timeframe": timeframe,
            "fast": fast,
            "slow": slow,
            "trade_size": trade_size,
            "starting_balance": self.settings.backtest.starting_balance_inr,
            "brokerage_bps": bt.brokerage_bps,
            "stt_sell_bps": bt.stt_sell_bps,
            "stamp_buy_bps": bt.stamp_buy_bps,
            "flat_fee_per_order": bt.flat_fee_per_order,
        }
        config_hash = hashlib.sha256(json.dumps(run_config, sort_keys=True).encode()).hexdigest()[:16]
        return BacktestResult(
            run_id=f"sma-{config_hash}-{uuid.uuid4().hex[:8]}",
            instrument_id=nautilus_instrument_id,
            n_fills=len(fills),
            fills=fills,
            positions=positions,
            account=account,
            config=run_config,
        )


def _money_to_float(value: object) -> float:
    text = str(value).split()[0].replace(",", "")
    try:
        return float(text)
    except ValueError:
        return float("nan")


def _commissions_total(column: object) -> float:
    """Sum commission amounts from cells like '[13.45 INR]' or '[1.2 INR, 3.4 INR]'."""
    import re

    total = 0.0
    for cell in column:  # type: ignore[attr-defined]
        matches = re.findall(r"[\d.]+", str(cell))
        for m in matches:
            try:
                total += float(m)
            except ValueError:
                continue
    return total


def summarize_result(result: BacktestResult) -> dict:
    metrics: dict[str, float | int | str] = {
        "run_id": result.run_id,
        "instrument_id": result.instrument_id,
        "n_fills": result.n_fills,
    }
    commissions = 0.0
    if not result.fills.empty and "commissions" in result.fills.columns:
        commissions = _commissions_total(result.fills["commissions"])
        metrics["total_commissions"] = round(commissions, 2)
    if not result.positions.empty and "realized_pnl" in result.positions.columns:
        pnl = result.positions["realized_pnl"].map(_money_to_float).dropna()
        net = float(pnl.sum())
        metrics["net_pnl"] = round(net, 2)
        metrics["gross_pnl"] = round(net + commissions, 2)
        metrics["n_closed_positions"] = len(result.positions)
    if not result.account.empty:
        for col in ("total", "free"):
            if col in result.account.columns:
                vals = result.account[col].map(_money_to_float).dropna()
                if len(vals):
                    metrics[f"final_{col}"] = float(vals.iloc[-1])
                break
    return metrics
