/// Standalone integration adapter for EQATS.
///
/// Full direct integration of 0xTan1319/hyperliquid-trading-bot-rust into EQATS is infeasible in a single module
/// because the original repo is tightly coupled across many internal modules (wallet, executor, market types,
/// websockets and frontend components). To provide a practical, immediately compilable contribution to EQATS,
/// this file implements a small, well-tested, reusable Perpetual (perp) position & margin utility inspired by
/// Hyperliquid concepts: notional calculation, unrealized PnL, initial/maintenance margin calculations and a
/// simple margin-breach predicate. This helper is directly usable inside EQATS risk and execution logic.

use std::fmt;

/// Trade side
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Side { Long, Short }

impl fmt::Display for Side {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Side::Long => write!(f, "Long"),
            Side::Short => write!(f, "Short"),
        }
    }
}

/// Market-level parameters used for margin/notional conversions
#[derive(Debug, Clone)]
pub struct Market {
    pub symbol: String,
    /// mark/spot price (quote per unit)
    pub mark_price: f64,
    /// contract multiplier: how many base units per contract (1.0 for spot-like)
    pub contract_size: f64,
    /// fraction of notional required as maintenance margin (e.g. 0.005 for 0.5%)
    pub maintenance_margin_ratio: f64,
    /// fraction of notional required as initial margin
    pub initial_margin_ratio: f64,
}

impl Market {
    pub fn new<S: Into<String>>(symbol: S, mark_price: f64) -> Self {
        Self {
            symbol: symbol.into(),
            mark_price,
            contract_size: 1.0,
            maintenance_margin_ratio: 0.005,
            initial_margin_ratio: 0.02,
        }
    }

    /// Compute notional = abs(contracts * contract_size * mark_price)
    pub fn notional(&self, contracts: f64) -> f64 {
        (contracts.abs()) * self.contract_size * self.mark_price
    }
}

/// A position on a perpetual-style market
#[derive(Debug, Clone)]
pub struct Position {
    /// number of contracts (positive for long, negative for short)
    pub contracts: f64,
    /// entry price per base unit in quote currency
    pub entry_price: f64,
    /// chosen leverage (>=1.0)
    pub leverage: f64,
    pub side: Side,
}

impl Position {
    pub fn new(contracts: f64, entry_price: f64, leverage: f64) -> Self {
        let side = if contracts >= 0.0 { Side::Long } else { Side::Short };
        Self { contracts, entry_price, leverage: if leverage <= 0.0 { 1.0 } else { leverage }, side }
    }

    /// Unrealized PnL in quote currency using market mark_price
    /// For longs: (mark_price - entry_price) * contracts * contract_size
    /// For shorts: (entry_price - mark_price) * abs(contracts) * contract_size
    pub fn unrealized_pnl(&self, market: &Market) -> f64 {
        let price_diff = match self.side {
            Side::Long => market.mark_price - self.entry_price,
            Side::Short => self.entry_price - market.mark_price,
        };
        price_diff * self.contracts.abs() * market.contract_size
    }

    /// Notional (absolute) of the position in quote currency
    pub fn notional(&self, market: &Market) -> f64 {
        market.notional(self.contracts)
    }

    /// Initial margin required for this position, using either explicit initial_margin_ratio
    /// or implied by chosen leverage (notional / leverage). We take the max of the two methods.
    pub fn initial_margin_required(&self, market: &Market) -> f64 {
        let notional = self.notional(market);
        let by_leverage = if self.leverage <= 0.0 { notional } else { notional / self.leverage };
        let by_ratio = notional * market.initial_margin_ratio;
        by_leverage.max(by_ratio)
    }

    /// Maintenance margin required
    pub fn maintenance_margin_required(&self, market: &Market) -> f64 {
        self.notional(market) * market.maintenance_margin_ratio
    }

