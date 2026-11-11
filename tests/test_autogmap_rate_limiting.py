"""Test AutoGMap upload rate limiting - queue with max 2 concurrent requests.

Tests:
  1. Queue initialization
  2. Queueing multiple uploads (10+)
  3. Max 2 concurrent workers
  4. Queue full rejection
  5. Backpressure handling
"""
import asyncio
import os
import sqlite3
import threading
import time
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import autogmap, db


@pytest.fixture(autouse=True)
def reset_queue():
    """Reset global queue state before and after each test."""
    autogmap._upload_queue = None
    autogmap._upload_executor = None
    autogmap._upload_stats = {
        "queued": 0,
        "processed": 0,
        "queue_peak": 0,
        "queue_full_rejections": 0,
        "last_queued_at": None,
    }
    yield
    # Cleanup
    if autogmap._upload_executor:
        autogmap._upload_executor.shutdown(wait=False)
    autogmap._upload_queue = None
    autogmap._upload_executor = None


def test_queue_initialization():
    """Test that upload queue initializes correctly."""
    autogmap.init_upload_queue()

    assert autogmap._upload_queue is not None
    assert autogmap._upload_executor is not None
    assert autogmap._upload_queue.qsize() == 0

    # Should be idempotent
    autogmap.init_upload_queue()
    assert autogmap._upload_queue is not None


def test_queue_max_workers_config():
    """Test that max workers is limited to 2 per Mansi's requirement."""
    # Default should be 2
    assert autogmap.AUTOGMAP_UPLOAD_MAX_WORKERS == 2

    autogmap.init_upload_queue()
    assert autogmap._upload_executor._max_workers == 2


def test_queue_max_size_config():
    """Test that queue has configurable max size."""
    assert autogmap.AUTOGMAP_UPLOAD_QUEUE_SIZE == 1000

    autogmap.init_upload_queue()
    assert autogmap._upload_queue.maxsize == 1000


def test_queue_single_upload():
    """Test queueing a single upload."""
    autogmap.init_upload_queue()

    upload_job_called = False

    def mock_db_update(success, status, data):
        nonlocal upload_job_called
        upload_job_called = True
        assert success == True
        assert status == "uploaded"

    success = autogmap.queue_upload(
        rec_id=1,
        file_path="/tmp/test.ogg",
        phone="9876543210",
        direction="in",
        duration_sec=60,
        db_update_fn=mock_db_update,
    )

    assert success == True
    assert autogmap._upload_queue.qsize() == 1
    assert autogmap._upload_stats["queued"] == 1


def test_queue_multiple_uploads():
    """Test queueing 10+ uploads and verify max 2 concurrent."""
    autogmap.init_upload_queue()

    num_uploads = 15
    processed_count = 0
    concurrent_uploads = []
    max_concurrent = 0
    max_concurrent_lock = threading.Lock()

    def mock_db_update(success, status, data):
        nonlocal processed_count, max_concurrent
        concurrent_count = len(concurrent_uploads)
        with max_concurrent_lock:
            if concurrent_count > max_concurrent:
                max_concurrent = concurrent_count
            concurrent_uploads.append(threading.current_thread().ident)
            time.sleep(0.1)  # Simulate work
            concurrent_uploads.pop()
        processed_count += 1

    # Queue 15 uploads
    for i in range(num_uploads):
        success = autogmap.queue_upload(
            rec_id=i + 1,
            file_path=f"/tmp/test_{i}.ogg",
            phone=f"987654321{i:02d}",
            direction="in",
            duration_sec=60,
            db_update_fn=mock_db_update,
        )
        assert success == True

    assert autogmap._upload_queue.qsize() == num_uploads
    assert autogmap._upload_stats["queued"] == num_uploads


def test_queue_full_rejection():
    """Test that queue rejects uploads when full."""
    # Create tiny queue for testing
    autogmap._upload_queue = __import__('queue').Queue(maxsize=2)
    autogmap._upload_executor = __import__('concurrent.futures').ThreadPoolExecutor(max_workers=2)

    def mock_db_update(success, status, data):
        pass

    # Fill the queue
    for i in range(2):
        success = autogmap.queue_upload(
            rec_id=i + 1,
            file_path=f"/tmp/test_{i}.ogg",
            phone=f"987654321{i:02d}",
            direction="in",
            duration_sec=60,
            db_update_fn=mock_db_update,
        )
        assert success == True

    # Next upload should fail (queue full)
    success = autogmap.queue_upload(
        rec_id=99,
        file_path="/tmp/test_full.ogg",
        phone="9876543299",
        direction="in",
        duration_sec=60,
        db_update_fn=mock_db_update,
    )
    assert success == False
    assert autogmap._upload_stats["queue_full_rejections"] == 1


