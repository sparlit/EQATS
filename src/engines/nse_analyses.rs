// src/engines/nse_analyses.rs
//! NSE Analyses weighting and normalization utilities.
//! This module adapts the weighting factor & normalization procedures
//! from the NSE_Analyses repository for use in eqats.

use std::cmp::{PartialOrd};

/// Compute raw weights inversely proportional to stratum size.
/// Returns a vector of weights that sum to 1.0.
pub fn compute_weights(strata_counts: &[usize]) -> Vec<f64> {
    if strata_counts.is_empty() {
        return Vec::new();
    }
    let total: usize = strata_counts.iter().sum();
    let total_f = total as f64;
    let n_strata = strata_counts.len() as f64;
    let mut weights: Vec<f64> = strata_counts
        .iter()
        .map(|&c| {
            if c == 0 {
                0.0
            } else {
                total_f / (c as f64 * n_strata)
            }
        })
        .collect();
    // Normalize so they sum to 1
    let sum: f64 = weights.iter().sum();
    if sum > 0.0 {
        weights.iter().map(|w| w / sum).collect()
    } else {
        vec![0.0; weights.len()]
    }
}

/// Apply weights to values (element‑wise multiplication).
pub fn apply_weights(values: &[f64], weights: &[f64]) -> Vec<f64> {
    assert_eq!(values.len(), weights.len());
    values
        .iter()
        .zip(weights.iter())
        .map(|(v, w)| v * w)
        .collect()
}

/// Normalize a slice of scores to the range [0, 1].
/// If all scores are identical, returns a vector of zeros.
pub fn normalize(scores: &[f64]) -> Vec<f64> {
    if scores.is_empty() {
        return Vec::new();
    }
    let min = scores.iter().cloned().fold(f64::INFINITY, f64::min);
    let max = scores.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    if (max - min).abs() < f64::EPSILON {
        return vec![0.0; scores.len()];
    }
    scores
        .iter()
        .map(|s| (s - min) / (max - min))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_weights_sums_to_one() {
        let counts = vec![10, 20, 30, 40];
        let w = compute_weights(&counts);
        let sum: f64 = w.iter().sum();
        assert!((sum - 1.0).abs() < 1e-9);
    }

    #[test]
    fn test_apply_weights() {
        let values = vec![1.0, 2.0, 3.0];
        let weights = vec![0.2, 0.3, 0.5];
        let weighted = apply_weights(&values, &weights);
        assert_eq!(weighted, vec![0.2, 0.6, 1.5]);
    }

    #[test]
    fn test_normalize_bounds() {
        let scores = vec![-5.0, 0.0, 5.0];
        let norm = normalize(&scores);
        assert!((norm[0] - 0.0).abs() < 1e-9);
        assert!((norm[1] - 0.5).abs() < 1e-9);
        assert!((norm[2] - 1.0).abs() < 1e-9);
    }

    #[test]
    fn test_normalize_constant() {
        let scores = vec![7.0, 7.0, 7.0];
        let norm = normalize(&scores);
        assert!(norm.iter().all(|&v| v.abs() < 1e-9));
    }
}
