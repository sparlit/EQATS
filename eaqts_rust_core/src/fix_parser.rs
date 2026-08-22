use std::ffi::CStr;
use std::os::raw::{c_char, c_int};

#[no_mangle]
pub extern "C" fn rust_parse_fix_message(
    raw_msg: *const c_char,
    out_tag_count: *mut c_int,
) -> c_int {
    if raw_msg.is_null() || out_tag_count.is_null() {
        return -1;
    }

    let c_str = unsafe { CStr::from_ptr(raw_msg) };
    let msg_str = match c_str.to_str() {
        Ok(s) => s,
        Err(_) => return -1,
    };

    let tag_count = msg_str.split('\x01').filter(|s| s.contains('=')).count();

    unsafe {
        *out_tag_count = tag_count as c_int;
    }

    0
}