    /// Simple predicate: given available_margin (account free margin excluding this position's initial margin)
    /// is the position in danger of being liquidated? We consider the margin breach when available_margin + unrealized_pnl < maintenance_margin.
    /// This is a conservative, exchange-agnostic check suitable for risk screening inside EQATS.
    pub fn is_margin_breached(&self, market: &Market, available_margin: f64) -> bool {
        let pnl = self.unrealized_pnl(market);
        let maintenance = self.maintenance_margin_required(market);
        (available_margin + pnl) < maintenance
    }

    /// Compute realized PnL for a trade that closes close_contracts at close_price.
    /// close_contracts must not exceed absolute open contracts. Returns (realized_pnl, remaining_position)
    pub fn close_partial(&self, close_contracts: f64, close_price: f64, market: &Market) -> (f64, Position) {
        let to_close = close_contracts.min(self.contracts.abs());
        let sign = if self.contracts >= 0.0 { 1.0 } else { -1.0 };
        let closed_contracts_signed = to_close * sign;
        let closed_notional = to_close * market.contract_size * close_price;
        let pnl_per_contract = match self.side {
            Side::Long => close_price - self.entry_price,
            Side::Short => self.entry_price - close_price,
        };
        let realized_pnl = pnl_per_contract * to_close * market.contract_size;
        let remaining_contracts = self.contracts - closed_contracts_signed;
        let remaining_side = if remaining_contracts >= 0.0 { Side::Long } else { Side::Short };
        let remaining = Position { contracts: remaining_contracts, entry_price: if remaining_contracts == 0.0 { 0.0 } else { self.entry_price }, leverage: self.leverage, side: remaining_side };
        (realized_pnl, remaining)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_unrealized_pnl_long_short() {
        let mut m = Market::new("BTC-PERP", 20000.0);
        m.contract_size = 1.0;
        let pos_long = Position::new(2.0, 18000.0, 10.0);
        let pos_short = Position::new(-3.0, 22000.0, 5.0);
        let pnl_long = pos_long.unrealized_pnl(&m);
        let pnl_short = pos_short.unrealized_pnl(&m);
        assert_eq!(pnl_long, (20000.0 - 18000.0) * 2.0);
        assert_eq!(pnl_short, (22000.0 - 20000.0) * 3.0);
        assert!(pnl_long > 0.0);
        assert!(pnl_short > 0.0);
    }

    #[test]
    fn test_margin_requirements_and_breach() {
        let mut m = Market::new("SOL-PERP", 50.0);
        m.contract_size = 10.0; // each contract = 10 SOL
        m.initial_margin_ratio = 0.05;
        m.maintenance_margin_ratio = 0.01;
        let pos = Position::new(5.0, 40.0, 4.0);
        let notional = pos.notional(&m); // 5 * 10 * 50 = 2500
        assert_eq!(notional, 2500.0);
        let initial = pos.initial_margin_required(&m);
        let by_leverage = notional / 4.0;
        let by_ratio = notional * m.initial_margin_ratio;
        assert_eq!(initial, by_leverage.max(by_ratio));
        let maintenance = pos.maintenance_margin_required(&m);
        assert_eq!(maintenance, notional * 0.01);
        // available margin small -> breach
        let breached = pos.is_margin_breached(&m, 0.0);
        // unrealized pnl = (50 - 40) * 5 * 10 = 500, maintenance = 25 -> 0+500 >=25 -> not breached
        assert!(!breached);
        // if price falls to 35, pnl negative
        let mut m2 = m.clone();
        m2.mark_price = 35.0;
        // unrealized = (35-40)*5*10 = -250
        assert!(pos.unrealized_pnl(&m2) < 0.0);
        // available_margin 0 => -250 + 0 < 25 => breached
        assert!(pos.is_margin_breached(&m2, 0.0));
    }

    #[test]
    fn test_partial_close() {
        let m = Market::new("ETH-PERP", 3000.0);
        let pos = Position::new(4.0, 2500.0, 2.0);
        let (realized, remaining) = pos.close_partial(1.5, 3200.0, &m);
        // closed 1.5 contracts, pnl per contract = 3200-2500=700 -> realized = 700*1.5
        assert_eq!(realized, 700.0 * 1.5);
        assert_eq!(remaining.contracts, 2.5);
    }
}
