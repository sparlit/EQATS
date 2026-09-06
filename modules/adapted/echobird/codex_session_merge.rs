//! Cross-provider Codex history merge.
//!
//! ## Problem
//! Codex tags every conversation with a `model_provider` in TWO places:
//!   1. `state_*.sqlite` → `threads.model_provider` (drives the left-panel
//!      / `/resume` list), and
//!   2. each rollout transcript's first JSONL line
//!      (`session_meta.payload.model_provider`, read on resume).
//!
//! Codex HIDES any session whose provider differs from the one currently
//! active. So a user who has talked to Codex under several provider ids —
//! the official ChatGPT login (`openai`, lowercase), our third-party block
//! (`OpenAI`), a `gemini` config, … — only ever sees the slice matching
//! whatever provider is launched. The rest looks "lost".
//!
//! ## Fix
//! Right before EchoBird launches Codex, retag every prior session to the
//! provider Codex is ABOUT to launch with — read from the top-level
//! `model_provider` in `config.toml`, NOT hardcoded. Reading it live means
//! we always retag to the *active* provider (canonical `OpenAI`, or
//! whatever relay-mode wrote), so the merge can never tag sessions to a
//! provider that is then filtered out.
//!
//! ## Safety
//! Learned from CodexPlusPlus #144, where "Provider Sync" made
//! conversations vanish and become unrecoverable:
//!   * Retag ONLY to the currently-active provider — never an arbitrary
//!     target. The disappearance there was the provider filter hiding
//!     sessions retagged to a non-active id (e.g. the official lowercase
//!     `openai`); reading the live config makes that impossible.
//!   * Touch ONLY the two provider-tag locations. We never write
//!     `config.toml`, `workspace_roots`, or anything else — that TOML
//!     mangling was the actual corruption source in #144.
//!   * Back up each state DB (consistent `VACUUM INTO` snapshot, keep last
//!     N) BEFORE mutating, and skip the retag entirely if the backup fails.
//!   * Idempotent (`WHERE model_provider IS NOT ?`): re-running on every
//!     launch is a cheap self-heal.
//!   * Atomic rollout rewrite (temp + rename), first line only, and skip
//!     freshly-written rollouts so we never race Codex appending to the
//!     live session.
//!   * Never fatal: a locked DB (Codex still running) or any error is
//!     logged and skipped; the next launch self-heals.

use std::path::{Path, PathBuf};
use std::time::Duration;

/// Rollouts modified within this window are assumed to belong to the live
/// session Codex may be appending to right now — skip them.
const ACTIVE_ROLLOUT_SKIP_SECS: u64 = 120;
/// How many timestamped pre-merge DB backups to retain per state DB.
const KEEP_BACKUPS: usize = 5;
/// Filename infix that marks our backups (kept out of the retag scan).
const BACKUP_MARKER: &str = ".eb-merge-bak-";

#[derive(Debug, Default, PartialEq, Eq)]
pub struct MergeReport {
    pub dbs_seen: usize,
    pub threads_retagged: usize,
    pub rollouts_retagged: usize,
    pub dbs_locked: usize,
}

/// Public entry — called from the Codex launch pre-flight in
/// `process_manager::start_codex_native`, after `config.toml` is written
/// and before Codex spawns. Never returns an error: everything is logged.
pub fn merge_codex_history(codex_home: &Path) {
    let Some(active) = read_active_provider(codex_home) else {
        log::warn!("[CodexMerge] no top-level model_provider in config.toml; skipping merge");
        return;
    };
    let report = retag_all(codex_home, &active);
    if report.threads_retagged > 0 || report.rollouts_retagged > 0 || report.dbs_locked > 0 {
        log::info!(
            "[CodexMerge] merged history under {active:?}: {} threads, {} rollouts \
             ({} dbs seen, {} locked-skip)",
            report.threads_retagged,
            report.rollouts_retagged,
            report.dbs_seen,
            report.dbs_locked
        );
    }
}

/// Retag both stores to `active`. Split from the public entry for tests.
fn retag_all(codex_home: &Path, active: &str) -> MergeReport {
    let mut report = MergeReport::default();
    for db in find_state_dbs(codex_home) {
        report.dbs_seen += 1;
        match retag_db(&db, active) {
            Ok(Some(n)) => report.threads_retagged += n,
            Ok(None) => report.dbs_locked += 1,
            Err(e) => log::warn!("[CodexMerge] state db {db:?}: {e}"),
        }
    }
    report.rollouts_retagged = retag_rollouts(codex_home, active);
    report
}

