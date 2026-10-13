use hyperliquid_rust_sdk::{AssetPosition, Error};
use rustc_hash::FxHasher;
use std::collections::{HashMap, HashSet};
use std::future::Future;
use std::hash::BuildHasherDefault;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{Mutex, Semaphore, mpsc::Sender};

use crate::wallet::MarginSnapshot;
use crate::{AdoptionInfo, OpenPositionLocal, Side, TradeOrigin, Wallet, roundf};

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Copy, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum MarginAllocation {
    Alloc(f64), //percentage of available margin
    Amount(f64),
}

pub type MarginMap = HashMap<String, f64, BuildHasherDefault<FxHasher>>;

#[derive(Clone, Copy, Debug)]
pub struct ChainPosition {
    pub local: OpenPositionLocal,
    pub leverage: usize,
    pub is_cross: bool,
    pub reserve: f64,
    pub external_adjustment: f64,
}

impl ChainPosition {
    pub fn parse(
        position: &hyperliquid_rust_sdk::PositionData,
        time: u64,
    ) -> Result<Option<Self>, Error> {
        let number = |label: &str, raw: &str| -> Result<f64, Error> {
            raw.parse::<f64>()
                .ok()
                .filter(|v| v.is_finite())
                .ok_or_else(|| Error::Custom(format!("invalid {label} for {}", position.coin)))
        };
        let size = number("position size", &position.szi)?;
        if size == 0.0 {
            return Ok(None);
        }
        let entry = number("entry price", position.entry_px.as_deref().unwrap_or(""))?;
        let margin = number("position margin", &position.margin_used)?;
        let upnl = number("unrealized PnL", &position.unrealized_pnl)?;
        let funding = number("cumulative funding", &position.cum_funding.since_open)?;
        let lev = position.leverage.value as usize;
        if entry <= 0.0 || margin < 0.0 || lev == 0 {
            return Err(Error::Custom(format!(
                "invalid position for {}",
                position.coin
            )));
        }
        let is_cross = match position.leverage.type_string.as_str() {
            "cross" => true,
            "isolated" => false,
            other => return Err(Error::Custom(format!("unsupported margin mode: {other}"))),
        };
        // Match wallet::position_margin_adjustment, including its funding convention.
        let external_adjustment = margin - upnl + funding;
        let reserve = external_adjustment
            .max(entry * size.abs() / lev as f64)
            .max(0.0);
        if !reserve.is_finite() || !external_adjustment.is_finite() {
            return Err(Error::InvalidMarginAmount);
        }
        Ok(Some(Self {
            local: OpenPositionLocal {
                open_time: None,
                size: size.abs(),
                entry_px: entry,
                side: if size > 0.0 { Side::Long } else { Side::Short },
                fees: 0.0,
                funding: 0.0,
                realised_pnl: 0.0,
                fill_type: None,
                origin: Some(TradeOrigin::Manual),
                adoption: Some(AdoptionInfo {
                    time,
                    unrealized_pnl: upnl,
                    funding_since_open: funding,
                }),
                closed_size: 0.0,
                closed_value: 0.0,
                close_origin: None,
            },
            leverage: lev,
            is_cross,
            reserve,
            external_adjustment,
        }))
    }
}

#[derive(Clone, Copy, Debug)]
pub struct MarketBootstrap {
    pub margin: f64,
    pub position: Option<ChainPosition>,
    pub snapshot_time: u64,
}
const MAX_CONCURRENT_MARGIN_SYNCS: usize = 8;
const MAX_MARGIN_SYNC_RETRIES: usize = 3;
const MARGIN_SYNC_TIMEOUT_SECS: u64 = 15;
static MARGIN_SYNC_LIMIT: Semaphore = Semaphore::const_new(MAX_CONCURRENT_MARGIN_SYNCS);

pub struct MarginBook {
    user: Arc<Wallet>,
    map: MarginMap,
    positions: HashMap<String, ChainPosition>,
    pub total_on_chain: f64,
    last_sync: Option<Instant>,
    sync_reset_tx: Option<Sender<()>>,
    version: u64,
}

struct MarginSyncRequest {
    user: Arc<Wallet>,
    bot_assets: HashSet<String>,
    version: u64,
}

