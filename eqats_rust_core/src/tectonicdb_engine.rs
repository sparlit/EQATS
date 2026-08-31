// TectonicDB High-Throughput Compressed Tick Storage Engine
// Adapted for EQATS Microkernel Monolith (Magic Range: 9500001)

use std::os::raw::{c_int, c_ulonglong};

/// Fixed size packed tick record for ultra-low latency C-ABI shared memory exchange
#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CompactTickRecord {
    pub timestamp_ns: u64,
    pub bid_price: f64,
    pub ask_price: f64,
    pub bid_size: f64,
    pub ask_size: f64,
    pub trade_price: f64,
    pub trade_volume: f64,
}

/// Compress an array of CompactTickRecord structs into a binary delta byte stream
#[no_mangle]
pub extern "C" fn rust_tectonicdb_pack_ticks(
    ticks: *const CompactTickRecord,
    count: c_int,
    out_buffer: *mut u8,
    buffer_capacity: c_int,
    out_written: *mut c_int,
) -> c_int {
    if ticks.is_null() || out_buffer.is_null() || out_written.is_null() || count <= 0 {
        return -1;
    }

    let tick_slice = unsafe { std::slice::from_raw_parts(ticks, count as usize) };
    let out_slice = unsafe { std::slice::from_raw_parts_mut(out_buffer, buffer_capacity as usize) };

    let mut cursor = 0usize;

    // Header: write record count (u32)
    if cursor + 4 > out_slice.len() {
        return -2;
    }
    let count_bytes = (count as u32).to_le_bytes();
    out_slice[cursor..cursor + 4].copy_from_slice(&count_bytes);
    cursor += 4;

    // Anchor tick (first record uncompressed)
    let anchor = &tick_slice[0];
    let record_size = std::mem::size_of::<CompactTickRecord>();
    if cursor + record_size > out_slice.len() {
        return -2;
    }

    unsafe {
        let ptr = out_slice.as_mut_ptr().add(cursor) as *mut CompactTickRecord;
        *ptr = *anchor;
    }
    cursor += record_size;

    // Subsequent ticks: delta encoded
    let mut prev_ts = anchor.timestamp_ns;
    let mut prev_bid = (anchor.bid_price * 10000.0).round() as i64;
    let mut prev_ask = (anchor.ask_price * 10000.0).round() as i64;

    for tick in &tick_slice[1..] {
        let ts_delta = tick.timestamp_ns.saturating_sub(prev_ts);
        let curr_bid = (tick.bid_price * 10000.0).round() as i64;
        let curr_ask = (tick.ask_price * 10000.0).round() as i64;

        let bid_delta = curr_bid - prev_bid;
        let ask_delta = curr_ask - prev_ask;

        let bid_size_bits = tick.bid_size.to_bits();
        let ask_size_bits = tick.ask_size.to_bits();
        let trade_price_bits = tick.trade_price.to_bits();
        let trade_vol_bits = tick.trade_volume.to_bits();

        // Layout: ts_delta (u64), bid_delta (i64), ask_delta (i64), sizes/trades (u64 x 4) = 56 bytes per delta record
        let needed = 8 + 8 + 8 + 8 + 8 + 8 + 8;
        if cursor + needed > out_slice.len() {
            return -2;
        }

        out_slice[cursor..cursor + 8].copy_from_slice(&ts_delta.to_le_bytes());
        cursor += 8;
        out_slice[cursor..cursor + 8].copy_from_slice(&bid_delta.to_le_bytes());
        cursor += 8;
        out_slice[cursor..cursor + 8].copy_from_slice(&ask_delta.to_le_bytes());
        cursor += 8;

        out_slice[cursor..cursor + 8].copy_from_slice(&bid_size_bits.to_le_bytes());
        cursor += 8;
        out_slice[cursor..cursor + 8].copy_from_slice(&ask_size_bits.to_le_bytes());
        cursor += 8;
        out_slice[cursor..cursor + 8].copy_from_slice(&trade_price_bits.to_le_bytes());
        cursor += 8;
        out_slice[cursor..cursor + 8].copy_from_slice(&trade_vol_bits.to_le_bytes());
        cursor += 8;

        prev_ts = tick.timestamp_ns;
        prev_bid = curr_bid;
        prev_ask = curr_ask;
    }

    unsafe {
        *out_written = cursor as c_int;
    }

    0
}

