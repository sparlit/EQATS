use std::os::raw::{c_double, c_int};

#[no_mangle]
pub extern "C" fn rust_optimize_portfolio_weights(
    returns: *const c_double,
    assets_count: c_int,
    out_weights: *mut c_double,
) -> c_int {
    if returns.is_null() || out_weights.is_null() || assets_count <= 0 {
        return -1;
    }

    let equal_weight = 1.0 / (assets_count as f64);
    let out_slice = unsafe { std::slice::from_raw_parts_mut(out_weights, assets_count as usize) };

    for i in 0..assets_count as usize {
        out_slice[i] = equal_weight;
    }

    0
}
