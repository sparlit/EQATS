# EchoBird Integration Blueprint for eqats

## Overview
EchoBird is a Tauri + Rust application that provides a unified Model Nexus for configuring LLM providers, one-click install & model switching for AI coding CLIs and desktop apps, bundled local LLM runtimes, and an app manager for AI tools.

## Proposed Integration

### Data Engines
- **Model Nexus as a Centralized LLM Config Hub**: eqats can store API keys, model endpoints, and routing rules for alternative data LLMs (e.g., news summarization, sentiment) in EchoBird's Model Nexus. The hub’s one‑click latency check ensures low‑latency access before committing to a data feed.
- **Bundled Inference Engines (vLLM / SGLang / llama.cpp)**: Deploy these runtimes locally to run open‑source LLMs for enriching market data (e.g., extracting signals from SEC filings, earnings call transcripts) without relying on external APIs, reducing cost and latency.

### Signal & Execution Logic
- **One‑Click Install & Model Switch for Coding CLIs**: Use EchoBird to provision and switch the underlying LLM for AI‑assisted coding tools such as Claude Code, Codex CLI, or OpenCode. Quant researchers can rapidly prototype, backtest, and deploy strategy code by toggling between models (e.g., a strong reasoning model for strategy design vs. a fast coding model for implementation) with a single click.
- **My AI Projects Workspace**: Host eqats‑generated strategy scripts, notebooks, or Dockerized agents inside EchoBird’s project manager. Version‑controlled, launchable with one click, and automatically using the configured LLM backend from Model Nexus.
- **App Manager for Execution Tools**: Launch execution‑related AI apps (e.g., OpenCode Desktop, custom trading bots) directly from EchoBird, ensuring they inherit the active model configuration.

### Risk Engineering
- **Currently No Direct Risk Features**: EchoBird does not provide risk limits, position sizing, or monitoring utilities. However, its App Manager can be repurposed to launch third‑party risk dashboards or monitoring agents that eqats already uses, benefitting from the same one‑click launch and model‑switching convenience.

## Implementation Steps
1. **Bundle EchoBird** as a optional component in the eqats developer toolkit (available via crates.io or Homebrew).
2. **Expose a thin Rust API** that reads Model Nexus configuration and injects it into eqats’ LLM client wrappers.
3. **Add a command** `eqats model-switch <provider>` that triggers EchoBird’s config rewrite for the selected CLI (Claude Code, Codex, etc.).
4. **Document workflows** for data enrichment (local LLM inference) and strategy development (AI‑assisted coding) using EchoBird’s one‑click install.

## Benefits
- Centralized management of LLM credentials and model selection across all eqats AI‑driven modules.
- Reduced setup friction for new developers: one‑click install of preferred coding LLMs.
- Ability to run private, local LLMs for sensitive data processing, enhancing data security.
- Cross‑platform consistency (Windows, macOS, Linux) matching eqats’ deployment targets.
