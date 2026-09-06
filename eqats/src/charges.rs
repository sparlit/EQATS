use pyo3::prelude::*;

/// Calculates charges based on trade value using the exact 0.69% rate.
#[pyfunction]
fn calculate_charges(trade_value: f64) -> f64 {
    (trade_value * 0.0069).max(0.0)
}

/// A Python module implemented in Rust.
#[pymodule]
fn eqats_charges(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(calculate_charges, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_charges() {
        assert_eq!(calculate_charges(10000.0), 69.0);
        assert_eq!(calculate_charges(0.0), 0.0);
        assert_eq!(calculate_charges(500.0), 3.45);
    }
}