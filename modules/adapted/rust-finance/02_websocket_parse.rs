// benches/02_websocket_parse.rs
// Benchmarks the serde JSON deserialization of market events representing Finnhub/Alpaca inputs.

use criterion::{black_box, criterion_group, criterion_main, Criterion, Throughput};
use serde::{Deserialize, Serialize};
use std::time::Duration;

#[derive(Debug, Serialize, Deserialize)]
pub struct TradeMessage {
    pub sym: String,
    pub p: f64,
    pub s: f64,
    pub t: u64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct FinnhubTradeEvent {
    pub data: Vec<TradeMessage>,
    #[serde(rename = "type")]
    pub event_type: String,
}

fn bench_json_parse(c: &mut Criterion) {
    let raw_json = r#"{
        "data": [
            {"p": 160.50, "s": 100, "sym": "AAPL", "t": 1640995200000},
            {"p": 160.51, "s": 200, "sym": "AAPL", "t": 1640995200050}
        ],
        "type": "trade"
    }"#;

    let mut group = c.benchmark_group("websocket_ingestion");
    group.throughput(Throughput::Bytes(raw_json.len() as u64));
    group.bench_function("parse_finnhub_trade", |b| {
        b.iter(|| {
            let parsed: FinnhubTradeEvent = serde_json::from_str(black_box(raw_json)).unwrap();
            black_box(parsed);
        })
    });
    group.finish();
}

criterion_group! {
    name = parse_benches;
    config = Criterion::default().measurement_time(Duration::from_secs(3));
    targets = bench_json_parse
}
criterion_main!(parse_benches);
