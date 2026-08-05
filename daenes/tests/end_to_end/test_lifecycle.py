"""How daenes starts, and how it stops.

What a single call does with an error belongs in the unit tests; what is left
here needs a real process, in a real container, with a real init to answer to.
"""

import time

from daenes.main.errors import ReturnCodes

from .conftest import (
    NAMESERVER_NAME,
    get_container_logs,
    wait_for_exit_code,
)

# Generous enough that a container waiting it out is unambiguously stuck.
STOP_TIMEOUT = 20


def test_sigterm_stops_daenes_promptly(network, deployment, start_daenes, zone, unique):
    """`docker stop` sends SIGTERM, which the kernel drops unless PID 1 handles it.

    Every restart and redeploy then waits out the whole stop timeout before a
    SIGKILL, for a process that had nothing left to do.
    """
    web = unique("web")
    deployment.add_container(network, name=web)
    daenes = start_daenes()
    zone.wait_for_names({NAMESERVER_NAME, web})

    wrapped = daenes.get_wrapped_container()
    started_at = time.monotonic()
    wrapped.stop(timeout=STOP_TIMEOUT)
    elapsed = time.monotonic() - started_at

    assert elapsed < STOP_TIMEOUT / 2, f"took {elapsed:.1f}s to stop"
    assert wrapped.wait()["StatusCode"] == 0
    assert "Received SIGTERM" in get_container_logs(daenes)


def test_a_socket_that_was_never_mounted_is_reported_at_startup(start_daenes):
    """The mistake every first deployment makes, and the one worth naming.

    Retrying it forever would leave a container that looks like it is working.
    """
    daenes = start_daenes(mount_socket=False)

    exit_code = wait_for_exit_code(daenes)

    assert exit_code == ReturnCodes.DOCKER_UNREACHABLE_AT_STARTUP
    assert "docker.sock" in get_container_logs(daenes)


def test_a_missing_dns_ip_stops_daenes(start_daenes):
    """The one setting daenes cannot read off the daemon, so it has to be given."""
    daenes = start_daenes(DNS_IP=None)

    exit_code = wait_for_exit_code(daenes)

    assert exit_code == ReturnCodes.MISSING_ENVIRONMENT_VARIABLE
    assert "DNS_IP" in get_container_logs(daenes)


def test_a_dns_ip_that_is_not_an_address_stops_daenes(start_daenes):
    """Told apart from a missing one, since the mistake is not the same one."""
    daenes = start_daenes(DNS_IP="the-dns-server")

    exit_code = wait_for_exit_code(daenes)

    assert exit_code == ReturnCodes.INVALID_ENVIRONMENT_VARIABLE
    assert "DNS_IP" in get_container_logs(daenes)


def test_a_setting_that_is_neither_true_nor_false_stops_daenes(start_daenes):
    """A yes spelled any other way would quietly mean no."""
    daenes = start_daenes(ALLOW_MULTIPLE_ADDRESSES_PER_NAME="yes")

    exit_code = wait_for_exit_code(daenes)

    assert exit_code == ReturnCodes.INVALID_ENVIRONMENT_VARIABLE
    assert "ALLOW_MULTIPLE_ADDRESSES_PER_NAME" in get_container_logs(daenes)
