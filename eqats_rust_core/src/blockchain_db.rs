//! Ultra-Low Latency Mission-Critical Custom Blockchain Database Engine
//! Single-file production-grade immutable settlement and audit layer for high-frequency trading.

use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, RwLock};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// Helper to format 16-byte UUID to string
pub fn format_uuid(uuid: &[u8; 16]) -> String {
    format!(
        "{:02x}{:02x}{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
        uuid[0], uuid[1], uuid[2], uuid[3],
        uuid[4], uuid[5],
        uuid[6], uuid[7],
        uuid[8], uuid[9],
        uuid[10], uuid[11], uuid[12], uuid[13], uuid[14], uuid[15]
    )
}

/// Helper to format 8-byte Asset symbol to clean ASCII string
pub fn format_symbol(symbol: &[u8; 8]) -> String {
    let s = String::from_utf8_lossy(symbol);
    s.trim_matches('\0').trim().to_string()
}

// ============================================================================
// 1. SHA-256 CRYPTOGRAPHIC ENGINE
// ============================================================================

const SHA256_K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

/// Pure, zero-dependency SHA-256 digest computation
pub fn sha256(data: &[u8]) -> [u8; 32] {
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ];

    let bit_len = (data.len() as u64) * 8;
    let mut padded = data.to_vec();
    padded.push(0x80);
    while (padded.len() % 64) != 56 {
        padded.push(0x00);
    }
    padded.extend_from_slice(&bit_len.to_be_bytes());

    for chunk in padded.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }

        let mut a = h[0];
        let mut b = h[1];
        let mut c = h[2];
        let mut d = h[3];
        let mut e = h[4];
        let mut f = h[5];
        let mut g = h[6];
        let mut h_val = h[7];

        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = h_val
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(SHA256_K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);

            h_val = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }

        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(h_val);
    }

    let mut out = [0u8; 32];
    for i in 0..8 {
        let bytes = h[i].to_be_bytes();
        out[i * 4..i * 4 + 4].copy_from_slice(&bytes);
    }
    out
}

pub fn sha256_hex(data: &[u8]) -> String {
    let digest = sha256(data);
    let mut hex = String::with_capacity(64);
    for b in digest {
        hex.push_str(&format!("{:02x}", b));
    }
    hex
}

// ============================================================================
// 2. MEMORY-ALIGNED DATA LAYER
// ============================================================================

/// Matched trade execution event payload.
/// Explicitly aligned layout for cache locality and fast serialization.
#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Transaction {
    /// Timestamp in nanoseconds since UNIX epoch (8 bytes)
    pub timestamp: u64,
    /// Price in fixed-point integer cents/pips (8 bytes)
    pub price: u64,
    /// Quantity of asset contracts/units (8 bytes)
    pub quantity: u64,
    /// 16-byte Trade UUID (16 bytes)
    pub trade_id: [u8; 16],
    /// 16-byte Buyer User ID UUID (16 bytes)
    pub buyer_id: [u8; 16],
    /// 16-byte Seller User ID UUID (16 bytes)
    pub seller_id: [u8; 16],
    /// 8-byte ASCII asset symbol padded with zero bytes (8 bytes)
    pub asset_symbol: [u8; 8],
}

impl Transaction {
    /// Construct new transaction payload with binary representations
    pub fn new(
        timestamp: u64,
        trade_id: [u8; 16],
        buyer_id: [u8; 16],
        seller_id: [u8; 16],
        asset_symbol: [u8; 8],
        price: u64,
        quantity: u64,
    ) -> Self {
        Self {
            timestamp,
            trade_id,
            buyer_id,
            seller_id,
            asset_symbol,
            price,
            quantity,
        }
    }

    /// Serialize transaction to fixed 80-byte binary buffer
    pub fn to_bytes(&self) -> [u8; 80] {
        let mut buf = [0u8; 80];
        buf[0..8].copy_from_slice(&self.timestamp.to_be_bytes());
        buf[8..16].copy_from_slice(&self.price.to_be_bytes());
        buf[16..24].copy_from_slice(&self.quantity.to_be_bytes());
        buf[24..40].copy_from_slice(&self.trade_id);
        buf[40..56].copy_from_slice(&self.buyer_id);
        buf[56..72].copy_from_slice(&self.seller_id);
        buf[72..80].copy_from_slice(&self.asset_symbol);
        buf
    }

