//! Load the private CLOB SDK from a shared library (.so / .dylib / .dll).
//! Set `LIBCOB_SDK_SO` to the path of the .so, or place versioned builds in `./lib/`:
//! - `lib/libclob_sdk-ubuntu-22.04.so` — glibc from Ubuntu 22.04 (runs on 22.04 and usually 24.04)
//! - `lib/libclob_sdk-ubuntu-24.04.so` — glibc from Ubuntu 24.04 (do not use on 22.04)
//! Legacy `lib/libclob_sdk.so` is still tried last. On Linux, Ubuntu `VERSION_ID` from
//! `/etc/os-release` picks the best candidate; `dlopen` is attempted in order until one succeeds.
//!
//! **CLOB V2 (2026):** Replace the bundled library with a build from Polymarket’s current
//! `rs-clob-client` / official release that targets `https://clob.polymarket.com` and V2 order signing.

use std::ffi::{c_char, c_int, CString};
use std::os::raw::c_ulonglong;
use std::path::Path;
use std::str::FromStr;
use std::sync::OnceLock;

use alloy::primitives::Address;

use anyhow::{Context, Result};
use libloading::Library;

/// Contract addresses from the .so (same shape as SDK ContractConfig).
/// Uses alloy::Address so this module does not depend on polymarket-client-sdk.
pub struct ContractConfig {
    pub exchange: Address,
    pub collateral: Address,
    pub conditional_tokens: Address,
    pub neg_risk_adapter: Option<Address>,
}

static LIB: OnceLock<Result<Library, String>> = OnceLock::new();

#[cfg(target_os = "linux")]
fn parse_os_release_ids() -> Option<(String, String)> {
    let content = std::fs::read_to_string("/etc/os-release").ok()?;
    let mut id = None::<String>;
    let mut version_id = None::<String>;
    for line in content.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("ID=") {
            id = Some(rest.trim_matches('"').to_string());
        } else if let Some(rest) = line.strip_prefix("VERSION_ID=") {
            version_id = Some(rest.trim_matches('"').to_string());
        }
    }
    Some((id?, version_id?))
}

fn push_lib_pair(out: &mut Vec<String>, name: &str) {
    out.push(format!("lib/{name}"));
    out.push(format!("src/lib/{name}"));
}

fn clob_sdk_candidate_paths() -> Vec<String> {
    let mut out = Vec::new();
    if let Ok(p) = std::env::var("LIBCOB_SDK_SO") {
        if Path::new(&p).exists() {
            out.push(p);
        }
    }
    #[cfg(target_os = "linux")]
    {
        if let Some((id, ver)) = parse_os_release_ids() {
            if id == "ubuntu" {
                push_lib_pair(&mut out, &format!("libclob_sdk-ubuntu-{ver}.so"));
                if ver == "24.04" {
                    // 22.04-linked .so often works on 24.04 if the 24.04 build fails to load.
                    push_lib_pair(&mut out, "libclob_sdk-ubuntu-22.04.so");
                }
            }
        }
        push_lib_pair(&mut out, "libclob_sdk.so");
    }
    #[cfg(not(target_os = "linux"))]
    {
        push_lib_pair(&mut out, "libclob_sdk.so");
    }
    out
}

fn open_first_loadable_library() -> Result<Library, String> {
    let mut attempts = Vec::new();
    for path in clob_sdk_candidate_paths() {
        if !Path::new(&path).exists() {
            continue;
        }
        match unsafe { Library::new(&path) } {
            Ok(lib) => return Ok(lib),
            Err(e) => attempts.push(format!("{path}: {e}")),
        }
    }
    if attempts.is_empty() {
        return Err(
            "CLOB SDK shared library not found. Set LIBCOB_SDK_SO to the path of the SDK .so, \
             or add lib/libclob_sdk-ubuntu-22.04.so and lib/libclob_sdk-ubuntu-24.04.so (see module docs)."
                .to_string(),
        );
    }
    Err(format!(
        "Failed to load any CLOB SDK candidate. Tried:\n{}\n\
         If you see GLIBC_ errors, use the .so built for your Ubuntu version (22.04 vs 24.04).",
        attempts.join("\n")
    ))
}

