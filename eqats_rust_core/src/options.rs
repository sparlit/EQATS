use std::os::raw::{c_double, c_int};

#[no_mangle]
pub extern "C" fn rust_calculate_gex_profile(
    spot: c_double,
    strikes: *const c_double,
    gammas: *const c_double,
    open_interest: *const c_double,
    len: c_int,
    out_net_gex: *mut c_double,
) -> c_int {
    if strikes.is_null()
        || gammas.is_null()
        || open_interest.is_null()
        || out_net_gex.is_null()
        || len <= 0
        || spot <= 0.0
    {
        return -1;
    }

    let k = unsafe { std::slice::from_raw_parts(strikes, len as usize) };
    let g = unsafe { std::slice::from_raw_parts(gammas, len as usize) };
    let oi = unsafe { std::slice::from_raw_parts(open_interest, len as usize) };

    let mut net_gex = 0.0;
    for i in 0..len as usize {
        let dollar_gamma = g[i] * oi[i] * 100.0 * spot * spot * 0.01;
        if k[i] >= spot {
            net_gex += dollar_gamma;
        } else {
            net_gex -= dollar_gamma;
        }
    }

    unsafe {
        *out_net_gex = net_gex;
    }

    0
}
