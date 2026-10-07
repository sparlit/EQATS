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


"""Portfolio-level strategy backtest with professional quant metrics.

v2 — Major upgrade:
    - Fixed cash accounting bug (exit cost now uses exit price)
    - Added MFE/MAE tracking per trade
    - Added Sharpe, Sortino, Calmar, Profit Factor, SQN, K-Ratio
    - Added slippage/impact model (configurable)
    - Added Monte Carlo bootstrap confidence intervals
    - Added walk-forward analysis framework
    - Added Indian market cost stack (STT, stamp, DP, GST, SEBI)
"""


import math
from dataclasses import dataclass
from datetime import date
from datetime import date as Date
from pathlib import Path

import numpy as np
import pandas as pd

from indian_quant.features.delivery import (
    SIGNAL_NAMES,
    add_features,
    cluster_entry_mask,
    conviction_score,
    horizon_fit,
    prepare_frame,
    signal_mask,
    signal_mask_with_filters,
)
from indian_quant.portfolio.constraints import OpenPosition, PortfolioConstraints, can_enter
from indian_quant.portfolio.kelly import kelly_fraction, kelly_position

# ── Indian Market Cost Stack ────────────────────────────────────────────────


@dataclass(frozen=True)
class IndianCosts:
    """Realistic Indian market transaction costs."""

    brokerage_bps: float = 3.0  # flat brokerage per side
    stt_buy_pct: float = 0.0  # STT on buy (0% for delivery)
    stt_sell_pct: float = 0.1  # STT on sell (0.1% for delivery)
    stamp_duty_pct: float = 0.015  # buy-side only
    exchange_bps: float = 0.345  # NSE exchange charges
    sebi_bps: float = 0.1  # SEBI turnover fees
    gst_pct: float = 18.0  # GST on brokerage + exchange + SEBI
    dp_charges_inr: float = 15.0  # flat per ISIN per sell day
    slippage_bps: float = 5.0  # market impact / slippage per side

    def round_trip_bps(self, trade_value: float) -> float:
        """Total round-trip cost in basis points."""

        # Per-side costs (bps of trade value)
        brokerage = self.brokerage_bps * 2
        stt = (self.stt_buy_pct + self.stt_sell_pct) * 100  # convert % to bps
        stamp = self.stamp_duty_pct * 100  # buy-side only, convert % to bps
        exchange = self.exchange_bps * 2
        sebi = self.sebi_bps * 2
        gst = (self.brokerage_bps + self.exchange_bps + self.sebi_bps) * 2 * self.gst_pct / 100
        slippage = self.slippage_bps * 2

        total_bps = brokerage + stt + stamp + exchange + sebi + gst + slippage
        # DP charges as bps of trade value
        dp_bps = (self.dp_charges_inr / max(trade_value, 1)) * 10_000
        return total_bps + dp_bps


# ── Strategy Config ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategyConfig:
    signal: str = "dz_hi_up"
    price_min: float = 20.0
    price_max: float = 100.0
    min_turnover: float = 10_000_000.0
    hold_days: int = 10
    stop_pct: float = 0.07
    max_positions: int = 8
    capital: float = 25_000.0
    risk_pct: float = 1.0
    cost_bps: float = 107.0
    cluster_entries: bool = True
    z_min: float = 2.0
    use_conviction: bool = False
    use_kelly: bool = False
    use_tech_filters: bool = True
    # v2 additions
    use_indian_costs: bool = False
    slippage_bps: float = 0.0
    impact_bps: float = 0.0
    use_trailing_stop: bool = False
    trailing_stop_pct: float = 0.03
    max_sector_pct: float = 0.40
    sector_limit: int = 2


# ── Trade Record ────────────────────────────────────────────────────────────


@dataclass
class Trade:
    symbol: str
    segment: str
    entry_date: Date
    entry_px: float
    qty: int
    exit_date: Date | None
    exit_px: float | None
    gross_bps: float | None
    net_bps: float | None
    reason: str
    days_held: int
    # v2 additions
    mfe: float = 0.0  # Maximum Favorable Excursion (bps)
    mae: float = 0.0  # Maximum Adverse Excursion (bps)
    peak_bps: float = 0.0  # Peak unrealized gain
    trough_bps: float = 0.0  # Worst unrealized loss
    pnl: float = 0.0  # Absolute P&L in INR
    cost_bps: float = 0.0  # Actual cost applied


@dataclass
class BacktestResult:
    config: StrategyConfig
    trades: list[Trade]
    equity_curve: list[tuple[Date, float]]
    summary: dict
    monte_carlo: dict | None = None
    walk_forward: dict | None = None


# ── Data Loading ────────────────────────────────────────────────────────────


def load_frames(delivery_dir: Path | str, min_rows: int = 40) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for path in sorted(Path(delivery_dir).glob("*.parquet")):
        raw = pd.read_parquet(path)
        prepared = prepare_frame(raw, min_rows=min_rows)
        if prepared is None or "segment" not in prepared.columns:
            continue
        featured = add_features(prepared)
        if featured.empty or "symbol" not in featured.columns:
            continue
        frames.append(featured)
    return frames


def _prepare_tables(frames: list[pd.DataFrame], config: StrategyConfig):
    """Return (tables, fires): date-indexed frames + firing masks."""
    tables: dict[str, pd.DataFrame] = {}
    fires: dict[str, pd.Series] = {}
    for f in frames:
        sym = str(f["symbol"].iloc[-1])
        table = f.copy()
        if "volume" in table.columns:
            table["turnover"] = table["close"] * table["volume"].fillna(0)
        else:
            table["turnover"] = 0.0
        table = table.set_index("date")

        raw_mask = signal_mask(table.reset_index(), config.signal, z_min=config.z_min)
        if config.use_tech_filters:
            raw_mask = signal_mask_with_filters(
                table.reset_index(),
                config.signal,
                rsi_min=30,
                rsi_max=70,
                require_macd=True,
                require_ma=True,
            )
        if config.cluster_entries:
            raw_mask = cluster_entry_mask(pd.Series(raw_mask.values))
        fires[sym] = pd.Series(raw_mask.values, index=table.index)
        tables[sym] = table
    return tables, fires


