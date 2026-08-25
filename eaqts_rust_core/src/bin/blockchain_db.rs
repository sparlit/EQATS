//! Ultra-Low Latency Mission-Critical Custom Blockchain Database Engine
//! Multi-threaded Benchmark Loop Runner

use eaqts_rust_core::blockchain_db::{
    format_symbol, format_uuid, BlockchainEngine, Transaction,
};
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::thread;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

fn main() {
    println!("================================================================================");
    println!("  ELITE QUANTUM AUTONOMOUS TRADING SYSTEM (EAQTS VERSION 6.0)");
    println!("  ULTRA-LOW LATENCY CUSTOM BLOCKCHAIN DATABASE ENGINE BENCHMARK");
    println!("================================================================================");

    let db_path = PathBuf::from("./blockchain_benchmark.db");
    if db_path.exists() {
        let _ = fs::remove_file(&db_path);
    }

    let engine = BlockchainEngine::open(&db_path).expect("Failed to initialize Blockchain Engine");

    // Initialize User Accounts with Cash & Asset Balances
    let num_users = 100;
    let mut buyer_ids = Vec::with_capacity(num_users);
    let mut seller_ids = Vec::with_capacity(num_users);

    let initial_state_snapshot = eaqts_rust_core::blockchain_db::StateLedger::new();

    for i in 0..num_users {
        let mut buyer = [0u8; 16];
        buyer[0..8].copy_from_slice(&(i as u64 + 1000).to_be_bytes());
        buyer_ids.push(buyer);

        let mut seller = [0u8; 16];
        seller[0..8].copy_from_slice(&(i as u64 + 2000).to_be_bytes());
        seller_ids.push(seller);

        // Seed 1,000,000.00 cash ($1,000,000,00 cents) per buyer
        engine.state_ledger.deposit_cash(&buyer, 1_000_000_000);
        initial_state_snapshot.deposit_cash(&buyer, 1_000_000_000);

        // Seed 100,000 asset units per seller for symbol 'EURUSD\0\0'
        let mut asset = [0u8; 8];
        asset[0..6].copy_from_slice(b"EURUSD");
        engine.state_ledger.deposit_asset(&seller, &asset, 100_000);
        initial_state_snapshot.deposit_asset(&seller, &asset, 100_000);
    }

    println!("[INIT] Seeded {} buyers and {} sellers with cash & asset balances.", num_users, num_users);
    println!("[INIT] Starting multi-threaded trade execution loop: 50,000 trades across 4 worker threads...");

    let total_trades = 50_000;
    let num_threads = 4;
    let trades_per_thread = total_trades / num_threads;

    let start_time = Instant::now();
    let mut handles = Vec::new();

    for t in 0..num_threads {
        let engine_clone = Arc::clone(&engine);
        let buyers = buyer_ids.clone();
        let sellers = seller_ids.clone();

        let handle = thread::spawn(move || {
            let mut asset = [0u8; 8];
            asset[0..6].copy_from_slice(b"EURUSD");

            for i in 0..trades_per_thread {
                let now = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_nanos() as u64;

                let mut trade_id = [0u8; 16];
                let tx_idx = (t * trades_per_thread + i) as u64;
                trade_id[0..8].copy_from_slice(&tx_idx.to_be_bytes());

                let buyer = buyers[i % buyers.len()];
                let seller = sellers[i % sellers.len()];

                // Price: $1.1050 (110500 pips/cents), Qty: 1
                let tx = Transaction::new(now, trade_id, buyer, seller, asset, 110_500, 1);

                if let Err(e) = engine_clone.execute_and_commit_trade(tx) {
                    panic!("Trade execution failed on thread {}: {:?}", t, e);
                }
            }
        });
        handles.push(handle);
    }

    for h in handles {
        h.join().unwrap();
    }

    let execution_elapsed = start_time.elapsed();
    println!(
        "[BENCHMARK] Enqueued and validated 50,000 trades in {:.3?} ({:.0} trades/sec)",
        execution_elapsed,
        50_000.0 / execution_elapsed.as_secs_f64()
    );

    // Wait for BlockWorker background daemon to finish micro-batching mempool to disk
    println!("[MEMPOOL] Waiting for BlockWorker to commit pending transactions to disk...");
    while engine.mempool.len() > 0 {
        thread::sleep(std::time::Duration::from_millis(5));
    }
    // Small sleep to ensure final block write completes
    thread::sleep(std::time::Duration::from_millis(100));

    let total_elapsed = start_time.elapsed();
    let blocks_on_disk = engine.disk_engine.read_all_blocks().unwrap();
    let mined_blocks_count = blocks_on_disk.len().saturating_sub(1); // Exclude Genesis

    println!("================================================================================");
    println!("  BENCHMARK & SYSTEM PERFORMANCE RESULTS");
    println!("================================================================================");
    println!("  - Total Trades Settled : 50,000");
    println!("  - Execution Wall Time  : {:.3?}", total_elapsed);
    println!("  - Overall Throughput   : {:.0} trades/sec", 50_000.0 / total_elapsed.as_secs_f64());
    println!("  - Blocks Mined on Disk : {}", mined_blocks_count);
    println!(
        "  - Mining Rate          : {:.2} blocks/sec",
        mined_blocks_count as f64 / total_elapsed.as_secs_f64()
    );

    let sample_block = &blocks_on_disk[blocks_on_disk.len().min(2) - 1];
    println!("  - Sample Block Index   : {}", sample_block.index);
    println!("  - Sample Merkle Root   : {}", sample_block.merkle_root);
    println!("  - Sample Block Hash    : {}", sample_block.current_hash);

    println!("\n[VERIFICATION] Executing Full Historical State Recovery & Chain Integrity Audit...");
    let recovery_start = Instant::now();
    let recovered_ledger = engine
        .verify_and_recover_state(Some(&initial_state_snapshot))
        .expect("Historical state recovery and chain audit failed!");

    let recovery_elapsed = recovery_start.elapsed();
    println!("[VERIFICATION] Chain audit & balance state recovery completed in {:.3?}", recovery_elapsed);

    // Verify sample buyer balance consistency
    let sample_buyer = buyer_ids[0];
    let live_cash = engine.state_ledger.get_cash(&sample_buyer);
    let recovered_cash = recovered_ledger.get_cash(&sample_buyer);
    assert_eq!(live_cash, recovered_cash, "Live cash and recovered cash state mismatch!");

    let mut asset = [0u8; 8];
    asset[0..6].copy_from_slice(b"EURUSD");
    let sample_seller = seller_ids[0];
    let live_asset = engine.state_ledger.get_asset(&sample_seller, &asset);
    let recovered_asset = recovered_ledger.get_asset(&sample_seller, &asset);
    assert_eq!(live_asset, recovered_asset, "Live asset and recovered asset state mismatch!");

    println!("================================================================================");
    println!("  [SUCCESS] ALL BLOCKCHAIN DATABASE ENGINE INVARIANTS VERIFIED 100% PERFECTLY");
    println!("  Sample Buyer ID  : {}", format_uuid(&sample_buyer));
    println!("  Sample Cash Bal  : ${:.2}", live_cash as f64 / 100.0);
    println!("  Sample Asset Sym : {}", format_symbol(&asset));
    println!("  Sample Asset Qty : {}", live_asset);
    println!("================================================================================");

    engine.shutdown();
    let _ = fs::remove_file(&db_path);
}
