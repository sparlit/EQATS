//! Transfer tokens from the exchange spot wallet to the EVM.
//!
//! Looks up a token by name and transfers the specified amount from the signer's spot
//! balance on the exchange to their corresponding EVM wallet address.

use std::time::{SystemTime, UNIX_EPOCH};

use clap::Parser;
use hypersdk::hypercore::{self as hypercore};
use rust_decimal::Decimal;

use crate::credentials::Credentials;

mod credentials;

#[derive(Parser, Debug, derive_more::Deref)]
#[command(author, version, about, long_about = None)]
struct Cli {
    #[deref]
    #[command(flatten)]
    common: Credentials,
    /// Token to transfer
    #[arg(short, long)]
    token: String,
    /// Amount to send
    #[arg(short, long)]
    amount: Decimal,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let _ = simple_logger::init_with_level(log::Level::Debug);

    let args = Cli::parse();
    let signer = args.get()?;

    let client = hypercore::mainnet();

    let tokens = client.spot_tokens().await?;
    let token = tokens
        .iter()
        .find(|token| token.name == args.token)
        .ok_or(anyhow::anyhow!("{} not found", args.token))?
        .clone();

    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    client
        .transfer_to_evm(&signer, token.clone(), args.amount, nonce)
        .await?;

    Ok(())
}