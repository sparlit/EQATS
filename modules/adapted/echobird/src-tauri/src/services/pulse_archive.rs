//! AI Pulse archive — per-day JSON files on disk.
//!
//! Layout: `~/.echobird/pulse/YYYY/MM/DD_{lang}.json`
//!
//! Each file:
//! ```json
//! { "schema": 1, "date": "2026-05-15", "lang": "zh",
//!   "item_count": 538, "items": [ ...NewsItem... ] }
//! ```
//!
//! Upstream feeds give a sliding 7-day window: missed days are lost
//! forever, so every fetch fans the items out into per-day buckets
//! (by local date of `published_at`) and atomically merges-with-existing
//! on disk. Result: as long as the user opens EchoBird at least every
//! 7 days, no day is dropped.
//!
//! Atomic write = `tmp file → rename`. A partial write never leaves a
//! day's archive in a half-parsed state.

use chrono::{Datelike, Duration, Local, Utc};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::PathBuf;

use crate::utils::platform::echobird_dir;

/// Some upstream aggregators (newsnow + juejin in particular, a few wechat
/// scrapers occasionally) stamp Beijing time as if it were UTC, so a story
/// published at 16:24 CST gets written as "2026-05-23T16:24:59Z" — 8h in
/// the future relative to the snapshot's own clock. The fix lives in
/// `scripts/filter_pulse.py` on the bot side, but it doesn't repair archive
/// files we already wrote with the bad data: those rows live in a
/// "future date" bucket file (e.g. `2026/05/24_zh.json` on a CST machine)
/// that the corrected upstream payload never touches, so cross-file dedupe
/// in `load_all` lets the bad row keep winning forever.
///
/// `effective_ts` mirrors the frontend's `itemTs()` future-guard: when
/// `published_at` parses to >now+5min it falls back to `first_seen_at` /
/// `last_seen_at`. `bucket_date` (write path) and `load_all` (read path)
/// both call through this so:
///   1. New writes never land in a future date file.
///   2. Pre-existing future date files are dropped at load time by the
///      `date > today+1` filter in `load_all`.
const FUTURE_SLACK_SECS: i64 = 5 * 60;

fn effective_ts(item: &NewsItem, now_plus_slack_ts: i64) -> &str {
    let pub_str = item.published_at.as_deref().unwrap_or("");
    if !pub_str.is_empty() {
        if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(pub_str) {
            if dt.timestamp() > now_plus_slack_ts {
                return item
                    .first_seen_at
                    .as_deref()
                    .filter(|s| !s.is_empty())
                    .or_else(|| item.last_seen_at.as_deref().filter(|s| !s.is_empty()))
                    .unwrap_or(pub_str);
            }
        }
    }
    pub_str
}

/// Mirror of the frontend's `NewsItem` shape. `serde(default)` on every
/// optional field so a future upstream-schema tweak that drops or renames
/// fields doesn't break archive reads.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewsItem {
    pub id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub site_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub site_name: Option<String>,
    pub source: String,
    pub title: String,
    pub url: String,
    #[serde(default)]
    pub published_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub first_seen_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_seen_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title_zh: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title_en: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct DayFile {
    #[serde(default = "default_schema")]
    schema: u32,
    date: String,
    lang: String,
    #[serde(default)]
    item_count: usize,
    items: Vec<NewsItem>,
}

#[derive(Debug, Deserialize)]
struct DayFileMeta {
    #[serde(default)]
    item_count: usize,
}

fn default_schema() -> u32 {
    1
}

const PULSE_SUBDIR: &str = "pulse";

fn pulse_root() -> PathBuf {
    echobird_dir().join(PULSE_SUBDIR)
}

/// Build the on-disk path for a (date, lang) pair. Returns `None` if
/// `date` isn't a well-formed `YYYY-MM-DD` — caller's responsibility to
/// skip the item rather than write to a path with embedded garbage.
fn day_path(date: &str, lang: &str) -> Option<PathBuf> {
    if date.len() < 10 {
        return None;
    }
    let year = &date[0..4];
    let month = &date[5..7];
    let day = &date[8..10];
    let all_digits = |s: &str| s.chars().all(|c| c.is_ascii_digit());
    if !all_digits(year) || !all_digits(month) || !all_digits(day) {
        return None;
    }
    if &date[4..5] != "-" || &date[7..8] != "-" {
        return None;
    }
    // Reject lang values that could escape the path (only zh / en
    // are written by the frontend, but defensive).
    if !lang.chars().all(|c| c.is_ascii_alphabetic()) {
        return None;
    }
    Some(
        pulse_root()
            .join(year)
            .join(month)
            .join(format!("{}_{}.json", day, lang)),
    )
}

