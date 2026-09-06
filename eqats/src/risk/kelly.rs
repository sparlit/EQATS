/// Computes the Kelly fraction for a binary outcome.

/// # Arguments

/// * p - Estimated probability of winning (0.0 ..= 1.0).
/// * b - Net odds received on the wager (decimal odds - 1). For example, odds of 2.0 => b = 1.0.
/// * f - Kelly multiplier (e.g., 0.5 for half‑Kelly, 1.0 for full Kelly).

/// # Returns

/// The fraction of the bankroll to wager. If the result is negative, returns 0.0 (no bet).

/// # Formula

/// f* = (p * b - (1 - p)) / b

/// # Example

/// 
/// use eqats::risk::kelly::kelly_fraction;
/// assert_eq!(kelly_fraction(0.6, 1.0, 1.0), 0.2);
/// 
pub fn kelly_fraction(p: f64, b: f64, f: f64) -> f64 {
    if b <= 0.0 || p < 0.0 || p > 1.0 {
        return 0.0;
    }
    let kelly = (p * b - (1.0 - p)) / b;
    if kelly <= 0.0 {
        0.0
    } else {
        kelly * f
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_kelly() {
        // p=0.6, b=1.0 => (0.6*1 - 0.4)/1 = 0.2
        assert_eq!(kelly_fraction(0.6, 1.0, 1.0), 0.2);
    }

    #[test]
    fn test_half_kelly() {
        assert_eq!(kelly_fraction(0.6, 1.0, 0.5), 0.1);
    }

    #[test]
    fn test_no_edge() {
        // p=0.5, b=1.0 => (0.5*1 - 0.5)/1 = 0.0
        assert_eq!(kelly_fraction(0.5, 1.0, 1.0), 0.0);
    }

    #[test]
    fn test_negative_edge() {
        // p=0.4, b=1.0 => (0.4*1 - 0.6)/1 = -0.2 => 0.0
        assert_eq!(kelly_fraction(0.4, 1.0, 1.0), 0.0);
    }

    #[test]
    fn test_zero_odds() {
        assert_eq!(kelly_fraction(0.8, 0.0, 1.0), 0.0);
    }

    #[test]
    fn test_invalid_probability() {
        assert_eq!(kelly_fraction(-0.1, 1.0, 1.0), 0.0);
        assert_eq!(kelly_fraction(1.2, 1.0, 1.0), 0.0);
    }
}