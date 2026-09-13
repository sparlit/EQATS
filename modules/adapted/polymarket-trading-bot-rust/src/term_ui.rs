//! Terminal presentation: colors when stderr is a TTY and `NO_COLOR` is unset.
//! Set `FORCE_COLOR=1` to enable styling when stderr is not a TTY (e.g. some IDE runners).
//! On-disk logs use `strip_ansi_for_file` in `log_to_history`.

use owo_colors::OwoColorize;
use std::io::IsTerminal;

/// Inner width between box borders (characters inside `║ … ║`).
pub const FRAME_INNER: usize = 76;

/// Strip ANSI escapes for history files and structured logs.
pub fn strip_ansi_for_file(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    let mut chars = input.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\x1b' {
            match chars.peek() {
                Some('[') => {
                    chars.next();
                    for ch in chars.by_ref() {
                        if ('\x40'..='\x7e').contains(&ch) {
                            break;
                        }
                    }
                }
                Some(']') => {
                    chars.next();
                    for ch in chars.by_ref() {
                        if ch == '\x07' || ch == '\x1b' {
                            break;
                        }
                    }
                }
                _ => {}
            }
        } else {
            out.push(c);
        }
    }
    out
}

fn use_color() -> bool {
    if std::env::var_os("NO_COLOR").is_some() {
        return false;
    }
    match std::env::var_os("FORCE_COLOR") {
        Some(v) if v.is_empty() || v == "1" || v == "true" => return true,
        Some(v) if v == "0" || v == "false" => {}
        Some(_) => return true,
        None => {}
    }
    std::io::stderr().is_terminal()
}

/// Full-width bar with centered title (total width = [`FRAME_INNER`]).
fn section_bar(title: &str) -> String {
    let t = format!(" {} ", title);
    let tl = t.chars().count();
    if tl >= FRAME_INNER {
        return "═".repeat(FRAME_INNER);
    }
    let dashes = FRAME_INNER - tl;
    let left = dashes / 2;
    let right = dashes - left;
    format!("{}{}{}", "═".repeat(left), t, "═".repeat(right))
}

fn print_section_bar_styled(title: &str) {
    let bar = section_bar(title);
    eprintln!(
        "{}",
        paint(&bar, || format!("{}", bar.truecolor(100, 130, 175).bold()))
    );
}

fn paint<F: FnOnce() -> String>(plain: &str, f: F) -> String {
    if use_color() {
        f()
    } else {
        plain.to_string()
    }
}

/// Bid/ask pair like `$0.65/$0.67` — higher contrast; cool tones for Up, warm for Down.
fn dollar_pair_styled(pair: &str, up_leg: bool) -> String {
    if pair == "N/A" {
        return format!("{}", pair.truecolor(100, 108, 120));
    }
    let Some(idx) = pair.find('/') else {
        return pair.to_string();
    };
    let bid = &pair[..idx];
    let ask = &pair[idx + 1..];
    if up_leg {
        format!(
            "{}{}{}",
            format!("{}", bid.bold().truecolor(85, 255, 175)),
            format!("{}", "/".truecolor(65, 95, 80)),
            format!("{}", ask.bold().truecolor(175, 255, 230))
        )
    } else {
        format!(
            "{}{}{}",
            format!("{}", bid.bold().truecolor(255, 130, 105)),
            format!("{}", "/".truecolor(95, 60, 58)),
            format!("{}", ask.bold().truecolor(255, 210, 188))
        )
    }
}

fn top_rule() -> String {
    let fill: String = "═".repeat(FRAME_INNER);
    let inner = paint(&fill, || format!("{}", fill.truecolor(72, 98, 140)));
    format!("╔{}╗", inner)
}

fn bottom_rule() -> String {
    let fill: String = "═".repeat(FRAME_INNER);
    let inner = paint(&fill, || format!("{}", fill.truecolor(72, 98, 140)));
    format!("╚{}╝", inner)
}

/// Compact startup header (replaces large ASCII art).
pub fn print_startup_banner(simulation: bool, limit_price: f64, history_path: &str) {
    let mode = if simulation {
        paint("SIMULATION", || format!("{}", "SIMULATION".bold().yellow()))
    } else {
        paint("LIVE", || format!("{}", "LIVE".bold().red()))
    };
    let line1 = paint("Polymarket Trading Bot", || {
        format!("{}", "Polymarket Trading Bot".bold().cyan())
    });
    let line2_plain = format!("Dual-limit ${:.2} · {} · {}", limit_price, mode, history_path);
    let line2 = paint(&line2_plain, || format!("{}", line2_plain.dimmed()));

    eprintln!();
    eprintln!("{}", top_rule());
    eprintln!("║ {:^w$} ║", line1, w = FRAME_INNER);
    eprintln!("║ {:^w$} ║", line2, w = FRAME_INNER);
    eprintln!("{}", bottom_rule());
    eprintln!();
}

