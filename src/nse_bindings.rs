use pyo3::prelude::*;
use pyo3::types::PyDict;

#[pyfunction]
fn get_quote(py: Python, symbol: &str) -> PyResult<f64> {
    let nse = py.import("nsepython")?;
    let quote: f64 = nse.get_call_attr("get_quote")?.call1((symbol,))?.extract()?;
    Ok(quote)
}

#[pyfunction]
fn get_historical(py: Python, symbol: &str, start: &str, end: &str) -> PyResult<String> {
    let nse = py.import("nsepython")?;
    let df: PyObject = nse.get_call_attr("get_history")?.call1((symbol, start, end))?;
    let json: String = df.getattr(py, "to_json")?.call0()?.extract()?;
    Ok(json)
}

#[pyfunction]
fn get_option_chain(py: Python, symbol: &str) -> PyResult<String> {
    let nse = py.import("nsepython")?;
    let df: PyObject = nse.get_call_attr("get_option_chain")?.call1((symbol,))?;
    let json: String = df.getattr(py, "to_json")?.call0()?.extract()?;
    Ok(json)
}

#[pyfunction]
fn get_index_data(py: Python, index: &str) -> PyResult<f64> {
    let nse = py.import("nsepython")?;
    let value: f64 = nse.get_call_attr("get_index_quote")?.call1((index,))?.extract()?;
    Ok(value)
}

#[pymodule]
fn nse_bindings(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_quote, m)?)?;
    m.add_function(wrap_pyfunction!(get_historical, m)?)?;
    m.add_function(wrap_pyfunction!(get_option_chain, m)?)?;
    m.add_function(wrap_pyfunction!(get_index_data, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::prepare_freethreaded_python;

    #[test]
    fn test_get_quote() {
        prepare_freethreaded_python();
        Python::with_gil(|py| {
            let func = wrap_pyfunction!(get_quote)(py).unwrap();
            let res: f64 = func.call1((py, "RELIANCE")).unwrap().extract().unwrap();
            assert!(res > 0.0);
        });
    }
}