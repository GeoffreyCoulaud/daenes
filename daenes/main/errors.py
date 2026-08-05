from enum import IntEnum


class ReturnCodes(IntEnum):
    """The exit codes daenes stops on, part of the container's interface."""

    MISSING_ENVIRONMENT_VARIABLE = 1
    INVALID_ENVIRONMENT_VARIABLE = 2
    UNRETRYABLE_EXCEPTION_IN_LIFECYCLE = 3
    DOCKER_UNREACHABLE_AT_STARTUP = 4
    DOCKER_TOO_OLD = 5


class RetryableError(Exception):
    """Raised for a failure the next turn of the loop may not hit.

    Docker restarting is the case it exists for: waiting beats taking the
    container down over it.
    """
