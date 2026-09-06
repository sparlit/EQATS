use pyo3::prelude::*;
use pyo3::types::PyDict;

/// A Python-exposed wrapper around Fenix brokers.
#[pyclass]
struct FenixBroker {
    broker: PyObject,
}

#[pymethods]
impl FenixBroker {
    #[new]
    fn py_new(py: Python, broker_name: &str, creds: Option<&PyDict>) -> PyResult<Self> {
        let fenix = py.import("fenix")?;
        let broker_class = fenix.getattr(broker_name)?;
        let instance = if let Some(creds) = creds {
            broker_class.call1((creds,))?
        } else {
            broker_class.call0()?
        };
        Ok(FenixBroker { broker: instance })
    }

    fn authenticate(&self, py: Python, params: Option<&PyDict>) -> PyResult<()> {
        let meth = self.broker.getattr(py, "authenticate")?;
        if let Some(params) = params {
            meth.call1((params,))?;
        } else {
            meth.call0()?;
        }
        Ok(())
    }

    fn load_fno_tokens(&self, py: Python) -> PyResult<(PyObject, PyObject)> {
        let meth = self.broker.getattr(py, "load_fno_tokens")?;
        let res = meth.call0()?;
        let tuple = py.extract::<(PyObject, PyObject)>(res)?;
        Ok(tuple)
    }

    fn market_order(
        &self,
        py: Python,
        token_dict: &PyDict,
        side: &PyObject,
        product: &PyObject,
        quantity: i32,
        unique_id: &str,
    ) -> PyResult<PyObject> {
        let meth = self.broker.getattr(py, "market_order")?;
        meth.call1((
            token_dict,
            side,
            product,
            quantity,
            unique_id,
        ))
    }

    fn fetch_net_positions(&self, py: Python) -> PyResult<PyObject> {
        let meth = self.broker.getattr(py, "fetch_net_positions")?;
        meth.call0()
    }
}

#[pymodule]
fn fenix_eqats(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<FenixBroker>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::Python;

    #[test]
    fn test_module_can_be_imported() {
        Python::with_gil(|py| {
            let module = PyModule::import(py, "fenix_eqats").expect("Module import failed");
            let _: PyObject = module.getattr("FenixBroker").expect("Class not found");
        });
    }
}
