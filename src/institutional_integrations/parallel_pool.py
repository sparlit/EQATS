"""
Parallel Pool Orchestrator Module for No-GIL Concurrent Processing.
Provides robust process and thread pool management without GIL bottlenecks.
"""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing as mp
import os
from typing import Any, Callable, List, Optional


class ParallelPoolOrchestrator:
    """
    No-GIL Process/Thread Pool Orchestrator for High-Performance Quant Tasks.
    """

    def __init__(self, max_workers: Optional[int] = None) -> None:
        self.max_workers = max_workers or max(1, os.cpu_count() or 4)

    def run_process_pool(self, func: Callable[..., Any], tasks: List[Any]) -> List[Any]:
        """
        Executes CPU-bound tasks across a ProcessPoolExecutor bypassing the Python GIL.
        """
        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=self.max_workers, mp_context=ctx) as executor:
            results = list(executor.map(func, tasks))
        return results

    def run_thread_pool(self, func: Callable[..., Any], tasks: List[Any]) -> List[Any]:
        """
        Executes I/O-bound tasks across a ThreadPoolExecutor.
        """
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            results = list(executor.map(func, tasks))
        return results


def get_parallel_orchestrator(max_workers: Optional[int] = None) -> ParallelPoolOrchestrator:
    return ParallelPoolOrchestrator(max_workers=max_workers)
