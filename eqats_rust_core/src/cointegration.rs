use std::os::raw::{c_double, c_int};

#[no_mangle]
pub extern "C" fn rust_calculate_spread_zscore(
    p1: *const c_double,
    p2: *const c_double,
    hedge_ratio: c_double,
    len: c_int,
    out_zscore: *mut c_double,
) -> c_int {
    if p1.is_null() || p2.is_null() || out_zscore.is_null() || len <= 1 || hedge_ratio == 0.0 {
        return -1;
    }

    let s1 = unsafe { std::slice::from_raw_parts(p1, len as usize) };
    let s2 = unsafe { std::slice::from_raw_parts(p2, len as usize) };

    let mut spreads = vec![0.0; len as usize];
    let mut sum = 0.0;

    for i in 0..len as usize {
        spreads[i] = s1[i] - hedge_ratio * s2[i];
        sum += spreads[i];
    }

    let mean = sum / (len as f64);
    let var_sum: f64 = spreads.iter().map(|s| (s - mean).powi(2)).sum();
    let std_dev = (var_sum / (len as f64)).sqrt();

    let last_spread = spreads[len as usize - 1];
    let zscore = if std_dev > 1e-8 {
        (last_spread - mean) / std_dev
    } else {
        0.0
    };

    unsafe {
        *out_zscore = zscore;
    }

    0
}
