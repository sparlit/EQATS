use pyo3::prelude::*;
use pyo3::types::{PyDict, PyModule};
use pyo3::wrap_pyfunction;

#[pyfunction]
fn get_history_py(symbol: String, start: String, end: String, index: bool) -> PyResult<PyObject> {
    Python::with_gil(|py| {
        let nsepy = PyModule::import(py, "nsepy")?;
        let get_history = nsepy.getattr("get_history")?;
        let args = (symbol, start, end);
        let kwargs = PyDict::new(py);
        kwargs.set_item("index", index)?;
        let result = get_history.call((args, kwargs))?;
        Ok(result.to_object(py))
    })
}

#[pymodule]
fn nsepy_bindings(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_history_py, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::prepare_freethreaded_python;

    #[test]
    fn test_module_loads() {
        Python::with_gil(|py| {
            let module = PyModule::import(py, "nsepy_bindings").expect("Failed to import nsepy_bindings");
            let _: pyo3::PyObject = module.getattr("get_history_py").expect("get_history_py missing");
        });
    }
}