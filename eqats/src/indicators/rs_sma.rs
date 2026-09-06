use pyo3::prelude::*;

/// Compute simple moving average.
#[pyfunction]
fn sma(values: Vec<f64>, window: usize) -> Vec<f64> {
    if window == 0 || values.len() < window {
        return vec![];
    }
    let mut result = Vec::with_capacity(values.len() - window + 1);
    let mut sum: f64 = values.iter().take(window).sum();
    result.push(sum / window as f64);
    for i in window..values.len() {
        sum += values[i] - values[i - window];
        result.push(sum / window as f64);
    }
    result
}

/// A Python module implemented in Rust.
#[pymodule]
fn eqats_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sma, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sma() {
        let v = vec![1.0, 2.0, 3.0, 4.0, 5.0];
        assert_eq!(sma(v, 3), vec![2.0, 3.0, 4.0]);
    }
}
