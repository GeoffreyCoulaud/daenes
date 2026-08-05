import logging
from contextlib import suppress
from queue import Empty, Full, Queue
from threading import Thread

from docker.client import DockerClient
from docker.errors import DockerException
from requests.exceptions import RequestException

# What the daemon is asked to send. Network events carry membership and
# addresses, `start` the moment where an endpoint exists and the network does
# not list the container yet, `rename` the only change of name no network event
# mentions. Values of one key are ORed, and the two keys ANDed:
# https://docs.docker.com/reference/cli/docker/system/events/#filter
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
    """The daemon's event stream, as something the lifecycle waits on.

    An event is never read: the daemon applies the filter, so anything it lets
    through means the deployment is worth reading again.
    """

    def __init__(self, client: DockerClient) -> None:
        self._client = client
        # One slot, taken atomically: an event arriving during a pass is neither
        # lost nor cause for waking twice.
        self._changes: Queue[None] = Queue(maxsize=1)
        self._watcher: Thread | None = None

    def wait_for_change(self, timeout: float) -> bool:
        self._start_watching()
        try:
            self._changes.get(timeout=timeout)
        except Empty:
            logging.debug("Nothing happened for %s seconds", timeout)
            return False
        return True

    def _start_watching(self) -> None:
        """Started on the first wait, so that building the application reads nothing."""
        if self._watcher is not None and self._watcher.is_alive():
            return
        logging.debug("Watching the docker event stream")
        # Daemon, so that a blocking read never holds up a shutdown.
        self._watcher = Thread(target=self._watch, daemon=True, name="docker-events")
        self._watcher.start()

    def _watch(self) -> None:
        """Read the stream until it ends, however it ends.

        Its end is not itself news: the wait runs out on its own and the next
        pass opens another stream, so a socket proxy refusing /events leaves
        daenes on its resync interval instead of passing every settle interval.
        """
        try:
            for _ in self._client.events(filters=WATCHED_EVENTS, decode=False):
                self._notice()
        except (DockerException, RequestException) as error:
            logging.debug("The docker event stream failed", exc_info=error)
        logging.info("The docker event stream ended, opening another next pass")

    def _notice(self) -> None:
        # A full queue already says the deployment changed.
        with suppress(Full):
            self._changes.put_nowait(None)
