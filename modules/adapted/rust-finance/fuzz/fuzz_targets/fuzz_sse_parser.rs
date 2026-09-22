#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // Attempt to parse arbitrary bytes as SSE (Server-Sent Events) data
    if let Ok(s) = std::str::from_utf8(data) {
        // Parse SSE format: "data: {...}\n\n"
        for line in s.lines() {
            if let Some(json_str) = line.strip_prefix("data: ") {
                let _ = serde_json::from_str::<serde_json::Value>(json_str);
            }
        }
    }
});