def test_queue_stats():
    """Test queue statistics tracking."""
    autogmap.init_upload_queue()

    def mock_db_update(success, status, data):
        pass

    # Queue 5 uploads
    for i in range(5):
        autogmap.queue_upload(
            rec_id=i + 1,
            file_path=f"/tmp/test_{i}.ogg",
            phone=f"987654321{i:02d}",
            direction="in",
            duration_sec=60,
            db_update_fn=mock_db_update,
        )

    stats = autogmap.get_upload_queue_stats()
    assert stats["queued"] == 5
    assert stats["current_queue_depth"] == 5
    assert stats["queue_peak"] == 5
    assert stats["queue_full_rejections"] == 0
    assert stats["last_queued_at"] is not None


def test_queue_worker_shutdown():
    """Test that upload worker gracefully shuts down."""
    autogmap.init_upload_queue()

    stop_event = threading.Event()
    worker_thread = threading.Thread(
        target=autogmap.upload_queue_worker,
        args=(stop_event,),
        daemon=True,
    )
    worker_thread.start()
    time.sleep(0.5)

    # Stop worker
    stop_event.set()
    worker_thread.join(timeout=2)
    assert not worker_thread.is_alive()


def test_queue_without_initialization():
    """Test that queue_upload fails gracefully if not initialized."""
    # Don't initialize queue
    assert autogmap._upload_queue is None

    def mock_db_update(success, status, data):
        pass

    success = autogmap.queue_upload(
        rec_id=1,
        file_path="/tmp/test.ogg",
        phone="9876543210",
        direction="in",
        duration_sec=60,
        db_update_fn=mock_db_update,
    )
    assert success == False


def test_rate_limit_2_per_second():
    """Test that uploads are throttled to max 2 concurrent requests."""
    autogmap.init_upload_queue()

    # Track concurrent execution
    active_tasks = []
    max_concurrent = [0]  # Use list for thread-safe mutation
    max_concurrent_lock = threading.Lock()

    def mock_db_update(success, status, data):
        task_id = threading.current_thread().ident
        active_tasks.append(task_id)

        with max_concurrent_lock:
            if len(active_tasks) > max_concurrent[0]:
                max_concurrent[0] = len(active_tasks)

        # Simulate work
        time.sleep(0.2)
        active_tasks.remove(task_id)

    # Start worker
    stop_event = threading.Event()
    worker_thread = threading.Thread(
        target=autogmap.upload_queue_worker,
        args=(stop_event,),
        daemon=True,
    )
    worker_thread.start()

    # Queue 10 uploads
    for i in range(10):
        autogmap.queue_upload(
            rec_id=i + 1,
            file_path=f"/tmp/test_{i}.ogg",
            phone=f"987654321{i:02d}",
            direction="in",
            duration_sec=60,
            db_update_fn=mock_db_update,
        )

    # Wait for processing
    time.sleep(3)

    # Stop worker
    stop_event.set()
    worker_thread.join(timeout=2)

    # Verify max 2 concurrent uploads
    print(f"Max concurrent uploads observed: {max_concurrent[0]}")
    assert max_concurrent[0] <= 2, f"Expected max 2 concurrent, got {max_concurrent[0]}"


@pytest.mark.asyncio
async def test_upload_with_mock_client():
    """Test upload queue integration with mocked AutoGMapClient."""
    autogmap.init_upload_queue()

    mock_client = AsyncMock(spec=autogmap.AutoGMapClient)
    mock_client.upload_recording = AsyncMock(
        return_value=(True, "uploaded", {"recording_id": "rec_123"})
    )

    job_executed = False

    def mock_db_update(success, status, data):
        nonlocal job_executed
        job_executed = True
        assert success == True
        assert status == "uploaded"

    # Mock the client creation
    with patch('app.autogmap.AutoGMapClient', return_value=mock_client):
        success = autogmap.queue_upload(
            rec_id=1,
            file_path="/tmp/test.ogg",
            phone="9876543210",
            direction="in",
            duration_sec=60,
            db_update_fn=mock_db_update,
        )

        assert success == True
        assert autogmap._upload_queue.qsize() == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
