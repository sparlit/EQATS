use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::Arc;

use flume::Receiver;
use log::warn;
use tokio::{
    sync::{
        Mutex,
        mpsc::{Sender, error::TrySendError},
    },
    time::{Duration, sleep, timeout},
};

use rustc_hash::FxHasher;
use std::hash::BuildHasherDefault;

use hyperliquid_rust_sdk::{
    AssetMeta, ClientCancelRequest, ClientLimit, ClientOrder, ClientOrderRequest, Error,
    ExchangeClient, ExchangeDataStatus, MarketOrderParams,
};

use super::*;
use crate::helper::exchange_client_with_timeout;
use crate::{BUILDER, MAX_DECIMALS, MarketCommand, PX_DECIMAL_ANOMALY, Wallet, roundf};

const MARKET_COMMAND_SEND_TIMEOUT_SECS: u64 = 5;

#[derive(Clone)]
struct SubmittedOrder {
    origin: TradeOrigin,
    strategy: Option<String>,
}

pub struct Executor {
    trade_rv: Receiver<ExecCommand>,
    market_tx: Sender<MarketCommand>,
    asset: AssetMeta,
    exchange_client: Arc<ExchangeClient>,
    wallet: Arc<Wallet>,
    strategy_name: String,
    submitted_orders: HashMap<u64, SubmittedOrder>,
    snapshot_time: u64,
    funding_time: u64,
    seen_fills: HashSet<u64>,
    fill_ids: VecDeque<u64>,
    manual_intervention_notified: bool,
    is_paused: bool,
    closing: bool,
    resting_orders: HashMap<u64, RestingOrderLocal, BuildHasherDefault<FxHasher>>,
    open_position: Arc<Mutex<Option<OpenPositionLocal>>>,
    decimals: Decimals,
}

impl Executor {
    const MAX_RETRIES: usize = 5;

    #[cfg(test)]
    pub(crate) async fn for_test(
        exchange: &crate::test_support::MockExchange,
        trade_rv: Receiver<ExecCommand>,
        market_tx: Sender<MarketCommand>,
        position: Option<OpenPositionLocal>,
    ) -> Self {
        let wallet = exchange.wallet().await;
        let asset = serde_json::from_value(
            serde_json::json!({"name":"BTC","szDecimals":4,"maxLeverage":50}),
        )
        .unwrap();
        let mut info = hyperliquid_rust_sdk::InfoClient::new(
            None,
            Some(hyperliquid_rust_sdk::BaseUrl::Localhost),
        )
        .await
        .unwrap();
        info.http_client.base_url = exchange.url.clone();
        let client = ExchangeClient {
            http_client: info.http_client,
            wallet: wallet.wallet.clone(),
            meta: serde_json::from_value(serde_json::json!({"universe":[]})).unwrap(),
            vault_address: None,
            coin_to_asset: HashMap::from([("BTC".into(), 0)]),
        };
        Self {
            trade_rv,
            market_tx,
            asset,
            exchange_client: Arc::new(client),
            wallet,
            strategy_name: "Original closer".into(),
            submitted_orders: HashMap::new(),
            snapshot_time: 1000,
            funding_time: 1000,
            seen_fills: HashSet::new(),
            fill_ids: VecDeque::new(),
            manual_intervention_notified: false,
            is_paused: false,
            closing: false,
            resting_orders: HashMap::default(),
            open_position: Arc::new(Mutex::new(position)),
            decimals: Decimals { sz: 4, px: 2 },
        }
    }