pub fn print_rule_dim() {
    let r: String = "─".repeat(FRAME_INNER);
    eprintln!(
        "{}",
        paint(&r, || format!("{}", r.truecolor(75, 85, 100)))
    );
}

pub fn print_section_title(title: &str) {
    let chev = paint("▶", || format!("{}", "▶".truecolor(255, 200, 90).bold()));
    let t = paint(title, || format!("{}", title.bold().truecolor(245, 248, 255)));
    eprintln!("  {} {}", chev, t);
    let u: String = "─".repeat((FRAME_INNER.saturating_sub(4)).max(20));
    eprintln!(
        "    {}",
        paint(&u, || format!("{}", u.truecolor(85, 95, 115)))
    );
}

pub fn print_simulation_hint() {
    let bar_t = section_bar(" SIMULATION · NO REAL ORDERS ");
    let line1 = "Live order book only — nothing is posted to the exchange.";
    let line2 = "To trade live: omit --simulation / -s (default is production), or pass --no-simulation.";
    if !use_color() {
        eprintln!("{}", bar_t);
        eprintln!("  {}", line1);
        eprintln!("  {}", line2);
        eprintln!();
        return;
    }
    eprintln!(
        "{}",
        format!("{}", bar_t.truecolor(255, 190, 70).bold())
    );
    eprintln!(
        "  {} {}",
        format!("{}", "⚠".bold().truecolor(255, 200, 80)),
        format!("{}", line1.bold().truecolor(255, 240, 210))
    );
    eprintln!(
        "    {}",
        format!("{}", line2.truecolor(200, 210, 230))
    );
    eprintln!();
}

/// One line for `log_to_history` / stderr (ANSI stripped for files).
pub fn print_discover_section_start(asset: &str) {
    if !use_color() {
        eprintln!("🔍 Discovering {} market…", asset);
        return;
    }
    eprintln!(
        "{} {} {}",
        "🔍".truecolor(255, 200, 90).bold(),
        format!("{}", "Discovering".truecolor(165, 180, 200)),
        format!("{}", format!("{} market…", asset).bold().truecolor(255, 220, 100))
    );
}

pub fn format_portfolio_sync_banner() -> String {
    let plain = "🔄 Syncing pending trades with portfolio balance…";
    paint(plain, || {
        format!(
            "{} {}",
            "🔄".truecolor(95, 200, 255).bold(),
            "Syncing pending trades with portfolio balance…"
                .bold()
                .truecolor(225, 235, 250)
        )
    })
}

/// After resolving an active up/down market (both outcomes trade under this condition).
pub fn print_market_found(asset: &str, slug: &str, condition_id: &str) {
    if !use_color() {
        eprintln!(
            "✅ Found {} market  📈 Up  ·  📉 Down",
            asset
        );
        eprintln!("   Slug       {}", slug);
        eprintln!("   Condition  {}", condition_id);
        return;
    }
    eprintln!(
        "{} {} {} {}",
        "✅".truecolor(90, 255, 140).bold(),
        format!("{}", "Found".bold().truecolor(235, 245, 255)),
        format!("{}", asset.bold().truecolor(255, 215, 95)),
        format!(
            "{}",
            "· 📈 Up · 📉 Down"
                .bold()
                .truecolor(140, 200, 255)
        )
    );
    eprintln!(
        "   {} {}",
        format!("{}", "Slug".bold().truecolor(120, 140, 165)),
        format!("{}", slug.truecolor(215, 225, 245))
    );
    eprintln!(
        "   {} {}",
        format!("{}", "Condition".bold().truecolor(120, 140, 165)),
        format!("{}", condition_id.truecolor(200, 210, 235))
    );
}

