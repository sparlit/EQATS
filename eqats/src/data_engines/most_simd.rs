//! SIMD-accelerated market data preprocessing for eqats.
//! This module adapts the portable SIMD core from wangrunji0408/most
//! to provide low-latency order book aggregation.

use std::simd::{f32x8, SimdElement};

/// Compute volume-weighted average price (VWAP) for a batch of orders
/// using SIMD vectors. Processes up to 8 prices/volumes per iteration.

/// # Arguments
/// * prices - slice of trade prices (f32)
/// * volumes - slice of trade volumes (f32), same length as prices

/// Returns the VWAP, or 0.0 if no data.
pub fn vwap_simd(prices: &[f32], volumes: &[f32]) -> f32 {
    assert_eq!(prices.len(), volumes.len(), "price and volume slices must match length");
    let mut sum_price_vol = f32x8::splat(0.0);
    let mut sum_vol = f32x8::splat(0.0);
    let chunk = 8;
    let mut i = 0;
    while i + chunk <= prices.len() {
        let p = f32x8::from_slice(&prices[i..i+chunk]);
        let v = f32x8::from_slice(&volumes[i..i+chunk]);
        sum_price_vol = sum_price_vol + p * v;
        sum_vol = sum_vol + v;
        i += chunk;
    }
    // scalar tail
    while i < prices.len() {
        sum_price_vol[0] += prices[i] * volumes[i];
        sum_vol[0] += volumes[i];
        i += 1;
    }
    let total_price_vol = sum_price_vol.reduce_sum();
    let total_vol = sum_vol.reduce_sum();
    if total_vol == 0.0 { 0.0 } else { total_price_vol / total_vol }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_vwap_simd() {
        let prices = [10.0, 10.5, 11.0, 11.5, 12.0];
        let volumes = [100.0, 200.0, 150.0, 50.0, 300.0];
        let expected = (10.0*100.0 + 10.5*200.0 + 11.0*150.0 + 11.5*50.0 + 12.0*300.0)
            / (100.0+200.0+150.0+50.0+300.0);
        let got = vwap_simd(&prices, &volumes);
        assert!((got - expected).abs() < 1e-6);
    }
}