use anyhow::Result;
use tracing::info;

pub struct DexterAnalyst {
    // API logic to come
}

impl Default for DexterAnalyst {
    fn default() -> Self {
        Self::new()
    }
}

impl DexterAnalyst {
    pub fn new() -> Self {
        Self {}
    }

    pub async fn run(&self) -> Result<()> {
        info!("Dexter Analyst started - waiting for data...");
        // This will listen for MarketEvents and periodically ping Claude
        Ok(())
    }
}