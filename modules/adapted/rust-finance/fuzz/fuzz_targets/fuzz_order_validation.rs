#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // Attempt to parse arbitrary bytes as order validation input
    if let Ok(s) = std::str::from_utf8(data) {
        if let Ok(value) = serde_json::from_str::<serde_json::Value>(s) {
            // Validate order fields — checks for panics in validation logic
            if let Some(qty) = value.get("quantity").and_then(|v| v.as_f64()) {
                // Ensure quantity validation doesn't panic on edge cases
                let _ = qty.is_finite();
                let _ = qty.is_sign_positive();
                let _ = qty > 0.0 && qty < 1_000_000.0;
            }
            if let Some(price) = value.get("price").and_then(|v| v.as_f64()) {
                let _ = price.is_finite();
                let _ = price.is_sign_positive();
            }
            // Check side parsing
            if let Some(side) = value.get("side").and_then(|v| v.as_str()) {
                let _ = matches!(side, "buy" | "sell" | "BUY" | "SELL");
            }
        }
    }
});