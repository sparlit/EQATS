use pyo3::prelude::*
use pyo3::types::PyModule;

/// Plots a chart using pytvlwcharts from a pandas DataFrame.
#[pyfunction]
fn plot_chart(py: Python, df: &PyBound<'_, PyAny>) -> PyResult<()> {
    // Import the pytvlwcharts module
    let pytvlwcharts = PyModule::import_bound(py, "pytvlwcharts")?;
    // Create a new chart instance
    let chart = pytvlwcharts.getattr("Chart")?.call0()?;
    // Load the DataFrame into the chart
    chart.call_method1("load", (df,))?;
    // Show the chart (works in Jupyter/Colab)
    let show = chart.getattr("show")?;
    show.call0()?;
    Ok(())
}

/// Define the Python module implemented in Rust.
#[pymodule]
fn eqats_charts(_py: Python, m: &PyBound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(plot_chart, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::prelude::*;

    #[test]
    fn test_module_import() {
        Python::with_gil(|py| {
            let module = PyModule::import_bound(py, "eqats_charts").expect("eqats_charts module should be importable");
            let func = module.getattr("plot_chart").expect("plot_chart function should exist");
            assert!(func.is_callable());
        });
    }
}