    pub async fn new(
        wallet: Arc<Wallet>,
        asset: AssetMeta,
        trade_rv: Receiver<ExecCommand>,
        market_tx: Sender<MarketCommand>,
        position: Option<OpenPositionLocal>,
        strategy_name: String,
        snapshot_time: u64,
    ) -> Result<Executor, Error> {
        let exchange_client = Arc::new(
            exchange_client_with_timeout("executor", wallet.wallet.clone(), wallet.url).await?,
        );

        let px_dec_fix = if PX_DECIMAL_ANOMALY.contains(&asset.name.as_str()) {
            2
        } else {
            1
        };
        let decimals = Decimals {
            sz: asset.sz_decimals,
            px: MAX_DECIMALS - asset.sz_decimals - px_dec_fix,
        };
        Ok(Executor {
            trade_rv,
            market_tx,
            asset,
            exchange_client,
            wallet,
            strategy_name,
            submitted_orders: HashMap::new(),
            snapshot_time,
            funding_time: snapshot_time,
            seen_fills: HashSet::new(),
            fill_ids: VecDeque::new(),
            manual_intervention_notified: false,
            is_paused: false,
            closing: false,
            resting_orders: HashMap::default(),
            open_position: Arc::new(Mutex::new(position)),
            decimals,
        })
    }

    pub(crate) fn set_trading_enabled(&mut self, enabled: bool) {
        self.is_paused = !enabled;
    }

    async fn with_position<F, R>(&self, f: F) -> R
    where
        F: FnOnce(&mut Option<OpenPositionLocal>) -> R,
    {
        let (r, position) = {
            let mut guard = self.open_position.lock().await;
            let r = f(&mut guard);
            (r, *guard)
        };
        self.update_market(SendUpdate::Position(position)).await;
        r
    }

    async fn open_trade(
        &mut self,
        order: HlOrder<'_>,
        intent: PositionOp,
        trigger: Option<TriggerKind>,
        origin: TradeOrigin,
    ) -> Result<RestingOrderLocal, Error> {
        let side = order.get_side();
        let limit_px = order.get_px();
        let size = order.get_sz();

        let status_res = match order {
            HlOrder::Market(market_order) if intent == PositionOp::Close => {
                let mid = self.wallet.mid_price(market_order.asset).await?;
                let request = reduce_only_market_order(market_order, mid, self.asset.sz_decimals)?;
                self.exchange_client
                    .order_with_builder(request, None, &BUILDER)
                    .await?
            }
            HlOrder::Market(market_order) => {
                self.exchange_client
                    .market_open_with_builder(market_order, &BUILDER)
                    .await?
            }
            HlOrder::Limit(limit_order) => {
                self.exchange_client
                    .order_with_builder(limit_order, None, &BUILDER)
                    .await?
            }
        };

        let result = match extract_order_status(status_res)? {
            ExchangeDataStatus::Filled(fill) => Ok(RestingOrderLocal {
                oid: fill.oid,
                limit_px,
                sz: size,
                side,
                intent,
                tpsl: trigger,
            }),
            ExchangeDataStatus::Resting(res) => Ok(RestingOrderLocal {
                oid: res.oid,
                limit_px,
                sz: size,
                side,
                intent,
                tpsl: trigger,
            }),

            ExchangeDataStatus::Error(err) if is_unapproved_builder_error(&err) => {
                Err(Error::UnapprovedBuilder(err))
            }
            ExchangeDataStatus::Error(err) => Err(Error::Custom(err)),

            _ => Err(Error::ExecutionFailure(
                "unexpected exchange status response".to_string(),
            )),
        };
        if let Ok(resting) = &result {
            self.submitted_orders.insert(
                resting.oid,
                SubmittedOrder {
                    origin,
                    strategy: (origin == TradeOrigin::Algo).then(|| self.strategy_name.clone()),
                },
            );
            // Retain recently canceled orders to recognize late fills, but bound
            // that history for long-running strategies which replace limits.
            let excess = self.submitted_orders.len().saturating_sub(10_000);
            if excess > 0 {
                let mut canceled: Vec<_> = self
                    .submitted_orders
                    .keys()
                    .copied()
                    .filter(|oid| *oid != resting.oid && !self.resting_orders.contains_key(oid))
                    .collect();
                canceled.sort_unstable();
                for oid in canceled.into_iter().take(excess) {
                    self.submitted_orders.remove(&oid);
                }
            }
        }
        result
    }
    async fn cancel_resting_oids(&mut self, oids: Vec<u64>) -> Result<(), Error> {
        let asset = self.asset.name.clone();
        let mut failed_cancels: HashSet<u64> = HashSet::new();
        for oid in oids {
            if self.resting_orders.remove(&oid).is_none() {
                continue;
            }
            let cancel = ClientCancelRequest {
                asset: asset.clone(),
                oid,
            };
            if let Err(e) = self.exchange_client.cancel(cancel, None).await {
                warn!("Failed to cancel oid {}: {:?}", oid, e);
                failed_cancels.insert(oid);
            }
        }
        let mut retries = 0;

        while !failed_cancels.is_empty() {
            retries += 1;
            let iterator = failed_cancels.iter().copied().collect::<Vec<_>>();
            for oid in iterator.iter() {
                let cancel = ClientCancelRequest {
                    asset: asset.clone(),
                    oid: *oid,
                };
                if self.exchange_client.cancel(cancel, None).await.is_ok() {
                    failed_cancels.remove(oid);
                }
            }

            if retries > Self::MAX_RETRIES {
                return Err(Error::Custom(format!(
                    "Failed to cancle resting order for {} market, please cancel manually on https://app.hyperliquid.xyz/trade/{}",
                    asset, asset,
                )));
            }
            sleep(Duration::from_millis(100)).await;
        }
        Ok(())
    }