pub fn print_discover_alt_slug_prefix(market_name: &str, prefix: &str) {
    if !use_color() {
        eprintln!(
            "🔍 Trying {} market with slug prefix '{}'…",
            market_name, prefix
        );
        return;
    }
    eprintln!(
        "{} {} {} {}",
        "🔍".truecolor(255, 200, 90).bold(),
        format!("{}", market_name.bold().truecolor(255, 220, 100)),
        format!("{}", "slug prefix".truecolor(140, 155, 175)),
        format!("{}", format!("'{}'", prefix).truecolor(165, 220, 255))
    );
}

pub fn print_discover_try_previous_slug(market_name: &str, try_slug: &str) {
    if !use_color() {
        eprintln!(
            "🔁 Trying previous {} market · {}",
            market_name, try_slug
        );
        return;
    }
    eprintln!(
        "{} {} {} {}",
        "🔁".truecolor(255, 175, 95),
        format!("{}", "Previous slot".truecolor(150, 165, 185)),
        format!("{}", market_name.bold().truecolor(255, 210, 90)),
        format!("{}", try_slug.truecolor(185, 210, 250))
    );
}

pub fn print_monitoring_start() {
    if !use_color() {
        eprintln!("📡 Starting market monitoring…");
        return;
    }
    eprintln!(
        "{} {}",
        "📡".truecolor(120, 210, 255).bold(),
        format!(
            "{}",
            "Starting market monitoring…"
                .bold()
                .truecolor(200, 230, 255)
        )
    );
}

/// One outcome token (📈 UP / 📉 DOWN) for CLOB order books.
pub fn print_outcome_token_id(market: &str, is_up: bool, token_id: &str) {
    let (icon, side_plain) = if is_up {
        ("📈", "UP")
    } else {
        ("📉", "DOWN")
    };
    if !use_color() {
        eprintln!("  {}  {:<7}  {}  {}", icon, market, side_plain, token_id);
        return;
    }
    let side_styled = if is_up {
        format!("{}", side_plain.bold().truecolor(95, 255, 165))
    } else {
        format!("{}", side_plain.bold().truecolor(255, 115, 125))
    };
    eprintln!(
        "  {}  {}  {}  {}",
        icon,
        format!("{}", market.bold().truecolor(255, 215, 95)),
        side_styled,
        format!("{}", token_id.truecolor(210, 218, 235))
    );
}

pub fn print_auth_start() {
    print_section_title("CLOB authentication");
}

pub fn print_auth_success(
    proxy_line: Option<&str>,
    api_key_preview: &str,
    signer_line: Option<&str>,
    signature_type: Option<u8>,
) {
    let top = format!("┌{}┐", "─".repeat(FRAME_INNER));
    let bot = format!("└{}┘", "─".repeat(FRAME_INNER));
    if !use_color() {
        eprintln!("{}", top);
        eprintln!("  ✓  Session ready");
        eprintln!("  ✓  API key  {}", api_key_preview);
        if let Some(s) = signer_line {
            eprintln!("  ✓  Signer   {}", s);
        }
        match proxy_line {
            Some(p) => eprintln!("  ✓  Proxy    {}", p),
            None => eprintln!("  ✓  Account  EOA (no proxy)"),
        }
        if let Some(sig) = signature_type {
            eprintln!("  ✓  SigType  {}", sig);
        }
        eprintln!("{}", bot);
        eprintln!();
        return;
    }
    eprintln!(
        "{}",
        format!("{}", top.truecolor(90, 100, 120))
    );
    let ok = format!("{}", "✓".bold().truecolor(80, 255, 130));
    eprintln!(
        "  {}  {}",
        ok,
        format!("{}", "Session ready".bold().truecolor(235, 240, 255))
    );
    eprintln!(
        "  {}  {} {}",
        ok,
        format!("{}", "API key".bold().truecolor(160, 175, 195)),
        format!("{}", api_key_preview.truecolor(220, 230, 245))
    );
    if let Some(s) = signer_line {
        eprintln!(
            "  {}  {} {}",
            ok,
            format!("{}", "Signer".bold().truecolor(160, 175, 195)),
            format!("{}", s.truecolor(220, 230, 245))
        );
    }
    match proxy_line {
        Some(p) => {
            eprintln!(
                "  {}  {} {}",
                ok,
                format!("{}", "Proxy".bold().truecolor(160, 175, 195)),
                format!("{}", p.truecolor(220, 230, 245))
            );
        }
        None => {
            eprintln!(
                "  {}  {}",
                ok,
                format!("{}", "Account: EOA (no proxy)".truecolor(185, 195, 210))
            );
        }
    }
    if let Some(sig) = signature_type {
        eprintln!(
            "  {}  {} {}",
            ok,
            format!("{}", "SigType".bold().truecolor(160, 175, 195)),
            format!("{}", sig.to_string().truecolor(220, 230, 245))
        );
    }
    eprintln!(
        "{}",
        format!("{}", bot.truecolor(90, 100, 120))
    );
    eprintln!();
}

