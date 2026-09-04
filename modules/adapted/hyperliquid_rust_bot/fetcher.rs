use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use hyperliquid_rust_sdk::{BaseUrl, InfoClient};
use log::warn;
use tokio::sync::Mutex;
use tokio::time::{Instant, sleep};

use super::candle_store::{CandleKey, CandleStore};
use crate::helper::info_client_with_timeout;
use crate::{Error, Price, TimeFrame, candles_snapshot};

const MAX_HTTP_RETRIES: usize = 5;
const RETRY_BASE_DELAY_MS: u64 = 500;
const RETRY_MAX_DELAY_MS: u64 = 20_000;
const RETRY_JITTER_MS: u64 = 250;

#[derive(Clone)]
pub(crate) struct RequestLimiter {
    interval: Duration,
    next_allowed: Arc<Mutex<Instant>>,
}

impl RequestLimiter {
    pub(crate) fn from_requests_per_second(rps: u32) -> Option<Self> {
        if rps == 0 {
            return None;
        }
        Some(Self {
            interval: Duration::from_secs_f64(1.0 / rps as f64),
            next_allowed: Arc::new(Mutex::new(Instant::now())),
        })
    }

    pub(crate) async fn acquire(&self) {
        let wait_for = {
            let mut next = self.next_allowed.lock().await;
            let now = Instant::now();
            if now >= *next {
                *next = now + self.interval;
                None
            } else {
                let wait = *next - now;
                *next += self.interval;
                Some(wait)
            }
        };

        if let Some(delay) = wait_for {
            sleep(delay).await;
        }
    }
}

/// Hyperliquid-only historical candle fetcher backed by the persistent cache.
pub struct Fetcher {
    client: InfoClient,
    store: Arc<CandleStore>,
    request_limiter: Option<RequestLimiter>,
}

impl Fetcher {
    pub async fn new(store: Arc<CandleStore>) -> Result<Self, Error> {
        let client = info_client_with_timeout("backtest", BaseUrl::Mainnet).await?;
        Ok(Self {
            client,
            store,
            request_limiter: None,
        })
    }

    pub(crate) fn set_request_limiter(&mut self, limiter: Option<RequestLimiter>) {
        self.request_limiter = limiter;
    }

    pub async fn fetch(
        &mut self,
        asset: &str,
        tf: TimeFrame,
        start: u64,
        end: u64,
    ) -> Result<Vec<Price>, Error> {
        self.fetch_with_progress(asset, tf, start, end, |_, _| {})
            .await
    }

    pub async fn fetch_with_progress<F>(
        &mut self,
        asset: &str,
        tf: TimeFrame,
        start: u64,
        end: u64,
        mut on_progress: F,
    ) -> Result<Vec<Price>, Error>
    where
        F: FnMut(u64, u64),
    {
        // Hyperliquid identifiers are case-sensitive. HIP-3 assets include a
        // lower-case DEX prefix (for example `xyz:TSLA`).
        let asset = asset.trim().to_string();
        if asset.is_empty() {
            return Ok(Vec::new());
        }
        if end <= start {
            return Err(Error::Custom(
                "Invalid time range: end must be greater than start".to_string(),
            ));
        }

        let candle_interval_ms = tf.to_millis();
        let range_start = start;
        let range_end = end.min(now_ms());
        if range_end <= range_start {
            return Err(Error::Custom(
                "Requested range is outside available historical data".to_string(),
            ));
        }

        let (normalized_start, normalized_end) =
            normalize_range(range_start, range_end, candle_interval_ms);
        let estimated_total =
            estimate_points_in_range(normalized_start, normalized_end, candle_interval_ms).max(1);
        let candle_key = CandleKey::new(asset.clone(), tf);

        let guard = self
            .store
            .acquire_key(&candle_key, |loaded, total| {
                on_progress(loaded, total);
            })
            .await;

        let lookup = self.store.lookup_range(
            &candle_key,
            normalized_start,
            normalized_end,
            candle_interval_ms,
        );
        let missing = lookup.missing;
        let cached = lookup.cached;
        let cached_in_range = lookup.cached_in_range;
        on_progress(cached_in_range, estimated_total);

        if let Some(values) = cached {
            on_progress(
                values.len() as u64,
                estimated_total.max(values.len() as u64),
            );
            return Ok(values);
        }

        let mut loaded = cached_in_range.min(estimated_total);
        for segment in missing {
            let segment_total =
                estimate_points_in_range(segment.start, segment.end, candle_interval_ms);
            let base_loaded = loaded;
            let data = self
                .fetch_segment(&asset, tf, segment.start, segment.end)
                .await?;
            let segment_loaded = data.len() as u64;
            let progress = base_loaded
                .saturating_add(segment_loaded.min(segment_total))
                .min(estimated_total);
            on_progress(progress, estimated_total);
            guard.send_progress(progress, estimated_total);

            self.store.insert_many(&candle_key, &data);
            loaded = self
                .store
                .count_range(&candle_key, normalized_start, normalized_end);
            on_progress(loaded.min(estimated_total), estimated_total);
            guard.send_progress(loaded.min(estimated_total), estimated_total);
        }

        let out = self
            .store
            .range_to_vec(&candle_key, normalized_start, normalized_end);
        on_progress(out.len() as u64, estimated_total.max(out.len() as u64));
        Ok(out)
    }

