use pyo3::prelude::*;

/// Fetch NSE data for a given symbol and date range using jugaad_data.
/// Returns a pandas DataFrame as a Python object.
#[pyfunction]
fn fetch_nse_data(symbol: &str, start_date: &str, end_date: &str) -> PyResult<PyObject> {
    Python::with_gil(|py| {
        // Import jugaad_data
        let jugaad = PyModule::import(py, "jugaad_data")?;
        let nse = jugaad.getattr("nse")?;
        let hist = nse.getattr("symbol_history")?;
        let df: PyObject = hist.call1((symbol, start_date, end_date))?;
        Ok(df)
    })
}

/// A Python module implemented in Rust.
#[pymodule]
fn nse_fetcher(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(fetch_nse_data, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::prelude::*;

    #[test]
    fn test_fetch_nse_data() {
        Python::with_gil(|py| {
            let func = pyo3::wrap_pyfunction!(fetch_nse_data).unwrap(py);
            let result = func.call1(py, ("RELIANCE", "01-01-2024", "01-02-2024")).unwrap();
            assert!(!result.is_none(py));
        });
    }
}