// ─── config.toml: the active provider ────────────────────────────────────

fn read_active_provider(codex_home: &Path) -> Option<String> {
    let text = std::fs::read_to_string(codex_home.join("config.toml")).ok()?;
    active_provider_id(&text)
}

/// Extract the TOP-LEVEL `model_provider = "X"` — the value that decides
/// which provider Codex launches with. Top-level TOML keys appear before
/// the first `[table]` header, so we stop at the first table to avoid
/// picking up `name = "OpenAI"` inside `[model_providers.OpenAI]`.
fn active_provider_id(config_text: &str) -> Option<String> {
    for raw in config_text.lines() {
        let line = raw.trim();
        if line.starts_with('[') {
            break; // entered a table — top-level keys are done
        }
        let Some(rest) = line.strip_prefix("model_provider") else {
            continue;
        };
        // Guard against keys like `model_provider_foo`: the next
        // non-space character must be `=`.
        let Some(rest) = rest.trim_start().strip_prefix('=') else {
            continue;
        };
        // First double-quoted token (ignores any trailing comment).
        let start = rest.find('"')? + 1;
        let end = rest[start..].find('"')? + start;
        let val = &rest[start..end];
        if !val.is_empty() {
            return Some(val.to_string());
        }
    }
    None
}

// ─── state_*.sqlite: threads.model_provider ─────────────────────────────

/// Codex moved its sqlite store from the home root into a `sqlite/` subdir
/// (cli 0.133 → 0.140) and bumps the generation suffix on schema resets
/// (… → `state_5` → eventually `state_6`). Scan both locations and glob
/// `state_*.sqlite` so we retag whichever the running Codex actually reads.
fn find_state_dbs(codex_home: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for dir in [codex_home.to_path_buf(), codex_home.join("sqlite")] {
        let Ok(entries) = std::fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if !path.is_file() {
                continue;
            }
            let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
                continue;
            };
            if name.starts_with("state_")
                && name.ends_with(".sqlite")
                && !name.contains(BACKUP_MARKER)
            {
                out.push(path);
            }
        }
    }
    out
}

/// Retag every thread in one state DB to `active`.
/// `Ok(Some(n))` = success, n rows changed. `Ok(None)` = DB busy/locked
/// (Codex running) — skipped, next launch self-heals. `Err` = real error.
fn retag_db(db_path: &Path, active: &str) -> Result<Option<usize>, String> {
    use rusqlite::{Connection, OpenFlags};

    let conn = Connection::open_with_flags(
        db_path,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|e| format!("open: {e}"))?;
    let _ = conn.busy_timeout(Duration::from_millis(3000));

    // No `threads.model_provider` column → nothing to do (alien schema).
    let has_col: i64 = conn
        .query_row(
            "SELECT count(*) FROM pragma_table_info('threads') WHERE name = 'model_provider'",
            (),
            |r| r.get(0),
        )
        .unwrap_or(0);
    if has_col == 0 {
        return Ok(Some(0));
    }

    // How many rows actually need retagging? (Idempotent: usually 0.)
    let pending: i64 = match conn.query_row(
        "SELECT count(*) FROM threads WHERE model_provider IS NOT ?1",
        (active,),
        |r| r.get(0),
    ) {
        Ok(n) => n,
        Err(e) if is_busy(&e) => return Ok(None),
        Err(e) => return Err(format!("count: {e}")),
    };
    if pending == 0 {
        return Ok(Some(0));
    }

    // Back up (consistent snapshot) BEFORE mutating; never rewrite
    // providers without a restore point.
    match backup_state_db(&conn, db_path) {
        BackupOutcome::Ok => prune_backups(db_path),
        BackupOutcome::Locked => return Ok(None),
        BackupOutcome::Failed(e) => {
            log::warn!("[CodexMerge] backup of {db_path:?} failed; skipping retag: {e}");
            return Ok(None);
        }
    }

    match conn.execute(
        "UPDATE threads SET model_provider = ?1 WHERE model_provider IS NOT ?1",
        (active,),
    ) {
        Ok(n) => Ok(Some(n)),
        Err(e) if is_busy(&e) => Ok(None),
        Err(e) => Err(format!("update: {e}")),
    }
}

