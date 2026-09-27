//! Order management commands for placing and canceling orders.
//!
//! This module provides CLI commands for:
//! - Placing limit orders
//! - Placing market orders
//! - Canceling orders (by OID or CLOID)
//!
//! ## Asset Name Formats
//!
//! Assets are specified by name using the following conventions:
//! - `BTC` - BTC perpetual on Hyperliquid DEX
//! - `PURR/USDC` - PURR spot market
//! - `xyz:BTC` - BTC perpetual on the "xyz" HIP3 DEX

use alloy::primitives::B128;
use clap::{Args, Subcommand, ValueEnum};
use hypersdk::hypercore::{
    BatchCancel, BatchCancelCloid, BatchOrder, Cancel, CancelByCloid, Cloid, HttpClient,
    OrderGrouping, OrderRequest, OrderTypePlacement, TimeInForce,
    api::{Action, OkResponse},
};
use rust_decimal::Decimal;

use crate::action::ActionArgs;
use crate::utils::resolve_asset;

/// Order management commands.
#[derive(Subcommand)]
pub enum OrderCmd {
    /// Place a limit order
    Limit(LimitOrderCmd),
    /// Place a market order
    Market(MarketOrderCmd),
    /// Cancel an order by OID or CLOID
    Cancel(CancelOrderCmd),
}

impl OrderCmd {
    pub async fn run(self) -> anyhow::Result<()> {
        match self {
            Self::Limit(cmd) => cmd.run().await,
            Self::Market(cmd) => cmd.run().await,
            Self::Cancel(cmd) => cmd.run().await,
        }
    }
}

/// Order side (buy or sell).
#[derive(Clone, Copy, ValueEnum, derive_more::Display)]
pub enum Side {
    #[display("BUY")]
    Buy,
    #[display("SELL")]
    Sell,
}

impl Side {
    pub fn is_buy(&self) -> bool {
        matches!(self, Side::Buy)
    }
}

/// Time-in-force option for limit orders.
#[derive(Clone, Copy, ValueEnum, Default)]
pub enum Tif {
    /// Good Till Cancel - standard order that remains until filled or canceled
    #[default]
    Gtc,
    /// Add Liquidity Only - maker-only order, rejected if it would take
    Alo,
    /// Immediate or Cancel - fill immediately or cancel unfilled portion
    Ioc,
}

impl From<Tif> for TimeInForce {
    fn from(tif: Tif) -> Self {
        match tif {
            Tif::Gtc => TimeInForce::Gtc,
            Tif::Alo => TimeInForce::Alo,
            Tif::Ioc => TimeInForce::Ioc,
        }
    }
}

/// Place a limit order.
#[derive(Args, derive_more::Deref)]
pub struct LimitOrderCmd {
    #[deref]
    #[command(flatten)]
    pub signer: ActionArgs,

    /// Asset name. Formats:
    /// - "BTC" for BTC perpetual
    /// - "PURR/USDC" for PURR spot market
    /// - "xyz:BTC" for BTC perpetual on xyz HIP3 DEX
    #[arg(long)]
    pub asset: String,

    /// Order side (buy or sell)
    #[arg(long)]
    pub side: Side,

    /// Limit price
    #[arg(long)]
    pub price: Decimal,

    /// Order size
    #[arg(long)]
    pub size: Decimal,

    /// Reduce-only order (can only reduce existing position)
    #[arg(long, default_value = "false")]
    pub reduce_only: bool,

    /// Time-in-force (gtc, alo, ioc)
    #[arg(long, default_value = "gtc")]
    pub tif: Tif,

    /// Optional client order ID (hex string, 16 bytes)
    #[arg(long)]
    pub cloid: Option<String>,
}

impl LimitOrderCmd {
    pub async fn run(self) -> anyhow::Result<()> {
        let client = HttpClient::new(self.chain);

        let asset_index = resolve_asset(&client, &self.asset).await?;

        let cloid = parse_cloid(self.cloid.as_deref())?;

        println!(
            "Placing limit order for {} (index {})",
            self.asset, asset_index
        );
        println!("CLOID: 0x{}", hex::encode(cloid.as_slice()));

        let order = OrderRequest {
            asset: asset_index,
            is_buy: self.side.is_buy(),
            limit_px: self.price,
            sz: self.size,
            reduce_only: self.reduce_only,
            order_type: OrderTypePlacement::Limit {
                tif: self.tif.into(),
            },
            cloid,
        };

        let batch = BatchOrder {
            orders: vec![order],
            grouping: OrderGrouping::Na,
            builder: None,
        };

        let response = self
            .signer
            .execute(client, |_, _| Action::Order(batch))
            .await?;
        print_statuses(response, false)?;

        Ok(())
    }
}

/// Place a market order.
#[derive(Args, derive_more::Deref)]
pub struct MarketOrderCmd {
    #[deref]
    #[command(flatten)]
    pub signer: ActionArgs,

    /// Asset name. Formats:
    /// - "BTC" for BTC perpetual
    /// - "PURR/USDC" for PURR spot market
    /// - "xyz:BTC" for BTC perpetual on xyz HIP3 DEX
    #[arg(long)]
    pub asset: String,

    /// Order side (buy or sell)
    #[arg(long)]
    pub side: Side,

    /// Order size
    #[arg(long)]
    pub size: Decimal,

    /// Slippage price (worst acceptable price for the market order)
    #[arg(long)]
    pub slippage_price: Decimal,

    /// Reduce-only order (can only reduce existing position)
    #[arg(long, default_value = "false")]
    pub reduce_only: bool,

    /// Optional client order ID (hex string, 16 bytes)
    #[arg(long)]
    pub cloid: Option<String>,
}

