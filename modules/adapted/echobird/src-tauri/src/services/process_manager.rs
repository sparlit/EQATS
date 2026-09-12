// Process Manager �?mirrors old processManager.ts
// Manages tool processes: start/stop CLI & GUI tools, monitor PIDs

use std::collections::HashMap;
use std::process::Command;
use std::sync::Arc;
use tokio::sync::Mutex;

/// Process info for a running tool
#[derive(Debug, Clone)]
struct ProcessInfo {
    pid: u32,
}

impl ProcessInfo {
    fn new(pid: u32) -> Self {
        Self { pid }
    }
}

/// Cooldown tracker (prevents rapid restarts)
struct CooldownSet {
    tools: HashMap<String, tokio::time::Instant>,
}

impl CooldownSet {
    fn new() -> Self {
        Self {
            tools: HashMap::new(),
        }
    }

    fn is_cooling(&self, tool_id: &str) -> bool {
        if let Some(ts) = self.tools.get(tool_id) {
            ts.elapsed() < std::time::Duration::from_secs(3)
        } else {
            false
        }
    }

    fn mark(&mut self, tool_id: &str) {
        self.tools
            .insert(tool_id.to_string(), tokio::time::Instant::now());
    }
}

/// Global process manager state
pub struct ProcessManager {
    processes: HashMap<String, ProcessInfo>,
    cooldown: CooldownSet,
}

impl Default for ProcessManager {
    fn default() -> Self {
        Self::new()
    }
}

impl ProcessManager {
    pub fn new() -> Self {
        Self {
            processes: HashMap::new(),
            cooldown: CooldownSet::new(),
        }
    }

    /// Start a tool process �?mirrors old Electron processManager.startTool logic
    pub async fn start_tool(
        &mut self,
        tool_id: &str,
        start_command: Option<&str>,
        cwd: Option<&str>,
    ) -> Result<(), String> {
        if self.cooldown.is_cooling(tool_id) {
            return Err("Please wait before launching again".to_string());
        }
        self.cooldown.mark(tool_id);

        // Claude Code: ensure onboarding is marked as completed
        if tool_id == "claudecode" {
            Self::ensure_claude_onboarding();
        }

        // Desktop apps load provider config at startup, so switching the model
        // while the app is open silently fails. Restore "launch = kill +
        // restart": terminate any running instance (including one the USER
        // opened, matched by image name) first, so the spawn below is a fresh
        // process with the current config. CLI tools re-read config per
        // invocation and are never touched. (A lone multi-open request once
        // removed this; the silent-switch failures it caused hit far more
        // users — so kill is the default, no toggle.)
        if crate::services::tool_manager::is_managed_desktop_tool(tool_id)
            && self.kill_desktop_instances(tool_id)
        {
            // Let the OS release the app's single-instance lock so the relaunch
            // starts a fresh process instead of focusing the dying instance.
            tokio::time::sleep(std::time::Duration::from_millis(800)).await;
        }

        // OpenScience runs a local web server (`openscience serve`) that caches
        // config in memory — like desktop apps, a running instance won't pick up
        // a model switch until it restarts (no file watcher on openscience.json;
        // config.dispose only fires via OpenScience's own API, not external file
        // writes). Kill OUR tracked instance by PID — NOT by image name — so a
        // user's own `openscience serve` in another terminal is left untouched.
        // Freeing port 4096 also makes the post-spawn browser-open reliable.
        if matches!(tool_id, "openscience" | "dsh") && self.kill_tracked_instance(tool_id) {
            tokio::time::sleep(std::time::Duration::from_millis(800)).await;
        }

        log::info!(
            "[ProcessManager] start_tool called: tool_id={}, start_command={:?}, \
             get_tool_start_command={:?}, get_tool_command={:?}, \
             get_tool_exe_path={:?}, is_vscode_extension={}",
            tool_id,
            start_command,
            crate::services::tool_manager::get_tool_start_command(tool_id),
            crate::services::tool_manager::get_tool_command(tool_id),
            crate::services::tool_manager::get_tool_exe_path(tool_id),
            crate::services::tool_manager::is_vscode_extension(tool_id),
        );

        // Priority 0: Codex pre-flight + launch entry.
        //
        // CLI always goes through here so the codex-specific PRE-FLIGHT runs
        // (start_codex_native → ensure_canonical_config writes
        // ~/.codex/config.toml = the 127.0.0.1 proxy, + bypass_onboarding).
        // The launch itself then uses the SAME generic start_cli_tool path as
        // claude/opencode — config and launch are separate concerns, so no
        // codex-specific launch logic is needed: once config.toml points at
        // the proxy, every codex invocation (ours or the user's own) routes
        // through it.
        //
        // Desktop only goes here when a third-party (non-OpenAI) relay
        // is configured — that's the only case where the proxy is
        // actually needed. Skipping otherwise preserves Desktop's normal
        // launchUri path (Priority 2.9), which is the *only* way to
        // start a Microsoft Store install of ChatGPT; direct-exe
        // spawn would fail with "not found" because Store packages live
        // under \\WindowsApps\... not \\Programs\\.
        //
        // Phase 7: replaced the Node launcher (cmd /C node codex-launcher.cjs)
        // with a Rust-native spawn that calls the same pre-flight helpers
        // (ensure_canonical_config + bypass_onboarding) and resolves the
        // Codex binary in-process. Users no longer need Node installed.
        let needs_native_path = match tool_id {
            "codex" => true,
            "chatgptdesktop" => Self::codex_has_third_party_relay(),
            _ => false,
        };
        if needs_native_path {
            return self.start_codex_native(tool_id, cwd);
        }

        // Priority 1: If explicit command is given from frontend, use it
        if let Some(cmd) = start_command {
            log::info!(
                "[ProcessManager] Starting tool: {} with explicit command: {}",
                tool_id,
                cmd
            );
            return self.start_cli_tool(tool_id, cmd, cwd);
        }

        // Priority 2: CLI tools with startCommand in paths.json (e.g. "openclaw gateway")
        if let Some(command) = crate::services::tool_manager::get_tool_start_command(tool_id) {
            // Extract base command (first word) for existence check
            let base_cmd = command.split_whitespace().next().unwrap_or(&command);
            // A curl/scoop/choco install can drop the binary in a dir that is not
            // on EchoBird's process PATH (the installing shell's setx only affects
            // future processes). The command_exists gate alone would reject it here
            // before start_cli_tool's PATH augmentation can help. Allow the launch
            // whenever paths.json still detects the binary on disk — start_cli_tool
            // prepends its dir to PATH, so `cmd /C <command>` resolves.
            if crate::utils::platform::command_exists(base_cmd).await
                || crate::services::tool_manager::get_tool_declared_exe_path(tool_id).is_some()
            {
                log::info!(
                    "[ProcessManager] Starting CLI tool: {} with startCommand: {}",
                    tool_id,
                    command
                );
                return self.start_cli_tool(tool_id, &command, cwd);
            } else {
                log::warn!("[ProcessManager] startCommand base '{}' for tool '{}' not found in PATH, skipping", base_cmd, tool_id);
            }
        }

        // Priority 2.9: MSIX / Store app — Windows-only. shell:AppsFolder\<AUMID>
        // is UWP-specific; on macOS/Linux this would shadow the platform-correct
        // GUI exe path below (paths.darwin / paths.linux). claudedesktop and
        // chatgptdesktop ship with both an AUMID and a valid .app / Linux path.
        #[cfg(windows)]
        if let Some(uri) = crate::services::tool_manager::get_tool_launch_uri(tool_id) {
            // Prefer a directly-launchable exe on disk over the Store AUMID.
            // winget installs Claude Desktop as a Squirrel build at
            // %LOCALAPPDATA%\AnthropicClaude\Claude.exe, whose AUMID
            // (shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude) does NOT resolve —
            // explorer.exe then pops a stray folder instead of the app. A true
            // MSIX/Store install has no exe at the declared paths (it lives
            // under WindowsApps), so this returns None and we use the AUMID as
            // before — no regression for Store installs.
            if crate::services::tool_manager::get_tool_declared_exe_path(tool_id).is_none() {
                log::info!(
                    "[ProcessManager] Launching MSIX/Store app for {}: {}",
                    tool_id,
                    uri
                );
                return self.start_shell_uri(tool_id, &uri);
            }
            log::info!(
                "[ProcessManager] {} has a directly-launchable exe on disk; preferring it over the Store AUMID",
                tool_id
            );
            // fall through to Priority 3 (GUI exe)
        }

        // Priority 3: GUI executable found (for desktop apps like CodeBuddy)
        if crate::services::tool_manager::get_tool_exe_path(tool_id).is_some() {
            log::info!(
                "[ProcessManager] Found GUI exe for {}, launching as desktop app",
                tool_id
            );
            return self.start_gui_tool(tool_id).await;
        }

        // Priority 4: VS Code extension tools — launch VS Code
        if crate::services::tool_manager::is_vscode_extension(tool_id) {
            log::info!(
                "[ProcessManager] Tool {} is a VS Code extension, launching VS Code",
                tool_id
            );
            return self.launch_vscode(tool_id).await;
        }

        // Priority 5: Fall back to CLI command from paths.json "command" field
        if let Some(command) = crate::services::tool_manager::get_tool_command(tool_id) {
            // Same non-PATH install allowance as Priority 2: if paths.json still
            // detects the binary on disk, proceed — start_cli_tool prepends its
            // dir to PATH so the bare command resolves.
            if crate::utils::platform::command_exists(&command).await
                || crate::services::tool_manager::get_tool_declared_exe_path(tool_id).is_some()
            {
                log::info!(
                    "[ProcessManager] Falling back to CLI command for {}: {}",
                    tool_id,
                    command
                );
                return self.start_cli_tool(tool_id, &command, cwd);
            } else {
                log::warn!(
                    "[ProcessManager] CLI command '{}' for tool '{}' not found in PATH",
                    command,
                    tool_id
                );
            }
        }

        Err(format!("No executable or command found for tool '{}'. The tool may be installed but not in PATH.", tool_id))
    }