/// Pick the YYYY-MM-DD bucket for an item using the user's local
/// timezone. Falls back: `effective_ts` (= published_at with future-guard)
/// → `first_seen_at` → `last_seen_at` → today. Without the timezone
/// conversion a naive `ts.slice(0,10)` lumps every CST 00:00–08:00 item
/// into the wrong (UTC) bucket — same bug the TS code at `itemLocalDate`
/// already fixes. The `effective_ts` indirection guarantees that a
/// future-stamped row goes into its `first_seen_at` day bucket instead
/// of a phantom future-date file.
fn bucket_date(item: &NewsItem, today_str: &str, now_plus_slack_ts: i64) -> String {
    let primary = effective_ts(item, now_plus_slack_ts);
    let pick: Option<&str> = if !primary.is_empty() {
        Some(primary)
    } else {
        item.first_seen_at
            .as_deref()
            .filter(|s| !s.is_empty())
            .or_else(|| item.last_seen_at.as_deref().filter(|s| !s.is_empty()))
    };

    let Some(ts) = pick else {
        return today_str.to_string();
    };

    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(ts) {
        let local = dt.with_timezone(&Local);
        return format!(
            "{:04}-{:02}-{:02}",
            local.year(),
            local.month(),
            local.day()
        );
    }

    // Last resort: if the string at least starts with "YYYY-MM-DD" we
    // trust that prefix. Loses timezone info but matches the legacy
    // localStorage bucketing — better than dumping everything into today.
    if ts.len() >= 10 {
        let head = &ts[..10];
        if head.chars().enumerate().all(|(i, c)| match i {
            4 | 7 => c == '-',
            _ => c.is_ascii_digit(),
        }) {
            return head.to_string();
        }
    }

    today_str.to_string()
}

/// Fan items out into per-day buckets, merge with whatever's already on
/// disk (dedupe by url, newer wins), atomic-write each bucket back.
///
/// Idempotent: re-running with the same input is a no-op once the data
/// is on disk. That property is why we can call this on every refresh
/// without worrying about double-counting.
pub fn save_fanout(lang: &str, items: Vec<NewsItem>) -> Result<usize, String> {
    if items.is_empty() {
        return Ok(0);
    }

    let now = Local::now();
    let today_str = format!("{:04}-{:02}-{:02}", now.year(), now.month(), now.day());
    let now_plus_slack = Utc::now().timestamp() + FUTURE_SLACK_SECS;

    let mut buckets: HashMap<String, Vec<NewsItem>> = HashMap::new();
    for it in items {
        let date = bucket_date(&it, &today_str, now_plus_slack);
        buckets.entry(date).or_default().push(it);
    }

    let mut total_written = 0usize;
    for (date, new_items) in buckets {
        let Some(path) = day_path(&date, lang) else {
            log::warn!("[PulseArchive] skipping malformed bucket: {}", date);
            continue;
        };

        // Load existing items for this date (if any).
        let existing_items: Vec<NewsItem> = if path.exists() {
            match fs::read_to_string(&path) {
                Ok(content) => match serde_json::from_str::<DayFile>(&content) {
                    Ok(df) => df.items,
                    Err(e) => {
                        log::warn!("[PulseArchive] {} parse error: {}", path.display(), e);
                        Vec::new()
                    }
                },
                Err(e) => {
                    log::warn!("[PulseArchive] {} read error: {}", path.display(), e);
                    Vec::new()
                }
            }
        } else {
            Vec::new()
        };

        // Dedupe by url. The HashMap insert semantics mean: incoming new
        // item replaces the cached one for the same url — that's
        // desirable because upstream sometimes back-fills better
        // translations / titles, and we want the freshest copy.
        let mut by_url: HashMap<String, NewsItem> = HashMap::new();
        for it in existing_items {
            by_url.insert(it.url.clone(), it);
        }
        for it in new_items {
            by_url.insert(it.url.clone(), it);
        }

        let mut merged: Vec<NewsItem> = by_url.into_values().collect();
        // Newest-first for human-friendly file inspection. Empty strings
        // sort to the bottom, which is also what we want for items
        // missing every timestamp. Sort key uses effective_ts so a
        // future-stamped row doesn't claim the top slot.
        merged.sort_by(|a, b| {
            let ka = effective_ts(a, now_plus_slack);
            let kb = effective_ts(b, now_plus_slack);
            kb.cmp(ka)
        });

        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("mkdir failed: {}", e))?;
        }

        let day_file = DayFile {
            schema: 1,
            date: date.clone(),
            lang: lang.to_string(),
            item_count: merged.len(),
            items: merged,
        };

        // serde_json::to_string (compact) keeps each day-file under
        // 200 KB even on heavy days — pretty-printing would double size
        // for no gain, since these files are read by code 99% of the time.
        let json = serde_json::to_string(&day_file).map_err(|e| format!("encode: {}", e))?;

        let tmp_path = path.with_extension("json.tmp");
        fs::write(&tmp_path, json).map_err(|e| format!("write tmp: {}", e))?;
        fs::rename(&tmp_path, &path).map_err(|e| format!("rename: {}", e))?;

        total_written += day_file.item_count;
    }

    Ok(total_written)
}

