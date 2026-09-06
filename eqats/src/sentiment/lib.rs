use once_cell::sync::Lazy;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

static PIPELINE: Lazy<PyObject> = Lazy::new(|| {
    Python::with_gil(|py| {
        let transformers = PyModule::import(py, "transformers").expect("transformers module not found");
        let pipeline = transformers.getattr("pipeline").expect("pipeline not found");
        let sentiment_pipeline = pipeline
            .call1((
                "sentiment-analysis",
                PyDict::new(py),
            ))
            .expect("failed to create pipeline")
            .call_method(py, "__getitem__", (0,), None)
            .expect("failed to get sentiment-analysis pipeline");
        sentiment_pipeline.into_py(py)
    })
});

#[pyfunction]
fn get_sentiment(text: &str) -> PyResult<f32> {
    Python::with_gil(|py| {
        let result: PyObject = PIPELINE
            .call1(py, (text,))
            .expect("pipeline call failed");
        let list: &PyList = result.downcast_bound::<PyList>(py).expect("expected list");
        let first: &PyDict = list.get_item(0).expect("first item").downcast_bound::<PyDict>(py).expect("expected dict");
        let label: String = first.get_item("label").expect("label").extract::<String>(py).expect("label str");
        let score: f32 = first.get_item("score").expect("score").extract::<f32>(py).expect("score f32");
        let sentiment = match label.as_str() {
            "Positive" => score,
            "Negative" => -score,
            "Neutral" => 0.0,
            _ => 0.0,
        };
        Ok(sentiment)
    })
}

#[pymodule]
fn eqats_sentiment(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_sentiment, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::prelude::*;
    #[test]
    fn test_get_sentiment() {
        Python::with_gil(|py| {
            let s = get_sentiment("Market is up today.").expect("failed");
            assert!(s >= -1.0 && s <= 1.0);
        });
    }
}