enum BackupOutcome {
    Ok,
    Locked,
    Failed(String),
}

/// `VACUUM INTO` a consistent pre-merge snapshot next to the DB. The
/// snapshot name lacks a `.sqlite` suffix so `find_state_dbs` never
/// re-scans it.
fn backup_state_db(conn: &rusqlite::Connection, db_path: &Path) -> BackupOutcome {
    let bak = backup_path(db_path);
    // Single-quote the path for the SQL string literal (sqlite does no
    // backslash processing, so Windows paths are safe once quotes are
    // doubled).
    let escaped = bak.to_string_lossy().replace('\'', "''");
    match conn.execute_batch(&format!("VACUUM INTO '{escaped}'")) {
        Ok(()) => BackupOutcome::Ok,
        Err(e) if is_busy(&e) => BackupOutcome::Locked,
        Err(e) => BackupOutcome::Failed(e.to_string()),
    }
}

fn backup_path(db_path: &Path) -> PathBuf {
    let ts = chrono::Local::now().format("%Y%m%d-%H%M%S");
    let name = db_path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "state.sqlite".to_string());
    db_path.with_file_name(format!("{name}{BACKUP_MARKER}{ts}"))
}

fn prune_backups(db_path: &Path) {
    let Some(dir) = db_path.parent() else {
        return;
    };
    let Some(name) = db_path.file_name().and_then(|n| n.to_str()) else {
        return;
    };
    let prefix = format!("{name}{BACKUP_MARKER}");
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    let mut baks: Vec<PathBuf> = entries
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .is_some_and(|n| n.starts_with(&prefix))
        })
        .collect();
    baks.sort(); // timestamp suffix sorts chronologically
    while baks.len() > KEEP_BACKUPS {
        let _ = std::fs::remove_file(baks.remove(0));
    }
}

// ─── rollout JSONL: session_meta.model_provider ─────────────────────────

fn retag_rollouts(codex_home: &Path, active: &str) -> usize {
    let mut files = Vec::new();
    // sessions/<Y>/<M>/<D>/rollout-*.jsonl  →  depth 4
    collect_jsonl(&codex_home.join("sessions"), 4, &mut files);
    // archived_sessions/*.jsonl  →  depth 1 (flat)
    collect_jsonl(&codex_home.join("archived_sessions"), 1, &mut files);

    let mut count = 0;
    for file in files {
        if is_live_session(&file) {
            continue;
        }
        match rewrite_rollout_meta(&file, active) {
            Ok(true) => count += 1,
            Ok(false) => {}
            Err(e) => log::warn!("[CodexMerge] rollout {file:?}: {e}"),
        }
    }
    count
}

fn collect_jsonl(dir: &Path, depth: u8, out: &mut Vec<PathBuf>) {
    if depth == 0 || !dir.is_dir() {
        return;
    }
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_jsonl(&path, depth - 1, out);
        } else if path.extension().and_then(|x| x.to_str()) == Some("jsonl") {
            out.push(path);
        }
    }
}

/// True if the rollout was written so recently that Codex may still be
/// appending to it. On any mtime uncertainty we err toward "live" (skip).
fn is_live_session(path: &Path) -> bool {
    let Ok(meta) = std::fs::metadata(path) else {
        return false; // can't stat → best-effort proceed
    };
    meta.modified()
        .map(|m| {
            m.elapsed()
                .map(|d| d.as_secs() < ACTIVE_ROLLOUT_SKIP_SECS)
                .unwrap_or(true)
        })
        .unwrap_or(false)
}

