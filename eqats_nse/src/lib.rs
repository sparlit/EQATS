use pyo3::prelude::*;

/// Fetch quote for a given NSE stock symbol.
#[pyfunction]
fn get_quote(py: Python, code: &str, all_data: bool) -> PyResult<PyObject> {
    let nse_module = py.import("nsetools")?;
    let nse_class = nse_module.getattr("Nse")?;
    let nse_instance = nse_class.call0()?;
    let quote = nse_instance.call_method1("get_quote", (code, all_data))?;
    Ok(quote)
}

/// A Python module implemented in Rust.
#[pymodule]
fn eqats_nse(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_quote, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::prelude::*;

    #[test]
    fn test_get_quote() {
        Python::with_gil(|py| {
            let result = get_quote(py, "INFY", false).expect("Failed to get quote");
            let dict = result.downcast::<PyDict>(py).expect("Result is not a dict");
            // Ensure we have at least one expected field
            let last_price = dict.get_item(py, "lastPrice").expect("Missing lastPrice field");
            assert!(!last_price.is_none());
        });
    }
}