 //! NSE analysis utilities: weighting and normalization.
//!
//! This module provides functions to compute weighted averages and z-score normalization
//! of survey responses, adapted from the NSE_Analyses repository.

use ndarray::{Array1, Array2};

/// Compute weighted average of a 1D array.
///
/// # Arguments
/// * values - Survey response values.
/// * weights - Corresponding weights (must sum to 1 for proper weighting).
///
/// # Returns
/// Weighted average as f64.
pub fn weighted_average(values: &Array1<f64>, weights: &Array1<f64>) -> f64 {
    assert_eq!(values.len(), weights.len(), "Length mismatch");
    values.dot(weights)
}

/// Normalize a 1D array to z-scores (zero mean, unit variance).
///
/// # Arguments
/// * data - Input data.
///
/// # Returns
/// Normalized array.
pub fn z_score_normalize(data: &Array1<f64>) -> Array1<f64> {
    let mean = data.mean().expect("Cannot compute mean of empty array");
    let std = ((data.mapv(|x| (x - mean).powi(2))).mean()
        .expect("Cannot compute variance"))
        .sqrt();
    if std == 0.0 {
        data.mapv(|_| 0.0)
    } else {
        (data - mean) / std
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ndarray::arr1;

    #[test]
    fn test_weighted_average() {
        let values = arr1(&[10.0, 20.0, 30.0]);
        let weights = arr1(&[0.1, 0.3, 0.6]); // sums to 1.0
        let avg = weighted_average(&values, &weights);
        assert!((avg - 24.0).abs() < 1e-9);
    }

    #[test]
    fn test_z_score_normalize() {
        let data = arr1(&[1.0, 2.0, 3.0, 4.0, 5.0]);
        let norm = z_score_normalize(&data);
        let expected = arr1(&[-1.41421356, -0.70710678, 0.0, 0.70710678, 1.41421356]);
        for i in 0..norm.len() {
            assert!((norm[i] - expected[i]).abs() < 1e-6);
        }
    }
}