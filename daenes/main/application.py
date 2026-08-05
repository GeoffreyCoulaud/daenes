import logging

from .errors import RetryableError
from .ports import ChangeNotifier, Clock
from .zone_synchronizer import ZoneSynchronizer


class Application:
    """The lifecycle: synchronize, wait for news, retry what is worth retrying.

    Nothing is read from the news but that there is some: every pass reads the
    whole deployment, so waking for nothing costs a pass that writes nothing,
    and the wait running out is a pass all the same.

    Anything a retry cannot fix propagates, for the entry point to turn into
    an exit code.
    """

    # Three durations, because the loop waits on three different things, and
    # every call site names them rather than lining them up.
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        synchronizer: ZoneSynchronizer,
        notifier: ChangeNotifier,
        clock: Clock,
        retry_interval: float,
        resync_interval: float,
        settle_interval: float,
    ) -> None:
        self._synchronizer = synchronizer
        self._notifier = notifier
        self._clock = clock
        self._retry_interval = retry_interval
        self._resync_interval = resync_interval
        self._settle_interval = settle_interval

    def run(self) -> None:
        """Run until an error no retry can fix, which is then raised."""
        while True:
            try:
                self._synchronizer.synchronize()
                if self._notifier.wait_for_change(self._resync_interval):
                    self._settle()
            except RetryableError as error:
                logging.error("Retryable error in lifecycle", exc_info=error)
                logging.info("Retrying in %d seconds", self._retry_interval)
                self._clock.sleep(self._retry_interval)

    def _settle(self) -> None:
        """Let a deployment that is moving finish moving.

        It comes up a container at a time, and every state it passes through
        would otherwise be a zone file of its own, and a transfer to every
        secondary server watching that zone.
        """
        logging.debug("The deployment changed, letting it settle")
        self._clock.sleep(self._settle_interval)
