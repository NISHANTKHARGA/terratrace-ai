"""Background job runner: bounded thread pool, cancellation, status tracking."""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

from app.config import settings
from app.core.logging import get_logger

log = get_logger("workers.jobs")


class JobRunner:
    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="terratrace-job")
        self._futures: Dict[str, Future] = None  # type: ignore[assignment]
        self._cancel = set()
        self._lock = threading.Lock()
        self._futures = {}

    def submit(self, job_id: str, fn: Callable[[], Any]) -> Future:
        with self._lock:
            if job_id in self._futures and not self._futures[job_id].done():
                raise ValueError(f"job {job_id} is already running")
            fut = self._pool.submit(self._wrap, job_id, fn)
            self._futures[job_id] = fut
            return fut

    def _wrap(self, job_id: str, fn: Callable[[], Any]) -> Any:
        started = time.time()
        try:
            return fn()
        except Exception as exc:  # engine records failure itself; keep pool alive
            log.exception("job crashed", extra={"extra_fields": {"job": job_id, "error": str(exc)}})
            return None
        finally:
            log.info("job finished", extra={"extra_fields": {
                "job": job_id, "seconds": round(time.time() - started, 2)}})

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            self._cancel.add(job_id)
            fut = self._futures.get(job_id)
        if fut and not fut.done():
            # cooperative cancellation: the engine polls `should_cancel`
            return True
        return False

    def should_cancel(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel

    def clear_cancel(self, job_id: str) -> None:
        with self._lock:
            self._cancel.discard(job_id)

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            fut = self._futures.get(job_id)
        return bool(fut and not fut.done())

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


runner = JobRunner(max_workers=max(1, settings.job_workers))
