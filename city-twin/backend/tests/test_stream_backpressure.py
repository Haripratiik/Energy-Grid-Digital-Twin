"""What happens to a subscriber that cannot keep up.

The SSE broadcaster gives every subscriber a bounded queue so one slow client
cannot make the simulation loop wait. Bounding the queue is only half of it: the
loop also has to drop the subscriber when the bound is reached, and the dropped
subscriber has to find out. It used not to. The loop removed the queue from its
list and the generator went on awaiting that queue forever, so the client kept
receiving ": keepalive" on a stream that would never carry data again. No error
reached the browser, so EventSource never reconnected. These tests pin both
halves.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from main import _EVICTED, _evict
from twin.ukf import UnscentedKalmanFilter


def test_a_dropped_subscriber_is_told_it_was_dropped():
    """Eviction has to be observable, or it is just a hang with extra steps."""
    q: asyncio.Queue = asyncio.Queue(maxsize=4)
    for i in range(4):
        q.put_nowait(f"payload-{i}")
    assert q.full()

    _evict(q)

    # The stale payloads are gone: this subscriber was already too slow to read
    # them, and holding them would leave no room for the one thing it must see.
    assert q.qsize() == 1
    assert q.get_nowait() is _EVICTED


def test_eviction_leaves_room_even_on_a_full_queue():
    """The sentinel must never itself hit the bound it is reporting."""
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    q.put_nowait("stale")
    _evict(q)                       # would raise QueueFull without the drain
    assert q.get_nowait() is _EVICTED


def test_the_sentinel_is_not_confusable_with_a_payload():
    """Payloads are JSON strings, so identity is the only safe test."""
    assert not isinstance(_EVICTED, str)


class TestInnovationBeforeUpdate:
    """The anomaly score has no meaning until there has been an innovation."""

    def _filter(self) -> UnscentedKalmanFilter:
        return UnscentedKalmanFilter(2, Q=np.eye(2) * 1e-3, R=np.eye(2) * 1e-2)

    def test_it_refuses_rather_than_raising_attributeerror(self):
        ukf = self._filter()
        with pytest.raises(RuntimeError, match="requires a preceding update"):
            ukf.normalized_innovation_sq(np.zeros(2))

    def test_it_works_once_an_update_has_run(self):
        ukf = self._filter()
        innovation = ukf.update(np.zeros(2), lambda x: x)
        score = ukf.normalized_innovation_sq(innovation)
        assert score >= 0.0