    /// True iff ~/.echobird/codex.json points at a non-OpenAI endpoint.
    /// Used to decide whether ChatGPT desktop needs to route through the
    /// dual-spoof launcher (third-party endpoints only) or can take the
    /// normal launchUri / GUI-exe path.
    fn codex_has_third_party_relay() -> bool {
        let relay_path = match dirs::home_dir() {
            Some(h) => h.join(".echobird").join("codex.json"),
            None => {
                log::warn!("[codex_has_third_party_relay] No home directory found");
                return false;
            }
        };

        log::info!(
            "[codex_has_third_party_relay] Checking relay config at: {:?}",
            relay_path
        );

        if !relay_path.exists() {
            log::warn!("[codex_has_third_party_relay] Relay config file does not exist");
            return false;
        }

        let content = match std::fs::read_to_string(&relay_path) {
            Ok(c) => c,
            Err(e) => {
                log::error!(
                    "[codex_has_third_party_relay] Failed to read relay config: {}",
                    e
                );
                return false;
            }
        };

        let cfg: serde_json::Value = match serde_json::from_str(&content) {
            Ok(v) => v,
            Err(e) => {
                log::error!(
                    "[codex_has_third_party_relay] Failed to parse relay config JSON: {}",
                    e
                );
                return false;
            }
        };

        let base_url = cfg.get("baseUrl").and_then(|v| v.as_str()).unwrap_or("");
        let is_third_party = !base_url.is_empty() && !base_url.contains("api.openai.com");

        log::info!(
            "[codex_has_third_party_relay] baseUrl='{}', is_third_party={}",
            base_url,
            is_third_party
        );

        is_third_party
    }

    /// Start Codex (CLI or Desktop) natively in Rust. Replaces the
    /// Phase 1-6 `node codex-launcher.cjs` indirection.
    ///
    /// Pre-flight: writes the canonical config.toml + patches Codex's
    /// global-state JSON so onboarding is skipped. Both helpers are
    /// idempotent and cheap when nothing has drifted.
    ///
    /// Spawn:
    ///   • Desktop mode tries the standalone .exe first (Programs install
    ///     or PATH), then falls back to the Microsoft Store shell URI
    ///     from tools/chatgptdesktop/paths.json.
    ///   • CLI mode tries the bundled native binary inside
    ///     @openai/codex-<triple>/vendor/... so the Rust TUI keeps a real
    ///     TTY. If that's missing we fall back to `codex.cmd` (loses TTY
    ///     in some shells but still launches).
    fn start_codex_native(&mut self, tool_id: &str, cwd: Option<&str>) -> Result<(), String> {
        use crate::services::codex_proxy;

        // Pre-flight helpers — both no-op when state is already correct.
        if let Some(codex_dir) = codex_proxy::default_codex_dir() {
            let cfg_path = codex_dir.join(codex_proxy::CODEX_CONFIG_FILENAME);
            // Relay path passed explicitly: ensure_canonical_config
            // reads it to detect relay-mode and skip the drift check
            // when the user has chosen to bypass the proxy.
            let relay_path = codex_proxy::default_relay_dir()
                .map(|d| d.join(codex_proxy::RELAY_FILENAME))
                .unwrap_or_default();
            match codex_proxy::ensure_canonical_config(&cfg_path, &relay_path) {
                Ok(out) if out.wrote => {
                    log::info!("[ProcessManager] config.toml self-healed ({})", out.reason)
                }
                Ok(_) => {}
                Err(e) => {
                    log::warn!("[ProcessManager] ensure_canonical_config failed (non-fatal): {e}")
                }
            }
            if let Err(e) = codex_proxy::bypass_onboarding(&codex_dir) {
                log::warn!("[ProcessManager] bypass_onboarding failed (non-fatal): {e}");
            }

            // Cross-provider history merge: retag every prior Codex session
            // to the provider config.toml now points at, so conversations
            // from other configs (official `openai`, our `OpenAI`, `gemini`,
            // …) all show up instead of being hidden by Codex's per-provider
            // filter. Self-healing + never fatal — a locked DB (Codex still
            // running) or any error is logged and skipped.
            crate::services::codex_session_merge::merge_codex_history(&codex_dir);
        }

        if tool_id == "chatgptdesktop" {
            self.start_codex_desktop_native(tool_id)
        } else {
            // Codex CLI launches through the SAME generic path as claude /
            // opencode: pass the bare `codex` command and let the shell
            // resolve + exec it (the npm shim's `#!/usr/bin/env node` shebang
            // is honoured). Proxy routing lives entirely in config.toml
            // (written by the pre-flight above) — config and launch are
            // separate concerns, so the launch needs no codex-specific logic.
            // OPENAI_* env is suppressed for codex inside start_cli_tool.
            self.start_cli_tool(tool_id, "codex", cwd)
        }
    }