    /// Deserialize transaction from 80-byte binary buffer
    pub fn from_bytes(buf: &[u8; 80]) -> Self {
        let mut timestamp_bytes = [0u8; 8];
        let mut price_bytes = [0u8; 8];
        let mut quantity_bytes = [0u8; 8];
        let mut trade_id = [0u8; 16];
        let mut buyer_id = [0u8; 16];
        let mut seller_id = [0u8; 16];
        let mut asset_symbol = [0u8; 8];

        timestamp_bytes.copy_from_slice(&buf[0..8]);
        price_bytes.copy_from_slice(&buf[8..16]);
        quantity_bytes.copy_from_slice(&buf[16..24]);
        trade_id.copy_from_slice(&buf[24..40]);
        buyer_id.copy_from_slice(&buf[40..56]);
        seller_id.copy_from_slice(&buf[56..72]);
        asset_symbol.copy_from_slice(&buf[72..80]);

        Self {
            timestamp: u64::from_be_bytes(timestamp_bytes),
            price: u64::from_be_bytes(price_bytes),
            quantity: u64::from_be_bytes(quantity_bytes),
            trade_id,
            buyer_id,
            seller_id,
            asset_symbol,
        }
    }

    /// Computes cryptographic hash digest of the transaction
    pub fn hash(&self) -> [u8; 32] {
        sha256(&self.to_bytes())
    }
}

/// Computes binary SHA-256 Merkle root from sequential list of transactions
pub fn compute_merkle_root(txs: &[Transaction]) -> String {
    if txs.is_empty() {
        return sha256_hex(b"EMPTY_BLOCK_MERKLE_ROOT");
    }

    let mut current_level: Vec<[u8; 32]> = txs.iter().map(|tx| tx.hash()).collect();

    while current_level.len() > 1 {
        let mut next_level = Vec::with_capacity((current_level.len() + 1) / 2);
        for chunk in current_level.chunks(2) {
            if chunk.len() == 2 {
                let mut combined = [0u8; 64];
                combined[0..32].copy_from_slice(&chunk[0]);
                combined[32..64].copy_from_slice(&chunk[1]);
                next_level.push(sha256(&combined));
            } else {
                // Duplicate odd leaf for balanced binary tree
                let mut combined = [0u8; 64];
                combined[0..32].copy_from_slice(&chunk[0]);
                combined[32..64].copy_from_slice(&chunk[0]);
                next_level.push(sha256(&combined));
            }
        }
        current_level = next_level;
    }

    let mut hex = String::with_capacity(64);
    for b in current_level[0] {
        hex.push_str(&format!("{:02x}", b));
    }
    hex
}

/// Block header structure containing metadata and transaction vector
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Block {
    /// Monotonically increasing sequential index
    pub index: u64,
    /// Block creation timestamp in nanoseconds since UNIX epoch
    pub timestamp: u64,
    /// Cryptographic Merkle Root hash string of transaction contents
    pub merkle_root: String,
    /// SHA-256 hash string of previous block in the chain
    pub previous_hash: String,
    /// SHA-256 hash string of current block header contents
    pub current_hash: String,
    /// Ordered list of transactions settled in this block
    pub transactions: Vec<Transaction>,
}

impl Block {
    /// Calculate deterministic SHA-256 hash string of block header
    pub fn calculate_hash(
        index: u64,
        timestamp: u64,
        merkle_root: &str,
        previous_hash: &str,
    ) -> String {
        let mut header_bytes = Vec::new();
        header_bytes.extend_from_slice(&index.to_be_bytes());
        header_bytes.extend_from_slice(&timestamp.to_be_bytes());
        header_bytes.extend_from_slice(merkle_root.as_bytes());
        header_bytes.extend_from_slice(previous_hash.as_bytes());
        sha256_hex(&header_bytes)
    }

