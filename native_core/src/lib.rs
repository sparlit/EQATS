use pyo3::prelude::*;
use pyo3::types::PyModule;
use rayon::prelude::*;

#[pyfunction]
fn compute_heavy_indicators_parallel(data: Vec<f64>) -> PyResult<Vec<f64>> {
    // Rayon automatically distributes tasks over hardware cores.
    // Because the GIL is completely missing, there is zero contention with Python.
    let results: Vec<f64> = data.par_iter()
        .map(|&val| {
            // High-throughput calculation loop
            val.sin().cos() * 42.0 
        })
        .collect();

    Ok(results)
}

/// Main module definition exposed to the Python 3.13 free-threaded binary
#[pymodule]
fn native_core(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_heavy_indicators_parallel, m)?)?;
    
    // =========================================================================
    // CRUCIAL: Declare to Python 3.13 that this module is Free-Threaded Safe.
    // Without this specific registration slot, Python will silently turn the GIL 
    // back on when 'import native_core' is parsed!
    // =========================================================================
    #[cfg(Py_GIL_DISABLED)]
    {
        m.add_module_builtins_slot(pyo3::ffi::Py_MOD_GIL_NOT_USED)?;
    }

    Ok(())
}
