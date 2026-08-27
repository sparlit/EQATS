use std::os::raw::{c_double, c_int};

#[no_mangle]
pub extern "C" fn rust_calculate_twap_slices(
    total_volume: c_double,
    num_slices: c_int,
    out_slice_size: *mut c_double,
) -> c_int {
    if total_volume <= 0.0 || num_slices <= 0 || out_slice_size.is_null() {
        return -1;
    }

    unsafe {
        *out_slice_size = total_volume / (num_slices as f64);
    }

    0
}
