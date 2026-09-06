use pyo3::prelude::*
use pyo3::types::PyDict;

#[pyfunction]
fn get_history(
    py: Python,
    symbol: &str,
    start_year: i32,
    start_month: i32,
    start_day: i32,
    end_year: i32,
    end_month: i32,
    end_day: i32,
    index: bool,
    derivatives: bool,
) -> PyResult<PyObject> {
    let nsepy = py.import("nsepy")?;
    let get_history_fn = nsepy.getattr("get_history")?;
    let datetime = py.import("datetime")?;
    let date_cls = datetime.getattr("date")?;
    let start_date = date_cls.call1((start_year, start_month, start_day))?;
    let end_date = date_cls.call1((end_year, end_month, end_day))?;
    let kwargs = PyDict::new(py);
    kwargs.set_item("symbol", symbol)?;
    kwargs.set_item("start", start_date)?;
    kwargs.set_item("end", end_date)?;
    kwargs.set_item("index", index)?;
    kwargs.set_item("derivatives", derivatives)?;
    let result = get_history_fn.call((), Some(kwargs))?;
    Ok(result)
}

#[pymodule]
fn eqats_nsepy(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_history, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::prelude::*;
    use pyo3::Python;

    #[test]
    fn test_get_history() {
        Python::with_gil(|py| {
            let df = get_history(py, "SBIN", 2015, 1, 1, 2015, 1, 10, false, false).expect("Failed to fetch history");
            // Ensure we got a DataFrame-like object with a Close attribute
            let close = df.getattr(py, "Close").expect("DataFrame missing Close column");
            assert!(!close.is_none(py));
        });
    }
}