"""Unit tests for daenes.main.docker_events.

Reading the stream is a method, and calling it is what most of these do: a
thread is only started where starting one is the thing being tested. Nothing
here waits on a duration either, since the queue behind `wait_for_change` is
where the two sides meet, and a queue can be looked into.
"""

from typing import cast

import pytest
from docker.client import DockerClient
from docker.errors import APIError, DockerException
from requests.exceptions import ConnectionError as ConnectionReset

from daenes.main.docker_events import WATCHED_EVENTS, DockerChangeNotifier

from .conftest import FakeDockerClient

# What a wait is given when the answer is already there, and when it never will
# be. Neither of them waits.
NO_WAIT = 0

# Long enough that a wait running it out is a bug rather than a slow machine.
A_MOMENT = 5

# Anything at all: what an event holds is never read.
AN_EVENT = object()


def make_notifier(client: object) -> DockerChangeNotifier:
    """A notifier over a daemon that is none, which it has no way of telling."""
    return DockerChangeNotifier(client=cast(DockerClient, client))


def read_the_stream(notifier: DockerChangeNotifier) -> None:
    """Read the stream here and now, rather than on a thread of its own."""
    notifier._watch()  # pylint: disable=protected-access


def news_waiting(notifier: DockerChangeNotifier) -> int:
    """How many wake-ups are waiting, without starting anything to find out."""
    return notifier._changes.qsize()  # pylint: disable=protected-access


def wait_for_the_reading_to_end(notifier: DockerChangeNotifier) -> None:
    """Let the thread reading the stream finish, and say so once it has.

    What lets a test watch a stream being read again without racing the thread
    that was reading the last one.
    """
    watcher = notifier._watcher  # pylint: disable=protected-access
    assert watcher is not None, "no stream was ever read"
    watcher.join(timeout=A_MOMENT)
    assert not watcher.is_alive(), "the stream was still being read"


def test_an_event_the_daemon_let_through_is_news():
    notifier = make_notifier(FakeDockerClient(events=(AN_EVENT,)))

    read_the_stream(notifier)

    assert news_waiting(notifier) == 1


def test_which_events_are_news_is_left_to_the_daemon():
    """Daenes says which ones it wants; applying that is the daemon's business."""
    client = FakeDockerClient(events=(AN_EVENT,))

    read_the_stream(make_notifier(client))

    assert client.event_filters == [WATCHED_EVENTS]


def test_the_stream_is_never_decoded():
    """What an event holds is never read, so nothing here can misread it."""
    client = FakeDockerClient(events=(AN_EVENT,))

    read_the_stream(make_notifier(client))

    assert client.event_decoding == [False]


def test_a_burst_of_events_is_one_pass_to_make():
    """A deployment coming up is one reason to read it again, not twenty."""
    notifier = make_notifier(FakeDockerClient(events=(AN_EVENT, AN_EVENT, AN_EVENT)))

    read_the_stream(notifier)

    assert news_waiting(notifier) == 1


def test_a_stream_that_ends_leaves_the_wait_to_run_out():
    """Rather than calling its own end news, which would be a pass every settle
    interval for as long as a daemon keeps refusing the endpoint."""
    notifier = make_notifier(FakeDockerClient(events=()))

    read_the_stream(notifier)

    assert news_waiting(notifier) == 0


@pytest.mark.parametrize(
    "client",
    [
        FakeDockerClient(events_error=DockerException("no such endpoint")),
        FakeDockerClient(events_error=ConnectionReset("connection reset")),
        FakeDockerClient(events=(APIError("stopped mid-sentence"),)),
    ],
    ids=["refused", "connection_reset", "stopped_mid_sentence"],
)
def test_a_stream_that_fails_is_no_crash_and_no_news(client):
    """Waiting the resync interval out is the answer to all of them, which is
    daenes doing what it did before it had anything to listen to."""
    notifier = make_notifier(client)

    read_the_stream(notifier)

    assert news_waiting(notifier) == 0


def test_waiting_answers_the_news_a_stream_brought():
    notifier = make_notifier(FakeDockerClient(events=(AN_EVENT,)))

    assert notifier.wait_for_change(A_MOMENT) is True


def test_waiting_gives_up_on_a_deployment_holding_still(quiet_client):
    """Which is what makes a pass happen anyway, every resync interval."""
    notifier = make_notifier(quiet_client)

    assert notifier.wait_for_change(NO_WAIT) is False


def test_one_stream_is_read_at_a_time(quiet_client):
    """A wait finding one already being read leaves it alone."""
    notifier = make_notifier(quiet_client)

    notifier.wait_for_change(NO_WAIT)
    quiet_client.reading.wait(timeout=A_MOMENT)
    notifier.wait_for_change(NO_WAIT)

    assert quiet_client.event_filters == [WATCHED_EVENTS]


def test_a_stream_that_ended_is_read_again_on_the_next_wait():
    """The only place it is read again, which is what keeps a daemon that is
    down from being asked as fast as it can refuse: once per pass that worked."""
    client = FakeDockerClient(events=(AN_EVENT,))
    notifier = make_notifier(client)

    notifier.wait_for_change(A_MOMENT)
    wait_for_the_reading_to_end(notifier)
    notifier.wait_for_change(A_MOMENT)
    wait_for_the_reading_to_end(notifier)

    assert client.event_filters == [WATCHED_EVENTS, WATCHED_EVENTS]
