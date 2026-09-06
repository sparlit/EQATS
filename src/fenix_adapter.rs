use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Wrapper around fenix broker for eqats.
#[pyclass]
struct FenixBroker {
    broker: PyObject,
}

#[pymethods]
impl FenixBroker {
    #[new]
    fn new(broker_name: &str) -> PyResult<Self> {
        Python::with_gil(|py| {
            let fenix = py.import('fenix')?;
            let broker_class = fenix.getattr(broker_name)?;
            let broker_instance = broker_class.call0()?;
            Ok(FenixBroker { broker: broker_instance.into() })
        })
    }

    fn authenticate(&self, params: &PyDict) -> PyResult<()> {
        Python::with_gil(|py| {
            let meth = self.broker.getattr('authenticate')?;
            meth.call1(py, (params,))?;
            Ok(())
        })
    }

    fn market_order(&self, token_dict: &PyDict, quantity: i32, side: &PyObject, product: &PyObject, unique_id: &str) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let meth = self.broker.getattr('market_order')?;
            let args = (token_dict, quantity, side, product, unique_id);
            let result = meth.call1(py, args)?;
            Ok(result.into())
        })
    }

    fn limit_order(&self, token_dict: &PyDict, price: f64, quantity: i32, side: &PyObject, product: &PyObject, unique_id: &str) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let meth = self.broker.getattr('limit_order')?;
            let args = (token_dict, price, quantity, side, product, unique_id);
            let result = meth.call1(py, args)?;
            Ok(result.into())
        })
    }

    fn fetch_net_positions(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let meth = self.broker.getattr('fetch_net_positions')?;
            let result = meth.call0(py)?;
            Ok(result.into())
        })
    }

    fn fetch_holdings(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let meth = self.broker.getattr('fetch_holdings')?;
            let result = meth.call0(py)?;
            Ok(result.into())
        })
    }

    fn fetch_margin_limits(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let meth = self.broker.getattr('fetch_margin_limits')?;
            let result = meth.call0(py)?;
            Ok(result.into())
        })
    }

    fn fetch_profile(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let meth = self.broker.getattr('fetch_profile')?;
            let result = meth.call0(py)?;
            Ok(result.into())
        })
    }
}

#[pymodule]
fn fenix_adapter(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<FenixBroker>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::prepare_freethreaded_python;

    #[test]
    fn test_import_fenix() {
        Python::with_gil(|py| {
            let fenix = py.import('fenix').expect('fenix should be importable');
            let version: String = fenix.getattr('__version__').expect('has version').extract().expect('version str');
            assert!(!version.is_empty());
        });
    }
}