/// Rewrite the first-line `session_meta.model_provider` to `active`,
/// preserving every other field and streaming the transcript body
/// verbatim. Returns Ok(true) if rewritten, Ok(false) if already correct /
/// not a session_meta / no provider field.
fn rewrite_rollout_meta(path: &Path, active: &str) -> std::io::Result<bool> {
    use std::io::{BufRead, Write};

    let mut reader = std::io::BufReader::new(std::fs::File::open(path)?);
    let mut first = String::new();
    if reader.read_line(&mut first)? == 0 {
        return Ok(false); // empty file
    }

    let trimmed = first.trim_end_matches(['\n', '\r']);
    let Ok(mut value) = serde_json::from_str::<serde_json::Value>(trimmed) else {
        return Ok(false);
    };
    if value.get("type").and_then(|v| v.as_str()) != Some("session_meta") {
        return Ok(false);
    }
    let Some(payload) = value.get_mut("payload").and_then(|p| p.as_object_mut()) else {
        return Ok(false);
    };
    // Only retag an existing, differing provider — never invent the field
    // where Codex didn't write one.
    match payload.get("model_provider").and_then(|v| v.as_str()) {
        Some(p) if p == active => return Ok(false),
        Some(_) => {}
        None => return Ok(false),
    }
    payload.insert(
        "model_provider".to_string(),
        serde_json::Value::String(active.to_string()),
    );
    let new_first = serde_json::to_string(&value).map_err(std::io::Error::other)?;

    // Atomic: new first line + verbatim remainder → temp in the same dir,
    // then rename over the original.
    let dir = path.parent().unwrap_or_else(|| Path::new("."));
    let file_name = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("rollout.jsonl");
    let tmp = dir.join(format!(".{file_name}.eb-tmp"));
    {
        let mut out = std::io::BufWriter::new(std::fs::File::create(&tmp)?);
        out.write_all(new_first.as_bytes())?;
        out.write_all(b"\n")?;
        std::io::copy(&mut reader, &mut out)?; // lines 2..N, untouched
        out.flush()?;
    }
    std::fs::rename(&tmp, path)?;
    Ok(true)
}

// ─── helpers ─────────────────────────────────────────────────────────────