/// Separator between colored quote segments (visible but not loud).
pub fn pipe_sep_colored() -> String {
    paint(" │ ", || format!("{}", " │ ".truecolor(78, 88, 105)))
}

/// One market row for the live quote line (plain text matches `price_log_line` slices).
pub fn fmt_btc_book(up: &str, down: &str) -> String {
    let plain = format!("📊 BTC: U{} D{}", up, down);
    paint(&plain, || {
        format!(
            "{} {} {}{} {}{}",
            format!("{}", "📊".truecolor(255, 210, 75).bold()),
            format!("{}", "BTC".bold().truecolor(248, 252, 255)),
            format!("{}", "U".bold().truecolor(120, 235, 160)),
            dollar_pair_styled(up, true),
            format!("{}", " D".bold().truecolor(255, 150, 125)),
            dollar_pair_styled(down, false)
        )
    })
}

pub fn fmt_eth_book(up: &str, down: &str) -> String {
    let plain = format!("ETH: U{} D{}", up, down);
    paint(&plain, || {
        format!(
            "{} {}{} {}{}",
            format!("{}", "ETH".bold().truecolor(130, 195, 255)),
            format!("{}", "U".bold().truecolor(120, 235, 160)),
            dollar_pair_styled(up, true),
            format!("{}", " D".bold().truecolor(255, 150, 125)),
            dollar_pair_styled(down, false)
        )
    })
}

pub fn fmt_sol_book(up: &str, down: &str) -> String {
    let plain = format!("SOL: U{} D{}", up, down);
    paint(&plain, || {
        format!(
            "{} {}{} {}{}",
            format!("{}", "SOL".bold().truecolor(110, 235, 245)),
            format!("{}", "U".bold().truecolor(120, 235, 160)),
            dollar_pair_styled(up, true),
            format!("{}", " D".bold().truecolor(255, 150, 125)),
            dollar_pair_styled(down, false)
        )
    })
}

pub fn fmt_xrp_book(up: &str, down: &str) -> String {
    let plain = format!("XRP: U{} D{}", up, down);
    paint(&plain, || {
        format!(
            "{} {}{} {}{}",
            format!("{}", "XRP".bold().truecolor(230, 160, 255)),
            format!("{}", "U".bold().truecolor(120, 235, 160)),
            dollar_pair_styled(up, true),
            format!("{}", " D".bold().truecolor(255, 150, 125)),
            dollar_pair_styled(down, false)
        )
    })
}

pub fn fmt_countdown(timer: &str) -> String {
    let plain = format!("⏱️  {}", timer);
    paint(&plain, || {
        format!(
            "{} {}",
            format!("{}", "⏱".bold().truecolor(70, 200, 255)),
            format!("{}", timer.bold().truecolor(150, 235, 255))
        )
    })
}

/// Chainlink spot vs price-to-beat (replaces plain `| BTC $…` tail).
pub fn fmt_chainlink_beat(btc_now: f64, beat: Option<f64>) -> String {
    let plain = match beat {
        Some(b) => {
            let d = btc_now - b;
            format!("| BTC ${:.0} beat ${:.0} Δ{:+.0}", btc_now, b, d)
        }
        None => format!("| BTC ${:.0} beat -", btc_now),
    };
    paint(&plain, || match beat {
        Some(b) => {
            let d = btc_now - b;
            let delta = if d >= 0.0 {
                format!("{}", format!(" Δ{:+.0}", d).bold().truecolor(90, 255, 150))
            } else {
                format!("{}", format!(" Δ{:+.0}", d).bold().truecolor(255, 100, 120))
            };
            format!(
                "{} {} {}{}{}{}",
                format!("{}", "| ".truecolor(72, 80, 96)),
                format!("{}", "BTC".bold().truecolor(245, 248, 255)),
                format!("{}", format!("${:.0}", btc_now).bold().truecolor(255, 215, 95)),
                format!("{}", " beat ".truecolor(130, 138, 150)),
                format!("{}", format!("${:.0}", b).bold().truecolor(205, 185, 255)),
                delta,
            )
        }
        None => format!(
            "{} {} {}{}",
            format!("{}", "| ".truecolor(72, 80, 96)),
            format!("{}", "BTC".bold().truecolor(245, 248, 255)),
            format!("{}", format!("${:.0}", btc_now).bold().truecolor(255, 215, 95)),
            format!("{}", " beat —".truecolor(145, 152, 170))
        ),
    })
}

