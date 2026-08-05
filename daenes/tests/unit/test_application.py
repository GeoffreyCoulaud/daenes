"""Unit tests for daenes.main.application."""

from unittest.mock import MagicMock

import pytest

from daenes.main.application import Application
from daenes.main.docker import DockerUnreachable
from daenes.main.errors import RetryableError

from .conftest import EndOfTest, FakeChangeNotifier

# Distinct values, so that no two of them can be swapped unnoticed.
RETRY_INTERVAL = 7
RESYNC_INTERVAL = 11
SETTLE_INTERVAL = 0.3

# What a notifier answers, spelled out where a test reads better for it.
CHANGED = True


def make_application(
    clock,
    outcomes: list,
    changes: tuple[bool | Exception, ...] = (),
) -> tuple[Application, MagicMock, FakeChangeNotifier]:
    """An application whose every pass and every wait was decided in advance."""
    synchronizer = MagicMock()
    synchronizer.synchronize.side_effect = outcomes
    notifier = FakeChangeNotifier(changes)
    application = Application(
        synchronizer=synchronizer,
        notifier=notifier,
        clock=clock,
        retry_interval=RETRY_INTERVAL,
        resync_interval=RESYNC_INTERVAL,
        settle_interval=SETTLE_INTERVAL,
    )
    return application, synchronizer, notifier


def test_a_successful_pass_waits_for_the_deployment_to_change(clock):
    """And waits no longer than the resync interval, which is the whole point:
    a pass happens on news, and happens anyway when there is none."""
    application, _, notifier = make_application(clock, [None, EndOfTest()])

    with pytest.raises(EndOfTest):
        application.run()

    assert notifier.waited == [RESYNC_INTERVAL]


def test_a_deployment_holding_still_costs_nothing_in_between(clock):
    """Nothing is slept through on the way: the wait is the waiting."""
    application, _, _ = make_application(clock, [None, EndOfTest()])

    with pytest.raises(EndOfTest):
        application.run()

    assert clock.slept == []


def test_a_deployment_that_changed_is_let_settle_first(clock):
    """It comes up a container at a time, and each state it passes through
    would otherwise be a zone file, and a transfer to every secondary."""
    application, _, _ = make_application(
        clock, [None, EndOfTest()], changes=(CHANGED,)
    )

    with pytest.raises(EndOfTest):
        application.run()

    assert clock.slept == [SETTLE_INTERVAL]


def test_a_retryable_error_waits_out_the_retry_interval(clock):
    """Waiting is what keeps a daemon that is down from being hammered."""
    application, _, notifier = make_application(
        clock, [RetryableError("down"), EndOfTest()]
    )

    with pytest.raises(EndOfTest):
        application.run()

    assert clock.slept == [RETRY_INTERVAL]
    assert not notifier.waited, "a pass that failed was waited on for news"


def test_a_wait_that_fails_is_retried_like_a_pass_that_did(clock):
    """Whatever a notifier needs to answer may be as absent as the deployment."""
    application, _, _ = make_application(
        clock, [None, EndOfTest()], changes=(DockerUnreachable(),)
    )

    with pytest.raises(EndOfTest):
        application.run()

    assert clock.slept == [RETRY_INTERVAL]


def test_an_unretryable_error_is_left_to_the_caller(clock):
    """Turning it into an exit code is the entry point's job, not the loop's."""
    application, synchronizer, _ = make_application(clock, [ValueError("unretryable")])

    with pytest.raises(ValueError):
        application.run()

    assert synchronizer.synchronize.call_count == 1


def test_run_survives_the_docker_daemon_going_away(clock):
    """Docker restarting is routine, and outlives nothing but a few turns."""
    outcomes = [DockerUnreachable(), DockerUnreachable(), None, EndOfTest()]
    application, synchronizer, notifier = make_application(clock, outcomes)

    with pytest.raises(EndOfTest):
        application.run()

    # Two failures, a recovery, and only then the exception ending the test.
    assert synchronizer.synchronize.call_count == 4
    assert clock.slept == [RETRY_INTERVAL, RETRY_INTERVAL]
    assert notifier.waited == [RESYNC_INTERVAL]
