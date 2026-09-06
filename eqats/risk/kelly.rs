use num_traits::{Float, FromPrimitive};

/// Compute the Kelly fraction f* = (bp - q) / b where b = net odds, p = win probability, q = 1-p.
/// Returns fraction clamped to [0, 1]. If b <= 0 or p outside [0,1], returns 0.
pub fn kelly_fraction<F: Float + FromPrimitive>(b: F, p: F) -> F {
    let zero = F::zero();
    let one = F::one();
    if b <= zero || p < zero || p > one {
        return zero;
    }
    let q = one - p;
    let numerator = b * p - q;
    if numerator <= zero {
        zero
    } else {
        let f = numerator / b;
        if f > one {
            one
        } else {
            f
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use approx::assert_relative_eq;

    #[test]
    fn test_kelly_basic() {
        // b = 1 (even odds), p = 0.6 => f = (1*0.6 - 0.4)/1 = 0.2
        let f = kelly_fraction(1.0, 0.6);
        assert_relative_eq!(f, 0.2, epsilon = 1e-12);
    }

    #[test]
    fn test_kelly_no_edge() {
        // b = 1, p = 0.5 => f = 0
        let f = kelly_fraction(1.0, 0.5);
        assert_relative_eq!(f, 0.0, epsilon = 1e-12);
    }

    #[test]
    fn test_kelly_clamp() {
        // b = 0.5, p = 0.9 => f = (0.5*0.9 - 0.1)/0.5 = (0.45-0.1)/0.5 = 0.35/0.5 = 0.7
        let f = kelly_fraction(0.5, 0.9);
        assert_relative_eq!(f, 0.7, epsilon = 1e-12);
        // edge case: b small, p high => f >1 should clamp to 1
        let f2 = kelly_fraction(0.1, 0.9); // (0.1*0.9 -0.1)/0.1 = (0.09-0.1)/0.1 = -0.01/0.1 = -0.1 => 0
        assert_relative_eq!(f2, 0.0, epsilon = 1e-12);
    }

    #[test]
    fn test_kelly_invalid_inputs() {
        assert_eq!(kelly_fraction(-1.0, 0.6), 0.0);
        assert_eq!(kelly_fraction(1.0, -0.1), 0.0);
        assert_eq!(kelly_fraction(1.0, 1.5), 0.0);
    }
}

use pyo3::prelude::*;

#[pyfunction]
fn kelly_fraction_py(b: f64, p: f64) -> f64 {
    kelly_fraction(b, p)
}

#[pymodule]
fn eqats_risk(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(kelly_fraction_py, m)?)?;
    Ok(())
}