fn load_lib() -> Result<&'static Library> {
    let lib = LIB
        .get_or_init(open_first_loadable_library)
        .as_ref()
        .map_err(|e| {
            let mut msg = e.clone();
            if msg.contains("GLIBC_") {
                msg.push_str(
                    "\n\nGlibc mismatch: the .so was linked for a newer glibc than this OS. \
                     On Ubuntu 22.04 use lib/libclob_sdk-ubuntu-22.04.so; on 24.04 use \
                     lib/libclob_sdk-ubuntu-24.04.so (or set LIBCOB_SDK_SO).",
                );
            }
            anyhow::anyhow!("{msg}")
        })?;
    Ok(lib)
}

/// Polygon mainnet chain ID (137). From the loaded .so.
pub fn polygon_chain_id() -> u64 {
    let lib = match load_lib() {
        Ok(l) => l,
        Err(_) => return 137, // fallback if .so not loaded yet and we're in a path that can't fail
    };
    let f: libloading::Symbol<unsafe extern "C" fn() -> c_ulonglong> =
        unsafe { lib.get(b"clob_sdk_polygon_chain_id") }.unwrap();
    unsafe { f() as u64 }
}

fn read_string_from_ffi(
    lib: &Library,
    fn_name: &[u8],
    chain_id: u64,
    neg_risk: bool,
) -> Result<Option<String>> {
    let mut buf = [0u8; 64];
    let f: libloading::Symbol<
        unsafe extern "C" fn(c_ulonglong, c_int, *mut c_char, usize) -> c_int,
    > = unsafe { lib.get(fn_name) }.context("FFI symbol not found")?;
    let ret = unsafe { f(chain_id as c_ulonglong, neg_risk as c_int, buf.as_mut_ptr() as *mut c_char, buf.len()) };
    if ret != 0 {
        return Ok(None); // chain not supported
    }
    let len = buf.iter().position(|&b| b == 0).unwrap_or(buf.len());
    let s = std::str::from_utf8(&buf[..len]).context("FFI returned invalid UTF-8")?;
    Ok(Some(s.to_string()))
}

/// Get contract config from the loaded SDK .so. Same as SDK's contract_config(chain_id, is_neg_risk).
pub fn contract_config(chain_id: u64, is_neg_risk: bool) -> Result<Option<ContractConfig>> {
    let lib = load_lib()?;
    let exchange = match read_string_from_ffi(
        lib,
        b"clob_sdk_contract_exchange_address",
        chain_id,
        is_neg_risk,
    )? {
        Some(s) => s,
        None => return Ok(None),
    };
    let collateral = match read_string_from_ffi(
        lib,
        b"clob_sdk_contract_collateral_address",
        chain_id,
        is_neg_risk,
    )? {
        Some(s) => s,
        None => return Ok(None),
    };
    let conditional_tokens = match read_string_from_ffi(
        lib,
        b"clob_sdk_contract_ctf_address",
        chain_id,
        is_neg_risk,
    )? {
        Some(s) => s,
        None => return Ok(None),
    };
    let neg_risk_adapter = read_string_from_ffi(
        lib,
        b"clob_sdk_contract_neg_risk_adapter_address",
        chain_id,
        is_neg_risk,
    )?
    .and_then(|s| if s.trim().is_empty() { None } else { Some(s) });

    let exchange = Address::from_str(exchange.trim()).context("Invalid exchange address from SDK")?;
    let collateral = Address::from_str(collateral.trim()).context("Invalid collateral address from SDK")?;
    let conditional_tokens =
        Address::from_str(conditional_tokens.trim()).context("Invalid CTF address from SDK")?;
    let neg_risk_adapter = neg_risk_adapter
        .as_ref()
        .and_then(|s| Address::from_str(s.trim()).ok());

    Ok(Some(ContractConfig {
        exchange,
        collateral,
        conditional_tokens,
        neg_risk_adapter,
    }))
}

/// Ensure the SDK .so is loaded and return POLYGON chain id. Use this where the bot currently uses POLYGON.
pub fn polygon() -> u64 {
    polygon_chain_id()
}

// ---------- Client FFI (create, orders, balance) ----------

const ERR_BUF_LEN: usize = 512;

fn copy_rust_to_c(s: &str) -> Result<CString> {
    CString::new(s).context("CString from Rust string")
}

