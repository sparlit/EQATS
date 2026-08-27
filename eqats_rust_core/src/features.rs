use std::os::raw::{c_double, c_int};

#[no_mangle]
pub extern "C" fn rust_extract_feature_matrix(
    prices: *const c_double,
    len: c_int,
    out_mean: *mut c_double,
    out_std: *mut c_double,
) -> c_int {
    if prices.is_null() || len <= 1 || out_mean.is_null() || out_std.is_null() {
        return -1;
    }

    let px = unsafe { std::slice::from_raw_parts(prices, len as usize) };
    let sum: f64 = px.iter().sum();
    let mean = sum / (len as f64);

    let var_sum: f64 = px.iter().map(|p| (p - mean).powi(2)).sum();
    let std_dev = (var_sum / (len as f64)).sqrt();

    unsafe {
        *out_mean = mean;
        *out_std = std_dev;
    }

    0
}
