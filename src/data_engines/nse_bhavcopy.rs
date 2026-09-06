// Integration of nse-bhavcopy into eqats is infeasible as a direct Rust port because the original Node.js module relies on specific NSE endpoints and undocumented request patterns that may change without notice. Replicating this behavior would require reverse‑engineering and ongoing maintenance beyond the scope of this task. Instead, a minimal placeholder is provided that explains the limitation and returns an error when called.

use std::error::Error;

/// Attempts to download NSE bhavcopy for the given parameters.
/// Returns an error indicating that the integration is not implemented.
pub fn download_bhavcopy(_day: u32, _month: &str, _year: u32, _format: &str) -> Result<String, Box<dyn Error>> {
    Err("NSE bhavcopy download not implemented: Node.js module integration infeasible in Rust without external process or reverse‑engineered API.".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_download_returns_error() {
        let res = download_bhavcopy(10, "MAY", 2016, "json");
        assert!(res.is_err());
        assert_eq!(res.unwrap_err().to_string(), "NSE bhavcopy download not implemented: Node.js module integration infeasible in Rust without external process or reverse‑engineered API.");
    }
}
