use std::os::raw::{c_double, c_int};

/// Structure representing a Bar input array for high-throughput Rust matching.
#[repr(C)]
pub struct RustBar {
    pub timestamp: c_double,
    pub open: c_double,
    pub high: c_double,
    pub low: c_double,
    pub close: c_double,
    pub volume: c_double,
}

/// Structure representing order fill result returned to caller.
#[repr(C)]
pub struct RustOrderFill {
    pub fill_price: c_double,
    pub filled_qty: c_double,
    pub commission: c_double,
    pub is_filled: c_int,
}

/// Direct C-ABI function to process a batch of market/limit orders against a single bar with dynamic ATR slippage
/// and tick size rounding.
#[no_mangle]
pub extern "C" fn rust_rqalpha_process_bar_orders(
    _bar_open: c_double,
    _bar_high: c_double,
    _bar_low: c_double,
    bar_close: c_double,
    atr_slippage: c_double,
    tick_size: c_double,
    is_buy: c_int,
    quantity: c_double,
    _price: c_double,
    commission_rate: c_double,
    out_fill: *mut RustOrderFill,
) -> c_int {
    if out_fill.is_null() || quantity <= 0.0 || bar_close <= 0.0 {
        return -1;
    }

    let raw_fill_price = if is_buy != 0 {
        bar_close + atr_slippage
    } else {
        bar_close - atr_slippage
    };

    let rounded_fill_price = if tick_size > 0.0 {
        let num_ticks = (raw_fill_price / tick_size).round();
        num_ticks * tick_size
    } else {
        raw_fill_price
    };

    let cost = rounded_fill_price * quantity;
    let commission = cost * commission_rate;

    unsafe {
        (*out_fill).fill_price = rounded_fill_price;
        (*out_fill).filled_qty = quantity;
        (*out_fill).commission = commission;
        (*out_fill).is_filled = 1;
    }

    0
}

/// Fast batch processing of N bars for vectorized RQAlpha backtest equity curve calculation.
#[no_mangle]
pub extern "C" fn rust_rqalpha_vectorized_portfolio_update(
    closes: *const c_double,
    len: c_int,
    initial_cash: c_double,
    position_qty: c_double,
    avg_entry_price: c_double,
    out_final_equity: *mut c_double,
    out_max_drawdown: *mut c_double,
) -> c_int {
    if closes.is_null() || len <= 0 || initial_cash <= 0.0 || out_final_equity.is_null() || out_max_drawdown.is_null() {
        return -1;
    }

    let close_slice = unsafe { std::slice::from_raw_parts(closes, len as usize) };
    let mut peak_equity = initial_cash;
    let mut max_drawdown = 0.0;
    let mut current_equity = initial_cash;

    for &close in close_slice {
        let unrealized = (close - avg_entry_price) * position_qty;
        current_equity = initial_cash + unrealized;
        if current_equity > peak_equity {
            peak_equity = current_equity;
        }
        let dd = if peak_equity > 0.0 {
            (peak_equity - current_equity) / peak_equity
        } else {
            0.0
        };
        if dd > max_drawdown {
            max_drawdown = dd;
        }
    }

    unsafe {
        *out_final_equity = current_equity;
        *out_max_drawdown = max_drawdown;
    }

    0
}
