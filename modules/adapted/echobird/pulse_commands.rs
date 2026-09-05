//! Tauri IPC for the AI Pulse on-disk archive.
//!
//! The frontend (`src/pages/AiPulse`) used to keep everything in
//! localStorage, capped at 3000 items, and lost on every WebView
//! origin reset (which happens on Tauri upgrades). These commands move
//! the archive to `~/.echobird/pulse/` so it survives reinstalls and
//! the only cap is the user's disk.

use crate::services::pulse_archive::{self, NewsItem};

/// Append/merge `items` into the per-day archive for `lang`. Returns the
/// total number of items now resident across all touched day-files —
/// purely informational; the frontend doesn't currently use it but the
/// return value is cheap to compute and useful in logs.
#[tauri::command]
pub fn pulse_save(lang: String, items: Vec<NewsItem>) -> Result<usize, String> {
    pulse_archive::save_fanout(&lang, items)
}

/// Pull every archived item for `lang` into memory, newest-first.
#[tauri::command]
pub fn pulse_load_all(lang: String) -> Vec<NewsItem> {
    pulse_archive::load_all(&lang)
}

/// `[(date, item_count)]` for every archived day. Used by the sidebar
/// so it can render even if `pulse_load_all` is slow on cold cache.
#[tauri::command]
pub fn pulse_list_dates(lang: String) -> Vec<(String, usize)> {
    pulse_archive::date_counts(&lang)
}
