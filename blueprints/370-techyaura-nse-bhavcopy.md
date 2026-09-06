# NSE Bhavcopy Integration Blueprint

## Overview
The nse-bhavcopy repository is a Node.js module for downloading NSE bhavcopy files. Direct integration into a Rust-based project like eqats would require a Node.js runtime, which adds complexity and deployment overhead.

## Recommended Approach
1. **Subprocess Wrapper**: Expose the Node.js module as a CLI script and call it from Rust using std::process::Command.
2. **Native Reimplementation**: Rewrite the download logic in Rust using reqwest to fetch the same NSE archive URLs, eliminating the Node.js dependency.
3. **PyO3 Bridge (if Python needed)**: If Python bindings are required, create a PyO3 module that wraps either the subprocess call or the native Rust implementation.

## Data Flow
- User invokes NSEBhavcopy::download_day or download_month.
- The implementation (either subprocess or native) constructs the appropriate NSE URL based on date and format.
- The file is retrieved and optionally saved to a configured output directory.
- Raw bytes or extracted content are returned to the caller for further processing (e.g., feeding into signal generation).

## Risks & Mitigations
- **Node.js Version**: Ensure compatibility with the required Node.js version (v8+).
- **URL Changes**: Monitor NSE archive URL scheme; update the URL builder if needed.
- **Error Handling**: Propagate network and IO errors via Result; callers can implement retry logic.

## Future Work
- Provide async version using tokio.
- Add support for streaming large files directly to disk.
- Integrate with eqats' data lake for automatic cataloging and versioning.