    /// ChatGPT desktop: try direct .exe spawn first, fall back to the
    /// Windows Store shell URI if the binary lookup misses.
    fn start_codex_desktop_native(&mut self, tool_id: &str) -> Result<(), String> {
        use crate::services::codex_proxy;

        if let Some(exe) = codex_proxy::resolve_desktop_binary() {
            log::info!(
                "[ProcessManager] Launching ChatGPT desktop (native exe): {:?}",
                exe
            );
            return self.spawn_codex_desktop_exe(tool_id, &exe);
        }

        // MSIX / Microsoft Store install — launch via the shell:AppsFolder
        // URI. ChatGPT desktop no longer needs any command-line arguments,
        // so the plain shell URI is sufficient.
        // Prefer the actually-installed Store package (stable OR beta, any
        // publisher hash) over the hardcoded paths.json URI, so beta-channel
        // installs launch correctly. Fall back to paths.json when the scan
        // finds nothing (or on non-Windows).
        let uri = codex_proxy::resolve_desktop_launch_uri_scanned().or_else(|| {
            let tools_dir = crate::services::tool_manager::find_tools_dir();
            tools_dir
                .as_deref()
                .and_then(codex_proxy::resolve_desktop_launch_uri)
        });
        if let Some(uri) = uri {
            log::info!(
                "[ProcessManager] Launching ChatGPT desktop via Store URI: {}",
                uri
            );
            return self.start_shell_uri(tool_id, &uri);
        }

        Err(
            "ChatGPT not found. Install it from https://openai.com/codex or the Microsoft Store."
                .to_string(),
        )
    }

    /// Spawn the ChatGPT desktop binary detached so EchoBird isn't pinned
    /// to the GUI process lifetime.
    fn spawn_codex_desktop_exe(
        &mut self,
        tool_id: &str,
        exe: &std::path::Path,
    ) -> Result<(), String> {
        let home = dirs::home_dir().unwrap_or_default();

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const DETACHED_PROCESS: u32 = 0x00000008;
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;

            let mut cmd = Command::new(exe);
            cmd.current_dir(&home);
            cmd.creation_flags(DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP);
            match cmd.spawn() {
                Ok(child) => {
                    let pid = child.id();
                    log::info!("[ProcessManager] ChatGPT desktop PID: {pid}");
                    self.processes
                        .insert(tool_id.to_string(), ProcessInfo::new(pid));
                    Ok(())
                }
                Err(e) => Err(format!("Failed to spawn ChatGPT desktop: {e}")),
            }
        }

        #[cfg(target_os = "macos")]
        {
            // macOS app bundle: spawn the inner executable directly.
            // (We could also use `open`, but the direct path gives us a
            // real PID to track.)
            let mut cmd = Command::new(exe);
            cmd.current_dir(&home);
            match cmd.spawn() {
                Ok(child) => {
                    let pid = child.id();
                    log::info!("[ProcessManager] ChatGPT desktop PID: {pid}");
                    self.processes
                        .insert(tool_id.to_string(), ProcessInfo::new(pid));
                    Ok(())
                }
                Err(e) => Err(format!("Failed to spawn ChatGPT desktop: {e}")),
            }
        }