    async fn cancel_all_resting(&mut self) -> Result<(), Error> {
        let oids = self.resting_orders.keys().copied().collect();
        self.cancel_resting_oids(oids).await
    }

    async fn cancel_force_target_resting(&mut self, order: &EngineOrder) -> Result<(), Error> {
        let oids = self
            .resting_orders
            .iter()
            .filter_map(|(&oid, resting)| {
                (resting.tpsl.is_none() && resting.intent == order.action).then_some(oid)
            })
            .collect();
        self.cancel_resting_oids(oids).await
    }

    fn into_hl_order(
        asset: &str,
        sz: f64,
        side: Side,
        limit: Option<Limit>,
        intent: PositionOp,
        decimals: Decimals,
    ) -> HlOrder<'_> {
        let is_long = side == Side::Long;
        let sz = roundf!(sz, decimals.sz);

        if let Some(limit) = limit {
            let reduce_only = (intent == PositionOp::Close) || limit.is_tpsl().is_some();
            let px = roundf!(limit.limit_px, decimals.px);
            HlOrder::Limit(ClientOrderRequest {
                asset: asset.to_string(),
                is_buy: is_long,
                reduce_only,
                limit_px: px,
                sz,
                cloid: None,
                order_type: limit.order_type.convert(px),
            })
        } else {
            HlOrder::Market(MarketOrderParams {
                asset,
                is_buy: is_long,
                sz,
                px: None,
                slippage: None,
                cloid: None,
                wallet: None,
            })
        }
    }
    /// Returns (trade_info, is_manual).
    async fn apply_fill(&mut self, mut fill: TradeFillInfo) -> (Option<TradeInfo>, bool) {
        let mut clean_up = false;
        let submitted = self.submitted_orders.get(&fill.oid).cloned();
        let is_manual = submitted.is_none();

        if let Some(resting) = self.resting_orders.get_mut(&fill.oid) {
            if let Some(trigger) = resting.tpsl {
                fill.fill_type = FillType::Trigger(trigger);
            }
            if resting.intent != fill.intent {
                warn!(
                    "Resting order intent mismatch: expected {:?}, got {:?}",
                    resting.intent, fill.intent
                );
            }
            if let Some(px) = resting.limit_px
                && resting.tpsl.is_none()
            {
                match resting.side {
                    Side::Long => {
                        if fill.price > px {
                            warn!("Long fill price {} > limit {}", fill.price, px);
                        }
                    }
                    Side::Short => {
                        if fill.price < px {
                            warn!("Short fill price {} < limit {}", fill.price, px);
                        }
                    }
                }
            }
            resting.sz -= fill.sz;
            if roundf!(resting.sz, self.asset.sz_decimals) == 0.0 {
                clean_up = true;
            }
        }

        if clean_up {
            self.resting_orders.remove(&fill.oid);
            self.submitted_orders.remove(&fill.oid);
        }

        let sz_decimals = self.asset.sz_decimals;
        let origin = submitted
            .as_ref()
            .map_or(TradeOrigin::Manual, |order| order.origin);
        let mut trade_info = self
            .with_position(|pos| apply_position_fill(pos, fill, sz_decimals, origin))
            .await;
        if let Some(trade) = &mut trade_info {
            trade.strategy = submitted.and_then(|order| order.strategy);
        }

        // Clean up resting orders if user closed position manually on HL
        if trade_info.is_some() && !clean_up {
            let _ = self.cancel_all_resting().await;
        }

        (trade_info, is_manual)
    }

    #[inline]
    async fn send_market_command(&self, label: &'static str, cmd: MarketCommand) -> bool {
        match self.market_tx.try_send(cmd) {
            Ok(()) => true,
            Err(TrySendError::Full(cmd)) => {
                match timeout(
                    Duration::from_secs(MARKET_COMMAND_SEND_TIMEOUT_SECS),
                    self.market_tx.send(cmd),
                )
                .await
                {
                    Ok(Ok(())) => true,
                    Ok(Err(_)) => {
                        warn!(
                            "[executor:{}] market command channel closed while sending {label}",
                            self.asset.name
                        );
                        false
                    }
                    Err(_) => {
                        warn!(
                            "[executor:{}] timed out sending {label} to market command queue",
                            self.asset.name
                        );
                        false
                    }
                }
            }
            Err(TrySendError::Closed(_)) => {
                warn!(
                    "[executor:{}] market command channel closed while sending {label}",
                    self.asset.name
                );
                false
            }
        }
    }

    #[inline]
    async fn update_market(&self, update: SendUpdate) -> bool {
        use SendUpdate::*;
        let cmd = match update {
            Trade(trade) => MarketCommand::ReceiveTrade(trade),
            Position(pos) => MarketCommand::UpdateOpenPosition(pos),
        };
        self.send_market_command("position/trade update", cmd).await
    }

    async fn kill(&mut self, close_paused_position: bool) {
        let _ = self.cancel_all_resting().await;

        let skip_paused_position = self.is_paused && !close_paused_position;
        let params = self
            .with_position(|pos| {
                if skip_paused_position && pos.is_some() {
                    return None;
                }

                if let Some(open_pos) = pos {
                    Some((!open_pos.side, open_pos.size))
                } else {
                    None
                }
            })
            .await;
        if let Some((side, size)) = params {
            self.closing = true;
            let asset = self.asset.name.clone();
            let op = PositionOp::Close;
            let mut retries = 0;
            loop {
                let trade = Self::into_hl_order(&asset, size, side, None, op, self.decimals);
                match self.open_trade(trade, op, None, TradeOrigin::Manual).await {
                    Ok(order_response) => {
                        let _ = self
                            .resting_orders
                            .insert(order_response.oid, order_response);
                        break;
                    }
                    Err(e) => {
                        retries += 1;
                        warn!("kill() close order failed (attempt {}): {}", retries, e);
                        if retries >= Self::MAX_RETRIES {
                            warn!(
                                "kill() exhausted retries for {} — position may still be open on-chain",
                                asset
                            );
                            break;
                        }
                        sleep(Duration::from_millis(100)).await;
                    }
                }
            }
        }
    }

    async fn submit_order(&mut self, order: EngineOrder) {
        let order_params: Option<(Side, f64)> = match order.action {
            PositionOp::OpenLong => Some((Side::Long, order.size)),
            PositionOp::OpenShort => Some((Side::Short, order.size)),
            PositionOp::Close => {
                self.with_position(|pos| {
                    if let Some(open_pos) = pos {
                        let size = order.size.min(open_pos.size);
                        let side = !open_pos.side;
                        Some((side, size))
                    } else {
                        None
                    }
                })
                .await
            }
        };

        if let Some((side, size)) = order_params {
            let asset = self.asset.name.clone();
            let trade =
                Self::into_hl_order(&asset, size, side, order.limit, order.action, self.decimals);
            let trigger = order.is_tpsl();
            match self
                .open_trade(trade, order.action, trigger, TradeOrigin::Algo)
                .await
            {
                Ok(order_response) => {
                    self.resting_orders
                        .insert(order_response.oid, order_response);
                }
                Err(Error::AuthError(msg)) => {
                    warn!("[executor] auth error: {msg}");
                    let _ = self
                        .send_market_command("auth error", MarketCommand::AuthError(msg))
                        .await;
                    self.is_paused = true;
                }
                Err(Error::UnapprovedBuilder(msg)) => {
                    warn!("[executor] builder fee approval error: {msg}");
                    let _ = self
                        .send_market_command(
                            "builder approval error",
                            MarketCommand::BuilderApprovalError(msg),
                        )
                        .await;
                    self.is_paused = true;
                }
                Err(e) => warn!("{}", e),
            }
        }
    }

    async fn force_taker(&mut self, order: EngineOrder) {
        if let Err(e) = self.cancel_force_target_resting(&order).await {
            warn!(
                "force taker failed while canceling target limit order: {}",
                e
            );
            return;
        }

        if matches!(order.action, PositionOp::OpenLong | PositionOp::OpenShort)
            && self.with_position(|pos| pos.is_some()).await
        {
            warn!("force taker open skipped because a position is already open");
            return;
        }

        self.submit_order(EngineOrder {
            limit: None,
            ..order
        })
        .await;
    }

    pub async fn start(&mut self) {
        use ExecCommand::*;
        while let Ok(cmd) = self.trade_rv.recv_async().await {
            match cmd {
                Order(order) => {
                    if self.is_paused {
                        continue;
                    }
                    self.submit_order(order).await;
                }
                ForceTaker(order) => {
                    if self.is_paused {
                        continue;
                    }
                    self.force_taker(order).await;
                }
                Control(control) => match control {
                    ExecControl::Kill => {
                        self.kill(false).await;
                        return;
                    }
                    ExecControl::Pause => {
                        self.is_paused = true;
                        let _ = self.cancel_all_resting().await;
                    }
                    ExecControl::Resume => {
                        self.is_paused = false;
                        self.manual_intervention_notified = false;
                    }
                    ExecControl::ForceClose => {
                        self.kill(true).await;
                    }
                },

                ReloadWallet(new_client) => {
                    log::info!(
                        "[executor] hot-reloaded exchange client for {}",
                        self.asset.name
                    );
                    self.exchange_client = new_client;
                }
                UpdateStrategy(name) => self.strategy_name = name,
                ReconcilePosition {
                    position: snapshot,
                    snapshot_time,
                } => {
                    self.is_paused = true;
                    self.closing = false;
                    // Reconciliation is only requested after the exchange has no
                    // outstanding orders. Discard stale local order tracking.
                    self.resting_orders.clear();
                    self.submitted_orders.clear();
                    self.snapshot_time = snapshot_time;
                    let position = {
                        let mut local = self.open_position.lock().await;
                        let previous = *local;
                        *local = reconciled_position(previous, snapshot);
                        // A preserved local position still counts streamed funding
                        // from its original baseline, including delayed deliveries.
                        if previous.is_none() || *local != previous {
                            self.funding_time = self.funding_time.max(snapshot_time);
                        }
                        *local
                    };
                    self.send_market_command(
                        "position reconciled",
                        MarketCommand::PositionReconciled(position),
                    )
                    .await;
                }
                Activate => {
                    let position = *self.open_position.lock().await;
                    self.send_market_command(
                        "position ready",
                        MarketCommand::PositionReconciled(position),
                    )
                    .await;
                }

                Event(event) => {
                    match event {
                        ExecEvent::Fill(fill) => {
                            if fill.time <= self.snapshot_time {
                                continue;
                            }
                            if let Some(tid) = fill.tid {
                                if !self.seen_fills.insert(tid) {
                                    continue;
                                }
                                self.fill_ids.push_back(tid);
                                if self.fill_ids.len() > 10_000 {
                                    if let Some(old) = self.fill_ids.pop_front() {
                                        self.seen_fills.remove(&old);
                                    }
                                }
                            }
                            let is_open =
                                matches!(fill.intent, PositionOp::OpenLong | PositionOp::OpenShort);
                            let is_known = self.submitted_orders.contains_key(&fill.oid);

                            if !is_known {
                                self.is_paused = true;
                                let _ = self.cancel_all_resting().await;
                                if !self.manual_intervention_notified {
                                    self.manual_intervention_notified = true;
                                    let _ = self
                                        .send_market_command(
                                            "manual trade detected",
                                            MarketCommand::ManualTradeDetected,
                                        )
                                        .await;
                                }
                            }

                            let (trade_info, _) = self.apply_fill(fill).await;

                            if let Some(trade_info) = trade_info {
                                if !is_open {
                                    self.closing = false;
                                }
                                self.update_market(SendUpdate::Trade(trade_info)).await;
                            }
                        }
                        ExecEvent::Funding {
                            amount: funding,
                            time,
                        } => {
                            if time <= self.funding_time {
                                continue;
                            }
                            self.funding_time = time;
                            self.with_position(|pos| {
                                if let Some(open_pos) = pos {
                                    open_pos.funding += funding;
                                } else {
                                    warn!("Received position funding but there was no OpenPositionLocal");
                                }
                            }).await;
                        }
                    }
                }
            }
        }
    }
}