/// Optional trailing status (e.g. hedge/trailing line) — high visibility.
pub fn fmt_trailing_status_line(s: &str) -> String {
    paint(s, || {
        format!(
            "{} {}",
            format!("{}", "⚡".truecolor(255, 185, 60).bold()),
            format!("{}", s.bold().truecolor(175, 230, 255))
        )
    })
}

/// Chainlink / price-to-beat suffix (plain body already has leading `|`).
pub fn fmt_oracle_tail(line: &str) -> String {
    paint(line, || format!("{}", line.truecolor(210, 175, 255)))
}

pub fn fmt_trailing_note(line: &str) -> String {
    paint(line, || format!("{}", line.italic().dimmed()))
}

/// Price tick for `log_to_history`: ANSI on stderr path, strip for files.
pub fn format_price_tick_line(iso_timestamp: &str, body: &str) -> String {
    if !use_color() {
        return format!("[{}] {}\n", iso_timestamp, strip_ansi_for_file(body));
    }
    let mid = if body.contains('\x1b') {
        body.to_string()
    } else {
        format!("{}", body.bold().truecolor(228, 232, 240))
    };
    format!(
        "{}{}{}\n",
        format!("{}", iso_timestamp.truecolor(115, 125, 140)),
        format!("{}", " │ ".truecolor(65, 75, 90)),
        mid
    )
}

pub fn trend_banner(elapsed_m: u64, elapsed_s: u64) -> String {
    let text_plain = format!(" ▶ Trend report · {:02}m {:02}s ", elapsed_m, elapsed_s);
    if use_color() {
        format!(
            " {}{}{}{}\n",
            format!("{}", "▶".truecolor(255, 200, 55).bold()),
            format!("{}", " Trend report".bold().truecolor(250, 250, 255)),
            format!("{}", " · ".truecolor(95, 105, 120)),
            format!(
                "{}",
                format!("{:02}m {:02}s", elapsed_m, elapsed_s)
                    .bold()
                    .truecolor(80, 205, 255)
            ),
        )
    } else {
        format!("{}\n", text_plain)
    }
}

pub fn trend_banner_end() -> String {
    let line: String = "─".repeat(FRAME_INNER);
    format!(
        "{}\n",
        paint(&line, || format!("{}", line.truecolor(70, 78, 92)))
    )
}

pub fn sim_divider() -> String {
    let line: String = "─".repeat(FRAME_INNER.saturating_sub(2));
    format!(
        "{}\n",
        paint(&line, || format!("{}", line.truecolor(68, 76, 92)))
    )
}

pub fn format_trend_row(
    label: &str,
    direction_label: &str,
    strength: f64,
    price_change: f64,
    slope: f64,
    duration: u64,
    samples: usize,
) -> String {
    let dir_styled = if direction_label.contains("UPTREND") {
        paint(direction_label, || {
            format!(
                "{}",
                direction_label
                    .bold()
                    .truecolor(70, 255, 140)
            )
        })
    } else if direction_label.contains("DOWNTREND") {
        paint(direction_label, || {
            format!(
                "{}",
                direction_label
                    .bold()
                    .truecolor(255, 95, 110)
            )
        })
    } else if direction_label.contains("SIDEWAYS") {
        paint(direction_label, || {
            format!(
                "{}",
                direction_label
                    .bold()
                    .truecolor(255, 220, 90)
            )
        })
    } else {
        paint(direction_label, || {
            format!("{}", direction_label.bold().truecolor(180, 185, 195))
        })
    };

    let lbl = paint(label, || format!("{}", label.bold().truecolor(120, 215, 255)));

    if !use_color() {
        return format!(
            "  {:<12} {:<12}  str {:>5.3}  Δ {:>+7.4}  slope {:>9.6}/s  {:>4}s  n={}",
            label, direction_label, strength, price_change, slope, duration, samples
        );
    }

    let str_v = format!("{}", format!("{:.3}", strength).bold().truecolor(255, 210, 120));
    let delta_v = format!(
        "{}",
        format!("{:+.4}", price_change)
            .bold()
            .truecolor(165, 235, 255)
    );
    let slope_v = format!("{}", format!("{:.6}", slope).truecolor(195, 200, 215));
    format!(
        "  {} {}   {} {}   {} {}   {} {}/s   {}s   n={}",
        lbl,
        dir_styled,
        format!("{}", "str".truecolor(120, 128, 142)),
        str_v,
        format!("{}", "Δ".truecolor(120, 128, 142)),
        delta_v,
        format!("{}", "slope".truecolor(120, 128, 142)),
        slope_v,
        format!("{}", format!("{}", duration).bold().truecolor(230, 235, 245)),
        samples
    )
}