        #[cfg(target_os = "linux")]
        {
            // No ChatGPT desktop Linux build as of 2026-07; this branch
            // exists for completeness only.
            let _ = (tool_id, exe, home);
            Err("ChatGPT desktop is not available on Linux.".to_string())
        }
    }

    /// Start a CLI tool via terminal
    fn start_cli_tool(
        &mut self,
        tool_id: &str,
        command: &str,
        cwd: Option<&str>,
    ) -> Result<(), String> {
        let home = dirs::home_dir().unwrap_or_default();
        // Working directory for the spawned terminal: the folder the user
        // picked in the frontend launch dialog (threaded through start_tool),
        // validated to still exist on disk — fall back to home if absent so a
        // stale/deleted path never fails the spawn. Coffee-CLI-style launchpad
        // picker, minus the per-tool persistence (we re-prompt every launch).
        let work_dir = cwd
            .map(std::path::PathBuf::from)
            .filter(|p| p.is_dir())
            .unwrap_or_else(|| home.clone());
        let echobird_dir = dirs::home_dir().unwrap_or_default().join(".echobird");
        let config_path = echobird_dir.join(format!("{}.json", tool_id));

        // Read echobird config for env vars and model info
        let mut api_key_env: Option<String> = None;
        let mut base_url_env: Option<String> = None;
        let mut model_id: Option<String> = None;
        let mut custom_api_key_env_name: Option<String> = None;
        if config_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&config_path) {
                if let Ok(config) = serde_json::from_str::<serde_json::Value>(&content) {
                    api_key_env = config
                        .get("apiKey")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string());
                    base_url_env = config
                        .get("baseUrl")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string());
                    model_id = config
                        .get("modelId")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string());
                    custom_api_key_env_name = config
                        .get("envKey")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string());
                }
            }
        }

        // Codex carries its upstream out-of-band (~/.codex/config.toml + the
        // 127.0.0.1 proxy) — config and launch are separate concerns. Never
        // inject OPENAI_* env for it: that would make Codex bypass the proxy
        // and hit the third-party endpoint directly.
        if tool_id == "codex" {
            api_key_env = None;
            base_url_env = None;
            custom_api_key_env_name = None;
        }

        // Build the final command with tool-specific args
        let mut full_command = command.to_string();

        // MiMo Code / Kilo Code keep no ~/.echobird relay file — pull the
        // selection from their native config so they get the same --model
        // injection as OpenCode.
        if tool_id == "mimocode" {
            model_id = crate::services::tool_config_manager::mimocode_echobird_model();
        }
        if tool_id == "kilo" {
            model_id = crate::services::tool_config_manager::kilo_echobird_model();
        }

        // OpenCode family: append --model echobird/{modelId} to force model
        // selection (beats project-level config and the TUI's recent-model
        // history, both of which can override the global config's `model`).
        if matches!(tool_id, "opencode" | "mimocode" | "kilo") {
            if let Some(ref mid) = model_id {
                full_command = format!("{} --model echobird/{}", command, mid);
            }
        }

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;

            const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
            const CREATE_NEW_CONSOLE: u32 = 0x00000010;

            // Use cmd.exe /C to run the command — this handles .cmd/.bat scripts
            // (npm-installed tools like openclaw.cmd, codex.cmd, opencode.cmd).
            // Resolve cmd.exe via %COMSPEC% / %SystemRoot%\System32 instead of
            // relying on PATH — some users have System32 stripped from PATH.
            let mut cmd = Command::new(resolve_cmd_exe());
            cmd.args(["/C", &full_command]);
            cmd.current_dir(&work_dir);

            // Augment PATH with the detected tool's bin dir so a bare
            // `cmd /C <command>` resolves tools installed outside EchoBird's
            // process PATH. The gap: Kimi Code's curl installer drops kimi.exe
            // in ~/.kimi-code/bin and only prepends that dir to the *installing*
            // shell's PATH (setx updates future processes, but an already-running
            // EchoBird keeps the stale env) — detection still finds it via the
            // hardcoded paths.json entry, but `cmd /C kimi` can't, so the spawned
            // console flashes "not recognized" and exits. npm-installed tools
            // (claude/codex/mimo in %APPDATA%\npm) are already in PATH, so this
            // is a no-op for them; it only fills the curl/binary-install gap.
            if let Some(exe) = crate::services::tool_manager::get_tool_declared_exe_path(tool_id) {
                if let Some(bin) = std::path::Path::new(&exe).parent() {
                    let augmented = match std::env::var_os("PATH") {
                        Some(existing) => {
                            let mut joined = std::ffi::OsString::new();
                            joined.push(bin.as_os_str());
                            joined.push(";");
                            joined.push(existing);
                            joined
                        }
                        None => bin.as_os_str().to_os_string(),
                    };
                    cmd.env("PATH", augmented);
                    log::info!(
                        "[ProcessManager] Augmented PATH with detected bin for {}: {}",
                        tool_id,
                        bin.display()
                    );
                }
            }

            // Set env vars directly on the Command — they inherit properly
            if let Some(ref key) = api_key_env {
                cmd.env("OPENAI_API_KEY", key);
                if let Some(ref env_name) = custom_api_key_env_name {
                    cmd.env(env_name, key);
                }
            }
            if let Some(ref url) = base_url_env {
                cmd.env("OPENAI_BASE_URL", url);
            }

            // CREATE_NEW_CONSOLE: visible terminal window for TUI tools
            // CREATE_NEW_PROCESS_GROUP: independent process
            cmd.creation_flags(CREATE_NEW_PROCESS_GROUP | CREATE_NEW_CONSOLE);

            match cmd.spawn() {
                Ok(child) => {
                    let pid = child.id();
                    log::info!(
                        "[ProcessManager] Tool {} started with PID: {}",
                        tool_id,
                        pid
                    );
                    self.processes
                        .insert(tool_id.to_string(), ProcessInfo::new(pid));
                    // OpenScience: the spawned `openscience serve` takes ~1-3s
                    // to bind port 4096; poll + auto-open the workspace in the
                    // user's browser so they don't copy the URL from the terminal.
                    if tool_id == "openscience" {
                        tokio::spawn(Self::wait_and_open_workspace("http://localhost:4096"));
                    } else if tool_id == "dsh" {
                        tokio::spawn(Self::wait_and_open_workspace("http://localhost:3080"));
                    }
                    Ok(())
                }
                Err(e) => Err(format!("Spawn error: {}", e)),
            }
        }

        // Non-Windows: TUI tools (claude/codex/opencode etc.) need a real
        // TTY, so we can't spawn the binary as a child of the Tauri GUI —
        // we launch it inside a terminal emulator (Linux) / Terminal.app
        // (macOS). All platform detail lives in spawn_in_unix_terminal so
        // the Codex native path can share the exact same mechanism.
        #[cfg(not(windows))]
        {
            let mut env_pairs: Vec<(String, String)> = Vec::new();
            if let Some(ref key) = api_key_env {
                env_pairs.push(("OPENAI_API_KEY".to_string(), key.clone()));
                if let Some(ref env_name) = custom_api_key_env_name {
                    env_pairs.push((env_name.clone(), key.clone()));
                }
            }
            if let Some(ref url) = base_url_env {
                env_pairs.push(("OPENAI_BASE_URL".to_string(), url.clone()));
            }

            let pid = Self::spawn_in_unix_terminal(tool_id, &work_dir, &full_command, &env_pairs)?;
            log::info!(
                "[ProcessManager] Tool {} started in terminal with PID: {}",
                tool_id,
                pid
            );
            self.processes
                .insert(tool_id.to_string(), ProcessInfo::new(pid));
            if tool_id == "openscience" {
                tokio::spawn(Self::wait_and_open_workspace("http://localhost:4096"));
            } else if tool_id == "dsh" {
                tokio::spawn(Self::wait_and_open_workspace("http://localhost:3080"));
            }
            Ok(())
        }
    }

    /// Launch `full_command` inside a fresh OS terminal so a TUI gets a
    /// real TTY, returning the spawned PID. This is the single place that
    /// knows how to "open a terminal" on each Unix platform; both
    /// `start_cli_tool` and the Codex CLI native path go through it so their
    /// Linux/macOS behavior can't drift apart. `env_pairs` are exported into
    /// the launched shell (empty for tools like Codex that carry their
    /// upstream config out-of-band).
    #[cfg(not(windows))]
    fn spawn_in_unix_terminal(
        tool_id: &str,
        cwd: &std::path::Path,
        full_command: &str,
        env_pairs: &[(String, String)],
    ) -> Result<u32, String> {
        // `tool_id` only names the macOS launch script; reference it on the
        // other targets so they don't warn about an unused parameter.
        #[cfg(not(target_os = "macos"))]
        let _ = tool_id;

        // Linux: find a terminal emulator and run the command through the
        // user's login+interactive shell inside it. `-l -i` sources
        // .bashrc/.zshrc where npm/bun/cargo PATH entries live; separate
        // flags (not `-ilc`) keep fish-shell happy.
        #[cfg(target_os = "linux")]
        {
            let term = find_terminal_emulator().ok_or_else(|| {
                "No terminal emulator found. Please install one of: \
                 gnome-terminal, konsole, xfce4-terminal, alacritty, \
                 kitty, wezterm, foot, tilix, or xterm."
                    .to_string()
            })?;

            let mut cmd = Command::new(&term.binary);
            cmd.args(term.prefix_args.iter().copied());
            let user_shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/bash".into());
            // The login+interactive shell sources the user's PATH (nvm/bun/
            // cargo), but the pause wrapper is POSIX-sh syntax that non-POSIX
            // shells (fish) can't parse. Have the login shell set up the
            // environment and then `exec /bin/sh` run the wrapper, so it works
            // regardless of $SHELL.
            let wrapped = wrap_with_pause_on_quick_or_error(full_command);
            let via_posix = format!("exec /bin/sh -c {}", shell_single_quote(&wrapped));
            cmd.arg(&user_shell)
                .arg("-l")
                .arg("-i")
                .arg("-c")
                .arg(&via_posix);
            cmd.current_dir(cwd);
            for (k, v) in env_pairs {
                cmd.env(k, v);
            }

            let child = cmd.spawn().map_err(|e| {
                format!(
                    "Failed to launch terminal '{}': {}",
                    term.binary.display(),
                    e
                )
            })?;
            Ok(child.id())
        }

        // macOS: Terminal.app is system-bundled, so no detection needed.
        // Bake env exports + a re-exec into the user's login shell into a
        // cached script and hand it to `open -a Terminal`. Env can't ride on
        // `open` itself because Terminal spawns a fresh login shell. Caveat:
        // `open` exits immediately, so the captured PID belongs to `open`,
        // not the tool — is_tool_running() will report it exited shortly
        // after launch, acceptable since users close the tab themselves.
        #[cfg(target_os = "macos")]
        {
            use std::os::unix::fs::PermissionsExt;

            let cache_dir = dirs::cache_dir()
                .unwrap_or_else(|| dirs::home_dir().unwrap_or_default().join(".cache"))
                .join("echobird");
            std::fs::create_dir_all(&cache_dir)
                .map_err(|e| format!("Failed to create cache dir: {}", e))?;

            let script_path = cache_dir.join(format!("launch-{}.sh", tool_id));

            let mut script = String::from("#!/bin/bash\n");
            for (k, v) in env_pairs {
                script.push_str(&format!("export {}={}\n", k, shell_single_quote(v)));
            }
            script.push_str(&format!(
                "cd {}\n",
                shell_single_quote(&cwd.to_string_lossy())
            ));
            // Same fish-compat reasoning as the Linux branch: the login shell
            // sets up PATH, then `exec /bin/sh` runs the POSIX pause wrapper.
            let via_posix = format!(
                "exec /bin/sh -c {}",
                shell_single_quote(&wrap_with_pause_on_quick_or_error(full_command))
            );
            script.push_str(&format!(
                "exec \"${{SHELL:-/bin/bash}}\" -l -i -c {}\n",
                shell_single_quote(&via_posix)
            ));

            std::fs::write(&script_path, &script)
                .map_err(|e| format!("Failed to write launch script: {}", e))?;

            let mut perms = std::fs::metadata(&script_path)
                .map_err(|e| format!("metadata: {}", e))?
                .permissions();
            perms.set_mode(0o755);
            std::fs::set_permissions(&script_path, perms).map_err(|e| format!("chmod: {}", e))?;

            let child = Command::new("open")
                .args(["-a", "Terminal"])
                .arg(&script_path)
                .spawn()
                .map_err(|e| format!("Failed to launch Terminal.app: {}", e))?;
            Ok(child.id())
        }

        // Other unix (*BSD, etc.): no terminal-emulator probe, so fall back
        // to the historical raw spawn. Realistically unreached in prod.
        #[cfg(all(unix, not(target_os = "linux"), not(target_os = "macos")))]
        {
            let parts: Vec<&str> = full_command.split_whitespace().collect();
            if parts.is_empty() {
                return Err("Empty command".to_string());
            }
            let mut cmd = Command::new(parts[0]);
            if parts.len() > 1 {
                cmd.args(&parts[1..]);
            }
            cmd.current_dir(cwd);
            for (k, v) in env_pairs {
                cmd.env(k, v);
            }
            let child = cmd.spawn().map_err(|e| format!("Spawn error: {}", e))?;
            Ok(child.id())
        }
    }

    /// Launch VS Code for extension-based tools
    async fn launch_vscode(&mut self, tool_id: &str) -> Result<(), String> {
        log::info!(
            "[ProcessManager] Launching VS Code for extension tool: {}",
            tool_id
        );

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
            const CREATE_NO_WINDOW: u32 = 0x08000000;

            // On Windows, `code` is actually `code.cmd` in PATH. Resolve
            // cmd.exe directly so we don't rely on PATH containing System32.
            let output = Command::new(resolve_cmd_exe())
                .args(["/c", "code"])
                .creation_flags(CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW)
                .spawn()
                .map_err(|e| {
                    format!(
                        "Failed to launch VS Code: {}. Is VS Code installed and in PATH?",
                        e
                    )
                })?;

            let pid = output.id();
            log::info!(
                "[ProcessManager] VS Code launched for {} with PID: {}",
                tool_id,
                pid
            );
            self.processes
                .insert(tool_id.to_string(), ProcessInfo::new(pid));
            Ok(())
        }

        #[cfg(target_os = "macos")]
        {
            let child = Command::new("open")
                .args(["-a", "Visual Studio Code"])
                .spawn()
                .map_err(|e| format!("Failed to launch VS Code: {}. Is VS Code installed?", e))?;

            let pid = child.id();
            log::info!(
                "[ProcessManager] VS Code launched for {} with PID: {}",
                tool_id,
                pid
            );
            self.processes
                .insert(tool_id.to_string(), ProcessInfo::new(pid));
            Ok(())
        }

        #[cfg(target_os = "linux")]
        {
            let child = Command::new("code").spawn().map_err(|e| {
                format!(
                    "Failed to launch VS Code: {}. Is VS Code installed and in PATH?",
                    e
                )
            })?;

            let pid = child.id();
            log::info!(
                "[ProcessManager] VS Code launched for {} with PID: {}",
                tool_id,
                pid
            );
            self.processes
                .insert(tool_id.to_string(), ProcessInfo::new(pid));
            Ok(())
        }

        #[cfg(target_os = "android")]
        {
            let _ = tool_id;
            return Err("Not available on mobile".to_string());
        }
    }

    /// Start a GUI tool by opening its executable
    /// Launch an MSIX/Store app via shell:AppsFolder URI (Windows only).
    /// On non-Windows hosts there are no Store apps, so this is a no-op error.
    fn start_shell_uri(&mut self, tool_id: &str, uri: &str) -> Result<(), String> {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            let result = Command::new("explorer.exe")
                .arg(uri)
                .creation_flags(CREATE_NO_WINDOW)
                .spawn();
            match result {
                Ok(child) => {
                    let pid = child.id();
                    log::info!(
                        "[ProcessManager] Launched {} via shell URI, PID: {}",
                        tool_id,
                        pid
                    );
                    self.processes
                        .insert(tool_id.to_string(), ProcessInfo::new(pid));
                    Ok(())
                }
                Err(e) => Err(format!("Failed to launch via shell URI: {}", e)),
            }
        }
        #[cfg(not(windows))]
        {
            let _ = (tool_id, uri);
            Err("Shell-URI launch is Windows-only".to_string())
        }
    }

    async fn start_gui_tool(&mut self, tool_id: &str) -> Result<(), String> {
        // Look up the executable path from tool definitions
        let exe_path = crate::services::tool_manager::get_tool_exe_path(tool_id)
            .ok_or_else(|| format!("No executable path found for tool '{}'", tool_id))?;

        log::info!(
            "[ProcessManager] Starting GUI tool: {} at {}",
            tool_id,
            exe_path
        );

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
            const CREATE_NO_WINDOW: u32 = 0x08000000;

            // Launch from the executable's own directory, like a desktop
            // shortcut does. Most GUIs (incl. Electron apps such as Hermes
            // Desktop's win-unpacked build) resolve resources relative to the
            // exe, but some rely on the working directory, so match shortcut
            // behaviour to be safe.
            let work_dir = std::path::Path::new(&exe_path)
                .parent()
                .map(|p| p.to_string_lossy().to_string());
            // PowerShell single-quoted strings escape a literal apostrophe by
            // doubling it (''). Escape before interpolating so a path with an
            // apostrophe (e.g. a Windows username like O'Brien) can't break the
            // quoting or inject commands.
            let exe_q = exe_path.replace('\'', "''");
            let ps_cmd = match &work_dir {
                Some(dir) => format!(
                    "$process = Start-Process '{}' -WorkingDirectory '{}' -PassThru; Write-Output $process.Id",
                    exe_q,
                    dir.replace('\'', "''")
                ),
                None => format!(
                    "$process = Start-Process '{}' -PassThru; Write-Output $process.Id",
                    exe_q
                ),
            };

            let output = Command::new("powershell")
                .args(["-Command", &ps_cmd])
                .creation_flags(CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW)
                .output()
                .map_err(|e| format!("PowerShell error: {}", e))?;

            let pid_str = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if let Ok(pid) = pid_str.parse::<u32>() {
                log::info!(
                    "[ProcessManager] GUI tool {} started with PID: {}",
                    tool_id,
                    pid
                );
                self.processes
                    .insert(tool_id.to_string(), ProcessInfo::new(pid));
                return Ok(());
            }
            Err(format!("Failed to launch GUI tool: {}", pid_str))
        }

        #[cfg(target_os = "macos")]
        {
            // exe_path is the inner Mach-O binary (…/Foo.app/Contents/MacOS/Foo).
            // Handing that straight to `open` makes LaunchServices treat the
            // executable as a *document* and route it to the user's default
            // text editor (Sublime Text, etc.) instead of launching the app —
            // so for a bundled app we must `open` the .app BUNDLE root. A bare
            // (non-bundle) binary has no .app ancestor; `open`-ing it would hit
            // the same document trap, so spawn it directly like the Linux path.
            let child = match exe_path.rfind(".app/") {
                Some(i) => Command::new("open")
                    .arg(&exe_path[..i + ".app".len()])
                    .spawn(),
                None => Command::new(&exe_path).spawn(),
            }
            .map_err(|e| format!("Failed to launch {}: {}", tool_id, e))?;

            let pid = child.id();
            log::info!(
                "[ProcessManager] GUI tool {} started ({}), PID: {}",
                tool_id,
                exe_path,
                pid
            );
            self.processes
                .insert(tool_id.to_string(), ProcessInfo::new(pid));
            Ok(())
        }

        #[cfg(target_os = "linux")]
        {
            let child = Command::new(&exe_path)
                .spawn()
                .map_err(|e| format!("Spawn error: {}", e))?;

            let pid = child.id();
            log::info!(
                "[ProcessManager] GUI tool {} started with PID: {}",
                tool_id,
                pid
            );
            self.processes
                .insert(tool_id.to_string(), ProcessInfo::new(pid));
            Ok(())
        }

        #[cfg(target_os = "android")]
        {
            let _ = (tool_id, exe_path);
            Err("Not available on mobile".to_string())
        }
    }

    /// Ensure Claude Code onboarding is marked as completed in ~/.claude.json
    /// and settings.json has allowedTools for non-interactive use
    fn ensure_claude_onboarding() {
        // ~/.claude.json: skip onboarding (only if missing)
        let claude_json = dirs::home_dir().unwrap_or_default().join(".claude.json");
        if !claude_json.exists() {
            let config = serde_json::json!({ "hasCompletedOnboarding": true });
            if let Ok(content) = serde_json::to_string_pretty(&config) {
                let _ = std::fs::write(&claude_json, content);
                log::info!(
                    "[ProcessManager] Created {:?} (onboarding skip)",
                    claude_json
                );
            }
        }

        // ~/.claude/settings.json: ensure allowedTools exist (only if missing)
        let claude_dir = dirs::home_dir().unwrap_or_default().join(".claude");
        let _ = std::fs::create_dir_all(&claude_dir);
        let settings_path = claude_dir.join("settings.json");
        if !settings_path.exists() {
            let settings = serde_json::json!({
                "allowedTools": ["Edit","Write","Bash","Read","MultiEdit","Glob","Grep","LS","TodoRead","TodoWrite","WebFetch","NotebookRead","NotebookEdit"]
            });
            if let Ok(content) = serde_json::to_string_pretty(&settings) {
                let _ = std::fs::write(&settings_path, content);
                log::info!(
                    "[ProcessManager] Created {:?} (allowedTools)",
                    settings_path
                );
            }
        }
    }

    /// Stop a running tool by PID
    pub async fn stop_tool(&mut self, tool_id: &str) -> Result<(), String> {
        let info = self
            .processes
            .remove(tool_id)
            .ok_or_else(|| "Tool is not running".to_string())?;

        log::info!(
            "[ProcessManager] Stopping tool: {} (PID: {})",
            tool_id,
            info.pid
        );

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            // Windows: taskkill /T /F to kill process tree
            let output = Command::new("taskkill")
                .args(["/pid", &info.pid.to_string(), "/T", "/F"])
                .creation_flags(CREATE_NO_WINDOW)
                .output()
                .map_err(|e| format!("taskkill error: {}", e))?;

            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                if !stderr.contains("not found") {
                    log::error!("[ProcessManager] taskkill stderr: {}", stderr);
                }
            }
        }

        #[cfg(not(windows))]
        {
            // Unix: SIGKILL
            unsafe {
                libc::kill(info.pid as i32, libc::SIGKILL);
            }
        }

        Ok(())
    }

    /// Kill every running instance of a desktop tool — by process image name
    /// (so it also catches an instance the USER launched, which we have no
    /// tracked PID for) and by dropping our own tracked PID. Returns true if
    /// anything was killed. Desktop-only: callers gate on
    /// `tool_manager::is_desktop_tool`. Restores "launch = kill + restart" so
    /// switching the model actually takes effect — a running desktop app loaded
    /// the OLD provider config at startup and won't pick up the change.
    fn kill_desktop_instances(&mut self, tool_id: &str) -> bool {
        // Drop our tracked PID so is_tool_running stays honest; the image-name
        // kill below terminates that process anyway.
        self.processes.remove(tool_id);

        let names = crate::services::tool_manager::get_tool_process_names(tool_id);
        let mut killed = false;
        for name in &names {
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                const CREATE_NO_WINDOW: u32 = 0x08000000;
                // /T also reaps the Electron helper-process tree.
                if let Ok(out) = Command::new("taskkill")
                    .args(["/IM", name.as_str(), "/F", "/T"])
                    .creation_flags(CREATE_NO_WINDOW)
                    .output()
                {
                    killed |= out.status.success();
                }
            }
            #[cfg(not(windows))]
            {
                // macOS/Linux: match the exact process (binary) name.
                if let Ok(out) = Command::new("pkill").args(["-x", name.as_str()]).output() {
                    killed |= out.status.success();
                }
            }
        }
        if killed {
            log::info!(
                "[ProcessManager] killed running instances of {tool_id} ({names:?}) for kill+restart"
            );
        }
        killed
    }

    /// Kill only the PID EchoBird spawned for `tool_id` (if any), leaving any
    /// user-started instance of the same binary running. Used by serve-style
    /// tools (OpenScience) where kill+restart is needed for a config/model
    /// switch to take effect, but a blanket image-name kill (like
    /// `kill_desktop_instances`) would nuke a user's own manually-started
    /// instance. Mirrors `stop_all`'s per-PID kill, scoped to one tool.
    ///
    /// A liveness pre-check guards the PID-reuse window: if the user already
    /// closed the serve terminal, the tracked PID is dead and we skip the kill
    /// so a later-reused PID is never force-killed. (`check_processes` reaps
    /// dead PIDs too but is only called on app quit; this runs on every
    /// relaunch, so check inline.) Residual risk: a reused PID that is alive
    /// as another process would still be killed — rare, since relaunch usually
    /// follows close quickly and Windows doesn't recycle PIDs instantly.
    fn kill_tracked_instance(&mut self, tool_id: &str) -> bool {
        let info = match self.processes.remove(tool_id) {
            Some(info) => info,
            None => return false,
        };
        let pid = info.pid;
        if !Self::pid_is_alive(pid) {
            log::info!("[ProcessManager] tracked {tool_id} PID {pid} already exited — skip kill");
            return false;
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            let killed = Command::new("taskkill")
                .args(["/pid", &pid.to_string(), "/T", "/F"])
                .creation_flags(CREATE_NO_WINDOW)
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false);
            if killed {
                log::info!("[ProcessManager] killed tracked {tool_id} PID {pid} for kill+restart");
            }
            killed
        }
        #[cfg(not(windows))]
        {
            unsafe {
                libc::kill(pid as i32, libc::SIGKILL);
            }
            log::info!("[ProcessManager] killed tracked {tool_id} PID {pid} for kill+restart");
            true
        }
    }

    /// Whether the process owning `pid` is still running. Used by
    /// `kill_tracked_instance` to skip dead (already-closed) PIDs.
    #[cfg(windows)]
    fn pid_is_alive(pid: u32) -> bool {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        // tasklist prints "No tasks are running which match..." when the PID is
        // gone; any other non-empty output means a process owns it.
        let Ok(out) = Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
        else {
            return false;
        };
        let s = String::from_utf8_lossy(&out.stdout);
        !s.contains("No tasks") && !s.trim().is_empty()
    }

    #[cfg(not(windows))]
    fn pid_is_alive(pid: u32) -> bool {
        // kill -0 returns 0 if the process exists, -1 (ESRCH) otherwise.
        unsafe { libc::kill(pid as i32, 0) == 0 }
    }

    /// After spawning a serve-style tool, poll its loopback URL and open the
    /// workspace in the user's default browser once it responds. We killed any
    /// tracked old instance first (see `start_tool`), so the port is free and the
    /// new serve lands there. Best-effort: on timeout the spawned terminal has
    /// already printed the real URL (which may differ if the port was taken by an
    /// unrelated app), so the user can still open it manually — we just log.
    async fn wait_and_open_workspace(url: &'static str) {
        let client = match reqwest::Client::builder()
            .timeout(std::time::Duration::from_millis(800))
            .build()
        {
            Ok(c) => c,
            Err(e) => {
                log::warn!("[ProcessManager] workspace probe client build failed: {e}");
                return;
            }
        };
        // Bound the whole probe to ~10s wall-clock, not a fixed iteration count:
        // a non-HTTP app squatting on the port could otherwise hold each request
        // for the full per-request timeout and inflate the loop manyfold. The
        // kill-old step frees the port for our serve, so the common path resolves
        // in a few hundred ms (Bun-compiled binary binds in ~1-3s).
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
        while std::time::Instant::now() < deadline {
            if client.get(url).send().await.is_ok() {
                Self::open_in_browser(url);
                log::info!("[ProcessManager] workspace ready at {url}, opened in browser");
                return;
            }
            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
        }
        log::warn!(
            "[ProcessManager] workspace did not respond at {url} within ~10s — \
             open the URL printed in the serve terminal manually (the port may differ if taken)"
        );
    }

    /// Open a URL in the user's default browser, platform-native, no window flash.
    fn open_in_browser(url: &str) {
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            // `start "" <url>` — the empty title arg prevents `start` from
            // treating the URL as a window title.
            let _ = Command::new("cmd")
                .args(["/C", "start", "", url])
                .creation_flags(CREATE_NO_WINDOW)
                .spawn();
        }
        #[cfg(target_os = "macos")]
        {
            let _ = Command::new("open").arg(url).spawn();
        }
        #[cfg(target_os = "linux")]
        {
            let _ = Command::new("xdg-open").arg(url).spawn();
        }
    }

    /// Get list of running tool IDs
    pub fn get_running_tools(&self) -> Vec<String> {
        self.processes.keys().cloned().collect()
    }

    /// Check if a tool is running
    pub fn is_tool_running(&self, tool_id: &str) -> bool {
        self.processes.contains_key(tool_id)
    }

    /// Stop all tools (called on app quit)
    pub fn stop_all(&mut self) {
        log::info!("[ProcessManager] Stopping all tools...");
        let tool_ids: Vec<String> = self.processes.keys().cloned().collect();

        for tool_id in &tool_ids {
            if let Some(info) = self.processes.remove(tool_id) {
                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    const CREATE_NO_WINDOW: u32 = 0x08000000;
                    let _ = Command::new("taskkill")
                        .args(["/pid", &info.pid.to_string(), "/T", "/F"])
                        .creation_flags(CREATE_NO_WINDOW)
                        .output();
                }
                #[cfg(not(windows))]
                {
                    unsafe {
                        libc::kill(info.pid as i32, libc::SIGKILL);
                    }
                }
            }
        }
    }

    /// Monitor running processes (check if PIDs still exist)
    #[cfg(windows)]
    pub async fn check_processes(&mut self) -> Vec<String> {
        let mut exited = Vec::new();

        for (tool_id, info) in &self.processes {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            let output = Command::new("tasklist")
                .args(["/FI", &format!("PID eq {}", info.pid), "/FO", "CSV", "/NH"])
                .creation_flags(CREATE_NO_WINDOW)
                .output();

            match output {
                Ok(out) => {
                    let stdout = String::from_utf8_lossy(&out.stdout);
                    if stdout.contains("No tasks") || stdout.trim().is_empty() {
                        log::info!(
                            "[ProcessManager] Tool {} (PID: {}) exited externally",
                            tool_id,
                            info.pid
                        );
                        exited.push(tool_id.clone());
                    }
                }
                Err(_) => {
                    exited.push(tool_id.clone());
                }
            }
        }

        for id in &exited {
            self.processes.remove(id);
        }

        exited
    }

    #[cfg(not(windows))]
    pub async fn check_processes(&mut self) -> Vec<String> {
        let mut exited = Vec::new();

        for (tool_id, info) in &self.processes {
            let alive = unsafe { libc::kill(info.pid as i32, 0) == 0 };
            if !alive {
                log::info!(
                    "[ProcessManager] Tool {} (PID: {}) exited externally",
                    tool_id,
                    info.pid
                );
                exited.push(tool_id.clone());
            }
        }

        for id in &exited {
            self.processes.remove(id);
        }

        exited
    }
}