/// Unpack a binary delta byte stream back into CompactTickRecord array
#[no_mangle]
pub extern "C" fn rust_tectonicdb_unpack_ticks(
    in_buffer: *const u8,
    buffer_len: c_int,
    out_ticks: *mut CompactTickRecord,
    max_out_count: c_int,
    out_count: *mut c_int,
) -> c_int {
    if in_buffer.is_null() || out_ticks.is_null() || out_count.is_null() || buffer_len < 4 {
        return -1;
    }

    let in_slice = unsafe { std::slice::from_raw_parts(in_buffer, buffer_len as usize) };
    let out_slice = unsafe { std::slice::from_raw_parts_mut(out_ticks, max_out_count as usize) };

    let mut cursor = 0usize;

    // Read count header
    let total_count = u32::from_le_bytes(in_slice[0..4].try_into().unwrap()) as usize;
    cursor += 4;

    if total_count == 0 {
        unsafe {
            *out_count = 0;
        }
        return 0;
    }

    if total_count > max_out_count as usize {
        return -2;
    }

    let record_size = std::mem::size_of::<CompactTickRecord>();
    if cursor + record_size > in_slice.len() {
        return -3;
    }

    // Anchor record
    let anchor_ptr = unsafe { in_slice.as_ptr().add(cursor) as *const CompactTickRecord };
    let anchor = unsafe { *anchor_ptr };
    cursor += record_size;

    out_slice[0] = anchor;

    let mut prev_ts = anchor.timestamp_ns;
    let mut prev_bid = (anchor.bid_price * 10000.0).round() as i64;
    let mut prev_ask = (anchor.ask_price * 10000.0).round() as i64;

    for idx in 1..total_count {
        if cursor + 56 > in_slice.len() {
            return -3;
        }

        let ts_delta = u64::from_le_bytes(in_slice[cursor..cursor + 8].try_into().unwrap());
        cursor += 8;
        let bid_delta = i64::from_le_bytes(in_slice[cursor..cursor + 8].try_into().unwrap());
        cursor += 8;
        let ask_delta = i64::from_le_bytes(in_slice[cursor..cursor + 8].try_into().unwrap());
        cursor += 8;

        let bid_size_bits = u64::from_le_bytes(in_slice[cursor..cursor + 8].try_into().unwrap());
        cursor += 8;
        let ask_size_bits = u64::from_le_bytes(in_slice[cursor..cursor + 8].try_into().unwrap());
        cursor += 8;
        let trade_price_bits = u64::from_le_bytes(in_slice[cursor..cursor + 8].try_into().unwrap());
        cursor += 8;
        let trade_vol_bits = u64::from_le_bytes(in_slice[cursor..cursor + 8].try_into().unwrap());
        cursor += 8;

        let curr_ts = prev_ts + ts_delta;
        let curr_bid = prev_bid + bid_delta;
        let curr_ask = prev_ask + ask_delta;

        out_slice[idx] = CompactTickRecord {
            timestamp_ns: curr_ts,
            bid_price: (curr_bid as f64) / 10000.0,
            ask_price: (curr_ask as f64) / 10000.0,
            bid_size: f64::from_bits(bid_size_bits),
            ask_size: f64::from_bits(ask_size_bits),
            trade_price: f64::from_bits(trade_price_bits),
            trade_volume: f64::from_bits(trade_vol_bits),
        };

        prev_ts = curr_ts;
        prev_bid = curr_bid;
        prev_ask = curr_ask;
    }

    unsafe {
        *out_count = total_count as c_int;
    }

    0
}

/// Perform high-speed timestamp range query filtering over CompactTickRecord array
#[no_mangle]
pub extern "C" fn rust_tectonicdb_filter_range(
    ticks: *const CompactTickRecord,
    count: c_int,
    start_ns: c_ulonglong,
    end_ns: c_ulonglong,
    out_ticks: *mut CompactTickRecord,
    max_out: c_int,
    out_count: *mut c_int,
) -> c_int {
    if ticks.is_null() || out_ticks.is_null() || out_count.is_null() || count <= 0 {
        return -1;
    }

    let in_slice = unsafe { std::slice::from_raw_parts(ticks, count as usize) };
    let out_slice = unsafe { std::slice::from_raw_parts_mut(out_ticks, max_out as usize) };

    let mut matched = 0usize;

    for tick in in_slice {
        if tick.timestamp_ns >= start_ns && tick.timestamp_ns <= end_ns {
            if matched < out_slice.len() {
                out_slice[matched] = *tick;
                matched += 1;
            } else {
                break;
            }
        }
    }

    unsafe {
        *out_count = matched as c_int;
    }

    0
}
