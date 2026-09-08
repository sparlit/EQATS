#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // Attempt to parse arbitrary bytes as a TOML config
    if let Ok(s) = std::str::from_utf8(data) {
        let _ = toml::from_str::<toml::Value>(s);
    }
});