#[derive(Debug, Clone)]
enum SendUpdate {
    Trade(TradeInfo),
    Position(Option<OpenPositionLocal>),
}

#[derive(Debug, Clone, Copy)]
struct Decimals {
    sz: u32,
    px: u32,
}

fn reduce_only_market_order(
    params: MarketOrderParams<'_>,
    mid: f64,
    sz_decimals: u32,
) -> Result<ClientOrderRequest, Error> {
    let slippage = params.slippage.unwrap_or(0.05);
    let raw_px = mid
        * if params.is_buy {
            1.0 + slippage
        } else {
            1.0 - slippage
        };
    if !raw_px.is_finite() || raw_px <= 0.0 || !params.sz.is_finite() || params.sz <= 0.0 {
        return Err(Error::Custom("invalid market close price or size".into()));
    }
    let significant_decimals = (4 - raw_px.log10().floor() as i32).max(0) as u32;
    let px_decimals = significant_decimals.min(6_u32.saturating_sub(sz_decimals));
    let sz = roundf!(params.sz, sz_decimals);
    let limit_px = roundf!(raw_px, px_decimals);
    if sz <= 0.0 || limit_px <= 0.0 {
        return Err(Error::Custom("market close rounds to zero".into()));
    }
    Ok(ClientOrderRequest {
        asset: params.asset.to_string(),
        is_buy: params.is_buy,
        reduce_only: true,
        limit_px,
        sz,
        cloid: params.cloid,
        order_type: ClientOrder::Limit(ClientLimit { tif: "Ioc".into() }),
    })
}