    /// Construct Genesis block
    pub fn create_genesis() -> Self {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos() as u64;
        let merkle_root = sha256_hex(b"GENESIS_BLOCK_SETTLEMENT");
        let previous_hash = "0000000000000000000000000000000000000000000000000000000000000000".to_string();
        let current_hash = Self::calculate_hash(0, timestamp, &merkle_root, &previous_hash);

        Self {
            index: 0,
            timestamp,
            merkle_root,
            previous_hash,
            current_hash,
            transactions: Vec::new(),
        }
    }

    /// Construct new data block from transactions and previous block reference
    pub fn new(index: u64, previous_hash: String, transactions: Vec<Transaction>) -> Self {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos() as u64;
        let merkle_root = compute_merkle_root(&transactions);
        let current_hash = Self::calculate_hash(index, timestamp, &merkle_root, &previous_hash);

        Self {
            index,
            timestamp,
            merkle_root,
            previous_hash,
            current_hash,
            transactions,
        }
    }

    /// Binary serialization format:
    /// [index: u64][timestamp: u64][merkle_len: u32][merkle_bytes][prev_len: u32][prev_bytes][curr_len: u32][curr_bytes][tx_count: u32][tx_0_bytes...tx_n_bytes]
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&self.index.to_be_bytes());
        bytes.extend_from_slice(&self.timestamp.to_be_bytes());

        let merkle_b = self.merkle_root.as_bytes();
        bytes.extend_from_slice(&(merkle_b.len() as u32).to_be_bytes());
        bytes.extend_from_slice(merkle_b);

        let prev_b = self.previous_hash.as_bytes();
        bytes.extend_from_slice(&(prev_b.len() as u32).to_be_bytes());
        bytes.extend_from_slice(prev_b);

        let curr_b = self.current_hash.as_bytes();
        bytes.extend_from_slice(&(curr_b.len() as u32).to_be_bytes());
        bytes.extend_from_slice(curr_b);

        bytes.extend_from_slice(&(self.transactions.len() as u32).to_be_bytes());
        for tx in &self.transactions {
            bytes.extend_from_slice(&tx.to_bytes());
        }

        bytes
    }

    /// Binary deserialization
    pub fn from_bytes(slice: &[u8]) -> Result<Self, String> {
        if slice.len() < 28 {
            return Err("Binary slice too short for block header".to_string());
        }

        let mut offset = 0;

        let index = u64::from_be_bytes(slice[offset..offset + 8].try_into().map_err(|_| "Invalid index")?);
        offset += 8;

        let timestamp = u64::from_be_bytes(slice[offset..offset + 8].try_into().map_err(|_| "Invalid timestamp")?);
        offset += 8;

        let merkle_len = u32::from_be_bytes(slice[offset..offset + 4].try_into().map_err(|_| "Invalid merkle_len")?) as usize;
        offset += 4;

        if offset + merkle_len > slice.len() {
            return Err("Merkle root offset out of bounds".to_string());
        }
        let merkle_root = String::from_utf8(slice[offset..offset + merkle_len].to_vec())
            .map_err(|e| format!("Invalid merkle_root utf8: {}", e))?;
        offset += merkle_len;

        if offset + 4 > slice.len() {
            return Err("Prev hash len offset out of bounds".to_string());
        }
        let prev_len = u32::from_be_bytes(slice[offset..offset + 4].try_into().map_err(|_| "Invalid prev_len")?) as usize;
        offset += 4;

        if offset + prev_len > slice.len() {
            return Err("Prev hash offset out of bounds".to_string());
        }
        let previous_hash = String::from_utf8(slice[offset..offset + prev_len].to_vec())
            .map_err(|e| format!("Invalid previous_hash utf8: {}", e))?;
        offset += prev_len;

        if offset + 4 > slice.len() {
            return Err("Curr hash len offset out of bounds".to_string());
        }
        let curr_len = u32::from_be_bytes(slice[offset..offset + 4].try_into().map_err(|_| "Invalid curr_len")?) as usize;
        offset += 4;

        if offset + curr_len > slice.len() {
            return Err("Curr hash offset out of bounds".to_string());
        }
        let current_hash = String::from_utf8(slice[offset..offset + curr_len].to_vec())
            .map_err(|e| format!("Invalid current_hash utf8: {}", e))?;
        offset += curr_len;

        if offset + 4 > slice.len() {
            return Err("Tx count offset out of bounds".to_string());
        }
        let tx_count = u32::from_be_bytes(slice[offset..offset + 4].try_into().map_err(|_| "Invalid tx_count")?) as usize;
        offset += 4;

        let mut transactions = Vec::with_capacity(tx_count);
        for _ in 0..tx_count {
            if offset + 80 > slice.len() {
                return Err("Transaction payload offset out of bounds".to_string());
            }
            let mut tx_buf = [0u8; 80];
            tx_buf.copy_from_slice(&slice[offset..offset + 80]);
            transactions.push(Transaction::from_bytes(&tx_buf));
            offset += 80;
        }

        Ok(Self {
            index,
            timestamp,
            merkle_root,
            previous_hash,
            current_hash,
            transactions,
        })
    }
}

