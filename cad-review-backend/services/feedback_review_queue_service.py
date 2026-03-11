from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional

from database import SessionLocal
from models import FeedbackThread

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_worker: threading.Thread | None = None
_stop_event: threading.Event | None = None
_active_threads: set[str] = set()
_processor: Optional[Callable[[str, str], None]] = None


def _poll_seconds() -> float:
    raw = os.getenv("FEEDBACK_REVIEW_QUEUE_POLL_SECONDS", "").strip()
    if not raw:
        return 0.5
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.5
    return value if value > 0 else 0.5


def _claim_next_thread() -> tuple[str, str] | None:
    db = SessionLocal()
    try:
        pending_threads = (
            db.query(FeedbackThread)
            .filter(
                FeedbackThread.status == "agent_reviewing",
                FeedbackThread.agent_decision.is_(None),
            )
            .order_by(FeedbackThread.updated_at.asc(), FeedbackThread.created_at.asc())
            .limit(20)
            .all()
        )
    finally:
        db.close()

    with _lock:
        for thread in pending_threads:
            if thread.id in _active_threads:
                continue
            _active_threads.add(thread.id)
            return thread.project_id, thread.id
    return None


def _release_thread(thread_id: str) -> None:
    with _lock:
        _active_threads.discard(thread_id)


def _run_loop() -> None:
    while True:
        stop_event = _stop_event
        if stop_event is None or stop_event.is_set():
            return

        processor = _processor
        if processor is None:
            time.sleep(_poll_seconds())
            continue

        claimed = _claim_next_thread()
        if not claimed:
            time.sleep(_poll_seconds())
            continue

        project_id, thread_id = claimed
        try:
            processor(project_id, thread_id)
        except Exception:
            logger.exception("feedback review worker failed: project=%s thread=%s", project_id, thread_id)
        finally:
            _release_thread(thread_id)


def start_feedback_review_worker(processor: Callable[[str, str], None]) -> None:
    global _worker, _stop_event, _processor
    with _lock:
        if _worker is not None and _worker.is_alive():
            _processor = processor
            return
        _processor = processor
        _stop_event = threading.Event()
        _worker = threading.Thread(
            target=_run_loop,
            name="feedback-review-worker",
            daemon=True,
        )
        _worker.start()


def stop_feedback_review_worker(timeout_seconds: float = 2.0) -> None:
    global _worker, _stop_event
    with _lock:
        worker = _worker
        stop_event = _stop_event
        _worker = None
        _stop_event = None
        _active_threads.clear()
    if stop_event is not None:
        stop_event.set()
    if worker is not None and worker.is_alive():
        worker.join(max(0.1, timeout_seconds))