// ─── Platform helpers ───

// Resolve cmd.exe via %COMSPEC% / %SystemRoot%\System32 instead of trusting
// PATH. Some environments (AV-cleaned, custom-policy, or tampered user PATH)
// drop System32, which makes bare `Command::new("cmd")` fail with "file not
// found". WezTerm / VS Code / Hyper all use the same fallback chain.
#[cfg(windows)]
fn resolve_cmd_exe() -> std::path::PathBuf {
    if let Ok(comspec) = std::env::var("COMSPEC") {
        let p = std::path::PathBuf::from(&comspec);
        if p.exists() {
            return p;
        }
    }
    if let Ok(sysroot) = std::env::var("SystemRoot") {
        let p = std::path::PathBuf::from(sysroot)
            .join("System32")
            .join("cmd.exe");
        if p.exists() {
            return p;
        }
    }
    std::path::PathBuf::from("cmd")
}

// Single-quote-wrap a string for safe inclusion in a POSIX shell command
// line. Embedded single quotes become '\''. Used to quote binary paths and
// env values that get spliced into `shell -c` strings (macOS launch script
// and the Codex CLI native path).
#[cfg(not(windows))]
fn shell_single_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}

// Wrap a user command so the terminal stays open when the tool exits quickly
// or with a non-zero status. The heuristic catches two real failure modes:
//   - tool not found / immediate error  -> non-zero exit, user needs to read it
//   - tool ran < 2s and exited 0        -> probably printed `--help` and quit;
//                                          user wants to see what it printed
// A long-running TUI (e.g. claude) that the user `/quit`s normally exits 0
// after >2s, so the terminal closes cleanly — no extra Enter press needed.
#[cfg(any(target_os = "linux", target_os = "macos"))]
fn wrap_with_pause_on_quick_or_error(cmd: &str) -> String {
    let mut s = String::new();
    s.push_str("start_ts=$(date +%s); ");
    s.push_str(cmd);
    s.push_str("; ec=$?; end_ts=$(date +%s); elapsed=$((end_ts - start_ts)); ");
    s.push_str("if [ $ec -ne 0 ] || [ $elapsed -lt 2 ]; then ");
    s.push_str("echo; echo \"[exit=$ec, ran ${elapsed}s -- press Enter to close]\"; ");
    s.push_str("read -r _; ");
    s.push_str("fi");
    s
}

