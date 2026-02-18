"""Unit tests for UploadManager._adjust_worker_count (no QThread started)."""

import time
import pytest
from unittest.mock import MagicMock, patch
from src.upload_manager import UploadManager
from src.stats_tracker import StatsTracker


@pytest.fixture()
def manager(mock_state_manager, stats_tracker):
    """An UploadManager ready for direct method calls (thread never started)."""
    m = UploadManager(
        upload_key="test-key",
        state_manager=mock_state_manager,
        stats_tracker=stats_tracker,
    )
    # Make measurement window immediate so tests don't have to wait
    m.MEASUREMENT_INTERVAL = 0
    return m


def _force_last_measurement(manager, seconds_ago: float = 60.0):
    """Set last_measurement_time far enough in the past to trigger a measurement."""
    manager.last_measurement_time = time.time() - seconds_ago


# ---------------------------------------------------------------------------
# set_manual_workers / set_auto_optimize
# ---------------------------------------------------------------------------


class TestWorkerConfiguration:
    def test_set_manual_workers_clamps_to_min(self, manager):
        manager.set_manual_workers(0)
        assert manager.current_workers == UploadManager.MIN_WORKERS

    def test_set_manual_workers_clamps_to_max(self, manager):
        manager.set_manual_workers(999)
        assert manager.current_workers == UploadManager.MAX_WORKERS

    def test_set_manual_workers_disables_auto_optimize(self, manager):
        manager.set_manual_workers(4)
        assert manager.auto_optimize is False
        assert manager.current_workers == 4

    def test_set_auto_optimize_true_resets_to_default(self, manager):
        manager.set_manual_workers(7)
        manager.set_auto_optimize(True)
        assert manager.auto_optimize is True
        assert manager.current_workers == UploadManager.DEFAULT_WORKERS

    def test_set_auto_optimize_false_uses_manual_workers(self, manager):
        manager.manual_workers = 5
        manager.set_auto_optimize(False)
        assert manager.auto_optimize is False
        assert manager.current_workers == 5


# ---------------------------------------------------------------------------
# _adjust_worker_count
# ---------------------------------------------------------------------------


class TestAdjustWorkerCount:
    def test_no_op_when_auto_optimize_disabled(self, manager):
        manager.set_manual_workers(2)
        initial = manager.current_workers
        manager._adjust_worker_count()
        assert manager.current_workers == initial

    def test_no_op_when_not_enough_time_elapsed(self, manager):
        manager.MEASUREMENT_INTERVAL = 9999
        manager.last_measurement_time = time.time()  # just now
        initial = manager.current_workers
        manager._adjust_worker_count()
        assert manager.current_workers == initial

    def test_first_call_records_measurement_no_change(self, manager):
        """First call has no prior throughput reference — should NOT change worker count."""
        manager.last_throughput = 0
        _force_last_measurement(manager)
        manager.stats_tracker.total_bytes_uploaded = 1024 * 100
        initial = manager.current_workers

        manager._adjust_worker_count()

        assert manager.current_workers == initial

    def test_throughput_improvement_increases_workers(self, manager):
        """When throughput improves >10%, worker count should increment."""
        manager.last_throughput = 1_000_000  # 1 MB/s baseline
        _force_last_measurement(manager)
        # Simulate 2 MB/s this interval → 100% improvement
        manager.stats_tracker.total_bytes_uploaded = 2_000_000
        manager.last_measurement_bytes = 0
        manager.last_measurement_time = time.time() - 1.0  # 1-second window

        signals = []
        manager.worker_count_changed.connect(lambda n: signals.append(n))

        manager._adjust_worker_count()

        assert manager.current_workers == UploadManager.DEFAULT_WORKERS + 1
        assert signals == [UploadManager.DEFAULT_WORKERS + 1]

    def test_throughput_degradation_decreases_workers(self, manager):
        """When throughput degrades >10%, worker count should decrement."""
        manager.last_throughput = 2_000_000  # 2 MB/s baseline
        manager.current_workers = 5
        _force_last_measurement(manager)
        # Simulate 1 MB/s this interval → 50% degradation
        manager.stats_tracker.total_bytes_uploaded = 1_000_000
        manager.last_measurement_bytes = 0
        manager.last_measurement_time = time.time() - 1.0

        signals = []
        manager.worker_count_changed.connect(lambda n: signals.append(n))

        manager._adjust_worker_count()

        assert manager.current_workers == 4
        assert signals == [4]

    def test_worker_count_does_not_exceed_max(self, manager):
        """Worker count should never exceed MAX_WORKERS."""
        manager.current_workers = UploadManager.MAX_WORKERS
        manager.last_throughput = 1_000_000
        _force_last_measurement(manager)
        manager.stats_tracker.total_bytes_uploaded = 5_000_000
        manager.last_measurement_bytes = 0
        manager.last_measurement_time = time.time() - 1.0

        manager._adjust_worker_count()

        assert manager.current_workers == UploadManager.MAX_WORKERS

    def test_worker_count_does_not_go_below_min(self, manager):
        """Worker count should never drop below MIN_WORKERS."""
        manager.current_workers = UploadManager.MIN_WORKERS
        manager.last_throughput = 2_000_000
        _force_last_measurement(manager)
        manager.stats_tracker.total_bytes_uploaded = 100  # near-zero throughput
        manager.last_measurement_bytes = 0
        manager.last_measurement_time = time.time() - 1.0

        manager._adjust_worker_count()

        assert manager.current_workers == UploadManager.MIN_WORKERS

    def test_small_throughput_change_does_not_adjust(self, manager):
        """A change within the improvement threshold leaves worker count unchanged."""
        manager.last_throughput = 1_000_000
        _force_last_measurement(manager)
        # 1.05 MB/s → 5% improvement (below 10% threshold)
        manager.stats_tracker.total_bytes_uploaded = 1_050_000
        manager.last_measurement_bytes = 0
        manager.last_measurement_time = time.time() - 1.0
        initial = manager.current_workers

        manager._adjust_worker_count()

        assert manager.current_workers == initial

    def test_measurement_state_updated_after_call(self, manager):
        """After calling _adjust_worker_count, last_measurement_time and bytes are updated."""
        _force_last_measurement(manager)
        manager.stats_tracker.total_bytes_uploaded = 500_000

        manager._adjust_worker_count()

        assert manager.last_measurement_bytes == 500_000
        assert manager.last_measurement_time == pytest.approx(time.time(), abs=1.0)
