# EAQTS v5.0 Optimization Guide

## Overview
This document details system optimization strategies implemented in EAQTS v5.0 to ensure zero-latency execution, low memory overhead, and 24x7 VPS process stability.

## Key Optimizations

### 1. Process Spawn Context
In Python 3.12, multi-threaded process forks are deprecated and prone to deadlock. EAQTS utilizes `multiprocessing.get_context('spawn')` when initializing process pools, ensuring isolated interpreter execution without inherited thread state.

### 2. SQLite WAL Auto-Checkpointing
High-frequency tick logging can inflate SQLite Write-Ahead Log (`.db-wal`) files. `DatabaseInfrastructure` automatically triggers `PRAGMA wal_checkpoint(PASSIVE)` during idle cycles or after batch transactions, flushing commits to the primary `.db` database without blocking read/write operations.

### 3. Fair Value Gap (FVG) Ring Buffer
`FVGCacheEngine` maintains active unmitigated Fair Value Gaps in a fixed-size ring buffer, converting historical price bar analysis from $O(N^2)$ to $O(1)$ operations on candle close.

### 4. DOM Canvas Debouncing
The desktop GUI (`gui.py`) throttles Depth of Market (DOM) re-renders to 100ms intervals, preventing main thread UI freezes during high-frequency tick bursts.
