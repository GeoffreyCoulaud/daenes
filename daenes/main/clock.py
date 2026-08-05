import time


class SystemClock:
    """The real clock, which only a running deployment uses."""

    def sleep(self, duration: float) -> None:
        time.sleep(duration)