/// Create authenticated CLOB client. Returns handle (non-zero) on success.
/// funder: None for EOA; Some(proxy_wallet_address) for proxy/safe.
/// signature_type: 0 = Eoa, 1 = Proxy, 2 = GnosisSafe.
pub fn client_create(
    clob_url: &str,
    private_key_hex: &str,
    chain_id: u64,
    funder: Option<&str>,
    signature_type: u8,
    api_key: &str,
    api_secret: &str,
    api_passphrase: &str,
) -> Result<u64> {
    let lib = load_lib()?;
    let create: libloading::Symbol<
        unsafe extern "C" fn(
            *const c_char,
            *const c_char,
            c_ulonglong,
            *const c_char,
            c_int,
            *const c_char,
            *const c_char,
            *const c_char,
            *mut c_char,
            usize,
        ) -> c_ulonglong,
    > = unsafe { lib.get(b"clob_sdk_client_create") }.with_context(|| {
            format!(
                "symbol clob_sdk_client_create not found in CLOB SDK library. \
                 Your .so only exports contract/chain symbols (polygon_chain_id, contract_*). \
                 Authentication and orders need a full build that also exports: client_create, client_destroy, \
                 post_limit_order, post_market_order, balance_allowance, update_balance_allowance, tick_size, neg_risk. \
                 Rebuild the CLOB SDK with the client/order FFI included, or set LIBCOB_SDK_SO to that .so."
            )
        })?;

    let c_url = copy_rust_to_c(clob_url)?;
    let c_pk = copy_rust_to_c(private_key_hex.trim_start_matches("0x"))?;
    let c_funder = funder
        .map(|s| copy_rust_to_c(s.trim()))
        .transpose()?;
    let c_key = copy_rust_to_c(api_key)?;
    let c_secret = copy_rust_to_c(api_secret)?;
    let c_pass = copy_rust_to_c(api_passphrase)?;

    let mut err_buf = vec![0i8; ERR_BUF_LEN];
    let handle = unsafe {
        create(
            c_url.as_ptr(),
            c_pk.as_ptr(),
            chain_id as c_ulonglong,
            c_funder.as_ref().map(|s| s.as_ptr()).unwrap_or(std::ptr::null()),
            signature_type as c_int,
            c_key.as_ptr(),
            c_secret.as_ptr(),
            c_pass.as_ptr(),
            err_buf.as_mut_ptr(),
            err_buf.len(),
        )
    };
    if handle == 0 {
        let len = err_buf.iter().position(|&b| b == 0).unwrap_or(ERR_BUF_LEN);
        let msg = std::str::from_utf8(unsafe { std::slice::from_raw_parts(err_buf.as_ptr() as *const u8, len) })
            .unwrap_or("unknown error");
        anyhow::bail!("CLOB client create failed: {}", msg);
    }
    Ok(handle)
}

/// Destroy client. Call when done with the handle.
pub fn client_destroy(handle: u64) -> Result<()> {
    let lib = load_lib()?;
    let destroy: libloading::Symbol<unsafe extern "C" fn(c_ulonglong) -> c_int> =
        unsafe { lib.get(b"clob_sdk_client_destroy") }.context("clob_sdk_client_destroy not found")?;
    let ret = unsafe { destroy(handle) };
    if ret != 0 {
        anyhow::bail!("client_destroy failed for handle {}", handle);
    }
    Ok(())
}

/// Post limit order. Returns order_id on success.
pub fn post_limit_order(
    handle: u64,
    token_id: &str,
    side: &str,
    price: &str,
    size: &str,
) -> Result<String> {
    let lib = load_lib()?;
    let f: libloading::Symbol<
        unsafe extern "C" fn(
            c_ulonglong,
            *const c_char,
            *const c_char,
            *const c_char,
            *const c_char,
            *mut c_char,
            usize,
            *mut c_char,
            usize,
        ) -> c_int,
    > = unsafe { lib.get(b"clob_sdk_post_limit_order") }.context("clob_sdk_post_limit_order not found")?;

    let c_token = copy_rust_to_c(token_id)?;
    let c_side = copy_rust_to_c(side)?;
    let c_price = copy_rust_to_c(price)?;
    let c_size = copy_rust_to_c(size)?;
    let mut order_id_buf = vec![0i8; 128];
    let mut err_buf = vec![0i8; ERR_BUF_LEN];

    let ret = unsafe {
        f(
            handle,
            c_token.as_ptr(),
            c_side.as_ptr(),
            c_price.as_ptr(),
            c_size.as_ptr(),
            order_id_buf.as_mut_ptr(),
            order_id_buf.len(),
            err_buf.as_mut_ptr(),
            err_buf.len(),
        )
    };
    if ret != 0 {
        let len = err_buf.iter().position(|&b| b == 0).unwrap_or(ERR_BUF_LEN);
        anyhow::bail!(
            "{}",
            std::str::from_utf8(unsafe { std::slice::from_raw_parts(err_buf.as_ptr() as *const u8, len) })
                .unwrap_or("unknown")
        );
    }
    let len = order_id_buf.iter().position(|&b| b == 0).unwrap_or(order_id_buf.len());
    Ok(String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(order_id_buf.as_ptr() as *const u8, len) }).into_owned())
}