// ============================================================================
// 3. IN-MEMORY STATE INTEGRATION ENGINE
// ============================================================================

/// Account balance tracking cash and asset positions
#[derive(Debug, Clone, Default)]
pub struct AccountBalance {
    pub cash: u64,
    pub assets: HashMap<[u8; 8], u64>,
}

/// Thread-safe in-memory State Ledger tracking cash and asset balances
#[derive(Debug, Default)]
pub struct StateLedger {
    balances: RwLock<HashMap<[u8; 16], AccountBalance>>,
}

impl StateLedger {
    pub fn new() -> Self {
        Self {
            balances: RwLock::new(HashMap::new()),
        }
    }

    /// Deposit cash balance into user account
    pub fn deposit_cash(&self, user_id: &[u8; 16], amount: u64) {
        let mut guard = self.balances.write().unwrap();
        let acc = guard.entry(*user_id).or_default();
        acc.cash = acc.cash.saturating_add(amount);
    }

    /// Deposit asset balance into user account
    pub fn deposit_asset(&self, user_id: &[u8; 16], asset: &[u8; 8], amount: u64) {
        let mut guard = self.balances.write().unwrap();
        let acc = guard.entry(*user_id).or_default();
        let pos = acc.assets.entry(*asset).or_default();
        *pos = pos.saturating_add(amount);
    }

    /// Query user cash balance
    pub fn get_cash(&self, user_id: &[u8; 16]) -> u64 {
        let guard = self.balances.read().unwrap();
        guard.get(user_id).map(|acc| acc.cash).unwrap_or(0)
    }

    /// Query user asset balance
    pub fn get_asset(&self, user_id: &[u8; 16], asset: &[u8; 8]) -> u64 {
        let guard = self.balances.read().unwrap();
        guard
            .get(user_id)
            .and_then(|acc| acc.assets.get(asset).copied())
            .unwrap_or(0)
    }

    /// Forcefully apply dual-entry trade balance deltas during historical replay
    pub fn apply_trade_delta_unchecked(&self, tx: &Transaction) {
        let mut guard = self.balances.write().unwrap();
        let total_cost = tx.price.saturating_mul(tx.quantity);

        let buyer_acc = guard.entry(tx.buyer_id).or_default();
        buyer_acc.cash = buyer_acc.cash.saturating_sub(total_cost);
        let buyer_asset_pos = buyer_acc.assets.entry(tx.asset_symbol).or_default();
        *buyer_asset_pos = buyer_asset_pos.saturating_add(tx.quantity);

        let seller_acc = guard.entry(tx.seller_id).or_default();
        seller_acc.cash = seller_acc.cash.saturating_add(total_cost);
        let seller_asset_pos = seller_acc.assets.entry(tx.asset_symbol).or_default();
        *seller_asset_pos = seller_asset_pos.saturating_sub(tx.quantity);
    }

