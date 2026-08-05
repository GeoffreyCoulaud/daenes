import logging
from contextlib import suppress
from queue import Empty, Full, Queue
from threading import Thread

from docker.client import DockerClient
from docker.errors import DockerException
from requests.exceptions import RequestException

# The events worth another pass over the deployment, as the daemon is asked to
# filter them. Asked of it rather than done here, which is what lets nothing in
# this module ever read an event.
#
# Network events carry every change of membership and of address: a container is
# connected before it starts, and disconnected after it dies. `start` covers the
# moment between the two, where the endpoint exists and the network does not
# list the container yet, and `rename` is the only change of name that produces
# no network event at all.
#
# Docker ANDs filters of different keys and ORs those of one key, so this reads
# as "a network or container event, among these actions". Each action belongs to
# one of the two types, apart from create and destroy which both have, and an
# event that turns out to change nothing costs a pass that writes nothing.
WATCHED_EVENTS: dict[str, list[str]] = {
    "type": ["network", "container"],
    "event": [
        "connect",
        "create",
        "destroy",
        "die",
        "disconnect",
        "rename",
        "start",
    ],
}


class DockerChangeNotifier:
    """The daemon's own event stream, as something the lifecycle waits on.

    What arrived is never read: which events are worth waking over is settled by
    the filter above, and the daemon is the one applying it. So this makes no
    claim about what an event looks like, and anything the daemon lets through
    means the deployment is worth reading again.
    """

    def __init__(self, client: DockerClient) -> None:
        self._client = client
        # One slot: several events during one pass are one reason to make
        # another, and taking the slot is atomic, so an event arriving while a
        # pass is running is neither lost nor cause for waking twice.
        self._changes: Queue[None] = Queue(maxsize=1)
        self._watcher: Thread | None = None

    def wait_for_change(self, timeout: float) -> bool:
        """Wait for the deployment to change, and say whether it did."""
        self._start_watching()
        try:
            self._changes.get(timeout=timeout)
        except Empty:
            logging.debug("Nothing happened for %s seconds", timeout)
            return False
        return True

    def _start_watching(self) -> None:
        """Read the stream on a thread of its own, unless one already does.

        Started on the first wait rather than on construction, so that building
        the application reaches for nothing. An event in between is left to the
        next pass, which is what the timeout above is there for.
        """
        if self._watcher is not None and self._watcher.is_alive():
            return
        logging.debug("Watching the docker event stream")
        # A daemon thread, so that a shutdown does not wait on a blocking read
        # of a stream that may say nothing for days.
        self._watcher = Thread(target=self._watch, daemon=True, name="docker-events")
        self._watcher.start()

    def _watch(self) -> None:
        """Turn everything the daemon says into one waiting caller waking up.

        A stream that ends, however it ends, is left at that: the wait it was
        serving runs out on its own, and the pass after that opens another. So a
        daemon that refuses the endpoint altogether, which a socket proxy may
        well do, costs one refused request per pass and leaves daenes reading
        the deployment on its resync interval, the way it would with nothing to
        listen to at all. Treating the end as news instead would make a pass
        every settle interval, for as long as the refusing lasted.
        """
        try:
            for _ in self._client.events(filters=WATCHED_EVENTS, decode=False):
                self._notice()
        except (DockerException, RequestException) as error:
            logging.debug("The docker event stream failed", exc_info=error)
        logging.info("The docker event stream ended, opening another next pass")

    def _notice(self) -> None:
        """Say that the deployment changed, to whoever waits for it next.

        A full queue is one that already says so, and saying it twice is saying
        the same thing.
        """
        with suppress(Full):
            self._changes.put_nowait(None)
