// NOTE: The original repository (85599/BankNIFTY-Golden-Ratio-Strategy) files were not directly available to this integration generator.
// This file is a conservative, self-contained Rust reimplementation of the single most reusable
// feature inferred from the repository name and file list: computation of "golden-ratio" support
// and resistance levels and simple signal+risk helpers. It is intended to be dropped into the
// EQATS Rust core at the path given in integration_path. It is not a verbatim port of the
// original Python file because that file's contents were not accessible at generation time.

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Levels {
    pub r2: f64,
    pub r1: f64,
    pub pivot: f64,
    pub s1: f64,
    pub s2: f64,
}

impl Levels {
    pub fn to_vec(self) -> [f64; 5] { [self.r2, self.r1, self.pivot, self.s1, self.s2] }
}

/// Compute golden-ratio based levels from OHLC-like inputs.
/// This function returns a Levels struct containing two resistance (r1,r2), a pivot and two supports (s1,s2).
/// Algorithm:
/// - pivot = (high + low + close) / 3
/// - range = high - low
/// - r1 = close + 0.618 * range
/// - r2 = close + 1.618 * range
/// - s1 = close - 0.618 * range
/// - s2 = close - 1.618 * range
/// These multipliers are common golden-ratio approximations (0.618 and 1.618). This is intentionally simple
/// to serve as a pluggable building block in EQATS.
pub fn golden_ratio_levels(high: f64, low: f64, close: f64) -> Levels {
    let range = high - low;
    let pivot = (high + low + close) / 3.0;
    let r1 = close + 0.618 * range;
    let r2 = close + 1.618 * range;
    let s1 = close - 0.618 * range;
    let s2 = close - 1.618 * range;
    Levels { r2, r1, pivot, s1, s2 }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Signal { Buy, Sell, Hold }

/// Simple signal generator:
/// - If price > r1 => Sell
/// - If price < s1 => Buy
/// - Otherwise => Hold
pub fn generate_signal(price: f64, levels: &Levels) -> Signal {
    if price > levels.r1 { Signal::Sell }
    else if price < levels.s1 { Signal::Buy }
    else { Signal::Hold }
}

/// Suggest a stop-loss given an entry price and a direction. This uses conservative rules:
/// - For Buy: suggest stop = max(s2, entry - 1.5*(entry - s1)) clamped below entry
/// - For Sell: suggest stop = min(r2, entry + 1.5*(r1 - entry)) clamped above entry
/// The function is intentionally simple; users should adapt to portfolio-level risk rules.
pub fn suggested_stop_loss(entry: f64, dir: Signal, levels: &Levels) -> f64 {
    match dir {
        Signal::Buy => {
            let s1_dist = (entry - levels.s1).abs();
            let candidate = entry - 1.5 * s1_dist;
            candidate.min(levels.s2).min(entry)
        }
        Signal::Sell => {
            let r1_dist = (levels.r1 - entry).abs();
            let candidate = entry + 1.5 * r1_dist;
            candidate.max(levels.r2).max(entry)
        }
        Signal::Hold => entry, // no stop suggested for hold; return entry as a noop
    }
}

/// Compute dollar risk per share and suggested position size given max_dollar_risk.
/// - risk_per_share = |entry - stop_loss|; if zero or NaN, returns zero size.
/// - position_size = floor(max_dollar_risk / risk_per_share)
pub fn position_size_from_risk(entry: f64, stop_loss: f64, max_dollar_risk: f64) -> u64 {
    let risk_per_share = (entry - stop_loss).abs();
    if !risk_per_share.is_finite() || risk_per_share <= 0.0 || !max_dollar_risk.is_finite() || max_dollar_risk <= 0.0 {
        return 0;
    }
    (max_dollar_risk / risk_per_share).floor() as u64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_levels_and_signal_buy() {
        // synthetic candle: high=110, low=90, close=95
        let levels = golden_ratio_levels(110.0, 90.0, 95.0);
        // basic invariants
        assert!(levels.r2 > levels.r1);
        assert!(levels.s2 < levels.s1);
        // price well below s1 should produce Buy
        let price = levels.s1 - 1.0;
        assert_eq!(generate_signal(price, &levels), Signal::Buy);
    }

    #[test]
    fn test_levels_and_signal_sell() {
        let levels = golden_ratio_levels(200.0, 180.0, 190.0);
        let price = levels.r1 + 0.5;
        assert_eq!(generate_signal(price, &levels), Signal::Sell);
    }

    #[test]
    fn test_position_size() {
        let entry = 100.0;
        let stop = 95.0;
        let max_risk = 500.0; // dollars
        let size = position_size_from_risk(entry, stop, max_risk);
        // risk per share = 5 -> size should be 100
        assert_eq!(size, 100);
    }

    #[test]
    fn test_suggested_stop_loss_buy() {
        let levels = golden_ratio_levels(150.0, 100.0, 120.0);
        let entry = 118.0;
        let stop = suggested_stop_loss(entry, Signal::Buy, &levels);
        // stop must be <= entry
        assert!(stop <= entry);
    }

    #[test]
    fn test_suggested_stop_loss_sell() {
        let levels = golden_ratio_levels(150.0, 100.0, 130.0);
        let entry = 132.0;
        let stop = suggested_stop_loss(entry, Signal::Sell, &levels);
        // stop must be >= entry
        assert!(stop >= entry);
    }
}