    /// Atomic dual-entry debit/credit ledger state validation & execution
    pub fn validate_and_apply_trade(&self, tx: &Transaction) -> Result<(), String> {
        let mut guard = self.balances.write().unwrap();

        let total_cost = tx.price.checked_mul(tx.quantity).ok_or("Price quantity overflow")?;

        // 1. Validate Buyer Cash Balance
        let buyer_acc = guard.entry(tx.buyer_id).or_default();
        if buyer_acc.cash < total_cost {
            return Err(format!(
                "Insufficient cash for buyer {}: available {}, required {}",
                format_uuid(&tx.buyer_id),
                buyer_acc.cash,
                total_cost
            ));
        }

        // 2. Validate Seller Asset Balance
        let seller_acc = guard.entry(tx.seller_id).or_default();
        let seller_asset_qty = seller_acc.assets.get(&tx.asset_symbol).copied().unwrap_or(0);
        if seller_asset_qty < tx.quantity {
            return Err(format!(
                "Insufficient asset balance for seller {}: available {}, required {}",
                format_uuid(&tx.seller_id),
                seller_asset_qty,
                tx.quantity
            ));
        }

        // 3. Execute Dual-Entry Balance State Change
        let buyer_acc = guard.get_mut(&tx.buyer_id).unwrap();
        buyer_acc.cash -= total_cost;
        let buyer_asset_pos = buyer_acc.assets.entry(tx.asset_symbol).or_default();
        *buyer_asset_pos = buyer_asset_pos.saturating_add(tx.quantity);

        let seller_acc = guard.get_mut(&tx.seller_id).unwrap();
        seller_acc.cash = seller_acc.cash.saturating_add(total_cost);
        let seller_asset_pos = seller_acc.assets.get_mut(&tx.asset_symbol).unwrap();
        *seller_asset_pos -= tx.quantity;

        Ok(())
    }
}

// ============================================================================
// 4. HIGH-THROUGHPUT ASYNCHRONOUS MEMPOOL BUFFER
// ============================================================================

/// Thread-safe transaction memory queue
pub struct Mempool {
    queue: Mutex<Vec<Transaction>>,
}

impl Mempool {
    pub fn new() -> Self {
        Self {
            queue: Mutex::new(Vec::with_capacity(10_000)),
        }
    }

    /// Push transaction into memory pool
    pub fn push(&self, tx: Transaction) -> usize {
        let mut guard = self.queue.lock().unwrap();
        guard.push(tx);
        guard.len()
    }

    /// Drain up to max_batch transactions from pool
    pub fn drain_up_to(&self, max_batch: usize) -> Vec<Transaction> {
        let mut guard = self.queue.lock().unwrap();
        if guard.is_empty() {
            return Vec::new();
        }
        let drain_count = guard.len().min(max_batch);
        guard.drain(0..drain_count).collect()
    }

