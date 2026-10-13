use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradeRow {
    pub id: uuid::Uuid,
    pub pubkey: String,
    pub market: String,
    pub side: String,
    pub size: f64,
    pub pnl: f64,
    pub total_pnl: f64,
    pub fees: f64,
    pub funding: f64,
    pub open_time: Option<i64>,
    pub open_price: f64,
    pub open_type: Option<String>,
    pub close_time: Option<i64>,
    pub close_price: f64,
    pub close_type: Option<String>,
    pub strategy: Option<String>,
    #[serde(default)]
    pub open_origin: Option<crate::TradeOrigin>,
    #[serde(default)]
    pub close_origin: Option<crate::TradeOrigin>,
    #[serde(default)]
    pub adoption: Option<crate::AdoptionInfo>,
    #[serde(default)]
    pub managed_pnl: Option<f64>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legacy_trade_rows_load_and_adopted_rows_round_trip_without_invented_history() {
        let legacy = serde_json::json!({
            "id":"00000000-0000-0000-0000-000000000001","pubkey":"test","market":"BTC",
            "side":"Long","size":1.0,"pnl":12.0,"total_pnl":12.0,"fees":1.0,"funding":0.0,
            "open_time":1000,"open_price":100.0,"open_type":"Market",
            "close_time":2000,"close_price":113.0,"close_type":"Market","strategy":"closer"
        });
        let mut row: TradeRow = serde_json::from_value(legacy).unwrap();
        assert_eq!(row.open_time, Some(1000));
        assert_eq!(row.open_origin, None);
        assert_eq!(row.adoption, None);
        row.open_time = None;
        row.open_type = None;
        row.open_origin = Some(crate::TradeOrigin::Manual);
        row.close_origin = Some(crate::TradeOrigin::Algo);
        row.adoption = Some(crate::AdoptionInfo {
            time: 1500,
            unrealized_pnl: 10.0,
            funding_since_open: 2.0,
        });
        row.managed_pnl = Some(2.0);
        let stored = serde_json::to_value(&row).unwrap();
        assert!(stored["open_time"].is_null());
        assert!(stored["open_type"].is_null());
        let loaded: TradeRow = serde_json::from_value(stored).unwrap();
        assert_eq!(loaded.open_origin, Some(crate::TradeOrigin::Manual));
        assert_eq!(loaded.close_origin, Some(crate::TradeOrigin::Algo));
        assert_eq!(loaded.adoption, row.adoption);
        assert_eq!(loaded.managed_pnl, Some(2.0));
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StrategySummary {
    pub id: uuid::Uuid,
    pub name: String,
    pub is_active: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StrategyRow {
    pub id: uuid::Uuid,
    pub name: String,
    pub on_idle: String,
    pub on_open: String,
    pub on_busy: String,
    pub indicators: serde_json::Value,
    pub state_declarations: Option<serde_json::Value>,
    pub is_active: Option<bool>,
    pub created_at: Option<chrono::DateTime<chrono::Utc>>,
    pub updated_at: Option<chrono::DateTime<chrono::Utc>>,
}