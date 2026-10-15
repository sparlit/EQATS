use std::collections::BTreeMap;
use crate::dtf::update::Update;

type Time = u64;

/// Enum for events
pub enum EventType {
    /// Cancel order event
    CancelEvent,
    /// Trade matched event
    TradeEvent,
    /// Create order event
    CreateEvent,
}

/// Data structure for storing events.
/// Each is a map from time to list of updates happened at or near that discrete time
#[derive(Debug)]
pub struct Events {
    /// cancelled orders
    pub cancelled: BTreeMap<Time, Vec<Update>>,
    /// trade events
    pub trades: BTreeMap<Time, Vec<Update>>,
    /// created orders
    pub created: BTreeMap<Time, Vec<Update>>,
}

impl<'a> From<&'a [Update]> for Events {
    fn from(ups: &[Update]) -> Events {

        let mut cancelled = BTreeMap::new();
        let mut trades = BTreeMap::new();
        let mut created = BTreeMap::new();

        let mut current_level = BTreeMap::new();

        for row in ups {

            let ts = row.ts;
            let price = row.price.to_bits();

            if row.is_trade {
                let v = trades.entry(ts).or_insert(Vec::new());
                (*v).push(row.clone());
            } else {
                let prev = if current_level.contains_key(&price) {
                    *current_level.get(&price).unwrap()
                } else {
                    0.
                };
                if row.size == 0. || row.size <= prev {
                    let v = cancelled.entry(ts).or_insert(Vec::new());
                    (*v).push(row.clone());
                } else if row.size > prev {
                    let v = created.entry(ts).or_insert(Vec::new());
                    (*v).push(row.clone());
                } else {
                    // size == prev
                    unreachable!();
                }
            }

            current_level.insert(price, row.size);
        }

        Events {
            cancelled,
            trades,
            created,
        }
    }
}

impl Events {
    /// Filter order events based on size
    pub fn filter_size(&self, event_type: EventType, from_size: f32, to_size: f32) -> Vec<Update> {
        let obj = match event_type {
            EventType::CancelEvent => &self.cancelled,
            EventType::CreateEvent => &self.created,
            EventType::TradeEvent => &self.trades,
        };

        let mut ret = Vec::new();
        for v in obj.values() {
            for up in v.iter() {
                if up.size >= from_size && up.size <= to_size {
                    ret.push(up.clone());
                }
            }
        }
        ret
    }
}

#[cfg(test)]
mod test {

    use super::*;
    use crate::dtf;
    static FNAME: &str = "../../test/test-data/bt_btcnav.dtf";
    static POLO: &str = "../../test/test-data/pl_btc_nav.dtf";

    #[test]
    fn test_into_events() {
        let ups = vec![
            Update {
                ts: 1000,
                seq: 1,
                is_trade: true,
                is_bid: true,
                price: 100.0,
                size: 10.0,
            },
            Update {
                ts: 1001,
                seq: 2,
                is_trade: false,
                is_bid: true,
                price: 100.0,
                size: 50.0,
            },
            Update {
                ts: 1002,
                seq: 3,
                is_trade: false,
                is_bid: false,
                price: 101.0,
                size: 30.0,
            },
            Update {
                ts: 1003,
                seq: 4,
                is_trade: false,
                is_bid: false,
                price: 101.0,
                size: 40.0,
            },
            Update {
                ts: 1004,
                seq: 5,
                is_trade: false,
                is_bid: true,
                price: 100.0,
                size: 20.0,
            },
            Update {
                ts: 1005,
                seq: 6,
                is_trade: false,
                is_bid: false,
                price: 101.0,
                size: 0.0,
            },
        ];

        let evts = Events::from(ups.as_slice());

        assert_eq!(evts.trades.len(), 1);
        assert!(evts.trades.contains_key(&1000));
        assert_eq!(evts.trades[&1000].len(), 1);
        assert_eq!(evts.trades[&1000][0].price, 100.0);
        assert_eq!(evts.trades[&1000][0].size, 10.0);
        assert!(evts.trades[&1000][0].is_trade);

        assert_eq!(evts.created.len(), 3);
        assert!(evts.created.contains_key(&1001));
        assert!(evts.created.contains_key(&1002));
        assert!(evts.created.contains_key(&1003));
        assert_eq!(evts.created[&1001][0].size, 50.0);
        assert_eq!(evts.created[&1002][0].size, 30.0);
        assert_eq!(evts.created[&1003][0].size, 40.0);

        assert_eq!(evts.cancelled.len(), 2);
        assert!(evts.cancelled.contains_key(&1004));
        assert!(evts.cancelled.contains_key(&1005));
        assert_eq!(evts.cancelled[&1004][0].size, 20.0);
        assert_eq!(evts.cancelled[&1005][0].size, 0.0);

        let empty_evts = Events::from(&[][..]);
        assert!(empty_evts.trades.is_empty());
        assert!(empty_evts.created.is_empty());
        assert!(empty_evts.cancelled.is_empty());
    }

    #[test]
    fn test_size_filter() {
        let records = dtf::file_format::decode(FNAME, Some(10000)).unwrap();
        let ups = records.as_slice();

        let evts = Events::from(ups);

        let cancels = evts.filter_size(EventType::CancelEvent, 100., 200.);
        assert!(cancels.len() > 0);
        for up in cancels.iter() {
            assert!(up.size >= 100. && up.size <= 200.);
        }

        let creates = evts.filter_size(EventType::CreateEvent, 100., 200.);
        assert!(creates.len() > 0);
        for up in creates.iter() {
            assert!(up.size >= 100. && up.size <= 200.);
        }

        let trades = evts.filter_size(EventType::TradeEvent, 100., 200.);
        assert!(trades.len() > 0);
        for up in trades.iter() {
            assert!(up.size >= 100. && up.size <= 200.);
        }
    }

    #[test]
    fn should_work_with_poloniex_too() {
        // TODO: more poloniex tests
        // The raw data doesn't look correct.
        let records = dtf::file_format::decode(POLO, Some(10000)).unwrap();

        let ups = records.as_slice();
        let evts = Events::from(ups);

        let trades = evts.filter_size(EventType::TradeEvent, 100., 200.);
        assert!(trades.len() > 0);
        for up in trades.iter() {
            assert!(up.size >= 100. && up.size <= 200.);
        }
    }
}