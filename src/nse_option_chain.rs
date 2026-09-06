use pyo3::prelude::*;
use reqwest::blocking::Client;
use serde_json::Value;
use std::error::Error;

#[pyfunction]
fn fetch_option_chain(symbol: &str) -> PyResult<Value> {
    let url = format!("https://www.nseindia.com/api/option-chain-indices?symbol={}", symbol);
    let client = Client::builder()
        .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        .build()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to build client: {}", e)))?;
    let resp = client.get(&url)
        .header("Accept", "application/json")
        .header("Accept-Language", "en-US,en;q=0.9")
        .header("Referer", "https://www.nseindia.com/option-chain")
        .send()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Request failed: {}", e)))?;
    if !resp.status().is_success() {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(format!("HTTP error: {}", resp.status())));
    }
    let data: Value = resp.json().map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("JSON parse error: {}", e)))?;
    Ok(data)
}

#[pymodule]
fn nse_option_chain(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(fetch_option_chain, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_url_formation() {
        let s = "NIFTY";
        let url = format!("https://www.nseindia.com/api/option-chain-indices?symbol={}", s);
        assert_eq!(url, "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY");
    }
}