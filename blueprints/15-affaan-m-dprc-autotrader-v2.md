# Integration Blueprint: Rig LLM Library into eqats

## Overview
Rig is a Rust library for LLM-powered apps with support for multiple model providers (OpenAI, Cohere, etc.) and vector stores (MongoDB, SQLite, in‑memory). It provides ergonomic abstractions for completions, embeddings, and agents.

## Mapping to eqats Domains

### Data Engines
- Use Rig’s vector store integrations to store/retrieve market‑data embeddings for similarity search.
- Use LLM completion/embedding pipelines to turn raw market data into features (e.g., news summarization).

### Signal & Execution Logic
- Create a Rig Agent that takes market context and returns a trading signal via a prompt.
- The agent’s output can be fed into eqats’ execution engine to generate orders.
- Rig’s tool‑calling lets the agent query external data (fundamentals, price feeds) as part of signal generation.

### Risk Engineering
- Rig does not provide risk limits, position sizing, or monitoring; risk stays in eqats’ risk module.

## Integration Steps
1. Add dependencies: `rig-core` and `tokio` (with macros, rt-multi-thread).
2. Configure LLM client: `let client = rig::providers::openai::Client::from_env();`
3. Build agent: `let agent = client.agent("gpt-4-turbo").build();`
4. Build prompt with market data and call `agent.prompt(&prompt).await?`.
5. Convert LLM output to eqats signal and pass to strategy.
6. (Optional) Store/retrieve embeddings using Rig’s MongoDB or SQLite vector store.

## Considerations
- Pin Rig version due to possible breaking changes.
- Ensure tokio runtime matches eqats.
- Handle Rig errors via eqats error types.
- Mock LLM client in tests using Rig’s in‑memory provider.

## Summary
Rig adds flexible LLM‑driven data enrichment and signal generation to eqats while leaving risk and execution to existing eqats components.