impl MarginBook {
    pub fn new(user: Arc<Wallet>, sync_reset_tx: Option<Sender<()>>) -> Self {
        Self {
            user,
            map: HashMap::default(),
            positions: HashMap::new(),
            total_on_chain: f64::from_bits(1),
            last_sync: None,
            sync_reset_tx,
            version: 0,
        }
    }

    pub async fn sync_shared(book: &Arc<Mutex<Self>>) -> Result<Vec<AssetPosition>, Error> {
        for _ in 0..MAX_MARGIN_SYNC_RETRIES {
            let request = {
                let book = book.lock().await;
                book.sync_request()
            };

            let snapshot = Self::fetch_sync(&request).await?;
            let positions = parsed_positions(&snapshot, &request.bot_assets)?;

            let mut book = book.lock().await;
            if book.version == request.version {
                book.apply_sync(snapshot.total, positions);
                return Ok(snapshot.positions);
            }
        }

        Err(Error::Custom(
            "margin book changed while syncing; retry later".to_string(),
        ))
    }

    /// Reclassify the asset and reserve its entire budget in a single commit.
    pub async fn add_market_shared(
        book: &Arc<Mutex<Self>>,
        asset: &str,
        allocation: MarginAllocation,
    ) -> Result<MarketBootstrap, Error> {
        for _ in 0..MAX_MARGIN_SYNC_RETRIES {
            let mut request = {
                let book = book.lock().await;
                if book.map.contains_key(asset) {
                    return Err(Error::Custom(format!(
                        "{asset} market is already allocated"
                    )));
                }
                book.sync_request()
            };
            request.bot_assets.insert(asset.to_string());
            let snapshot = Self::fetch_sync(&request).await?;
            snapshot.ensure_no_orders(asset)?;
            let positions = parsed_positions(&snapshot, &request.bot_assets)?;
            let position = positions.get(asset).copied();
            let snapshot_time = snapshot.time_for(asset)?;
            let mut book = book.lock().await;
            if book.version != request.version {
                continue;
            }
            let used = used_with_positions(&book.map, &positions);
            let margin = resolve_allocation(allocation, snapshot.total - used)?;
            validate_position_budget(asset, margin, position)?;
            book.map.insert(asset.to_string(), margin);
            book.apply_sync(snapshot.total, positions);
            return Ok(MarketBootstrap {
                margin,
                position,
                snapshot_time,
            });
        }
        Err(Error::Custom(
            "margin book changed while adding market; retry later".into(),
        ))
    }

    /// Paused markets use a fresh snapshot before accepting strategy orders again.
    pub async fn resume_market_shared(
        book: &Arc<Mutex<Self>>,
        asset: &str,
    ) -> Result<MarketBootstrap, Error> {
        for _ in 0..MAX_MARGIN_SYNC_RETRIES {
            let request = book.lock().await.sync_request();
            let snapshot = Self::fetch_sync(&request).await?;
            snapshot.ensure_no_orders(asset)?;
            let positions = parsed_positions(&snapshot, &request.bot_assets)?;
            let position = positions.get(asset).copied();
            let snapshot_time = snapshot.time_for(asset)?;
            let mut book = book.lock().await;
            if book.version != request.version {
                continue;
            }
            let margin = *book
                .map
                .get(asset)
                .ok_or_else(|| Error::Custom(format!("{asset} market doesn't exist")))?;
            // Existing exposure can still be reduced when the account is underfunded.
            book.apply_sync(snapshot.total, positions);
            return Ok(MarketBootstrap {
                margin,
                position,
                snapshot_time,
            });
        }
        Err(Error::Custom(
            "margin book changed while resuming; retry later".into(),
        ))
    }

    pub async fn sync_total_if_stale_shared(
        book: &Arc<Mutex<Self>>,
        max_age: Duration,
    ) -> Result<f64, Error> {
        let fresh_total = {
            let book = book.lock().await;
            book.last_sync
                .is_some_and(|last_sync| last_sync.elapsed() < max_age)
                .then(|| book.available_total())
        };

        if let Some(total) = fresh_total {
            return Ok(total);
        }

        Self::sync_shared(book).await?;

        let book = book.lock().await;
        Ok(book.available_total())
    }

