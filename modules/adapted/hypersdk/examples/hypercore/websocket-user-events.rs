//! Subscribe to advanced user WebSocket feeds.
//!
//! This example demonstrates the user-oriented streams that are useful for
//! execution engines and account-state services:
//!
//! - `userEvents`
//! - `userTwapSliceFills`
//! - `userTwapHistory`
//! - `activeAssetData`
//! - `webData3`
//! - `userHistoricalOrders`
//!
//! # Usage
//!
//! ```bash
//! cargo run --example websocket-user-events -- --user 0xYourAddress --coin BTC
//! ```

use clap::Parser;
use futures::StreamExt;
use hypersdk::{
    Address,
    hypercore::{
        self,
        types::{Incoming, Subscription, TwapStatus, UserEvent},
        ws::Event,
    },
};

#[derive(Parser, Debug)]
#[command(author, version, about = "Subscribe to advanced user WS feeds")]
struct Args {
    /// User address to subscribe for
    #[arg(long)]
    user: Address,
    /// Asset symbol for activeAssetData feed (perps only)
    #[arg(long, default_value = "BTC")]
    coin: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let _ = simple_logger::init_with_level(log::Level::Info);
    let args = Args::parse();

    let client = hypercore::mainnet();

    let role = client.user_role(args.user).await?;

    let user = match role {
        hypercore::UserRole::SubAccount { master } => Some(master),
        _ => None,
    }
    .unwrap_or(args.user);

    let mut ws = client.websocket();
    ws.subscribe(Subscription::UserEvents { user });
    ws.subscribe(Subscription::UserTwapSliceFills { user });
    ws.subscribe(Subscription::UserTwapHistory { user });
    ws.subscribe(Subscription::ActiveAssetData {
        user,
        coin: args.coin.clone(),
    });
    ws.subscribe(Subscription::WebData3 { user });
    ws.subscribe(Subscription::UserHistoricalOrders { user });
    ws.subscribe(Subscription::ClearinghouseState { user, dex: None });
    ws.subscribe(Subscription::AllDexsClearinghouseState { user });
    ws.subscribe(Subscription::OpenOrders { user, dex: None });
    ws.subscribe(Subscription::SpotState {
        user,
        is_portfolio_margin: None,
    });

    log::info!(
        "Subscribed for user={} coin={}. Waiting for events...",
        args.user,
        args.coin
    );

    while let Some(event) = ws.next().await {
        match event {
            Event::Connected => println!("Connected"),
            Event::Disconnected => println!("Disconnected, reconnecting..."),
            Event::Message(msg) => match msg {
                Incoming::UserEvents(user_event) => match user_event {
                    UserEvent::Fills { fills } => {
                        println!("userEvents.fills: {} fill(s)", fills.len());
                    }
                    UserEvent::Funding { funding } => {
                        println!(
                            "userEvents.funding: {} usdc={} rate={}",
                            funding.coin, funding.usdc, funding.funding_rate
                        );
                    }
                    UserEvent::Liquidation { liquidation } => {
                        println!(
                            "userEvents.liquidation: lid={} liquidated_user={} ntl_pos={}",
                            liquidation.lid,
                            liquidation.liquidated_user,
                            liquidation.liquidated_ntl_pos
                        );
                    }
                    UserEvent::NonUserCancel { non_user_cancel } => {
                        println!(
                            "userEvents.nonUserCancel: {} cancel(s)",
                            non_user_cancel.len()
                        );
                    }
                    UserEvent::Unknown(raw) => {
                        println!("userEvents.unknown: {}", raw);
                    }
                },
                Incoming::UserTwapSliceFills(payload) => {
                    println!(
                        "userTwapSliceFills: snapshot={:?} slices={}",
                        payload.is_snapshot,
                        payload.twap_slice_fills.len()
                    );
                }
                Incoming::UserTwapHistory(payload) => {
                    for item in payload.history {
                        let status = match item.status.status {
                            TwapStatus::Activated => "activated",
                            TwapStatus::Terminated => "terminated",
                            TwapStatus::Finished => "finished",
                            TwapStatus::Error => "error",
                            TwapStatus::Unknown => "unknown",
                        };
                        println!(
                            "userTwapHistory: {} {} sz={} executed={} status={} ({})",
                            item.state.coin,
                            item.state.side,
                            item.state.sz,
                            item.state.executed_sz,
                            status,
                            item.status.description.as_deref().unwrap_or("")
                        );
                    }
                }
                Incoming::ActiveAssetData(data) => {
                    let max_sz = data
                        .max_trade_szs_pair()
                        .map(|(long, short)| format!("long={}, short={}", long, short))
                        .unwrap_or_else(|| "n/a".to_string());
                    let avail = data
                        .available_to_trade_pair()
                        .map(|(long, short)| format!("long={}, short={}", long, short))
                        .unwrap_or_else(|| "n/a".to_string());
                    println!(
                        "activeAssetData: {} lev={} {} maxTradeSzs=[{}] availableToTrade=[{}]",
                        data.coin, data.leverage.leverage_type, data.leverage.value, max_sz, avail
                    );
                }
                Incoming::WebData3 { data: payload } => {
                    let keys = payload.as_object().map(|m| m.len()).unwrap_or(0);
                    println!("webData3: object_keys={}", keys);
                }
                Incoming::UserHistoricalOrders {
                    is_snapshot,
                    order_history,
                    ..
                } => {
                    println!(
                        "userHistoricalOrders: snapshot={} n={}",
                        is_snapshot,
                        order_history.len()
                    );
                }
                Incoming::ClearinghouseState {
                    dex,
                    user,
                    clearinghouse_state,
                } => {
                    println!(
                        "clearingHouseState: user={} dex={:?} clearinghouse_state={:?}",
                        user, dex, clearinghouse_state
                    );
                }
                Incoming::AllDexsClearinghouseState {
                    user,
                    clearinghouse_states,
                } => {
                    println!(
                        "allDexsClearinghouseState: user={} clearinghouse_states={}",
                        user,
                        clearinghouse_states.len()
                    );
                }
                Incoming::SpotState { user, spot_state } => {
                    println!("SpotState: user={} spot_state={:?}", user, spot_state);
                }
                Incoming::OpenOrders { dex, user, orders } => {
                    println!(
                        "openOrders: user={} dex={:?} orders={:?}",
                        user, dex, orders,
                    );
                }
                Incoming::SubscriptionResponse(resp) => {
                    println!("subscriptionResponse: {:?}", resp);
                }
                Incoming::Ping | Incoming::Pong => {}
                _ => {}
            },
        }
    }

    Ok(())
}