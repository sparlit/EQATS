/// Placeholder for Engle-Granger Cointegration Test
pub struct CointegrationTest {
    pub critical_value: f64, // e.g., -3.9 for 1% significance
}

impl CointegrationTest {
    pub fn new(critical_value: f64) -> Self {
        Self { critical_value }
    }

    pub fn is_cointegrated(&self, adf_statistic: f64) -> bool {
        // More negative ADF means stronger reversion
        adf_statistic < self.critical_value
    }
}
