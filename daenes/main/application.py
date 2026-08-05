import logging

from .errors import RetryableError
from .ports import Clock
from .zone_synchronizer import ZoneSynchronizer


class Application:
    """The lifecycle: synchronize, wait, retry what is worth retrying.

    Anything a retry cannot fix propagates, for the entry point to turn into
    an exit code.
    """

    def __init__(
        self,
        synchronizer: ZoneSynchronizer,
        clock: Clock,
        retry_interval: float,
        success_interval: float,
    ) -> None:
        self._synchronizer = synchronizer
        self._clock = clock
        self._retry_interval = retry_interval
        self._success_interval = success_interval

    def run(self) -> None:
        """Run until an error no retry can fix, which is then raised."""
        while True:
            try:
                self._synchronizer.synchronize()
            except RetryableError as error:
                logging.error("Retryable error in lifecycle", exc_info=error)
                logging.info("Retrying in %d seconds", self._retry_interval)
                self._clock.sleep(self._retry_interval)
            else:
                self._clock.sleep(self._success_interval)
