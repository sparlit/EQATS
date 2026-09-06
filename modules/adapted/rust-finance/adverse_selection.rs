pub struct AdverseSelectionGuard {
    pub vpin_threshold: f64, // Volume-Synchronized Probability of Informed Trading
}

impl AdverseSelectionGuard {
    pub fn is_flow_toxic(&self, current_vpin: f64) -> bool {
        current_vpin > self.vpin_threshold
    }

    pub fn adjust_spread(&self, base_spread: f64, current_vpin: f64) -> f64 {
        if self.is_flow_toxic(current_vpin) {
            // Widen spread to defend against informed toxic flow
            base_spread * (1.0 + (current_vpin - self.vpin_threshold) * 2.0)
        } else {
            base_spread
        }
    }
}
