//! Send USDC to another Hyperliquid account.
//!
//! Demonstrates how to transfer USD (USDC) from your exchange balance to a specified
//! destination address using `send_usdc` with a timestamp-based nonce.

use std::time::{SystemTime, UNIX_EPOCH};

use clap::Parser;
use hypersdk::{
    Address,
    hypercore::{self as hypercore, types::UsdSend},
};
use rust_decimal::Decimal;

use crate::credentials::Credentials;

mod credentials;

#[derive(Parser, Debug, derive_more::Deref)]
#[command(author, version, about, long_about = None)]
struct Cli {
    #[deref]
    #[command(flatten)]
    common: Credentials,
    /// Address to send the transfer to.
    #[arg(short, long)]
    to: Address,
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

    println!("From {} to {}", signer.address(), args.to);

    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    client
        .send_usdc(
            &signer,
            UsdSend {
                destination: args.to,
                amount: args.amount,
                time: nonce,
            },
            nonce,
        )
        .await?;

    Ok(())
}