/// Post market order. amount_is_usdc: true = amount in pUSD (collateral notional), false = amount in shares. order_type: "FOK" or "FAK".
pub fn post_market_order(
    handle: u64,
    token_id: &str,
    side: &str,
    amount: &str,
    amount_is_usdc: bool,
    order_type: &str,
) -> Result<String> {
    let lib = load_lib()?;
    let f: libloading::Symbol<
        unsafe extern "C" fn(
            c_ulonglong,
            *const c_char,
            *const c_char,
            *const c_char,
            c_int,
            *const c_char,
            *mut c_char,
            usize,
            *mut c_char,
            usize,
        ) -> c_int,
    > = unsafe { lib.get(b"clob_sdk_post_market_order") }.context("clob_sdk_post_market_order not found")?;

    let c_token = copy_rust_to_c(token_id)?;
    let c_side = copy_rust_to_c(side)?;
    let c_amount = copy_rust_to_c(amount)?;
    let c_ot = copy_rust_to_c(order_type)?;
    let mut order_id_buf = vec![0i8; 128];
    let mut err_buf = vec![0i8; ERR_BUF_LEN];

    let ret = unsafe {
        f(
            handle,
            c_token.as_ptr(),
            c_side.as_ptr(),
            c_amount.as_ptr(),
            if amount_is_usdc { 1 } else { 0 },
            c_ot.as_ptr(),
            order_id_buf.as_mut_ptr(),
            order_id_buf.len(),
            err_buf.as_mut_ptr(),
            err_buf.len(),
        )
    };
    if ret != 0 {
        let len = err_buf.iter().position(|&b| b == 0).unwrap_or(ERR_BUF_LEN);
        anyhow::bail!(
            "{}",
            std::str::from_utf8(unsafe { std::slice::from_raw_parts(err_buf.as_ptr() as *const u8, len) })
                .unwrap_or("unknown")
        );
    }
    let len = order_id_buf.iter().position(|&b| b == 0).unwrap_or(order_id_buf.len());
    Ok(String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(order_id_buf.as_ptr() as *const u8, len) }).into_owned())
}

/// Fetch balance and allowance for token. asset_type: "Collateral" (pUSD) or "Conditional".
pub fn balance_allowance(
    handle: u64,
    token_id: &str,
    asset_type: &str,
) -> Result<(String, String)> {
    let lib = load_lib()?;
    let f: libloading::Symbol<
        unsafe extern "C" fn(
            c_ulonglong,
            *const c_char,
            *const c_char,
            *mut c_char,
            usize,
            *mut c_char,
            usize,
            *mut c_char,
            usize,
        ) -> c_int,
    > = unsafe { lib.get(b"clob_sdk_balance_allowance") }.context("clob_sdk_balance_allowance not found")?;

    let c_token = copy_rust_to_c(token_id)?;
    let c_at = copy_rust_to_c(asset_type)?;
    let mut balance_buf = vec![0i8; 64];
    let mut allowance_buf = vec![0i8; 64];
    let mut err_buf = vec![0i8; ERR_BUF_LEN];

    let ret = unsafe {
        f(
            handle,
            c_token.as_ptr(),
            c_at.as_ptr(),
            balance_buf.as_mut_ptr(),
            balance_buf.len(),
            allowance_buf.as_mut_ptr(),
            allowance_buf.len(),
            err_buf.as_mut_ptr(),
            err_buf.len(),
        )
    };
    if ret != 0 {
        let len = err_buf.iter().position(|&b| b == 0).unwrap_or(ERR_BUF_LEN);
        anyhow::bail!(
            "{}",
            std::str::from_utf8(unsafe { std::slice::from_raw_parts(err_buf.as_ptr() as *const u8, len) })
                .unwrap_or("unknown")
        );
    }
    let blen = balance_buf.iter().position(|&b| b == 0).unwrap_or(balance_buf.len());
    let alen = allowance_buf.iter().position(|&b| b == 0).unwrap_or(allowance_buf.len());
    let balance = String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(balance_buf.as_ptr() as *const u8, blen) }).into_owned();
    let allowance = String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(allowance_buf.as_ptr() as *const u8, alen) }).into_owned();
    Ok((balance, allowance))
}

