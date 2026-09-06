// Stealth BSC Bundler integration for EQATS
// Purpose: deterministic algorithm to split a total BNB stake into N 'stealth' buy orders
// respecting per-order min/max and producing a reproducible sequence given a seed.

use std::fmt;

pub struct Bundler {
    total_bnb: f64,
    bundles: usize,
    min_amount: f64,
    max_amount: f64,
    seed: u64,
}

#[derive(Debug, Clone)]
pub struct Order {
    pub to: String,
    pub amount_bnb: f64,
    pub memo: String,
}

impl fmt::Display for Order {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // JSON-like one-line serialization (no external deps)
        write!(f, "{{\"to\":\"{}\",\"amount_bnb\":{:.8},\"memo\":\"{}\"}}", self.to, self.amount_bnb, self.memo)
    }
}

impl Bundler {
    pub fn new(total_bnb: f64, bundles: usize, min_amount: f64, max_amount: f64, seed: u64) -> Result<Self, &'static str> {
        if bundles == 0 {
            return Err("bundles must be > 0");
        }
        if min_amount < 0.0 || max_amount < 0.0 {
            return Err("amounts must be non-negative");
        }
        if min_amount > max_amount {
            return Err("min_amount must be <= max_amount");
        }
        // Feasibility quick check
        let min_total = min_amount * (bundles as f64);
        let max_total = max_amount * (bundles as f64);
        if total_bnb + 1e-12 < min_total || total_bnb - 1e-12 > max_total {
            return Err("total_bnb not feasible with given min/max per bundle");
        }
        Ok(Self { total_bnb, bundles, min_amount, max_amount, seed })
    }

    // Public API: generate amounts vector (length == bundles) that sums to total_bnb and respects bounds
    pub fn generate_amounts(&self) -> Result<Vec<f64>, &'static str> {
        sample_and_fit(self.seed, self.total_bnb, self.bundles, self.min_amount, self.max_amount)
    }

    // Build simple orders addressed to token_address with generated amounts
    pub fn generate_orders(&self, token_address: &str) -> Result<Vec<Order>, &'static str> {
        let amounts = self.generate_amounts()?;
        let mut orders = Vec::with_capacity(amounts.len());
        for (i, a) in amounts.into_iter().enumerate() {
            orders.push(Order {
                to: token_address.to_string(),
                amount_bnb: a,
                memo: format!("bundle-{}-seed{}", i, self.seed),
            });
        }
        Ok(orders)
    }
}

// Deterministic xorshift RNG (small, no external deps)
struct XorShift64 { state: u64 }
impl XorShift64 {
    fn new(seed: u64) -> Self { let s = if seed == 0 { 0x9E3779B97F4A7C15u64 } else { seed }; Self { state: s } }
    fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }
    fn next_f64(&mut self) -> f64 {
        // produce (0,1)
        let v = self.next_u64();
        // map to [0,1) safely
        (v as f64) / (std::u64::MAX as f64 + 1.0)
    }
}

fn sample_and_fit(seed: u64, total: f64, n: usize, min: f64, max: f64) -> Result<Vec<f64>, &'static str> {
    if n == 0 { return Err("n must be > 0"); }
    let eps = 1e-12f64;
    if total + eps < (min * n as f64) || total - eps > (max * n as f64) { return Err("infeasible"); }

    let mut rng = XorShift64::new(seed);
    // initial sample
    let mut amounts: Vec<f64> = (0..n).map(|_| {
        let r = rng.next_f64();
        min + r * (max - min)
    }).collect();

    // iterative clamp and redistribute
    let mut locked = vec![false; n];
    for _iter in 0..200 {
        // compute locked sum
        let sum_locked: f64 = amounts.iter().enumerate().filter(|(i,_)| locked[*i]).map(|(_,v)| *v).sum();
        let mut unlocked_idx: Vec<usize> = amounts.iter().enumerate().filter(|(i,_)| !locked[*i]).map(|(i,_)| i).collect();
        let remaining_total = total - sum_locked;
        if unlocked_idx.is_empty() {
            // all locked, check sum
            let s: f64 = amounts.iter().sum();
            if (s - total).abs() <= 1e-9 { return Ok(amounts); }
            return Err("cannot fit amounts to total");
        }

        // sample proposals for unlocked slots
        let mut proposals: Vec<f64> = unlocked_idx.iter().map(|_| {
            let r = rng.next_f64();
            min + r * (max - min)
        }).collect();
        let sum_prop: f64 = proposals.iter().sum();
        if sum_prop <= 0.0 { return Err("rng produced degenerate proposals"); }
        // scale proposals to remaining_total
        let scale = remaining_total / sum_prop;
        for (i, &idx) in unlocked_idx.iter().enumerate() {
            amounts[idx] = proposals[i] * scale;
        }

        // clamp newly produced to bounds and update locks
        let mut any_lock_change = false;
        for i in 0..n {
            if !locked[i] {
                if amounts[i] < min - 1e-14 {
                    amounts[i] = min;
                    locked[i] = true;
                    any_lock_change = true;
                } else if amounts[i] > max + 1e-14 {
                    amounts[i] = max;
                    locked[i] = true;
                    any_lock_change = true;
                }
            }
        }
        // after clamping, check if within tolerance
        let s: f64 = amounts.iter().sum();
        if (s - total).abs() <= 1e-9 { return Ok(amounts); }
        if !any_lock_change {
            // stable but not exact due to rounding: final normalization
            let normalize = total / s;
            for v in amounts.iter_mut() { *v *= normalize; }
            // last clamp pass to ensure bounds
            for v in amounts.iter_mut() {
                if *v < min { *v = min; }
                if *v > max { *v = max; }
            }
            let s2: f64 = amounts.iter().sum();
            if (s2 - total).abs() <= 1e-8 { return Ok(amounts); }
            // otherwise continue iterations
        }
    }
    Err("unable to converge to a feasible allocation")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn basic_split_sum_and_bounds() {
        let b = Bundler::new(1.0, 5, 0.05, 0.5, 42).unwrap();
        let amounts = b.generate_amounts().unwrap();
        let sum: f64 = amounts.iter().sum();
        assert!((sum - 1.0).abs() < 1e-8, "sum mismatch: {}", sum);
        for a in amounts { assert!(a + 1e-12 >= 0.05 && a <= 0.5 + 1e-12); }
    }

    #[test]
    fn generate_orders_json_like() {
        let b = Bundler::new(0.7, 3, 0.1, 0.4, 7).unwrap();
        let orders = b.generate_orders("0xTokenAddr").unwrap();
        assert_eq!(orders.len(), 3);
        for o in orders { let s = format!("{}", o); assert!(s.contains("\"to\"")); }
    }
}