    async fn fetch_segment(
        &self,
        asset: &str,
        tf: TimeFrame,
        start: u64,
        end: u64,
    ) -> Result<Vec<Price>, Error> {
        let mut collected = self.request_candles(asset, tf, start, end).await?;
        collected.retain(|price| price.close_time > start && price.open_time < end);

        // Hyperliquid is authoritative for bucket alignment and market-closure
        // gaps. Never manufacture missing candles.
        let mut by_open_time = BTreeMap::new();
        for price in collected {
            by_open_time.insert(price.open_time, price);
        }
        Ok(by_open_time.into_values().collect())
    }

    async fn request_candles(
        &self,
        asset: &str,
        tf: TimeFrame,
        start: u64,
        end: u64,
    ) -> Result<Vec<Price>, Error> {
        for attempt in 0..=MAX_HTTP_RETRIES {
            if let Some(limiter) = &self.request_limiter {
                limiter.acquire().await;
            }

            match candles_snapshot(&self.client, asset, tf, start, end).await {
                Ok(prices) => return Ok(prices),
                Err(error) if attempt < MAX_HTTP_RETRIES => {
                    let delay = retry_delay_for_attempt(attempt);
                    warn!(
                        "Hyperliquid candle request failed for {} {} range={}..{} (attempt {}/{}): {}. Retrying in {}ms",
                        asset,
                        tf,
                        start,
                        end,
                        attempt + 1,
                        MAX_HTTP_RETRIES + 1,
                        error,
                        delay.as_millis()
                    );
                    sleep(delay).await;
                }
                Err(error) => {
                    return Err(Error::Custom(format!(
                        "Hyperliquid candle request failed for {asset} {tf} after {} attempts: {error}",
                        MAX_HTTP_RETRIES + 1
                    )));
                }
            }
        }

        Err(Error::Custom(
            "Hyperliquid candle request failed after retries".to_string(),
        ))
    }
}

fn normalize_range(start_ms: u64, end_ms: u64, candle_interval_ms: u64) -> (u64, u64) {
    let normalized_start = start_ms.saturating_sub(start_ms % candle_interval_ms);
    let normalized_end = std::cmp::max(
        normalized_start.saturating_add(candle_interval_ms),
        div_ceil(end_ms, candle_interval_ms).saturating_mul(candle_interval_ms),
    );

    (normalized_start, normalized_end)
}

fn estimate_points_in_range(start: u64, end: u64, step: u64) -> u64 {
    if end <= start {
        return 0;
    }
    std::cmp::max(1, div_ceil(end - start, step))
}

fn retry_delay_for_attempt(attempt: usize) -> Duration {
    let factor = 1_u64 << attempt.min(8);
    let exp = RETRY_BASE_DELAY_MS.saturating_mul(factor);
    let capped = exp.min(RETRY_MAX_DELAY_MS);
    let jitter = jitter_ms(RETRY_JITTER_MS);
    Duration::from_millis(capped.saturating_add(jitter))
}

fn jitter_ms(max_ms: u64) -> u64 {
    if max_ms == 0 {
        return 0;
    }
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(duration) => (duration.subsec_nanos() as u64) % max_ms,
        Err(_) => 0,
    }
}

fn div_ceil(value: u64, divisor: u64) -> u64 {
    if divisor == 0 {
        return 0;
    }
    value / divisor + u64::from(!value.is_multiple_of(divisor))
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_range_keeps_expected_bounds() {
        assert_eq!(normalize_range(61_000, 121_000, 60_000), (60_000, 180_000));
    }

    #[test]
    fn hyperliquid_asset_identifiers_are_not_normalized() {
        let hip3 = CandleKey::new("xyz:TSLA", TimeFrame::Hour1);
        let capitalized = CandleKey::new("XYZ:TSLA", TimeFrame::Hour1);
        let k_prefixed = CandleKey::new("kPEPE", TimeFrame::Min1);

        assert_eq!(hip3.asset, "xyz:TSLA");
        assert_eq!(capitalized.asset, "XYZ:TSLA");
        assert_ne!(hip3.asset, capitalized.asset);
        assert_eq!(k_prefixed.asset, "kPEPE");
    }
}