    pub async fn update_asset_shared(
        book: &Arc<Mutex<Self>>,
        update: AssetMargin,
    ) -> Result<f64, Error> {
        let (asset, requested_margin) = update;
        if !is_valid_margin_value(requested_margin) {
            return Err(Error::InvalidMarginAmount);
        }

        {
            let book = book.lock().await;
            if !book.map.contains_key(&asset) {
                return Err(Error::Custom(format!("{} market doesn't exist", asset)));
            }
        }

        Self::sync_shared(book).await?;

        let mut book = book.lock().await;
        let Some(current_margin) = book.map.get(&asset).copied() else {
            return Err(Error::Custom(format!("{} market doesn't exist", asset)));
        };
        let current_reserve = book.positions.get(&asset).map_or(0.0, |p| p.reserve);
        let free = book.free() + current_margin.max(current_reserve);
        validate_position_budget(
            &asset,
            requested_margin,
            book.positions.get(&asset).copied(),
        )?;

        if requested_margin > free {
            return Err(Error::InsufficientFreeMargin(roundf!(free, 2)));
        }

        book.map.insert(asset, requested_margin);
        book.version = book.version.saturating_add(1);
        book.reset_sync_timer();

        Ok(requested_margin)
    }

    fn reset_sync_timer(&self) {
        if let Some(tx) = &self.sync_reset_tx {
            let _ = tx.try_send(());
        }
    }

    fn sync_request(&self) -> MarginSyncRequest {
        MarginSyncRequest {
            user: Arc::clone(&self.user),
            bot_assets: self.map.keys().cloned().collect(),
            version: self.version,
        }
    }

    async fn fetch_sync(request: &MarginSyncRequest) -> Result<MarginSnapshot, Error> {
        let _permit = MARGIN_SYNC_LIMIT
            .acquire()
            .await
            .map_err(|_| Error::Custom("margin sync limiter closed".to_string()))?;

        margin_sync_timeout(
            Duration::from_secs(MARGIN_SYNC_TIMEOUT_SECS),
            request.user.margin_snapshot(&request.bot_assets),
        )
        .await
    }

    fn apply_sync(&mut self, total_on_chain: f64, positions: HashMap<String, ChainPosition>) {
        self.total_on_chain = total_on_chain;
        self.positions = positions;
        self.version = self.version.saturating_add(1);
        self.last_sync = Some(Instant::now());
        self.reset_sync_timer();
    }

    fn available_total(&self) -> f64 {
        self.total_on_chain - self.used()
    }

    pub fn allocate_from_current(
        &mut self,
        asset: String,
        alloc: MarginAllocation,
    ) -> Result<f64, Error> {
        if self.map.contains_key(&asset) {
            return Err(Error::Custom(format!(
                "{asset} market is already allocated"
            )));
        }
        let margin = resolve_allocation(alloc, self.free())?;
        self.map.insert(asset, margin);
        self.version = self.version.saturating_add(1);
        self.reset_sync_timer();
        Ok(margin)
    }

    pub fn remove(&mut self, asset: &str) {
        if self.map.remove(asset).is_some() {
            if let Some(position) = self.positions.remove(asset) {
                self.total_on_chain -= position.external_adjustment;
            }
            self.last_sync = None;
            self.version = self.version.saturating_add(1);
            self.reset_sync_timer();
        }
    }

    pub fn is_empty(&self) -> bool {
        self.map.is_empty()
    }

    pub fn used(&self) -> f64 {
        used_with_positions(&self.map, &self.positions)
    }

    pub fn free(&self) -> f64 {
        self.total_on_chain - self.used()
    }

    pub fn reset(&mut self) {
        self.map.clear();
        self.positions.clear();
        self.last_sync = None;
        self.version = self.version.saturating_add(1);
        self.reset_sync_timer();
    }
}

fn parsed_positions(
    snapshot: &MarginSnapshot,
    assets: &HashSet<String>,
) -> Result<HashMap<String, ChainPosition>, Error> {
    let mut positions = HashMap::new();
    for position in &snapshot.positions {
        let asset = &position.position.coin;
        if assets.contains(asset) {
            if let Some(parsed) =
                ChainPosition::parse(&position.position, snapshot.time_for(asset)?)?
            {
                positions.insert(asset.clone(), parsed);
            }
        }
    }
    Ok(positions)
}

fn used_with_positions(budgets: &MarginMap, positions: &HashMap<String, ChainPosition>) -> f64 {
    budgets
        .iter()
        .map(|(asset, budget)| budget.max(positions.get(asset).map_or(0.0, |p| p.reserve)))
        .sum()
}

