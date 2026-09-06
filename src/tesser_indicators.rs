use pyo3::prelude::*;
use rust_decimal::Decimal;
use std::collections::VecDeque;

#[pyclass]
struct SimpleSMA {
    period: usize,
    sum: Decimal,
    values: VecDeque<Decimal>,
}

#[pymethods]
impl SimpleSMA {
    #[new]
    fn new(period: usize) -> Self {
        SimpleSMA {
            period,
            sum: Decimal::ZERO,
            values: VecDeque::with_capacity(period),
        }
    }

    fn update(&mut self, price: f64) -> Option<f64> {
        let dec = Decimal::from_f64(price).expect("valid f64");
        if self.values.len() == self.period {
            if let Some(old) = self.values.pop_front() {
                self.sum = self.sum - old;
            }
        }
        self.values.push_back(dec);
        self.sum = self.sum + dec;
        if self.values.len() == self.period {
            let avg = self.sum / Decimal::from(self.period as u64);
            Some(avg.to_f64().unwrap())
        } else {
            None
        }
    }
}

#[pymodule]
fn tesser_indicators(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<SimpleSMA>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use rust_decimal::Decimal;

    #[test]
    fn test_sma() {
        let mut sma = SimpleSMA::new(3);
        assert_eq!(sma.update(1.0), None);
        assert_eq!(sma.update(2.0), None);
        let avg = sma.update(3.0).unwrap();
        assert!((avg - 2.0).abs() < 1e-9);
        let avg2 = sma.update(4.0).unwrap();
        assert!((avg2 - 3.0).abs() < 1e-9);
    }
}