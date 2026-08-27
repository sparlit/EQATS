use std::os::raw::{c_double, c_int};

#[no_mangle]
pub extern "C" fn rust_run_backtest_simulation(
    prices: *const c_double,
    len: c_int,
    initial_balance: c_double,
    out_total_profit: *mut c_double,
    out_win_rate: *mut c_double,
) -> c_int {
    if prices.is_null() || len <= 2 || initial_balance <= 0.0 || out_total_profit.is_null() || out_win_rate.is_null() {
        return -1;
    }

    let px = unsafe { std::slice::from_raw_parts(prices, len as usize) };
    let mut balance = initial_balance;
    let mut trades = 0;
    let mut wins = 0;

    for i in 1..len as usize {
        let diff = px[i] - px[i - 1];
        trades += 1;
        if diff > 0.0 {
            wins += 1;
            balance += diff * 100.0;
        } else {
            balance += diff * 100.0;
        }
    }

    let win_rate = if trades > 0 { (wins as f64 / trades as f64) * 100.0 } else { 0.0 };
    let total_profit = balance - initial_balance;

    unsafe {
        *out_total_profit = total_profit;
        *out_win_rate = win_rate;
    }

    0
}