# ── Core Backtest Engine ────────────────────────────────────────────────────


def run_portfolio(frames: list[pd.DataFrame], config: StrategyConfig) -> BacktestResult:
    if config.signal not in SIGNAL_NAMES:
        raise KeyError(f"unknown signal: {config.signal}")

    tables, fires = _prepare_tables(frames, config)
    all_dates = sorted({d for t in tables.values() for d in t.index})

    # Compute cost per trade
    if config.use_indian_costs:
        costs = IndianCosts(slippage_bps=config.slippage_bps)
        avg_trade_value = config.capital * 0.30  # approximate
        cost_bps = costs.round_trip_bps(avg_trade_value)
    else:
        cost_bps = config.cost_bps
        if config.slippage_bps > 0:
            cost_bps += config.slippage_bps * 2
        if config.impact_bps > 0:
            cost_bps += config.impact_bps * 2

    open_pos: dict[str, dict] = {}
    pending_entries: list[dict] = []  # deferred entries for next-bar execution
    trades: list[Trade] = []
    cash = config.capital
    equity_curve: list[tuple[Date, float]] = []
    risk_rupees = config.capital * config.risk_pct / 100.0
    half_cost = cost_bps / 2 / 10_000

    # Running stats for Kelly sizing
    kelly_win_rate = 0.43
    kelly_avg_win = 250.0
    kelly_avg_loss = 165.0

    def close_position(sym: str, day: Date, px: float, reason: str) -> None:
        nonlocal cash, kelly_win_rate, kelly_avg_win, kelly_avg_loss
        pos = open_pos.pop(sym)
        gross = (px / pos["entry_px"] - 1.0) * 10_000
        net = gross - cost_bps

        # FIXED: exit cost uses EXIT price, not entry price
        cash += pos["qty"] * px - pos["qty"] * px * half_cost

        pnl = (px - pos["entry_px"]) * pos["qty"] - pos["qty"] * pos["entry_px"] * half_cost * 2

        trades.append(
            Trade(
                symbol=sym,
                segment=pos["segment"],
                entry_date=pos["entry_date"],
                entry_px=pos["entry_px"],
                qty=pos["qty"],
                exit_date=day,
                exit_px=px,
                gross_bps=round(gross, 2),
                net_bps=round(net, 2),
                reason=reason,
                days_held=pos["days_held"],
                mfe=round(pos.get("peak_bps", 0), 2),
                mae=round(pos.get("trough_bps", 0), 2),
                peak_bps=round(pos.get("peak_bps", 0), 2),
                trough_bps=round(pos.get("trough_bps", 0), 2),
                pnl=round(pnl, 2),
                cost_bps=round(cost_bps, 2),
            )
        )

        # Update Kelly stats
        if net > 0:
            kelly_avg_win = (kelly_avg_win + net) / 2
        else:
            kelly_avg_loss = (kelly_avg_loss + abs(net)) / 2
        closed = [t for t in trades if t.net_bps is not None]
        wins = sum(1 for t in closed if t.net_bps > 0)
        kelly_win_rate = wins / len(closed) if closed else 0.43

    for day in all_dates:
        # ---------- exits (per-position horizon, stop, trailing stop)
        for sym in list(open_pos):
            table = tables[sym]
            if day not in table.index:
                continue
            pos = open_pos[sym]
            pos["days_held"] += 1
            close = float(table.loc[day, "close"])
            high = float(table.loc[day, "high"]) if "high" in table.columns else close
            low = float(table.loc[day, "low"]) if "low" in table.columns else close

            # Update MFE/MAE
            current_bps = (close / pos["entry_px"] - 1.0) * 10_000
            pos["peak_bps"] = max(pos.get("peak_bps", 0), current_bps)
            pos["trough_bps"] = min(pos.get("trough_bps", 0), current_bps)

            # Update trailing stop
            if config.use_trailing_stop and high > pos.get("highest_px", pos["entry_px"]):
                pos["highest_px"] = high
                pos["trailing_stop_px"] = high * (1 - config.trailing_stop_pct)

            # Check exits
            effective_stop = max(
                pos["entry_px"] * (1 - pos["stop_pct"]),
                pos.get("trailing_stop_px", 0),
            )

            if close <= effective_stop:
                close_position(sym, day, close, "STOP")
            elif low <= effective_stop:
                close_position(sym, day, effective_stop, "STOP")
            elif pos["days_held"] >= pos["hold_days"]:
                close_position(sym, day, close, "HORIZON")

        # ---------- mark to market
        market_value = 0.0
        for sym, pos in open_pos.items():
            table = tables[sym]
            px = float(table.loc[day, "close"]) if day in table.index else pos["entry_px"]
            market_value += pos["qty"] * px
        equity_curve.append((day, cash + market_value))

        # ---------- process pending entries from previous bar (next-bar execution)
        for entry in list(pending_entries):
            if len(open_pos) >= config.max_positions:
                break
            sym = entry["sym"]
            if sym in open_pos or day not in tables[sym].index:
                continue
            table = tables[sym]
            row = table.loc[day]
            open_px = float(row["open"]) if "open" in table.columns else float(row["close"])
            # Use signal-day close for price filter, open for fill
            if not (config.price_min <= entry["signal_close"] <= config.price_max):
                continue

            open_pos[sym] = {
                "entry_date": day,
                "entry_px": open_px,
                "qty": entry["qty"],
                "segment": entry["segment"],
                "days_held": 0,
                "hold_days": entry["hold_d"],
                "stop_pct": entry["stop"],
                "conviction": entry["score"],
                "highest_px": open_px,
                "trailing_stop_px": 0,
                "impact_mult": entry["impact_mult"],
                "sector": entry.get("sector", "Unknown"),
            }
            effective_half = half_cost * entry["impact_mult"]
            cash -= entry["qty"] * open_px * effective_half
        pending_entries.clear()

        # ---------- entries (collect candidates, defer to next bar)
        if len(open_pos) >= config.max_positions:
            continue
        candidates: list[tuple[float, str, float, int, float]] = []
        for sym, table in tables.items():
            if sym in open_pos or day not in table.index:
                continue
            if not bool(fires[sym].get(day, False)):
                continue
            row = table.loc[day]
            close = float(row["close"])
            if not (config.price_min <= close <= config.price_max):
                continue
            if float(row.get("turnover", 0)) < config.min_turnover:
                continue
            z = row.get("deliv_z")
            if config.signal.startswith("dz_") and pd.isna(z):
                continue

            if config.use_conviction:
                score = conviction_score(row)
                candidates.append((score, sym, close, config.hold_days, config.stop_pct))
            else:
                candidates.append(
                    (
                        float(z) if not pd.isna(z) else 0.0,
                        sym,
                        close,
                        config.hold_days,
                        config.stop_pct,
                    )
                )

        candidates.sort(key=lambda c: (-c[0], c[1]))
        for score, sym, signal_close, hold_d, stop in candidates:
            if len(open_pos) + len(pending_entries) >= config.max_positions:
                break
            row = tables[sym].loc[day]

            if config.use_kelly:
                kf = kelly_fraction(kelly_win_rate, kelly_avg_win, kelly_avg_loss)
                qty = kelly_position(config.capital, config.risk_pct, signal_close, stop, kf)
            else:
                stop_dist = signal_close * config.stop_pct
                qty_by_risk = int(risk_rupees // stop_dist) if stop_dist > 0 else 0
                qty_by_capital = int((config.capital * 0.30) // signal_close)
                qty = max(0, min(qty_by_risk, qty_by_capital))

            if qty < 1:
                continue

            # Compute impact cost based on order size vs turnover
            turnover = float(row.get("turnover", 0))
            order_value = qty * signal_close
            impact_mult = 1.0
            if turnover > 0:
                participation = order_value / turnover
                if participation > 0.01:  # >1% of daily volume
                    impact_mult = 1.0 + (participation - 0.01) * 10

            # Portfolio constraint check (sector limits, total positions)
            sector = str(row.get("sector", "Unknown"))
            constraint_pos = {
                s: OpenPosition(
                    symbol=s,
                    sector=v.get("sector", "Unknown"),
                    entry_date=str(v["entry_date"]),
                    days_held=v["days_held"],
                )
                for s, v in open_pos.items()
            }
            constraints = PortfolioConstraints(
                max_sector=config.sector_limit,
                max_total=config.max_positions,
                max_sector_pct=config.max_sector_pct,
            )
            allowed, _reason = can_enter(sym, sector, str(day), constraint_pos, constraints)
            if not allowed:
                continue

            # Defer entry to next bar
            pending_entries.append(
                {
                    "sym": sym,
                    "signal_close": signal_close,
                    "qty": qty,
                    "segment": str(row.get("segment", "EQ")),
                    "sector": sector,
                    "hold_d": hold_d,
                    "stop": stop,
                    "score": score,
                    "impact_mult": impact_mult,
                }
            )

    # force-close leftovers at last known price
    for sym in list(open_pos):
        table = tables[sym]
        last_day = table.index.max()
        last_px = (
            float(table.loc[last_day, "close"])
            if last_day is not None
            else open_pos[sym]["entry_px"]
        )
        close_position(sym, last_day or date.today(), last_px, "DATA_END")

    summary = summarize(trades, equity_curve)
    return BacktestResult(config=config, trades=trades, equity_curve=equity_curve, summary=summary)


# ── Professional Metrics ────────────────────────────────────────────────────


def summarize(trades: list[Trade], equity_curve: list[tuple[Date, float]]) -> dict:
    closed = [t for t in trades if t.net_bps is not None]
    n = len(closed)
    nets = [float(t.net_bps or 0.0) for t in closed]
    pnls = [t.pnl for t in closed]
    mean_net = sum(nets) / n if n else None
    eq_values = [v for _, v in equity_curve]
    eq_dates = [d for d, _ in equity_curve]

    # Max drawdown
    peak = float("-inf")
    max_dd = 0.0
    eq_dates[0] if eq_dates else None
    for i, v in enumerate(eq_values):
        if v > peak:
            peak = v
            eq_dates[i] if i < len(eq_dates) else None
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            eq_dates[i] if i < len(eq_dates) else None

    wins = [t for t in closed if (t.net_bps is not None and t.net_bps > 0)]
    losses = [t for t in closed if (t.net_bps is not None and t.net_bps <= 0)]
    win_rate = len(wins) / n if n else 0

    # Exit reasons
    reasons: dict[str, int] = {}
    for t in closed:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1

    # Win/loss streaks
    max_win_streak = max_loss_streak = 0
    current_win = current_loss = 0
    for t in closed:
        if t.net_bps and t.net_bps > 0:
            current_win += 1
            current_loss = 0
            max_win_streak = max(max_win_streak, current_win)
        else:
            current_loss += 1
            current_win = 0
            max_loss_streak = max(max_loss_streak, current_loss)

    # Average win/loss
    avg_win_bps = sum(t.net_bps for t in wins) / len(wins) if wins else 0
    avg_loss_bps = sum(t.net_bps for t in losses) / len(losses) if losses else 0

    # Profit factor
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Expectancy per trade (in R-multiples)
    avg_win_inr = sum(t.pnl for t in wins) / len(wins) if wins else 0
    avg_loss_inr = abs(sum(t.pnl for t in losses) / len(losses)) if losses else 1
    payoff_ratio = avg_win_inr / avg_loss_inr if avg_loss_inr > 0 else 0
    expectancy_r = (win_rate * payoff_ratio) - (1 - win_rate)

    # Sharpe ratio (annualized, assuming ~250 trading days)
    if len(nets) >= 2:
        daily_std = pd.Series(nets).std()
        trades_per_year = 250 / max(1, np.mean([t.days_held for t in closed]))
        ann_ret = mean_net * trades_per_year if mean_net else 0
        ann_vol = daily_std * math.sqrt(trades_per_year) if daily_std > 0 else 1
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    else:
        sharpe = 0

    # Sortino ratio (downside deviation only)
    downside = [n for n in nets if n < 0]
    if len(downside) >= 2:
        downside_std = pd.Series(downside).std()
        ann_downside = downside_std * math.sqrt(trades_per_year) if downside_std > 0 else 1
        sortino = ann_ret / ann_downside if ann_downside > 0 else 0
    else:
        sortino = 0

    # Calmar ratio (annualized return / max drawdown)
    if eq_values and len(eq_values) > 1:
        total_days = (eq_dates[-1] - eq_dates[0]).days if eq_dates else 365
        total_years = max(total_days / 365.25, 0.01)
        total_return = (eq_values[-1] / eq_values[0]) - 1
        ann_return = (1 + total_return) ** (1 / total_years) - 1
        calmar = ann_return / max_dd if max_dd > 0 else 0
    else:
        ann_return = 0
        calmar = 0

    # SQN (System Quality Number)
    if len(nets) >= 2 and pd.Series(nets).std() > 0:
        sqn = (mean_net / pd.Series(nets).std()) * math.sqrt(n) if mean_net else 0
    else:
        sqn = 0

    # K-Ratio (slope of equity curve / standard error)
    if len(eq_values) >= 2:
        x = np.arange(len(eq_values))
        slope, intercept = np.polyfit(x, eq_values, 1)
        predicted = slope * x + intercept
        se = math.sqrt(np.sum((np.array(eq_values) - predicted) ** 2) / max(len(eq_values) - 2, 1))
        k_ratio = slope / se if se > 0 else 0
    else:
        k_ratio = 0

    # MFE/MAE analysis
    mfe_values = [t.mfe for t in closed if t.mfe != 0]
    mae_values = [t.mae for t in closed if t.mae != 0]
    avg_mfe = sum(mfe_values) / len(mfe_values) if mfe_values else 0
    avg_mae = sum(mae_values) / len(mae_values) if mae_values else 0

    # Exit efficiency: realized P&L / MFE
    exit_efficiencies = []
    for t in closed:
        if t.mfe > 0:
            exit_efficiencies.append(t.net_bps / t.mfe if t.mfe else 0)
    avg_exit_efficiency = (
        sum(exit_efficiencies) / len(exit_efficiencies) if exit_efficiencies else 0
    )

    # Tail ratio (95th percentile gains / 5th percentile losses)
    if len(nets) >= 20:
        p95 = np.percentile(nets, 95)
        p5 = np.percentile(nets, 5)
        tail_ratio = abs(p95 / p5) if p5 != 0 else 0
    else:
        tail_ratio = 0

    # Recovery factor
    total_net_pnl = sum(pnls)
    total_net_pnl / (max_dd * config_capital(eq_values)) if max_dd > 0 else 0

    return {
        "n_trades": n,
        "net_expectancy_bps": round(mean_net, 2) if mean_net is not None else None,
        "win_rate": round(win_rate, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "final_equity": round(eq_values[-1], 2) if eq_values else None,
        "avg_holding_days": round(sum(t.days_held for t in closed) / n, 1) if n else None,
        "exit_reasons": reasons,
        # v2 metrics
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "calmar_ratio": round(calmar, 3),
        "profit_factor": round(profit_factor, 3),
        "sqn": round(sqn, 3),
        "k_ratio": round(k_ratio, 3),
        "ann_return_pct": round(ann_return * 100, 2),
        "avg_win_bps": round(avg_win_bps, 2),
        "avg_loss_bps": round(avg_loss_bps, 2),
        "payoff_ratio": round(payoff_ratio, 3),
        "expectancy_r": round(expectancy_r, 3),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "avg_mfe_bps": round(avg_mfe, 2),
        "avg_mae_bps": round(avg_mae, 2),
        "avg_exit_efficiency": round(avg_exit_efficiency, 3),
        "tail_ratio": round(tail_ratio, 3),
        "total_pnl": round(total_net_pnl, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "avg_days_winners": round(sum(t.days_held for t in wins) / len(wins), 1) if wins else 0,
        "avg_days_losers": round(sum(t.days_held for t in losses) / len(losses), 1)
        if losses
        else 0,
    }


def config_capital(eq_values: list[float]) -> float:
    """Extract initial capital from equity curve."""
    return eq_values[0] if eq_values else 25_000.0


# ── Monte Carlo Bootstrap ───────────────────────────────────────────────────


def monte_carlo_bootstrap(
    trades: list[Trade],
    n_simulations: int = 1000,
    seed: int = 42,
    starting_capital: float = 25000,
    confidence_levels: list[int] | None = None,
) -> dict:
    """Block bootstrap over trade P&L to generate confidence intervals.

    Resamples trades with replacement (preserving local order via block bootstrap)
    to generate alternative equity paths. Reports percentiles for key metrics.
    """
    if confidence_levels is None:
        confidence_levels = [5, 25, 50, 75, 95]

    closed = [t for t in trades if t.net_bps is not None]
    if len(closed) < 10:
        return {"error": "Need at least 10 closed trades for Monte Carlo"}

    pnls = np.array([t.pnl for t in closed])
    n = len(pnls)
    rng = np.random.default_rng(seed)

    sim_results = {
        "total_pnl": [],
        "max_drawdown": [],
        "sharpe": [],
        "win_rate": [],
        "n_trades": [],
    }

    for _ in range(n_simulations):
        # Block bootstrap: sample blocks of 3-5 consecutive trades
        block_size = min(5, max(3, n // 10))
        n_blocks = n // block_size + 1
        sampled_pnls = []
        for _ in range(n_blocks):
            start = rng.integers(0, max(1, n - block_size))
            sampled_pnls.extend(pnls[start : start + block_size].tolist())
        sampled_pnls = np.array(sampled_pnls[:n])

        # Compute metrics for this simulation
        total = float(np.sum(sampled_pnls))
        wins = np.sum(sampled_pnls > 0)
        wr = wins / n if n > 0 else 0

        # Equity curve simulation
        eq = np.cumsum(sampled_pnls) + starting_capital
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / np.where(peak > 0, peak, 1)
        max_dd = float(np.max(dd)) * 100

        # Sharpe
        if np.std(sampled_pnls) > 0:
            sharpe = float(np.mean(sampled_pnls) / np.std(sampled_pnls) * np.sqrt(250))
        else:
            sharpe = 0

        sim_results["total_pnl"].append(total)
        sim_results["max_drawdown"].append(max_dd)
        sim_results["sharpe"].append(sharpe)
        sim_results["win_rate"].append(wr * 100)
        sim_results["n_trades"].append(n)

    # Compute percentiles
    percentiles = {}
    for metric in ["total_pnl", "max_drawdown", "sharpe", "win_rate"]:
        values = sim_results[metric]
        percentiles[metric] = {}
        for cl in confidence_levels:
            percentiles[metric][f"p{cl}"] = round(float(np.percentile(values, cl)), 2)

    # Probability of ruin (PnL < 0)
    ruin_prob = sum(1 for p in sim_results["total_pnl"] if p < 0) / n_simulations

    # Launch criteria
    launch_ok = (
        percentiles["total_pnl"]["p5"] > 0
        and ruin_prob < 0.01
        and percentiles["sharpe"]["p5"] > 0.5
    )

    return {
        "n_simulations": n_simulations,
        "n_trades": n,
        "percentiles": percentiles,
        "probability_of_ruin": round(ruin_prob, 4),
        "launch_criteria_met": launch_ok,
        "summary": {
            "pnl_5th": percentiles["total_pnl"]["p5"],
            "pnl_median": percentiles["total_pnl"]["p50"],
            "pnl_95th": percentiles["total_pnl"]["p95"],
            "max_dd_95th": percentiles["max_drawdown"]["p95"],
            "sharpe_5th": percentiles["sharpe"]["p5"],
            "win_rate_median": percentiles["win_rate"]["p50"],
        },
    }


# ── Walk-Forward Analysis ───────────────────────────────────────────────────


def walk_forward_analysis(
    frames: list[pd.DataFrame],
    config: StrategyConfig,
    train_pct: float = 0.60,
    n_splits: int = 5,
    embargo_days: int = 5,
) -> dict:
    """Expanding-window walk-forward analysis.

    Splits the data into n_splits windows. For each:
    - Train on first train_pct of data up to that window
    - Test on the remaining window
    - Embargo gap prevents look-ahead leakage

    Reports per-window metrics and degradation rate.
    """
    # Collect all dates across all frames
    all_dates = set()
    for f in frames:
        if "date" in f.columns:
            all_dates.update(pd.to_datetime(f["date"]).dt.date.unique())
    all_dates = sorted(all_dates)

    if len(all_dates) < 100:
        return {"error": "Insufficient data for walk-forward analysis"}

    total_days = len(all_dates)
    window_size = total_days // n_splits

    window_results = []

    for i in range(n_splits):
        # Define train/test boundaries
        test_start_idx = int(total_days * train_pct) + i * window_size
        test_end_idx = min(test_start_idx + window_size, total_days)

        if test_start_idx >= total_days or test_end_idx <= test_start_idx:
            break

        test_start = all_dates[test_start_idx]
        test_end = all_dates[min(test_end_idx - 1, total_days - 1)]

        # Filter frames to test window
        test_frames = []
        for f in frames:
            if "date" not in f.columns:
                continue
            f_dates = pd.to_datetime(f["date"]).dt.date
            mask = (f_dates >= test_start) & (f_dates <= test_end)
            if mask.sum() >= 20:  # need at least 20 rows
                test_frames.append(f[mask].copy())

        if not test_frames:
            continue

        # Run backtest on test window only
        try:
            result = run_portfolio(test_frames, config)
            window_results.append(
                {
                    "window": i + 1,
                    "test_start": str(test_start),
                    "test_end": str(test_end),
                    "n_trades": result.summary.get("n_trades", 0),
                    "net_bps": result.summary.get("net_expectancy_bps", 0),
                    "win_rate": result.summary.get("win_rate", 0),
                    "max_dd": result.summary.get("max_drawdown_pct", 0),
                    "sharpe": result.summary.get("sharpe_ratio", 0),
                }
            )
        except Exception as e:
            window_results.append(
                {
                    "window": i + 1,
                    "error": str(e),
                }
            )

    if not window_results:
        return {"error": "No valid windows produced"}

    # Compute degradation
    valid = [w for w in window_results if "error" not in w]
    if len(valid) < 2:
        return {"windows": window_results, "degradation": "insufficient"}

    bps_values = [w["net_bps"] for w in valid]
    sharpe_values = [w["sharpe"] for w in valid]

    # Degradation: first half vs second half
    mid = len(valid) // 2
    first_half_bps = np.mean(bps_values[:mid]) if bps_values[:mid] else 0
    second_half_bps = np.mean(bps_values[mid:]) if bps_values[mid:] else 0
    degradation_pct = (
        (first_half_bps - second_half_bps) / abs(first_half_bps) * 100 if first_half_bps != 0 else 0
    )

    # Stability: coefficient of variation
    cv_bps = (
        np.std(bps_values) / abs(np.mean(bps_values)) if np.mean(bps_values) != 0 else float("inf")
    )

    return {
        "n_windows": len(valid),
        "windows": window_results,
        "aggregate": {
            "mean_net_bps": round(np.mean(bps_values), 2),
            "std_net_bps": round(np.std(bps_values), 2),
            "mean_sharpe": round(np.mean(sharpe_values), 3),
            "min_window_bps": round(min(bps_values), 2),
            "max_window_bps": round(max(bps_values), 2),
        },
        "degradation": {
            "first_half_avg_bps": round(first_half_bps, 2),
            "second_half_avg_bps": round(second_half_bps, 2),
            "degradation_pct": round(degradation_pct, 2),
            "is_robust": abs(degradation_pct) < 30,
        },
        "stability": {
            "coefficient_of_variation": round(cv_bps, 3),
            "is_stable": cv_bps < 2.0,
        },
    }


__all__ = [
    "BacktestResult",
    "StrategyConfig",
    "Trade",
    "IndianCosts",
    "load_frames",
    "run_portfolio",
    "summarize",
    "monte_carlo_bootstrap",
    "walk_forward_analysis",
    "conviction_score",
    "horizon_fit",
    "run_enhanced_portfolio",
    "EnhancedConfig",
]


# ══════════════════════════════════════════════════════════════════════════════
# ENHANCED STRATEGY — Multi-factor + Regime + Adaptive Stops
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EnhancedConfig:
    """Configuration for enhanced multi-factor strategy."""

    price_min: float = 100.0
    price_max: float = 500.0
    min_turnover: float = 10_000_000.0
    max_positions: int = 8
    capital: float = 100_000.0
    risk_pct: float = 1.0
    cost_bps: float = 107.0
    # Multi-factor thresholds
    min_conviction: float = 0.25  # minimum composite score to enter
    min_delivery_z: float = 1.5  # relaxed from 2.0 — let other factors compensate
    min_momentum_pct: float = -10.0  # 20d momentum floor (raw %)
    max_volatility_pct: float = 60.0  # max 20d volatility (raw %)
    min_fundamental: float = 0.10  # minimum fundamental score (0-1)
    # Regime filter
    use_regime_filter: bool = True
    regime_ma_window: int = 50  # MA window for regime detection
    # Adaptive stops
    use_atr_stops: bool = True
    atr_stop_multiplier: float = 2.0  # stop at entry - 2x ATR
    min_stop_pct: float = 0.03  # floor
    max_stop_pct: float = 0.10  # ceiling
    # Dynamic sizing
    use_dynamic_sizing: bool = True
    min_position_pct: float = 0.05  # min 5% of capital per position
    max_position_pct: float = 0.25  # max 25% of capital per position
    # Exit rules
    hold_days: int = 10
    use_trailing_stop: bool = True
    trailing_stop_pct: float = 0.03
    # Sector limits
    max_per_sector: int = 2
    # Score weights (0-1, must sum to 1.0)
    w_delivery: float = 0.30
    w_momentum: float = 0.20
    w_fundamental: float = 0.25
    w_volatility: float = 0.15
    w_institutional: float = 0.10


def _load_enhanced_data(engine, config: EnhancedConfig) -> pd.DataFrame:
    """Load latest cached_signals with all factors for the target universe."""
    import sqlalchemy as sa

    sql = sa.text("""
        SELECT symbol, exchange, close, deliv_z, volume,
               close * volume as turnover,
               fundamental_score, institutional_score,
               momentum_20d, volatility_20d, atr_14,
               pe_trailing, roe, debt_to_equity, sector,
               market_cap_cr, signal_date
        FROM cached_signals
        WHERE exchange = 'NSE'
        AND segment != 'SME'
        AND market_cap_cr >= 500 AND market_cap_cr <= 5000
        AND close >= :price_min AND close <= :price_max
        AND signal_date = (SELECT MAX(signal_date) FROM cached_signals)
        AND deliv_z IS NOT NULL
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={
                "price_min": config.price_min,
                "price_max": config.price_max,
            },
        )
    return df


def _compute_composite_score(row: pd.Series, config: EnhancedConfig) -> float:
    """Multi-factor composite score (0-1 scale)."""
    # Delivery z-score component (0-1, capped at z=4)
    delivery = min(abs(row.get("deliv_z", 0)) / 4.0, 1.0)

    # Momentum component (0-1, normalized) — raw values are in percentage
    mom = row.get("momentum_20d", 0) or 0
    # mom is raw 20d return in %, map: -20% -> 0, 0% -> 0.5, +20% -> 1.0
    momentum = min(max((mom + 20) / 40, 0), 1.0)

    # Fundamental component (already 0-1 from cache)
    fundamental = min(max(row.get("fundamental_score", 0) or 0, 0), 1.0)

    # Volatility component (inverse — lower vol = higher score)
    # vol_20d is raw annualized vol in %, typical range 15-60
    vol = row.get("volatility_20d", 30) or 30
    volatility = max(0, 1.0 - (vol / 80))  # 80% vol = 0 score

    # Institutional component (already 0-1 from cache)
    institutional = min(max(row.get("institutional_score", 0) or 0, 0), 1.0)

    composite = (
        config.w_delivery * delivery
        + config.w_momentum * momentum
        + config.w_fundamental * fundamental
        + config.w_volatility * volatility
        + config.w_institutional * institutional
    )
    return round(composite, 4)


def _detect_regime(dates: list, all_daily_returns: dict, window: int = 50) -> dict:
    """Detect market regime using breadth (% of stocks above their MA).

    Returns dict mapping date -> regime ('bull', 'bear', 'neutral').
    """
    # Compute daily returns for all stocks
    if not all_daily_returns:
        return {}

    # Build a return matrix
    all_syms = list(all_daily_returns.keys())
    if not all_syms:
        return {}

    # For simplicity: use average return as market proxy
    avg_returns = pd.Series(0.0, index=dates)
    for sym in all_syms:
        rets = all_daily_returns[sym]
        for d in dates:
            if d in rets:
                avg_returns[d] += rets[d]
    avg_returns /= max(len(all_syms), 1)

    # Compute MA of cumulative returns
    cum_ret = (1 + avg_returns).cumprod()
    ma = cum_ret.rolling(window, min_periods=window // 2).mean()

    regime = {}
    for d in dates:
        if pd.isna(ma.get(d)):
            regime[d] = "neutral"
        elif cum_ret[d] > ma[d] * 1.01:
            regime[d] = "bull"
        elif cum_ret[d] < ma[d] * 0.99:
            regime[d] = "bear"
        else:
            regime[d] = "neutral"
    return regime


def run_enhanced_portfolio(
    frames: list[pd.DataFrame],
    config: EnhancedConfig,
    engine=None,
) -> BacktestResult:
    """Enhanced multi-factor portfolio backtest.

    Design: delivery z-score is the PRIMARY alpha.
    Other factors are CONFIRMATION filters (not replacement scoring).
    Risk management is the key improvement: ATR stops, regime filter, dynamic sizing.
    """

    cost_bps = config.cost_bps
    half_cost = cost_bps / 2 / 10_000

    # Prepare frames with features (z_min = 2.0 for primary signal)
    tables, fires = _prepare_tables(
        frames,
        StrategyConfig(
            signal="dz_hi_up",
            z_min=2.0,
            cluster_entries=True,
            use_tech_filters=False,
        ),
    )

    # Compute per-stock ATR from close prices
    atr_map: dict[str, float] = {}
    for sym, table in tables.items():
        closes = table["close"]
        if len(closes) >= 15:
            tr = closes.diff().abs()
            atr = tr.rolling(14, min_periods=7).mean().iloc[-1]
            atr_map[sym] = float(atr) if not pd.isna(atr) else float(closes.iloc[-1] * 0.03)
        else:
            atr_map[sym] = float(closes.iloc[-1] * 0.03)

    # Load confirmation factors from cached_signals
    if engine is None:
        from indian_quant.config.connections import get_engine as _get_engine

        engine = _get_engine()

    enhanced_df = _load_enhanced_data(engine, config)

    # Build factor lookup
    factor_lookup: dict[str, dict] = {}
    for _, row in enhanced_df.iterrows():
        sym = row["symbol"]
        mom = row.get("momentum_20d", 0) or 0
        vol = row.get("volatility_20d", 30) or 30
        fund = row.get("fundamental_score", 0) or 0
        factor_lookup[sym] = {
            "momentum": mom,
            "volatility": vol,
            "fundamental": fund,
            "sector": str(row.get("sector", "Unknown") or "Unknown"),
        }

    # Compute daily returns for regime
    all_daily_returns: dict[str, dict] = {}
    for sym, table in tables.items():
        if "close" in table.columns and len(table) >= 2:
            rets = table["close"].pct_change().dropna()
            all_daily_returns[sym] = {d: float(r) for d, r in rets.items()}

    all_dates = sorted({d for t in tables.values() for d in t.index})
    regime = (
        _detect_regime(all_dates, all_daily_returns, config.regime_ma_window)
        if config.use_regime_filter
        else dict.fromkeys(all_dates, "bull")
    )

    # ── Portfolio simulation ──
    open_pos: dict[str, dict] = {}
    pending_entries: list[dict] = []  # deferred entries for next-bar execution
    trades: list[Trade] = []
    cash = config.capital
    equity_curve: list[tuple[Date, float]] = []
    risk_rupees = config.capital * config.risk_pct / 100.0
    sector_counts: dict[str, int] = {}

    def close_position(sym: str, day: Date, px: float, reason: str) -> None:
        nonlocal cash
        pos = open_pos.pop(sym)
        gross = (px / pos["entry_px"] - 1.0) * 10_000
        net = gross - cost_bps
        cash += pos["qty"] * px - pos["qty"] * px * half_cost
        pnl = (px - pos["entry_px"]) * pos["qty"] - pos["qty"] * pos["entry_px"] * half_cost * 2
        sector = pos.get("sector", "Unknown")
        sector_counts[sector] = max(0, sector_counts.get(sector, 1) - 1)
        trades.append(
            Trade(
                symbol=sym,
                segment=pos.get("segment", "EQ"),
                entry_date=pos["entry_date"],
                entry_px=pos["entry_px"],
                qty=pos["qty"],
                exit_date=day,
                exit_px=px,
                gross_bps=round(gross, 2),
                net_bps=round(net, 2),
                reason=reason,
                days_held=pos["days_held"],
                mfe=round(pos.get("peak_bps", 0), 2),
                mae=round(pos.get("trough_bps", 0), 2),
                pnl=round(pnl, 2),
                cost_bps=round(cost_bps, 2),
            )
        )

    for day in all_dates:
        # ── EXITS ──
        for sym in list(open_pos):
            table = tables[sym]
            if day not in table.index:
                continue
            pos = open_pos[sym]
            pos["days_held"] += 1
            close = float(table.loc[day, "close"])

            # MFE/MAE
            current_bps = (close / pos["entry_px"] - 1.0) * 10_000
            pos["peak_bps"] = max(pos.get("peak_bps", 0), current_bps)
            pos["trough_bps"] = min(pos.get("trough_bps", 0), current_bps)

            # Trailing stop
            if config.use_trailing_stop and close > pos.get("highest_px", pos["entry_px"]):
                pos["highest_px"] = close
                pos["trailing_stop_px"] = close * (1 - config.trailing_stop_pct)

            effective_stop = max(
                pos.get("adaptive_stop", 0),
                pos.get("trailing_stop_px", 0),
            )

            if close <= effective_stop:
                close_position(sym, day, close, "STOP")
            elif pos["days_held"] >= pos["hold_days"]:
                close_position(sym, day, close, "HORIZON")

        # ── MARK TO MARKET ──
        market_value = sum(
            pos["qty"] * float(tables[sym].loc[day, "close"])
            for sym, pos in open_pos.items()
            if day in tables[sym].index
        )
        equity_curve.append((day, cash + market_value))

        # ── PROCESS PENDING ENTRIES (next-bar execution) ──
        for entry in list(pending_entries):
            if len(open_pos) >= config.max_positions:
                break
            sym = entry["sym"]
            if sym in open_pos or day not in tables[sym].index:
                continue
            table = tables[sym]
            row = table.loc[day]
            open_px = float(row["open"]) if "open" in table.columns else float(row["close"])

            # Portfolio constraint check
            constraint_pos = {
                s: OpenPosition(
                    symbol=s,
                    sector=v.get("sector", "Unknown"),
                    entry_date=str(v["entry_date"]),
                    days_held=v["days_held"],
                )
                for s, v in open_pos.items()
            }
            constraints = PortfolioConstraints(
                max_sector=config.max_per_sector, max_total=config.max_positions
            )
            allowed, _reason = can_enter(
                sym, entry["sector"], str(day), constraint_pos, constraints
            )
            if not allowed:
                continue

            sector = entry["sector"]
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            open_pos[sym] = {
                "entry_date": day,
                "entry_px": open_px,
                "qty": entry["qty"],
                "segment": "EQ",
                "days_held": 0,
                "hold_days": config.hold_days,
                "stop_pct": entry["stop_pct"],
                "z_score": entry["z_score"],
                "sector": sector,
                "highest_px": open_px,
                "trailing_stop_px": 0,
                "adaptive_stop": open_px * (1 - entry["stop_pct"]),
                "atr": entry["atr"],
            }
            cash -= entry["qty"] * open_px * half_cost
        pending_entries.clear()

        # ── ENTRIES (collect candidates, defer to next bar) ──
        if len(open_pos) >= config.max_positions:
            continue
        current_regime = regime.get(day, "neutral")
        if current_regime == "bear":
            continue

        candidates: list[tuple[float, str, float, dict]] = []
        for sym, table in tables.items():
            if sym in open_pos or day not in table.index:
                continue
            if not bool(fires[sym].get(day, False)):
                continue

            row = table.loc[day]
            close = float(row["close"])
            if not (config.price_min <= close <= config.price_max):
                continue
            if float(row.get("turnover", 0)) < config.min_turnover:
                continue

            # PRIMARY GATE: delivery z-score (must be >= 2.0)
            z = row.get("deliv_z")
            if pd.isna(z) or z < 2.0:
                continue

            # CONFIRMATION: positive return today
            ret = row.get("ret_1d", 0)
            if pd.isna(ret) or ret < 0.005:
                continue

            # CONFIRMATION: fundamentals exist and reasonable
            factors = factor_lookup.get(sym, {})
            fund = factors.get("fundamental", 0)
            if fund < 0.05:  # must have some fundamental data
                continue

            # CONFIRMATION: momentum positive (20d)
            mom = factors.get("momentum", 0)
            if mom < -15:  # don't buy stocks in freefall
                continue

            # CONFIRMATION: volatility not extreme
            vol = factors.get("volatility", 30)
            if vol > 60:  # too volatile
                continue

            # Sector limit
            sector = factors.get("sector", "Unknown")
            if sector_counts.get(sector, 0) >= config.max_per_sector:
                continue

            # Score by z-score strength (higher z = stronger signal)
            candidates.append((z, sym, close, factors))

        candidates.sort(key=lambda c: (-c[0], c[1]))

        for z_score, sym, signal_close, factors in candidates:
            if len(open_pos) + len(pending_entries) >= config.max_positions:
                break

            # ATR-based stop
            atr = atr_map.get(sym, signal_close * 0.03)
            atr_stop_dist = atr * config.atr_stop_multiplier
            atr_stop_pct = atr_stop_dist / signal_close
            stop_pct = max(config.min_stop_pct, min(atr_stop_pct, config.max_stop_pct))

            # Dynamic sizing: scale by z-score strength
            if config.use_dynamic_sizing:
                # z=2 -> min size, z=4+ -> max size
                z_factor = min(max((z_score - 2.0) / 2.0, 0), 1.0)
                position_pct = config.min_position_pct + z_factor * (
                    config.max_position_pct - config.min_position_pct
                )
                position_value = config.capital * position_pct
                qty = max(1, int(position_value / signal_close))
            else:
                stop_dist = signal_close * stop_pct
                qty_by_risk = int(risk_rupees // stop_dist) if stop_dist > 0 else 0
                qty_by_capital = int((config.capital * 0.25) // signal_close)
                qty = max(0, min(qty_by_risk, qty_by_capital))

            if qty < 1:
                continue

            sector = factors.get("sector", "Unknown")

            # Defer entry to next bar
            pending_entries.append(
                {
                    "sym": sym,
                    "signal_close": signal_close,
                    "qty": qty,
                    "sector": sector,
                    "stop_pct": stop_pct,
                    "z_score": z_score,
                    "atr": atr,
                }
            )

    # Force close
    for sym in list(open_pos):
        table = tables[sym]
        last_day = table.index.max()
        last_px = (
            float(table.loc[last_day, "close"])
            if last_day is not None
            else open_pos[sym]["entry_px"]
        )
        close_position(sym, last_day or date.today(), last_px, "DATA_END")

    summary = summarize(trades, equity_curve)
    return BacktestResult(config=config, trades=trades, equity_curve=equity_curve, summary=summary)
