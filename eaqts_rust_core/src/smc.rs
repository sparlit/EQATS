use std::os::raw::{c_double, c_int};

#[no_mangle]
pub extern "C" fn rust_detect_smc_fvg(
    highs: *const c_double,
    lows: *const c_double,
    len: c_int,
    out_fvg_count: *mut c_int,
) -> c_int {
    if highs.is_null() || lows.is_null() || len < 3 || out_fvg_count.is_null() {
        return -1;
    }

    let h = unsafe { std::slice::from_raw_parts(highs, len as usize) };
    let l = unsafe { std::slice::from_raw_parts(lows, len as usize) };

    let mut count = 0;
    for i in 2..len as usize {
        // Bullish FVG: Low of candle i > High of candle i-2
        if l[i] > h[i - 2] {
            count += 1;
        }
        // Bearish FVG: High of candle i < Low of candle i-2
        if h[i] < l[i - 2] {
            count += 1;
        }
    }

    unsafe {
        *out_fvg_count = count;
    }

    0
}