/// Load every item we have on disk for a given lang, sorted newest-first.
///
/// Yes, "every" — current archive volumes (50 MB / year for the lightest
/// news-item shape) make global loading cheap enough that the simplicity
/// is worth more than lazy windowing. If users ever break 5+ years of
/// archive we can revisit, but that's a multi-year-from-now problem.
pub fn load_all(lang: &str) -> Vec<NewsItem> {
    // Self-heal: drop any date file dated more than 1 day past today in
    // the user's local TZ. These can only exist as residue from the
    // pre-fix upstream bug where future-stamped items got bucketed into
    // phantom future dates (e.g. 2026/05/24_zh.json holding a single
    // 2026-05-23T16:24:59Z-stamped row on a CST machine). Skipping the
    // file at load time keeps the bad URL out of seen_urls so the real
    // entry from the correct day bucket wins the cross-file dedupe. The
    // file itself stays on disk and goes cold once the URL drops out of
    // the upstream 7-day window — not worth deleting eagerly.
    let now_local = Local::now();
    let tomorrow_local = now_local + Duration::days(1);
    let max_date_str = format!(
        "{:04}-{:02}-{:02}",
        tomorrow_local.year(),
        tomorrow_local.month(),
        tomorrow_local.day()
    );

    let dates: Vec<String> = list_all_dates(lang)
        .into_iter()
        .filter(|d| d.as_str() <= max_date_str.as_str())
        .collect();
    let mut out: Vec<NewsItem> = Vec::new();
    let mut seen_urls: HashSet<String> = HashSet::new();

    for date in &dates {
        let Some(path) = day_path(date, lang) else {
            continue;
        };
        let Ok(content) = fs::read_to_string(&path) else {
            continue;
        };
        let df: DayFile = match serde_json::from_str(&content) {
            Ok(d) => d,
            Err(e) => {
                log::warn!("[PulseArchive] {} parse error: {}", path.display(), e);
                continue;
            }
        };
        for it in df.items {
            // Cross-day url dedupe — a freak upstream timestamp change
            // could land the same URL in two day files; this guards
            // against double-display.
            if seen_urls.insert(it.url.clone()) {
                out.push(it);
            }
        }
    }

    // Sort key uses effective_ts (with future-guard) so a row whose
    // published_at is in the future doesn't claim the top slot. Matches
    // the frontend `itemTs()` so display order and label agree.
    let now_plus_slack = Utc::now().timestamp() + FUTURE_SLACK_SECS;
    out.sort_by(|a, b| {
        let ka = effective_ts(a, now_plus_slack);
        let kb = effective_ts(b, now_plus_slack);
        kb.cmp(ka)
    });

    out
}

/// Enumerate every `YYYY-MM-DD` we have a file for, desc.
pub fn list_all_dates(lang: &str) -> Vec<String> {
    let root = pulse_root();
    let mut dates: Vec<String> = Vec::new();

    let Ok(year_entries) = fs::read_dir(&root) else {
        return dates;
    };
    let lang_suffix = format!("_{}.json", lang);

    for ye in year_entries.flatten() {
        let yname = ye.file_name().to_string_lossy().into_owned();
        if yname.len() != 4 || !yname.chars().all(|c| c.is_ascii_digit()) {
            continue;
        }
        let Ok(month_entries) = fs::read_dir(ye.path()) else {
            continue;
        };
        for me in month_entries.flatten() {
            let mname = me.file_name().to_string_lossy().into_owned();
            if mname.len() != 2 || !mname.chars().all(|c| c.is_ascii_digit()) {
                continue;
            }
            let Ok(day_entries) = fs::read_dir(me.path()) else {
                continue;
            };
            for de in day_entries.flatten() {
                let fname = de.file_name().to_string_lossy().into_owned();
                let Some(day_part) = fname.strip_suffix(&lang_suffix) else {
                    continue;
                };
                if day_part.len() != 2 || !day_part.chars().all(|c| c.is_ascii_digit()) {
                    continue;
                }
                dates.push(format!("{}-{}-{}", yname, mname, day_part));
            }
        }
    }

    dates.sort();
    dates.reverse();
    dates
}

/// Sidebar feed: every archived date plus its item count, sorted desc.
/// Counts come from each file's `item_count` header so we don't have to
/// deserialize the items array — ~10× faster than `load_all` for the
/// "how many entries per day" question the sidebar actually asks.
pub fn date_counts(lang: &str) -> Vec<(String, usize)> {
    let dates = list_all_dates(lang);
    let mut out: Vec<(String, usize)> = Vec::with_capacity(dates.len());
    for date in dates {
        let Some(path) = day_path(&date, lang) else {
            continue;
        };
        let Ok(content) = fs::read_to_string(&path) else {
            continue;
        };
        let Ok(meta) = serde_json::from_str::<DayFileMeta>(&content) else {
            continue;
        };
        out.push((date, meta.item_count));
    }
    out
}