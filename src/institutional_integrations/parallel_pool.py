"""
No-GIL Parallel Pool Orchestrator Script for EQATS.

Provides high-performance multi-threading and multi-processing execution pools
bypassing single-threaded execution bottlenecks across strategy evaluation,
analytical calculations, backtesting sweeps, and background tasks.
"""

import logging
import os
import sys
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ParallelPoolOrchestrator:
    """
    High-Performance Thread and Process Orchestrator for concurrent
    no-GIL strategy matrix calculation and multi-asset ingestion.
    """

    def __init__(self, max_threads: int | None = None, max_processes: int | None = None):
        cpu_count = os.cpu_count() or 4
        self.max_threads = max_threads or (cpu_count * 4)
        self.max_processes = max_processes or cpu_count
        self._thread_pool: ThreadPoolExecutor | None = None
        self._process_pool: ProcessPoolExecutor | None = None

    def get_thread_executor(self) -> ThreadPoolExecutor:
        if self._thread_pool is None:
            self._thread_pool = ThreadPoolExecutor(
                max_workers=self.max_threads,
                thread_name_prefix="eqats_parallel_thread",
            )
        return self._thread_pool

    def get_process_executor(self) -> ProcessPoolExecutor:
        if self._process_pool is None:
            self._process_pool = ProcessPoolExecutor(max_workers=self.max_processes)
        return self._process_pool

    def map_threads(self, fn: Callable[..., Any], *iterables: Iterable[Any]) -> list[Any]:
        """Executes a callable concurrently across threads."""
        executor = self.get_thread_executor()
        return list(executor.map(fn, *iterables))

    def map_processes(self, fn: Callable[..., Any], *iterables: Iterable[Any]) -> list[Any]:
        """Executes a callable concurrently across processes (bypassing GIL)."""
        executor = self.get_process_executor()
        return list(executor.map(fn, *iterables))

    def submit_thread(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        executor = self.get_thread_executor()
        return executor.submit(fn, *args, **kwargs)

    def submit_process(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        executor = self.get_process_executor()
        return executor.submit(fn, *args, **kwargs)

    def shutdown(self, wait: bool = True) -> None:
        if self._thread_pool:
            self._thread_pool.shutdown(wait=wait)
            self._thread_pool = None
        if self._process_pool:
            self._process_pool.shutdown(wait=wait)
            self._process_pool = None


_GLOBAL_PARALLEL_POOL: ParallelPoolOrchestrator | None = None


def get_parallel_pool() -> ParallelPoolOrchestrator:
    global _GLOBAL_PARALLEL_POOL
    if _GLOBAL_PARALLEL_POOL is None:
        _GLOBAL_PARALLEL_POOL = ParallelPoolOrchestrator()
    return _GLOBAL_PARALLEL_POOL


def parallel_thread_map(fn: Callable[..., Any], *iterables: Iterable[Any]) -> list[Any]:
    return get_parallel_pool().map_threads(fn, *iterables)


def parallel_process_map(fn: Callable[..., Any], *iterables: Iterable[Any]) -> list[Any]:
    return get_parallel_pool().map_processes(fn, *iterables)