fn reconciled_position(
    local: Option<OpenPositionLocal>,
    snapshot: Option<OpenPositionLocal>,
) -> Option<OpenPositionLocal> {
    match (local, snapshot) {
        (Some(local), Some(chain))
            if local.side == chain.side
                && (local.size - chain.size).abs() < 1e-10
                && (local.entry_px - chain.entry_px).abs() <= chain.entry_px.abs() * 1e-8 =>
        {
            Some(local)
        }
        (_, snapshot) => snapshot,
    }
}

fn apply_position_fill(
    position: &mut Option<OpenPositionLocal>,
    fill: TradeFillInfo,
    sz_decimals: u32,
    origin: TradeOrigin,
) -> Option<TradeInfo> {
    if let Some(open) = position {
        if fill.side != open.side {
            let remaining = (fill.sz - open.size).max(0.0);
            let trade = open.apply_close_fill_with_origin(&fill, sz_decimals, origin);
            if trade.is_some() {
                *position = None;
                // A reversal contains a closing portion and a new opening portion.
                if roundf!(remaining, sz_decimals) > 0.0 && fill.intent != PositionOp::Close {
                    let mut next = OpenPositionLocal::new(TradeFillInfo {
                        sz: remaining,
                        fee: fill.fee * remaining / fill.sz,
                        ..fill
                    });
                    next.origin = Some(origin);
                    *position = Some(next);
                }
            }
            return trade;
        }
        if fill.intent != PositionOp::Close {
            open.apply_open_fill(&fill);
            open.origin = open.origin.map(|old| old.combine(origin));
        }
    } else if fill.intent != PositionOp::Close {
        let mut open = OpenPositionLocal::new(fill);
        open.origin = Some(origin);
        *position = Some(open);
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        margin::ChainPosition,
        test_support::{MockExchange, account, position},
    };

    fn adopted(size: &str) -> OpenPositionLocal {
        let raw = position(size, "100", "298");
        ChainPosition::parse(
            &serde_json::from_value(raw["position"].clone()).unwrap(),
            1000,
        )
        .unwrap()
        .unwrap()
        .local
    }

    fn fill(size: f64, price: f64, time: u64, tid: u64) -> TradeFillInfo {
        TradeFillInfo {
            price,
            sz: size,
            oid: 42,
            fee: size * 0.1,
            side: Side::Short,
            intent: PositionOp::Close,
            fill_type: FillType::Market,
            time,
            tid: Some(tid),
        }
    }

    async fn executor(
        exchange: &MockExchange,
    ) -> (
        Executor,
        flume::Sender<ExecCommand>,
        tokio::sync::mpsc::Receiver<MarketCommand>,
    ) {
        let (trade_tx, trade_rv) = flume::bounded(32);
        let (market_tx, market_rv) = tokio::sync::mpsc::channel(64);
        (
            Executor::for_test(exchange, trade_rv, market_tx, Some(adopted("10"))).await,
            trade_tx,
            market_rv,
        )
    }

    #[tokio::test]
    async fn adopted_position_closes_reduce_only_and_reports_partial_fills_once() {
        let exchange = MockExchange::new(account(vec![], "1000", 1000)).await;
        let (mut exec, tx, mut rx) = executor(&exchange).await;
        exec.submit_order(EngineOrder::market_close(20.0)).await;
        let requests = exchange.requests.lock().await;
        let order = &requests
            .iter()
            .find(|r| r["action"]["type"] == "order")
            .expect("submitted close")["action"]["orders"][0];
        assert_eq!(order["r"], true);
        assert_eq!(order["b"], false);
        assert_eq!(order["s"], "10"); // clamps to the imported size
        assert_eq!(order["t"]["limit"]["tif"], "Ioc");
        drop(requests);

        tx.send(ExecCommand::UpdateStrategy("Different strategy".into()))
            .unwrap();
        tx.send(ExecCommand::Event(ExecEvent::Fill(fill(
            10.0, 120.0, 1000, 1,
        ))))
        .unwrap();
        let first = fill(4.0, 120.0, 1100, 2);
        tx.send(ExecCommand::Event(ExecEvent::Fill(first))).unwrap();
        tx.send(ExecCommand::Event(ExecEvent::Fill(first))).unwrap();
        tx.send(ExecCommand::Event(ExecEvent::Funding {
            amount: -99.0,
            time: 1000,
        }))
        .unwrap();
        tx.send(ExecCommand::Event(ExecEvent::Funding {
            amount: -0.5,
            time: 1200,
        }))
        .unwrap();
        tx.send(ExecCommand::Event(ExecEvent::Funding {
            amount: -0.5,
            time: 1200,
        }))
        .unwrap();
        tx.send(ExecCommand::Event(ExecEvent::Fill(fill(
            6.0, 130.0, 1300, 3,
        ))))
        .unwrap();
        drop(tx);
        tokio::time::timeout(Duration::from_secs(3), exec.start())
            .await
            .unwrap();
        assert!(exec.open_position.lock().await.is_none());
        let mut trades = Vec::new();
        while let Ok(command) = rx.try_recv() {
            if let MarketCommand::ReceiveTrade(trade) = command {
                trades.push(trade);
            }
        }
        assert_eq!(trades.len(), 1);
        let trade = &trades[0];
        assert_eq!(trade.open.origin, Some(TradeOrigin::Manual));
        assert_eq!(trade.close.origin, Some(TradeOrigin::Algo));
        assert_eq!(trade.strategy.as_deref(), Some("Original closer"));
        assert_eq!(trade.open.time, None);
        assert_eq!(trade.size, 10.0);
        assert_eq!(trade.close.price, 126.0);
        assert_eq!(trade.pnl, 258.5);
        assert_eq!(trade.managed_pnl(), 158.5);
        assert_eq!(trade.fees, 1.0);
        assert_eq!(trade.funding, -0.5);
    }

    #[tokio::test]
    async fn manual_close_is_reported_and_pauses_instead_of_discarding_history() {
        let exchange = MockExchange::new(account(vec![], "1000", 1000)).await;
        let (mut exec, tx, mut rx) = executor(&exchange).await;
        tx.send(ExecCommand::Event(ExecEvent::Fill(fill(
            10.0, 120.0, 1100, 1,
        ))))
        .unwrap();
        drop(tx);
        exec.start().await;
        assert!(exec.is_paused);
        let mut reported = false;
        while let Ok(command) = rx.try_recv() {
            if let MarketCommand::ReceiveTrade(trade) = command {
                assert_eq!(trade.close.origin, Some(TradeOrigin::Manual));
                assert_eq!(trade.strategy, None);
                reported = true;
            }
        }
        assert!(reported);
    }

    #[tokio::test]
    async fn resume_preserves_delayed_funding_for_a_matching_local_position() {
        let exchange = MockExchange::new(account(vec![], "1000", 1000)).await;
        let (mut exec, tx, _rx) = executor(&exchange).await;
        tx.send(ExecCommand::ReconcilePosition {
            position: Some(adopted("10")),
            snapshot_time: 2000,
        })
        .unwrap();
        tx.send(ExecCommand::Event(ExecEvent::Funding {
            amount: -0.75,
            time: 1500,
        }))
        .unwrap();
        tx.send(ExecCommand::Event(ExecEvent::Funding {
            amount: -0.75,
            time: 1500,
        }))
        .unwrap();
        drop(tx);
        exec.start().await;
        assert_eq!(exec.open_position.lock().await.unwrap().funding, -0.75);
    }

    #[test]
    fn short_adoption_closes_and_reversals_split_fees_between_positions() {
        let mut short = Some(adopted("-10"));
        let trade = apply_position_fill(
            &mut short,
            TradeFillInfo {
                side: Side::Long,
                ..fill(10.0, 80.0, 1100, 1)
            },
            4,
            TradeOrigin::Algo,
        )
        .unwrap();
        assert!(short.is_none());
        assert_eq!(trade.pnl, 199.0);
        let mut long = Some(adopted("10"));
        let trade = apply_position_fill(
            &mut long,
            TradeFillInfo {
                intent: PositionOp::OpenShort,
                ..fill(15.0, 120.0, 1100, 2)
            },
            4,
            TradeOrigin::Manual,
        )
        .unwrap();
        assert_eq!(trade.fees, 1.0);
        let new_short = long.unwrap();
        assert_eq!(new_short.side, Side::Short);
        assert_eq!(new_short.size, 5.0);
        assert_eq!(new_short.fees, 0.5);
        assert_eq!(new_short.origin, Some(TradeOrigin::Manual));
        assert!(new_short.adoption.is_none());
    }

    #[test]
    fn reconciliation_preserves_known_history_only_for_matching_exposure() {
        let mut local = adopted("10");
        local.funding = -1.0;
        local.fees = 0.5;
        assert_eq!(
            reconciled_position(Some(local), Some(adopted("10"))),
            Some(local)
        );
        let changed = adopted("-10");
        assert_eq!(
            reconciled_position(Some(local), Some(changed)),
            Some(changed)
        );
        assert!(reconciled_position(Some(local), None).is_none());
    }
}