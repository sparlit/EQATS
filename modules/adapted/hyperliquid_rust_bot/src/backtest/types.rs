use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use uuid::Uuid;

use crate::{EngineView, IndicatorData, OpenPositionLocal, Price, TimeFrame, TradeInfo};

pub type PnlTracker = BTreeMap<u64, f64>;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BacktestConfig {
    pub asset: String,
    pub strategy_id: Uuid,
    /// `None` requests automatic resolution derived from the strategy's
    /// indicator timeframes. Results always contain the resolved value.
    pub resolution: Option<TimeFrame>,
    pub margin: f64,
    pub lev: usize,
    pub taker_fee_bps: u32,
    pub maker_fee_bps: u32,
    pub funding_rate_bps_per_8h: f64,
    pub start_time: u64,
    pub end_time: u64,
    pub snapshot_interval_candles: u64,
    #[serde(default = "default_max_equity_points")]
    pub max_equity_points: usize,
    #[serde(default = "default_max_snapshots")]
    pub max_snapshots: usize,
}

fn default_max_equity_points() -> usize {
    // Hyperliquid exposes at most the latest 5,000 candles. Keeping the full
    // primary series avoids losing uPnL extremes to equity-only downsampling.
    5000
}

fn default_max_snapshots() -> usize {
    500
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BacktestRunRequest {
    #[serde(default)]
    pub run_id: Option<String>,
    pub config: BacktestConfig,
    pub warmup_candles: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", tag = "kind")]
pub enum BacktestProgress {
    Initializing,
    LoadingCandles { loaded: u64, total: u64 },
    WarmingEngine { loaded: u64, total: u64 },
    Simulating { processed: u64, total: u64 },
    Finalizing,
    Done,
    Failed { message: String },
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CandlePoint {
    pub open_time: u64,
    pub close_time: u64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

impl From<Price> for CandlePoint {
    fn from(p: Price) -> Self {
        Self {
            open_time: p.open_time,
            close_time: p.close_time,
            open: p.open,
            high: p.high,
            low: p.low,
            close: p.close,
            volume: p.vlm,
        }
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EquityPoint {
    pub ts: u64,
    pub equity: f64,
    pub balance: f64,
    pub upnl: f64,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum SnapshotReason {
    Open,
    Reduce,
    Flatten,
    Close,
    ForceClose,
    CancelResting,
    Fill,
    Interval,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PositionSnapshot {
    pub id: u64,
    pub ts: u64,
    pub candle: CandlePoint,
    pub upnl: f64,
    pub balance: f64,
    pub equity: f64,
    pub reason: SnapshotReason,
    pub engine_state: EngineView,
    pub indicators: Vec<IndicatorData>,
    pub position: Option<OpenPositionLocal>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BacktestSummary {
    pub initial_equity: f64,
    pub final_equity: f64,
    pub net_pnl: f64,
    pub return_pct: f64,
    pub max_drawdown_abs: f64,
    pub max_drawdown_pct: f64,
    pub total_trades: usize,
    pub wins: usize,
    pub losses: usize,
    pub win_rate_pct: f64,
    pub gross_profit: f64,
    pub gross_loss: f64,
    pub avg_win: f64,
    pub avg_loss: f64,
    pub profit_factor: Option<f64>,
    pub expectancy: f64,
    #[serde(default)]
    pub sharpe_ratio: Option<f64>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BacktestResult {
    pub run_id: String,
    pub started_at: u64,
    pub finished_at: u64,
    pub candles_loaded: u64,
    pub candles_processed: u64,
    pub config: BacktestConfig,
    pub summary: BacktestSummary,
    pub trades: Vec<TradeInfo>,
    pub equity_curve: Vec<EquityPoint>,
    pub snapshots: Vec<PositionSnapshot>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BacktestSim {
    pub config: BacktestConfig,
    pub pending_order_ids: Vec<u64>,
    pub position: Option<OpenPositionLocal>,
    pub trades: Vec<TradeInfo>,
    pub pnl: PnlTracker,
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn config_accepts_auto_resolution_and_has_no_source_contract() {
        let config: BacktestConfig = serde_json::from_value(json!({
            "asset": "xyz:TSLA",
            "strategyId": Uuid::nil(),
            "resolution": null,
            "margin": 1_000.0,
            "lev": 2,
            "takerFeeBps": 3,
            "makerFeeBps": 1,
            "fundingRateBpsPer8h": 0.0,
            "startTime": 1,
            "endTime": 2,
            "snapshotIntervalCandles": 10
        }))
        .expect("auto-resolution config should deserialize");

        assert_eq!(config.asset, "xyz:TSLA");
        assert_eq!(config.resolution, None);
        assert_eq!(config.max_equity_points, default_max_equity_points());
        assert_eq!(config.max_snapshots, default_max_snapshots());

        let serialized = serde_json::to_value(config).expect("config should serialize");
        assert!(serialized.get("source").is_none());
    }
}