    /// Query current queue depth
    pub fn len(&self) -> usize {
        let guard = self.queue.lock().unwrap();
        guard.len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

// ============================================================================
// 5. PERSISTENT DISK STORAGE ENGINE
// ============================================================================

/// Append-only flat-file binary storage engine with index framing
pub struct DiskLedgerEngine {
    file: Mutex<File>,
    pub path: PathBuf,
}

impl DiskLedgerEngine {
    pub fn open<P: AsRef<Path>>(path: P) -> Result<Self, String> {
        let file_path = path.as_ref().to_path_buf();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(&file_path)
            .map_err(|e| format!("Failed to open disk ledger file: {}", e))?;

        Ok(Self {
            file: Mutex::new(file),
            path: file_path,
        })
    }

    /// Append block binary stream to disk with length framing and CRC checksum
    pub fn append_block(&self, block: &Block) -> Result<(), String> {
        let mut file = self.file.lock().unwrap();
        file.seek(SeekFrom::End(0))
            .map_err(|e| format!("Disk seek failed: {}", e))?;

        let block_bytes = block.to_bytes();
        let length = block_bytes.len() as u32;

        // Compute checksum of block binary
        let checksum = sha256(&block_bytes);

        // Frame header: [MAGIC: 4b][LENGTH: u32][CHECKSUM: 32b][BLOCK_BYTES]
        let mut record = Vec::with_capacity(4 + 4 + 32 + block_bytes.len());
        record.extend_from_slice(b"EQTS");
        record.extend_from_slice(&length.to_be_bytes());
        record.extend_from_slice(&checksum);
        record.extend_from_slice(&block_bytes);

        file.write_all(&record)
            .map_err(|e| format!("Failed to write block record to disk: {}", e))?;

        file.sync_all()
            .map_err(|e| format!("Failed to sync block record to disk: {}", e))?;

        Ok(())
    }

    /// Read all historical blocks sequentially from disk genesis to head
    pub fn read_all_blocks(&self) -> Result<Vec<Block>, String> {
        let mut file = self.file.lock().unwrap();
        file.seek(SeekFrom::Start(0))
            .map_err(|e| format!("Disk seek start failed: {}", e))?;

        let mut blocks = Vec::new();
        let mut buffer = Vec::new();
        file.read_to_end(&mut buffer)
            .map_err(|e| format!("Failed to read disk contents: {}", e))?;

        let mut offset = 0;
        while offset < buffer.len() {
            if offset + 40 > buffer.len() {
                return Err("Corrupted frame header at EOF".to_string());
            }

            if &buffer[offset..offset + 4] != b"EQTS" {
                return Err(format!("Invalid magic header at offset {}", offset));
            }
            offset += 4;

            let length = u32::from_be_bytes(
                buffer[offset..offset + 4]
                    .try_into()
                    .map_err(|_| "Invalid length")?,
            ) as usize;
            offset += 4;

            let expected_checksum = &buffer[offset..offset + 32];
            offset += 32;

            if offset + length > buffer.len() {
                return Err(format!("Unexpected EOF at record length {}", length));
            }

            let block_bytes = &buffer[offset..offset + length];
            offset += length;

            let actual_checksum = sha256(block_bytes);
            if actual_checksum != expected_checksum {
                return Err("Checksum mismatch in persisted block record".to_string());
            }

            let block = Block::from_bytes(block_bytes)?;
            blocks.push(block);
        }

        Ok(blocks)
    }
}

// ============================================================================
// 6. CIRCUIT BREAKER & UNIFIED BLOCKCHAIN ENGINE
// ============================================================================

#[derive(Debug, PartialEq, Eq)]
pub enum EngineError {
    CircuitBreakerTripped,
    ValidationError(String),
    StorageError(String),
}

pub struct BlockchainEngine {
    pub state_ledger: Arc<StateLedger>,
    pub mempool: Arc<Mempool>,
    pub disk_engine: Arc<DiskLedgerEngine>,
    pub circuit_breaker: Arc<AtomicBool>,
    pub latest_block_hash: Arc<RwLock<String>>,
    pub latest_block_index: Arc<AtomicU64>,
    pub total_tx_processed: Arc<AtomicU64>,
    worker_handle: Mutex<Option<JoinHandle<()>>>,
    stop_signal: Arc<AtomicBool>,
}

impl BlockchainEngine {
    /// Boot up database engine, initialize genesis block if fresh disk, and spawn BlockWorker daemon
    pub fn open<P: AsRef<Path>>(data_path: P) -> Result<Arc<Self>, String> {
        let disk_engine = Arc::new(DiskLedgerEngine::open(data_path)?);
        let state_ledger = Arc::new(StateLedger::new());
        let mempool = Arc::new(Mempool::new());
        let circuit_breaker = Arc::new(AtomicBool::new(false));
        let latest_block_hash = Arc::new(RwLock::new(String::new()));
        let latest_block_index = Arc::new(AtomicU64::new(0));
        let total_tx_processed = Arc::new(AtomicU64::new(0));
        let stop_signal = Arc::new(AtomicBool::new(false));

        // Scan existing blocks or create Genesis block
        let existing_blocks = disk_engine.read_all_blocks()?;
        if existing_blocks.is_empty() {
            let genesis = Block::create_genesis();
            disk_engine.append_block(&genesis)?;
            *latest_block_hash.write().unwrap() = genesis.current_hash.clone();
            latest_block_index.store(0, Ordering::SeqCst);
        } else {
            let last_block = existing_blocks.last().unwrap();
            *latest_block_hash.write().unwrap() = last_block.current_hash.clone();
            latest_block_index.store(last_block.index, Ordering::SeqCst);
        }

        let engine = Arc::new(Self {
            state_ledger,
            mempool,
            disk_engine,
            circuit_breaker,
            latest_block_hash,
            latest_block_index,
            total_tx_processed,
            worker_handle: Mutex::new(None),
            stop_signal,
        });

        // Spawn high-throughput BlockWorker background daemon
        let worker_engine = Arc::clone(&engine);
        let handle = thread::spawn(move || {
            worker_engine.run_block_worker();
        });

        *engine.worker_handle.lock().unwrap() = Some(handle);

        Ok(engine)
    }

    /// Atomic execution entrypoint:
    /// Validates trade, applies state balance change, pushes to ingestion mempool queue
    pub fn execute_and_commit_trade(&self, tx: Transaction) -> Result<(), EngineError> {
        // 1. Check Circuit Breaker
        if self.circuit_breaker.load(Ordering::SeqCst) {
            return Err(EngineError::CircuitBreakerTripped);
        }

        // 2. Validate and Apply Dual-Entry State Ledger Change
        self.state_ledger
            .validate_and_apply_trade(&tx)
            .map_err(EngineError::ValidationError)?;

        // 3. Forward Transaction into Ingestion Queue
        self.mempool.push(tx);
        self.total_tx_processed.fetch_add(1, Ordering::SeqCst);

        Ok(())
    }

    /// Background Asynchronous BlockWorker Daemon
    /// Micro-batching triggers:
    /// - Condition A (Time-based): 50 milliseconds elapsed
    /// - Condition B (Volume-based): 5,000 transactions accumulated
    fn run_block_worker(&self) {
        let mut last_block_time = Instant::now();

        while !self.stop_signal.load(Ordering::SeqCst) {
            let pending_count = self.mempool.len();
            let elapsed = last_block_time.elapsed();

            let should_flush = (pending_count >= 5_000)
                || (pending_count > 0 && elapsed >= Duration::from_millis(50));

            if should_flush {
                let txs = self.mempool.drain_up_to(5_000);
                if !txs.is_empty() {
                    let next_index = self.latest_block_index.load(Ordering::SeqCst) + 1;
                    let prev_hash = self.latest_block_hash.read().unwrap().clone();

                    let block = Block::new(next_index, prev_hash, txs);

                    // Attempt persistent disk append
                    if let Err(e) = self.disk_engine.append_block(&block) {
                        eprintln!("[CIRCUIT BREAKER TRIPPED] Disk commit failure: {}", e);
                        self.circuit_breaker.store(true, Ordering::SeqCst);
                        break;
                    }

                    // Update memory references
                    *self.latest_block_hash.write().unwrap() = block.current_hash.clone();
                    self.latest_block_index.store(next_index, Ordering::SeqCst);
                    last_block_time = Instant::now();
                }
            } else {
                thread::sleep(Duration::from_millis(2));
            }
        }
    }

    /// Verify historical genesis-to-head block integrity and rebuild state ledger from scratch
    pub fn verify_and_recover_state(&self, initial_state: Option<&StateLedger>) -> Result<StateLedger, String> {
        let blocks = self.disk_engine.read_all_blocks()?;
        if blocks.is_empty() {
            return Err("Cannot recover state: disk ledger is empty".to_string());
        }

        let recovered_ledger = StateLedger::new();

        // If an initial state (pre-trade starting balances) is supplied, seed it
        if let Some(init) = initial_state {
            let init_guard = init.balances.read().unwrap();
            let mut rec_guard = recovered_ledger.balances.write().unwrap();
            *rec_guard = init_guard.clone();
        }

        // 1. Verify Genesis Block
        let genesis = &blocks[0];
        if genesis.index != 0 {
            return Err("Invalid Genesis block index".to_string());
        }

        let expected_genesis_hash = Block::calculate_hash(
            0,
            genesis.timestamp,
            &genesis.merkle_root,
            &genesis.previous_hash,
        );
        if genesis.current_hash != expected_genesis_hash {
            return Err("Genesis block hash mismatch".to_string());
        }

        // 2. Sequentially Verify Chain Hashes, Merkle Roots, and Replay Block Transactions
        for i in 1..blocks.len() {
            let prev = &blocks[i - 1];
            let curr = &blocks[i];

            if curr.index != prev.index + 1 {
                return Err(format!("Block index mismatch at block {}", curr.index));
            }

            if curr.previous_hash != prev.current_hash {
                return Err(format!(
                    "Previous hash pointer mismatch at block {}: expected {}, got {}",
                    curr.index, prev.current_hash, curr.previous_hash
                ));
            }

            let expected_merkle = compute_merkle_root(&curr.transactions);
            if curr.merkle_root != expected_merkle {
                return Err(format!(
                    "Merkle root mismatch at block {}: expected {}, got {}",
                    curr.index, expected_merkle, curr.merkle_root
                ));
            }

            let expected_hash = Block::calculate_hash(
                curr.index,
                curr.timestamp,
                &curr.merkle_root,
                &curr.previous_hash,
            );
            if curr.current_hash != expected_hash {
                return Err(format!("Block current hash mismatch at block {}", curr.index));
            }

            // Replay historical transaction deltas sequentially onto recovered balance ledger
            for tx in &curr.transactions {
                recovered_ledger.apply_trade_delta_unchecked(tx);
            }
        }

        Ok(recovered_ledger)
    }

    /// Shutdown worker daemon cleanly
    pub fn shutdown(&self) {
        self.stop_signal.store(true, Ordering::SeqCst);
        if let Some(handle) = self.worker_handle.lock().unwrap().take() {
            let _ = handle.join();
        }
    }
}

impl Drop for BlockchainEngine {
    fn drop(&mut self) {
        self.shutdown();
    }
}

// ============================================================================
// 7. UNIT TESTS
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn test_sha256_known_vectors() {
        assert_eq!(
            sha256_hex(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256_hex(b"hello world"),
            "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        );
    }

    #[test]
    fn test_transaction_serialization_roundtrip() {
        let mut trade_id = [0u8; 16];
        trade_id[0] = 0xAA;
        let mut buyer_id = [0u8; 16];
        buyer_id[0] = 0xBB;
        let mut seller_id = [0u8; 16];
        seller_id[0] = 0xCC;
        let mut asset = [0u8; 8];
        asset[0..6].copy_from_slice(b"EURUSD");

        let tx = Transaction::new(1600000000000, trade_id, buyer_id, seller_id, asset, 110500, 10);
        let bytes = tx.to_bytes();
        let deserialized = Transaction::from_bytes(&bytes);

        assert_eq!(tx, deserialized);
    }

    #[test]
    fn test_merkle_tree_computation() {
        let mut trade_id = [0u8; 16];
        trade_id[0] = 1;
        let buyer_id = [2u8; 16];
        let seller_id = [3u8; 16];
        let mut asset = [0u8; 8];
        asset[0..3].copy_from_slice(b"BTC");

        let tx1 = Transaction::new(100, trade_id, buyer_id, seller_id, asset, 5000000, 1);
        let tx2 = Transaction::new(101, trade_id, buyer_id, seller_id, asset, 5000100, 2);

        let root = compute_merkle_root(&[tx1, tx2]);
        assert_eq!(root.len(), 64);
    }

    #[test]
    fn test_blockchain_engine_execution_and_recovery() {
        let test_db = PathBuf::from("./test_blockchain_temp.db");
        if test_db.exists() {
            let _ = fs::remove_file(&test_db);
        }

        {
            let engine = BlockchainEngine::open(&test_db).expect("Engine open failed");

            let buyer = [1u8; 16];
            let seller = [2u8; 16];
            let mut asset = [0u8; 8];
            asset[0..3].copy_from_slice(b"XAU");

            let init_state = StateLedger::new();
            init_state.deposit_cash(&buyer, 1_000_000);
            init_state.deposit_asset(&seller, &asset, 500);

            engine.state_ledger.deposit_cash(&buyer, 1_000_000);
            engine.state_ledger.deposit_asset(&seller, &asset, 500);

            let tx = Transaction::new(200, [5u8; 16], buyer, seller, asset, 200000, 2);
            engine.execute_and_commit_trade(tx).expect("Trade execution failed");

            // Wait for worker to commit block
            thread::sleep(Duration::from_millis(100));

            assert_eq!(engine.state_ledger.get_cash(&buyer), 600_000);
            assert_eq!(engine.state_ledger.get_cash(&seller), 400_000);
            assert_eq!(engine.state_ledger.get_asset(&buyer, &asset), 2);
            assert_eq!(engine.state_ledger.get_asset(&seller, &asset), 498);

            let recovered = engine.verify_and_recover_state(Some(&init_state)).expect("State recovery failed");
            assert_eq!(recovered.get_cash(&buyer), 600_000);
            assert_eq!(recovered.get_cash(&seller), 400_000);

            engine.shutdown();
        }

        let _ = fs::remove_file(&test_db);
    }
}
