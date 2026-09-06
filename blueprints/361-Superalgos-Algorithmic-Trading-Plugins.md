# Integration Blueprint for Superalgos Plugins into eqats

## Overview
The Superalgos Algorithmic-Trading-Plugins repository contains a collection of trading plugins written in JavaScript/TypeScript that extend the Superalgos platform with data engines, signal generation, execution logic, and risk management features.

## Domain Mapping
- **Data Engines**: Historical data loaders, real-time ticker subscriptions, CSV/JSON parsers.
- **Signal & Execution Logic**: Technical indicator libraries, strategy template engines, order execution adapters.
- **Risk Engineering**: Position sizing calculators, stop‑loss/take‑profit managers, drawdown limiters.

## Integration Approach
Due to the language mismatch (JavaScript/TypeScript vs Rust) and the tight coupling of plugins to the Superalgos runtime, direct in‑process linking is not feasible. Instead, eqats will treat each plugin as an external Node.js script and invoke it via a thin Rust wrapper (see src/plugins/superalgos_plugin.rs). This approach preserves the original plugin logic while providing a safe, typed interface from Rust.

## Steps
1. **Expose Plugin Interface** – Ensure each plugin exports a main function that accepts JSON configuration via stdin and outputs results via stdout.
2. **Rust Wrapper** – Use std::process::Command to spawn node <plugin.js> with appropriate arguments, marshaling JSON payloads.
3. **Error Handling** – Convert Node.js process errors into Rust Result types.
4. **Testing** – Provide unit tests that verify the wrapper returns an error for missing scripts and correctly forwards output.
5. **Packaging** – Bundle required Node.js dependencies (package.json, node_modules) alongside the Rust binary or document external installation.

## Future Work
- Explore compiling plugins to WebAssembly via wasm-pack for tighter integration.
- Develop a native Rust re‑implementation of high‑value plugins (e.g., popular indicators) to eliminate the external process overhead.
