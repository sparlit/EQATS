use pyo3::prelude::*;
use ndarray::{Array1};

#[pyfunction]
fn run_backtest(prices: Vec<f64>, signals: Vec<f64>, initial_capital: f64) -> PyResult<(f64, f64, f64)> {
    if prices.len() != signals.len() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "prices and signals must have same length",
        ));
    }
    if prices.is_empty() {
        return Ok((0.0, 0.0, 0.0));
    }
    let price_arr = Array1::from_vec(prices);
    let signal_arr = Array1::from_vec(signals);
    let price_shifted = price_arr.slice(s![..-1]);
    let price_next = price_arr.slice(s![1..]);
    let price_ret = (&price_next - &price_shifted) / &price_shifted;
    let signal_lag = signal_arr.slice(s![..-1]);
    let strat_ret = &signal_lag * &price_ret;
    let mut equity = vec![initial_capital];
    let mut cum = initial_capital;
    for r in strat_ret.iter() {
        cum *= 1.0 + r;
        equity.push(cum);
    }
    let total_return = equity.last().unwrap() / initial_capital - 1.0;
    let mean_ret = strat_ret.mean().unwrap_or(0.0);
    let std_ret = strat_ret.std(0.0);
    let sharpe = if std_ret > 0.0 { (mean_ret / std_ret) * (252.0f64).sqrt() } else { 0.0 };
    let mut max_dd = 0.0;
    let mut peak = equity[0];
    for &eq in equity.iter().skip(1) {
        if eq > peak { peak = eq; }
        let dd = (peak - eq) / peak;
        if dd > max_dd { max_dd = dd; }
    }
    Ok((total_return, sharpe, max_dd))
}

#[pymodule]
fn eqats_backtest(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_backtest, m)?)?;
    Ok(())
}