pub fn format_trend_insufficient(label: &str, min_samples: usize) -> String {
    let lbl = paint(label, || format!("{}", label.bold().truecolor(120, 215, 255)));
    let tail = format!("… need ≥{} samples", min_samples);
    let tail_s = paint(&tail, || format!("{}", tail.truecolor(130, 138, 150)));
    format!("  {:<12} {}", lbl, tail_s)
}

pub fn format_sim_head(market: &str, m: u64, s: u64) -> String {
    let plain = format!("  {}  {:>3}m {:02}s", market, m, s);
    paint(&plain, || {
        format!(
            "  {}  {}{} {:02}s",
            format!("{}", market.bold().truecolor(255, 210, 85)),
            format!("{}", format!("{:>3}", m).bold().truecolor(100, 200, 255)),
            format!("{}", "m".truecolor(120, 130, 145)),
            s,
        )
    })
}

pub fn format_sim_prices(
    up_bid: f64,
    up_ask: f64,
    up_at_limit: bool,
    down_bid: f64,
    down_ask: f64,
    down_at_limit: bool,
) -> String {
    let u_pair = format!("${:.2}/${:.2}", up_bid, up_ask);
    let d_pair = format!("${:.2}/${:.2}", down_bid, down_ask);
    let mark_u = if up_at_limit { "●@0.45" } else { "○     " };
    let mark_d = if down_at_limit { "●@0.45" } else { "○     " };

    let u_s = paint(&u_pair, || {
        format!(
            "{}{}",
            format!("{}", "Up ".bold().truecolor(140, 255, 175)),
            dollar_pair_styled(&u_pair, true)
        )
    });
    let d_s = paint(&d_pair, || {
        format!(
            "{}{}",
            format!("{}", "Dn ".bold().truecolor(255, 165, 140)),
            dollar_pair_styled(&d_pair, false)
        )
    });
    let mu = if up_at_limit {
        paint(mark_u, || format!("{}", mark_u.bold().truecolor(255, 235, 100)))
    } else {
        paint(mark_u, || format!("{}", mark_u.truecolor(85, 95, 110)))
    };
    let md = if down_at_limit {
        paint(mark_d, || format!("{}", mark_d.bold().truecolor(255, 235, 100)))
    } else {
        paint(mark_d, || format!("{}", mark_d.truecolor(85, 95, 110)))
    };

    let sep = paint(" · ", || format!("{}", " · ".truecolor(75, 82, 95)));
    format!("     {} {}  {}  {} {}", u_s, mu, sep, d_s, md)
}

pub fn format_sim_fills(up_filled: bool, down_filled: bool) -> String {
    let a = format!("Up={}", if up_filled { "yes" } else { "no" });
    let b = format!("Dn={}", if down_filled { "yes" } else { "no" });
    let a_s = paint(&a, || {
        format!(
            "{} {}",
            "Up=".truecolor(120, 128, 142),
            if up_filled {
                format!("{}", "yes".bold().truecolor(85, 255, 150))
            } else {
                format!("{}", "no".truecolor(110, 118, 130))
            }
        )
    });
    let b_s = paint(&b, || {
        format!(
            "{} {}",
            "Dn=".truecolor(120, 128, 142),
            if down_filled {
                format!("{}", "yes".bold().truecolor(85, 255, 150))
            } else {
                format!("{}", "no".truecolor(110, 118, 130))
            }
        )
    });
    format!("     fills  {}  {}", a_s, b_s)
}

