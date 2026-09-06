use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct PositionRequest {
    pub symbol: String,
    pub margin: f64,
    pub leverage: u32,
    pub side: String, // "long" or "short"
    pub stop_loss: Option<f64>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[pyclass]
pub struct Position {
    #[pyclass(get)]
    pub id: u64,
    #[pyclass(get)]
    pub symbol: String,
    #[pyclass(get)]
    pub margin: f64,
    #[pyclass(get)]
    pub leverage: u32,
    #[pyclass(get)]
    pub side: String,
    #[pyclass(get)]
    pub stop_loss: Option<f64>,
    #[pyclass(get)]
    pub entry_price: f64,
    #[pyclass(get)]
    pub status: String,
}

#[pyclass]
pub struct PositionManager {
    positions: HashMap<u64, Position>,
    next_id: u64,
}

#[pymethods]
impl PositionManager {
    #[new]
    fn new() -> Self {
        PositionManager {
            positions: HashMap::new(),
            next_id: 1,
        }
    }

    fn open_position(&mut self, req: PositionRequest) -> PyResult<Position> {
        let id = self.next_id;
        self.next_id += 1;
        let position = Position {
            id,
            symbol: req.symbol.clone(),
            margin: req.margin,
            leverage: req.leverage,
            side: req.side.clone(),
            stop_loss: req.stop_loss,
            entry_price: 0.0, // placeholder
            status: "open".to_string(),
        };
        self.positions.insert(id, position.clone());
        Ok(position)
    }

    fn close_position(&mut self, id: u64) -> PyResult<Option<Position>> {
        Ok(self.positions.remove(&id))
    }

    fn get_account_snapshot(&self) -> PyResult<Vec<Position>> {
        Ok(self.positions.values().cloned().collect())
    }
}

#[pymodule]
fn raderbot_position(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PositionManager>()?;
    m.add_class::<Position>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::prepare_freethreaded_python;

    #[test]
    fn test_position_manager() {
        Python::with_gil(|py| {
            let mgr = PyCell::new(py, PositionManager::new()).unwrap();
            let mut mgr_mut = mgr.borrow_mut(py);
            let req = PositionRequest {
                symbol: "BTCUSDT".to_string(),
                margin: 100.0,
                leverage: 10,
                side: "long".to_string(),
                stop_loss: Some(90.0),
            };
            let pos = mgr_mut.open_position(req).unwrap();
            assert_eq!(pos.symbol, "BTCUSDT");
            assert_eq!(pos.id, 1);
            let snapshot = mgr_mut.get_account_snapshot().unwrap();
            assert_eq!(snapshot.len(), 1);
            let closed = mgr_mut.close_position(1).unwrap().unwrap();
            assert_eq!(closed.status, "open"); // status unchanged
            let snapshot_after = mgr_mut.get_account_snapshot().unwrap();
            assert!(snapshot_after.is_empty());
        });
    }
}