impl MarketOrderCmd {
    pub async fn run(self) -> anyhow::Result<()> {
        let client = HttpClient::new(self.chain);

        let asset_index = resolve_asset(&client, &self.asset).await?;

        let cloid = parse_cloid(self.cloid.as_deref())?;

        println!(
            "Placing market order for {} (index {})",
            self.asset, asset_index
        );
        println!("CLOID: 0x{}", hex::encode(cloid.as_slice()));

        // Market orders use FrontendMarket TIF with a slippage price
        let order = OrderRequest {
            asset: asset_index,
            is_buy: self.side.is_buy(),
            limit_px: self.slippage_price,
            sz: self.size,
            reduce_only: self.reduce_only,
            order_type: OrderTypePlacement::Limit {
                tif: TimeInForce::FrontendMarket,
            },
            cloid,
        };

        let batch = BatchOrder {
            orders: vec![order],
            grouping: OrderGrouping::Na,
            builder: None,
        };

        let response = self
            .signer
            .execute(client, |_, _| Action::Order(batch))
            .await?;
        print_statuses(response, false)?;

        Ok(())
    }
}

/// Cancel an order by OID or CLOID.
///
/// Specify either `--oid` for exchange-assigned order ID or `--cloid` for client-assigned order ID.
#[derive(Args, derive_more::Deref)]
pub struct CancelOrderCmd {
    #[deref]
    #[command(flatten)]
    pub signer: ActionArgs,

    /// Asset name. Formats:
    /// - "BTC" for BTC perpetual
    /// - "PURR/USDC" for PURR spot market
    /// - "xyz:BTC" for BTC perpetual on xyz HIP3 DEX
    #[arg(long)]
    pub asset: String,

    /// Exchange-assigned order ID to cancel
    #[arg(long)]
    pub oid: Option<u64>,

    /// Client-assigned order ID to cancel (hex string, 16 bytes)
    #[arg(long)]
    pub cloid: Option<String>,
}

impl CancelOrderCmd {
    pub async fn run(self) -> anyhow::Result<()> {
        // Validate that exactly one of oid or cloid is provided
        match (&self.oid, &self.cloid) {
            (None, None) => anyhow::bail!("Must specify either --oid or --cloid"),
            (Some(_), Some(_)) => anyhow::bail!("Cannot specify both --oid and --cloid"),
            _ => {}
        }

        let client = HttpClient::new(self.chain);

        let asset_index = resolve_asset(&client, &self.asset).await?;

        let action = if let Some(cloid) = &self.cloid {
            let cloid_bytes = parse_cloid_required(cloid)?;
            println!("Canceling {} order with CLOID {}", self.asset, cloid);
            Action::CancelByCloid(BatchCancelCloid {
                cancels: vec![CancelByCloid {
                    asset: asset_index as u32,
                    cloid: cloid_bytes,
                }],
                fast: false,
            })
        } else {
            let oid = self.oid.expect("validated above");
            println!("Canceling {} order with OID {}", self.asset, oid);
            Action::Cancel(BatchCancel {
                cancels: vec![Cancel {
                    asset: asset_index,
                    oid,
                }],
                fast: false,
            })
        };
        let response = self.signer.execute(client, |_, _| action).await?;
        print_statuses(response, true)?;

        Ok(())
    }
}

/// Preserve the inner order/cancel result for both ordinary and multisig requests.
fn print_statuses(response: OkResponse, cancel: bool) -> anyhow::Result<()> {
    let statuses = match response {
        OkResponse::Order { statuses } if !cancel => statuses,
        OkResponse::Cancel { statuses } if cancel => statuses,
        other => anyhow::bail!("Unexpected response: {other:?}"),
    };
    anyhow::ensure!(!statuses.is_empty(), "No order statuses returned");
    for (i, status) in statuses.iter().enumerate() {
        println!(
            "  {} {}: {:?}",
            if cancel { "Cancel" } else { "Order" },
            i,
            status
        );
    }
    for status in &statuses {
        if let Some(error) = status.error() {
            anyhow::bail!(
                "{} failed: {error}",
                if cancel { "Cancel" } else { "Order" }
            );
        }
    }
    Ok(())
}

/// Parse an optional CLOID string into a B128.
/// If None is provided, generates a random CLOID.
fn parse_cloid(cloid: Option<&str>) -> anyhow::Result<Cloid> {
    match cloid {
        Some(s) => parse_cloid_required(s),
        None => Ok(B128::random()),
    }
}

/// Parse a required CLOID string into a B128.
fn parse_cloid_required(cloid: &str) -> anyhow::Result<B128> {
    cloid
        .parse()
        .map_err(|e| anyhow::anyhow!("Invalid CLOID: {}", e))
}

#[cfg(test)]
mod tests {
    use super::*;
    use hypersdk::hypercore::OrderResponseStatus;

    #[test]
    fn reports_inner_rejections_and_unexpected_responses_as_errors() {
        for cancel in [false, true] {
            let response = |statuses| {
                if cancel {
                    OkResponse::Cancel { statuses }
                } else {
                    OkResponse::Order { statuses }
                }
            };
            print_statuses(response(vec![OrderResponseStatus::Success]), cancel).unwrap();
            let error = print_statuses(
                response(vec![OrderResponseStatus::Error("rejected".into())]),
                cancel,
            )
            .unwrap_err();
            assert!(error.to_string().contains("rejected"));
            assert!(print_statuses(response(vec![]), cancel).is_err());
            assert!(print_statuses(OkResponse::Default, cancel).is_err());
        }
        assert!(
            print_statuses(
                OkResponse::Cancel {
                    statuses: vec![OrderResponseStatus::Success]
                },
                false,
            )
            .is_err()
        );
    }
}