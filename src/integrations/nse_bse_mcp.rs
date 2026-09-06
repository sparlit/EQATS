// Integration of nse-bse-mcp into eqats is infeasible as a library because the
// project provides only a Windows GUI executable and does not expose a public
// API or documented MCP bindings. The MCP protocol implementation is internal
// and not documented, preventing reliable client creation without reverse-
// engineering. This module provides a placeholder that returns an error when
// attempted to be used.

use std::error::Error;
use std::fmt;

#[derive(Debug)]
pub struct NseBseMcpError;

impl fmt::Display for NseBseMcpError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "nse-bse-mcp integration not available")
    }
}

impl Error for NseBseMcpError {}

/// Attempt to create a client for the nse-bse-mcp MCP server.
// Always returns an error because no client implementation is possible.
pub fn nse_bse_mcp_client() -> Result<NseBseMcpClient, Box<dyn Error>> {
    Err(Box::new(NseBseMcpError))
}

/// Placeholder client struct.
pub struct NseBseMcpClient;

impl NseBseMcpClient {
    /// Dummy method that would fetch data.
    pub fn fetch_data(&self) -> Result<(), Box<dyn Error>> {
        Err(Box::new(NseBseMcpError))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_client_returns_error() {
        assert!(nse_bse_mcp_client().is_err());
        let client = NseBseMcpClient;
        assert!(client.fetch_data().is_err());
    }
}