#[cfg(target_os = "linux")]
struct TerminalLauncher {
    binary: std::path::PathBuf,
    /// Args that go between the terminal binary and the user command, e.g.
    /// `gnome-terminal --` or `xterm -e`. After these we always append
    /// `bash -lc <full_command>`.
    prefix_args: &'static [&'static str],
}

// Probe the user's system for a usable terminal emulator. Order matters:
// `x-terminal-emulator` is the Debian/Ubuntu meta-binary that already points
// at whatever the user picked, so it's the most user-respecting choice. The
// rest are fallbacks ordered roughly by ubiquity.
#[cfg(target_os = "linux")]
fn find_terminal_emulator() -> Option<TerminalLauncher> {
    const CANDIDATES: &[(&str, &[&str])] = &[
        ("x-terminal-emulator", &["-e"]),
        ("gnome-terminal", &["--"]),
        ("konsole", &["-e"]),
        // xfce4-terminal/tilix accept argv after `-x`; `-e` wants a single string.
        ("xfce4-terminal", &["-x"]),
        ("tilix", &["-x"]),
        ("alacritty", &["-e"]),
        ("kitty", &[]),
        ("wezterm", &["start", "--"]),
        ("foot", &[]),
        ("xterm", &["-e"]),
    ];

    for &(name, prefix_args) in CANDIDATES {
        if let Ok(path) = which::which(name) {
            return Some(TerminalLauncher {
                binary: path,
                prefix_args,
            });
        }
    }
    None
}

// ─── Global singleton ───

use tokio::sync::OnceCell;

static PROCESS_MANAGER: OnceCell<Arc<Mutex<ProcessManager>>> = OnceCell::const_new();

async fn get_manager() -> Arc<Mutex<ProcessManager>> {
    PROCESS_MANAGER
        .get_or_init(|| async { Arc::new(Mutex::new(ProcessManager::new())) })
        .await
        .clone()
}

/// Start a tool process
pub async fn start_tool(
    tool_id: &str,
    start_command: Option<&str>,
    cwd: Option<&str>,
) -> Result<(), String> {
    let mgr = get_manager().await;
    let mut mgr = mgr.lock().await;
    mgr.start_tool(tool_id, start_command, cwd).await
}