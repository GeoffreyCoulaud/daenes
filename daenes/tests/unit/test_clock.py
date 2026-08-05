"""Unit tests for daenes.main.clock."""

import time

from daenes.main.clock import SystemClock

# Short enough not to slow the suite down, long enough to outlast the noise.
A_SHORT_WAIT = 0.01


def test_sleep_waits_out_the_duration_it_was_given():
    clock = SystemClock()

    before = time.monotonic()
    clock.sleep(A_SHORT_WAIT)

    assert time.monotonic() - before >= A_SHORT_WAIT