fn validate_position_budget(
    asset: &str,
    budget: f64,
    position: Option<ChainPosition>,
) -> Result<(), Error> {
    if let Some(position) = position {
        if budget + 1e-8 < position.reserve {
            return Err(Error::Custom(format!(
                "{asset} has an open position: total market budget must be at least ${:.2} (including existing margin)",
                position.reserve
            )));
        }
    }
    Ok(())
}

fn resolve_allocation(alloc: MarginAllocation, free: f64) -> Result<f64, Error> {
    let margin = match alloc {
        MarginAllocation::Alloc(fraction) if is_valid_margin_value(fraction) && fraction <= 1.0 => {
            free * fraction
        }
        MarginAllocation::Amount(amount) if is_valid_margin_value(amount) => amount,
        _ => return Err(Error::InvalidMarginAmount),
    };
    if !is_valid_margin_value(margin) || margin > free + 1e-8 {
        return Err(Error::InsufficientFreeMargin(roundf!(free.max(0.0), 2)));
    }
    Ok(margin)
}

pub type AssetMargin = (String, f64);

fn is_valid_margin_value(value: f64) -> bool {
    value.is_finite() && value > 0.0
}

async fn margin_sync_timeout<T, F>(duration: Duration, fut: F) -> Result<T, Error>
where
    F: Future<Output = Result<T, Error>>,
{
    tokio::time::timeout(duration, fut)
        .await
        .map_err(|_| Error::Custom("margin sync timed out".to_string()))?
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::{MockExchange, account, position};

    #[tokio::test]
    async fn adoption_reclassifies_margin_once_and_removal_restores_external_reservation() {
        let exchange =
            MockExchange::new(account(vec![position("10", "100", "298")], "1098", 1000)).await;
        let book = Arc::new(Mutex::new(MarginBook::new(exchange.wallet().await, None)));
        MarginBook::sync_shared(&book).await.unwrap();
        assert_eq!(book.lock().await.free(), 800.0);
        let adopted = MarginBook::add_market_shared(&book, "BTC", MarginAllocation::Amount(300.0))
            .await
            .unwrap();
        assert_eq!(
            adopted.position.unwrap().local.origin,
            Some(TradeOrigin::Manual)
        );
        assert_eq!(adopted.position.unwrap().leverage, 5);
        assert_eq!(adopted.snapshot_time, 1000);
        assert_eq!(book.lock().await.free(), 700.0);
        MarginBook::sync_shared(&book).await.unwrap();
        assert_eq!(book.lock().await.free(), 700.0);
        assert!(
            MarginBook::add_market_shared(&book, "BTC", MarginAllocation::Amount(300.0))
                .await
                .is_err()
        );
        assert!(
            MarginBook::update_asset_shared(&book, ("BTC".into(), 199.0))
                .await
                .is_err()
        );
        assert_eq!(book.lock().await.free(), 700.0);
        book.lock().await.remove("BTC");
        // This must already be conservative even if the subsequent HTTP sync fails.
        assert_eq!(book.lock().await.free(), 800.0);
        MarginBook::sync_shared(&book).await.unwrap();
        assert_eq!(book.lock().await.free(), 800.0);
    }

    #[tokio::test]
    async fn percent_budget_includes_existing_margin_and_other_market_budgets() {
        let exchange =
            MockExchange::new(account(vec![position("-10", "100", "298")], "1098", 1000)).await;
        let book = Arc::new(Mutex::new(MarginBook::new(exchange.wallet().await, None)));
        MarginBook::add_market_shared(&book, "ETH", MarginAllocation::Amount(100.0))
            .await
            .unwrap();
        let bootstrap = MarginBook::add_market_shared(&book, "BTC", MarginAllocation::Alloc(0.5))
            .await
            .unwrap();
        assert_eq!(bootstrap.margin, 450.0);
        assert_eq!(bootstrap.position.unwrap().local.side, Side::Short);
        assert_eq!(book.lock().await.free(), 450.0);
        *exchange.account.lock().await = account(vec![], "1120", 2000);
        MarginBook::sync_shared(&book).await.unwrap();
        assert_eq!(book.lock().await.free(), 570.0);
    }

    #[tokio::test]
    async fn concurrent_additions_retry_against_the_committed_asset_set() {
        let exchange =
            MockExchange::new(account(vec![position("10", "100", "298")], "1098", 1000)).await;
        let book = Arc::new(Mutex::new(MarginBook::new(exchange.wallet().await, None)));
        let (btc, eth) = tokio::join!(
            MarginBook::add_market_shared(&book, "BTC", MarginAllocation::Amount(300.0)),
            MarginBook::add_market_shared(&book, "ETH", MarginAllocation::Amount(100.0)),
        );
        btc.unwrap();
        eth.unwrap();
        assert_eq!(book.lock().await.free(), 600.0);
        MarginBook::sync_shared(&book).await.unwrap();
        assert_eq!(book.lock().await.free(), 600.0);
        let resume = MarginBook::resume_market_shared(&book, "BTC")
            .await
            .unwrap();
        assert_eq!(resume.position.unwrap().local.size, 10.0);
        assert_eq!(book.lock().await.free(), 600.0);
    }

    #[tokio::test]
    async fn invalid_or_underfunded_adoption_leaves_book_unchanged() {
        let exchange =
            MockExchange::new(account(vec![position("10", "-50", "148")], "948", 1000)).await;
        let book = Arc::new(Mutex::new(MarginBook::new(exchange.wallet().await, None)));
        MarginBook::sync_shared(&book).await.unwrap();
        let before = book.lock().await.free();
        for allocation in [
            MarginAllocation::Amount(199.0),
            MarginAllocation::Amount(1001.0),
            MarginAllocation::Amount(f64::NAN),
            MarginAllocation::Alloc(1.1),
        ] {
            assert!(
                MarginBook::add_market_shared(&book, "BTC", allocation)
                    .await
                    .is_err()
            );
            assert!(book.lock().await.is_empty());
            assert_eq!(book.lock().await.free(), before);
        }
        exchange.account.lock().await["assetPositions"][0]["position"]["entryPx"] =
            serde_json::Value::Null;
        assert!(
            MarginBook::add_market_shared(&book, "BTC", MarginAllocation::Amount(300.0))
                .await
                .is_err()
        );
        assert!(book.lock().await.is_empty());
        assert_eq!(book.lock().await.free(), before);
    }

    #[tokio::test]
    async fn outstanding_protective_orders_block_adoption_without_changing_book() {
        let exchange =
            MockExchange::new(account(vec![position("10", "100", "298")], "1098", 1000)).await;
        *exchange.orders.lock().await = serde_json::json!([{
            "coin":"BTC","side":"A","limitPx":"110","sz":"10","oid":42,"timestamp":900,
            "origSz":"10","isPositionTpsl":true,"isTrigger":true,"reduceOnly":true,
            "triggerCondition":"Price above 110","triggerPx":"110","orderType":"Take Profit Market",
            "children":[],"tif":null,"cloid":null
        }]);
        let book = Arc::new(Mutex::new(MarginBook::new(exchange.wallet().await, None)));
        let error = MarginBook::add_market_shared(&book, "BTC", MarginAllocation::Amount(300.0))
            .await
            .unwrap_err();
        assert!(error.to_string().contains("outstanding orders"), "{error}");
        assert!(book.lock().await.is_empty());
    }

    #[test]
    fn cross_positions_and_extra_isolated_collateral_keep_their_mode_and_reserve() {
        let mut raw = position("10", "100", "498");
        let parsed = ChainPosition::parse(
            &serde_json::from_value(raw["position"].clone()).unwrap(),
            1000,
        )
        .unwrap()
        .unwrap();
        assert!(!parsed.is_cross);
        assert_eq!(parsed.reserve, 400.0);
        raw["position"]["leverage"]["type"] = serde_json::json!("cross");
        let parsed = ChainPosition::parse(
            &serde_json::from_value(raw["position"].clone()).unwrap(),
            1000,
        )
        .unwrap()
        .unwrap();
        assert!(parsed.is_cross);
        assert_eq!(parsed.reserve, 400.0);
    }

    #[tokio::test]
    async fn margin_sync_timeout_reports_stalled_future() {
        let result = margin_sync_timeout(
            Duration::from_millis(1),
            std::future::pending::<Result<(), Error>>(),
        )
        .await;

        assert!(matches!(result, Err(Error::Custom(message)) if message.contains("timed out")));
    }

    #[test]
    fn margin_value_validation_rejects_non_finite_values() {
        assert!(is_valid_margin_value(1.0));
        assert!(!is_valid_margin_value(0.0));
        assert!(!is_valid_margin_value(f64::NAN));
        assert!(!is_valid_margin_value(f64::INFINITY));
    }
}