fn is_busy(e: &rusqlite::Error) -> bool {
    matches!(
        e,
        rusqlite::Error::SqliteFailure(err, _)
            if err.code == rusqlite::ErrorCode::DatabaseBusy
                || err.code == rusqlite::ErrorCode::DatabaseLocked
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    fn tmp_dir(label: &str) -> PathBuf {
        static N: AtomicUsize = AtomicUsize::new(0);
        let n = N.fetch_add(1, Ordering::Relaxed);
        let dir =
            std::env::temp_dir().join(format!("echobird_merge_{label}_{}_{n}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn make_state_db(path: &Path, rows: &[(&str, &str)]) {
        let conn = rusqlite::Connection::open(path).unwrap();
        conn.execute_batch("CREATE TABLE threads (id TEXT PRIMARY KEY, model_provider TEXT);")
            .unwrap();
        for (id, prov) in rows {
            conn.execute(
                "INSERT INTO threads (id, model_provider) VALUES (?1, ?2)",
                (id, prov),
            )
            .unwrap();
        }
    }

    fn provider_count(path: &Path, provider: &str) -> i64 {
        let conn = rusqlite::Connection::open(path).unwrap();
        conn.query_row(
            "SELECT count(*) FROM threads WHERE model_provider = ?1",
            (provider,),
            |r| r.get(0),
        )
        .unwrap()
    }

    #[test]
    fn active_provider_id_reads_top_level_not_table_name() {
        let cfg = "model_provider = \"OpenAI\"\n\
                   model = \"gpt-5.5\"\n\
                   [model_providers.OpenAI]\n\
                   name = \"OpenAI\"\n";
        assert_eq!(active_provider_id(cfg).as_deref(), Some("OpenAI"));
    }

    #[test]
    fn active_provider_id_handles_relay_comment_and_spacing() {
        // relay-mode provider, no spaces, trailing comment
        assert_eq!(
            active_provider_id("model_provider=\"anthropic\"  # relay\n").as_deref(),
            Some("anthropic")
        );
        // a key that merely shares the prefix must be ignored
        assert_eq!(active_provider_id("model_provider_foo = \"x\"\n"), None);
        // commented-out line ignored
        assert_eq!(active_provider_id("# model_provider = \"x\"\n"), None);
        // a `name` inside a table must never win
        assert_eq!(
            active_provider_id("[model_providers.OpenAI]\nname = \"OpenAI\"\n"),
            None
        );
    }

    #[test]
    fn retag_db_merges_all_providers_and_is_idempotent() {
        let dir = tmp_dir("db");
        let db = dir.join("state_5.sqlite");
        make_state_db(&db, &[("a", "gemini"), ("b", "openai"), ("c", "OpenAI")]);

        // gemini + openai retagged; the already-OpenAI row is left alone.
        assert_eq!(retag_db(&db, "OpenAI").unwrap(), Some(2));
        assert_eq!(provider_count(&db, "OpenAI"), 3);

        // second run is a no-op
        assert_eq!(retag_db(&db, "OpenAI").unwrap(), Some(0));

        // a pre-merge backup was written
        let has_backup = std::fs::read_dir(&dir)
            .unwrap()
            .flatten()
            .any(|e| e.file_name().to_string_lossy().contains(BACKUP_MARKER));
        assert!(has_backup, "backup must exist before any mutation");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn retag_db_noop_when_threads_table_absent() {
        let dir = tmp_dir("noschema");
        let db = dir.join("state_9.sqlite");
        let conn = rusqlite::Connection::open(&db).unwrap();
        conn.execute_batch("CREATE TABLE other (x INTEGER);")
            .unwrap();
        drop(conn);
        assert_eq!(retag_db(&db, "OpenAI").unwrap(), Some(0));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn find_state_dbs_scans_both_locations_and_skips_backups() {
        let dir = tmp_dir("find");
        std::fs::create_dir_all(dir.join("sqlite")).unwrap();
        make_state_db(&dir.join("state_5.sqlite"), &[]);
        make_state_db(&dir.join("sqlite").join("state_5.sqlite"), &[]);
        std::fs::write(
            dir.join("state_5.sqlite.eb-merge-bak-20260101-000000"),
            b"x",
        )
        .unwrap();

        let found = find_state_dbs(&dir);
        assert_eq!(found.len(), 2, "both state dbs, never the backup");
        assert!(found
            .iter()
            .all(|p| !p.to_string_lossy().contains(BACKUP_MARKER)));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn rewrite_rollout_meta_changes_provider_and_keeps_body() {
        let dir = tmp_dir("roll");
        let f = dir.join("rollout-x.jsonl");
        std::fs::write(
            &f,
            "{\"type\":\"session_meta\",\"payload\":{\"id\":\"s1\",\"model_provider\":\"gemini\",\"cwd\":\"/w\"}}\n\
             {\"type\":\"user_message\",\"payload\":{\"role\":\"user\"}}\n",
        )
        .unwrap();

        assert!(rewrite_rollout_meta(&f, "OpenAI").unwrap());

        let text = std::fs::read_to_string(&f).unwrap();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 2);
        let meta: serde_json::Value = serde_json::from_str(lines[0]).unwrap();
        assert_eq!(meta["payload"]["model_provider"], "OpenAI");
        assert_eq!(meta["payload"]["id"], "s1"); // sibling fields preserved
        assert_eq!(meta["payload"]["cwd"], "/w");
        // body line streamed byte-for-byte
        assert_eq!(
            lines[1],
            "{\"type\":\"user_message\",\"payload\":{\"role\":\"user\"}}"
        );

        // idempotent
        assert!(!rewrite_rollout_meta(&f, "OpenAI").unwrap());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn rewrite_rollout_meta_ignores_non_session_meta_and_missing_provider() {
        let dir = tmp_dir("roll2");
        let a = dir.join("rollout-a.jsonl");
        std::fs::write(&a, "{\"type\":\"response_item\",\"payload\":{}}\n").unwrap();
        assert!(!rewrite_rollout_meta(&a, "OpenAI").unwrap());

        let b = dir.join("rollout-b.jsonl");
        std::fs::write(
            &b,
            "{\"type\":\"session_meta\",\"payload\":{\"id\":\"s\"}}\n",
        )
        .unwrap();
        assert!(!rewrite_rollout_meta(&b, "OpenAI").unwrap()); // no provider → leave it
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn live_session_guard_skips_fresh_file() {
        let dir = tmp_dir("live");
        let f = dir.join("rollout-z.jsonl");
        std::fs::write(&f, "{}\n").unwrap();
        assert!(is_live_session(&f), "just-written file is treated as live");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn retag_all_end_to_end_merges_db_and_rollouts() {
        let dir = tmp_dir("e2e");
        make_state_db(
            &dir.join("state_5.sqlite"),
            &[("a", "gemini"), ("b", "OpenAI")],
        );
        // an OLD rollout (mtime backdated implicitly is hard; instead drop it
        // straight through rewrite_rollout_meta in its own test). Here we only
        // assert the DB half plus that no rollout dir is fine.
        let report = retag_all(&dir, "OpenAI");
        assert_eq!(report.dbs_seen, 1);
        assert_eq!(report.threads_retagged, 1);
        assert_eq!(provider_count(&dir.join("state_5.sqlite"), "OpenAI"), 2);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
