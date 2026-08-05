import time


class SystemClock:
    """The real clock, the only Clock a running deployment ever uses."""

    def sleep(self, duration: float) -> None:
        time.sleep(duration)