/// `SIM [BTC] …` status for `log_println!`.
pub fn format_sim_tag_line(market: &str, detail: &str) -> String {
    let plain = format!("SIM [{}] {}", market, detail);
    paint(&plain, || {
        format!(
            "  {} {}{}{} {}",
            format!("{}", "SIM".bold().truecolor(255, 115, 210)),
            format!("{}", "[".truecolor(100, 108, 120)),
            format!("{}", market.bold().truecolor(255, 220, 95)),
            format!("{}", "]".truecolor(100, 108, 120)),
            format!("{}", detail.bold().truecolor(235, 240, 250))
        )
    })
}

pub fn print_strategy_config(
    limit_price: f64,
    early_min: u64,
    std_min: u64,
    hedge_px: f64,
    trailing: f64,
    shares_line: &str,
    markets_line: &str,
) {
    let top = format!("┌{}┐", "─".repeat(FRAME_INNER));
    let bot = format!("└{}┘", "─".repeat(FRAME_INNER));

    let line_orders = format!(
        "Limit buys: BTC, ETH, SOL, XRP — Up & Down @ {}",
        format!("${:.2}", limit_price)
    );
    let line_hedge = format!(
        "One-sided fill → hedge: {}m (early) or {}m (standard) if unfilled ask ≥ {}; \
         1× market buy + cancel open limit.",
        early_min,
        std_min,
        format!("${:.2}", hedge_px)
    );
    let line_trail = format!(
        "2m trailing hedge: lowest unfilled + {:.3} → market buy at ask \
         (dual_limit_hedge_trailing_stop).",
        trailing
    );

    print_section_bar_styled(" TRADING STRATEGY ");

    if !use_color() {
        eprintln!("{}", top);
        eprintln!("  • {}", line_orders);
        eprintln!("  • {}", line_hedge);
        eprintln!("  • {}", line_trail);
        eprintln!("  • {}", shares_line);
        eprintln!("  • {}", markets_line);
        eprintln!("{}", bot);
        return;
    }

    eprintln!(
        "{}",
        format!("{}", top.truecolor(90, 100, 120))
    );
    eprintln!(
        "  {} {}",
        format!("{}", "•".bold().truecolor(255, 200, 90)),
        format!(
            "{}{}",
            "Limit buys: BTC, ETH, SOL, XRP — Up & Down @ "
                .truecolor(185, 195, 210),
            format!("{}", format!("${:.2}", limit_price).bold().truecolor(255, 220, 100))
        )
    );
    eprintln!(
        "  {} {}",
        format!("{}", "•".bold().truecolor(255, 200, 90)),
        format!(
            "{}{} {}{} {}{} {}",
            "One-sided fill ".truecolor(185, 195, 210),
            "→ hedge:".bold().truecolor(235, 240, 255),
            format!("{}", format!("{}m ", early_min).bold().truecolor(120, 220, 255)),
            "(early) ".truecolor(150, 160, 175),
            format!("{}", format!("{}m ", std_min).bold().truecolor(120, 220, 255)),
            "(standard) ".truecolor(150, 160, 175),
            format!(
                "{} {}{} {}",
                "if unfilled ask ≥".truecolor(185, 195, 210),
                format!("{}", format!("${:.2}", hedge_px).bold().truecolor(255, 220, 100)),
                "; ".truecolor(185, 195, 210),
                "1× market buy + cancel limit.".bold().truecolor(200, 255, 190)
            )
        )
    );
    eprintln!(
        "  {} {}",
        format!("{}", "•".bold().truecolor(255, 200, 90)),
        format!(
            "{}{} {}{}",
            "2m trail: ".bold().truecolor(120, 215, 255),
            "lowest unfilled + ".truecolor(185, 195, 210),
            format!("{}", format!("{:.3}", trailing).bold().truecolor(255, 220, 100)),
            " → market buy at ask · dual_limit_hedge_trailing_stop"
                .truecolor(185, 195, 210)
        )
    );
    eprintln!(
        "  {} {} {}",
        format!("{}", "•".bold().truecolor(255, 200, 90)),
        format!("{}", "Size ·".bold().truecolor(160, 175, 195)),
        format!("{}", shares_line.truecolor(235, 240, 250))
    );
    let markets_rest = markets_line
        .strip_prefix("Markets: ")
        .unwrap_or(markets_line);
    eprintln!(
        "  {} {} {}",
        format!("{}", "•".bold().truecolor(255, 200, 90)),
        format!("{}", "Markets ·".bold().truecolor(160, 175, 195)),
        format!("{}", markets_rest.bold().truecolor(130, 230, 255))
    );
    eprintln!(
        "{}",
        format!("{}", bot.truecolor(90, 100, 120))
    );
}