/// Update balance/allowance cache. asset_type: "Collateral" or "Conditional".
pub fn update_balance_allowance(handle: u64, token_id: &str, asset_type: &str) -> Result<()> {
    let lib = load_lib()?;
    let f: libloading::Symbol<
        unsafe extern "C" fn(c_ulonglong, *const c_char, *const c_char, *mut c_char, usize) -> c_int,
    > = unsafe { lib.get(b"clob_sdk_update_balance_allowance") }.context("clob_sdk_update_balance_allowance not found")?;

    let c_token = copy_rust_to_c(token_id)?;
    let c_at = copy_rust_to_c(asset_type)?;
    let mut err_buf = vec![0i8; ERR_BUF_LEN];
    let ret = unsafe { f(handle, c_token.as_ptr(), c_at.as_ptr(), err_buf.as_mut_ptr(), err_buf.len()) };
    if ret != 0 {
        let len = err_buf.iter().position(|&b| b == 0).unwrap_or(ERR_BUF_LEN);
        anyhow::bail!(
            "{}",
            std::str::from_utf8(unsafe { std::slice::from_raw_parts(err_buf.as_ptr() as *const u8, len) })
                .unwrap_or("unknown")
        );
    }
    Ok(())
}

/// Get tick size for token (e.g. "0.01").
pub fn tick_size(handle: u64, token_id: &str) -> Result<String> {
    let lib = load_lib()?;
    let f: libloading::Symbol<
        unsafe extern "C" fn(c_ulonglong, *const c_char, *mut c_char, usize, *mut c_char, usize) -> c_int,
    > = unsafe { lib.get(b"clob_sdk_tick_size") }.context("clob_sdk_tick_size not found")?;

    let c_token = copy_rust_to_c(token_id)?;
    let mut out_buf = vec![0i8; 32];
    let mut err_buf = vec![0i8; ERR_BUF_LEN];
    let ret = unsafe {
        f(
            handle,
            c_token.as_ptr(),
            out_buf.as_mut_ptr(),
            out_buf.len(),
            err_buf.as_mut_ptr(),
            err_buf.len(),
        )
    };
    if ret != 0 {
        let len = err_buf.iter().position(|&b| b == 0).unwrap_or(ERR_BUF_LEN);
        anyhow::bail!(
            "{}",
            std::str::from_utf8(unsafe { std::slice::from_raw_parts(err_buf.as_ptr() as *const u8, len) })
                .unwrap_or("unknown")
        );
    }
    let len = out_buf.iter().position(|&b| b == 0).unwrap_or(out_buf.len());
    Ok(String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(out_buf.as_ptr() as *const u8, len) }).into_owned())
}

/// Get neg_risk for token. Returns true/false.
pub fn neg_risk(handle: u64, token_id: &str) -> Result<bool> {
    let lib = load_lib()?;
    let f: libloading::Symbol<
        unsafe extern "C" fn(c_ulonglong, *const c_char, *mut c_char, usize) -> c_int,
    > = unsafe { lib.get(b"clob_sdk_neg_risk") }.context("clob_sdk_neg_risk not found")?;

    let c_token = copy_rust_to_c(token_id)?;
    let mut err_buf = vec![0i8; ERR_BUF_LEN];
    let ret = unsafe { f(handle, c_token.as_ptr(), err_buf.as_mut_ptr(), err_buf.len()) };
    if ret == -1 {
        let len = err_buf.iter().position(|&b| b == 0).unwrap_or(ERR_BUF_LEN);
        anyhow::bail!(
            "{}",
            std::str::from_utf8(unsafe { std::slice::from_raw_parts(err_buf.as_ptr() as *const u8, len) })
                .unwrap_or("unknown")
        );
    }
    Ok(ret == 1)
}