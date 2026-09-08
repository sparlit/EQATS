#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // Attempt to parse arbitrary bytes as a JSON market event
    if let Ok(s) = std::str::from_utf8(data) {
        // Try parsing as a generic JSON value (mimics market event deserialization)
        if let Ok(value) = serde_json::from_str::<serde_json::Value>(s) {
            // Attempt to extract common market event fields
            let _ = value.get("symbol");
            let _ = value.get("price");
            let _ = value.get("timestamp");
            let _ = value.get("volume");
            let _ = value.get("exchange");
        }
    }
});