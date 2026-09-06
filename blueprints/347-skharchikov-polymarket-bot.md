# Integration Blueprint

## Feature Selected
Kelly Criterion position sizing (risk engineering) from polymarket-bot.

## Purpose
Provide a reusable Rust function that computes the optimal fraction of capital to wager given a predicted win probability p and net odds b (decimal odds - 1).

## Integration Points
- Add eqats/src/risk/kelly.rs module.
- Expose kelly_fraction(p, b, f) where f is the Kelly fraction multiplier (e.g., 0.5 for half‑Kelly).
- Use in strategy execution before placing a bet via the CLOB client.
- Unit test validates edge cases (p=0, p=1, b=0).

## Dependencies
No external crates beyond the standard library.

## Testing
Run cargo test --package eqats --lib risk::kelly::tests to verify correctness.
