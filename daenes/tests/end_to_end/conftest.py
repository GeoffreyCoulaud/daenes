"""Fixtures for the contract and end-to-end tests.

Everything is asserted from the outside: real networks and containers on a real
daemon, daenes built from the repository's own Dockerfile, and the zone files
it leaves on disk read back the way a DNS server would read them.

Daenes reads the whole daemon rather than one network of it, so nothing here is
isolated the way a client and a server would be. Each test is given a zone of
its own instead, and only ever looks at that zone. The zones of other tests, and
of whatever else is running on the machine, land in the same directory and are
none of its business. That is what lets these run in parallel, and on a daemon
nobody emptied first.

No secret is needed anywhere, so all of this runs on every pull request.
"""

# pytest resolves fixtures by parameter name, so the shadowing is deliberate.
# pylint: disable=redefined-outer-name

import os
import secrets
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from docker.client import DockerClient
from docker.errors import NotFound
from filelock import FileLock
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

REPO_ROOT = Path(__file__).resolve().parents[3]
DAENES_IMAGE_TAG = "daenes:e2e"

# Something to put on a network that does nothing but stay there.
IDLE_IMAGE = "alpine:latest"
IDLE_COMMAND = "sleep infinity"

# The labels daenes reads, spelled out rather than imported from it: they are
# the interface the README documents, and a test restating it proves nothing.
DOMAIN_LABEL = "daenes.domain"
ENABLED_LABEL = "daenes.enabled"

# What turns a dual stack network into an IPv6 only one.
IPV4_OPTION = "com.docker.network.enable_ipv4"

# Where the image expects its two mounts.
SOCKET_MOUNT = "/var/run/docker.sock"
ZONES_MOUNT = "/zones"

DEFAULT_SOCKET = "/var/run/docker.sock"
UNIX_SCHEME = "unix://"

# What every zone here names as its nameserver, and the name it names it under.
NAMESERVER_ADDRESS = "10.0.0.53"
NAMESERVER_NAME = "ns"

# How a zone file spells the zone's own name, which is what a record answering
# for the domain itself is written under.
APEX_NAME = "@"

# The intervals daenes is started with here, short enough for a test to watch
# several passes go by without waiting on them.
SUCCESS_INTERVAL = 2
RETRY_INTERVAL = 1

# Generous: a test only waits this out when something is actually wrong.
TIMEOUT = 60


def poll_until(
    predicate: Callable[[], Any],
    *,
    timeout: float,
    interval: float = 0.2,
) -> Any:
    """Call `predicate` until it answers something truthy, or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
        except Exception as error:  # pylint: disable=broad-exception-caught
            last_error = error
        else:
            if result:
                return result
            last_error = None
        time.sleep(interval)
    raise TimeoutError(
        f"Condition not met within {timeout}s, last error: {last_error!r}"
    ) from last_error


def get_container_logs(container: DockerContainer) -> str:
    """Everything a container wrote to stdout and stderr so far."""
    stdout, stderr = container.get_logs()
    return (stdout + b"\n" + stderr).decode(errors="replace")


def wait_for_exit_code(container: DockerContainer, *, timeout: float = TIMEOUT) -> int:
    """Block until daenes exits, and answer the code it exited on."""
    try:
        return container.get_wrapped_container().wait(timeout=timeout)["StatusCode"]
    except Exception as error:  # pylint: disable=broad-exception-caught
        raise AssertionError(
            f"daenes was still running {timeout}s later, logs:\n"
            f"{get_container_logs(container)}"
        ) from error


def get_is_running(container: DockerContainer) -> bool:
    """Whether a container's process is still alive."""
    wrapped = container.get_wrapped_container()
    wrapped.reload()
    return wrapped.status == "running"


def get_address(container: DockerContainer, network: Network, key: str) -> str:
    """The address docker gave a container on a network."""
    wrapped = container.get_wrapped_container()
    wrapped.reload()
    return wrapped.attrs["NetworkSettings"]["Networks"][network.name][key]


def wait_for_log(
    container: DockerContainer,
    *fragments: str,
    timeout: float = TIMEOUT,
) -> str:
    """The log line holding every fragment given, once daenes has written it.

    One line rather than the whole output: daenes reports on every network of
    the daemon, so the other tests' zones are in there too.
    """

    def read() -> str | None:
        return next(
            (
                line
                for line in get_container_logs(container).splitlines()
                if all(fragment in line for fragment in fragments)
            ),
            None,
        )

    try:
        return poll_until(read, timeout=timeout)
    except TimeoutError as error:
        raise AssertionError(
            f"No log line held all of {fragments}, logs:\n"
            f"{get_container_logs(container)}"
        ) from error


def _build_daenes_image() -> None:
    """Build the image with `docker buildx build`.

    Not testcontainers' `DockerImage`, which builds through docker-py's legacy
    builder API and cannot share BuildKit's cache with the Buildx-based CI
    build and push steps.
    """
    command = ["docker", "buildx", "build", "--load"]
    # The GitHub Actions cache only exists inside a workflow run. Reads are
    # always safe there; writes are opt-in because the cache is shared with the
    # default branch, and untrusted code must never populate it.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        command += ["--cache-from", "type=gha"]
        if os.environ.get("E2E_CACHE_WRITE") == "true":
            command += ["--cache-to", "type=gha,mode=max,ignore-error=true"]
    command += ["-t", DAENES_IMAGE_TAG, str(REPO_ROOT)]
    subprocess.run(command, check=True)


@pytest.fixture(scope="session")
def daenes_image(tmp_path_factory: pytest.TempPathFactory, worker_id: str) -> str:
    """The daenes image, built from the repository's own Dockerfile."""
    if worker_id == "master":
        _build_daenes_image()
        return DAENES_IMAGE_TAG
    # Session fixtures run once per xdist worker, but the image tag is shared.
    marker = tmp_path_factory.getbasetemp().parent / "daenes-image"
    with FileLock(f"{marker}.lock"):
        if not marker.exists():
            _build_daenes_image()
            marker.write_text(DAENES_IMAGE_TAG)
    return DAENES_IMAGE_TAG


@pytest.fixture(scope="session")
def docker_socket() -> str:
    """The socket on this host, which is what daenes is given to read."""
    host = os.environ.get("DOCKER_HOST", "")
    path = host[len(UNIX_SCHEME) :] if host.startswith(UNIX_SCHEME) else DEFAULT_SOCKET
    if not Path(path).exists():
        pytest.skip(f"No docker socket at {path}, and daenes is given one to read")
    return path


@pytest.fixture
def client() -> Iterator[DockerClient]:
    """A client of the daemon, for the tests questioning it themselves."""
    connected = DockerClient.from_env()
    yield connected
    connected.close()


@pytest.fixture
def token() -> str:
    """What tells this test's zone and containers from every other test's."""
    return secrets.token_hex(4)


@pytest.fixture
def origin(token: str) -> str:
    """A zone of this test's own, under the domain meant for local names."""
    return f"t{token}.internal"


@pytest.fixture
def unique(token: str) -> Callable[[str], str]:
    """A name no test running beside this one can hold at the same time."""
    return lambda name: f"{name}-{token}"


class Deployment:
    """What one test puts on the daemon, and takes off it afterwards.

    Containers go first and networks after, since the daemon refuses to remove
    a network anything is still attached to.
    """

    def __init__(self) -> None:
        self._networks: list[Network] = []
        self._containers: list[DockerContainer] = []

    def add_network(
        self,
        domain: str | None = None,
        ipv6: bool = False,
        ipv4: bool = True,
        **labels: str,
    ) -> Network:
        """A network, publishing a domain when it is given one.

        The daemon picks the subnets, IPv6 included, so two of these never
        collide however many tests are running.
        """
        if domain is not None:
            labels[DOMAIN_LABEL] = domain
        settings: dict[str, Any] = {"labels": labels, "enable_ipv6": ipv6}
        if not ipv4:
            settings["options"] = {IPV4_OPTION: "false"}
        network = Network(docker_network_kw=settings).create()
        self._networks.append(network)
        return network

    def add_container(
        self,
        network: Network,
        name: str | None = None,
        aliases: tuple[str, ...] = (),
        hostname: str | None = None,
        dns_search: tuple[str, ...] = (),
        **labels: str,
    ) -> DockerContainer:
        """A container that does nothing but hold its names and an address.

        What it runs is no business of daenes: only the names docker knows it
        by there, and the addresses it answers at.
        """
        container = (
            DockerContainer(IDLE_IMAGE)
            .with_command(IDLE_COMMAND)
            .with_network(network)
            .with_kwargs(
                labels=labels, hostname=hostname, dns_search=list(dns_search)
            )
        )
        if name is not None:
            container.with_name(name)
        if aliases:
            container.with_network_aliases(*aliases)
        container.start()
        self._containers.append(container)
        return container

    def remove(self, container: DockerContainer) -> None:
        """Take one container down before the test is over."""
        container.stop()
        self._containers.remove(container)

    def close(self) -> None:
        for container in self._containers:
            container.stop()
        for network in self._networks:
            # A container's endpoint outlives the container itself by a moment.
            poll_until(_remover(network), timeout=30, interval=1)


def _remover(network: Network) -> Callable[[], bool]:
    def remove() -> bool:
        network.remove()
        return True

    return remove


@pytest.fixture
def deployment() -> Iterator[Deployment]:
    """The networks and containers this test asks the daemon for."""
    made = Deployment()
    yield made
    made.close()


@pytest.fixture
def network(deployment: Deployment, origin: str) -> Network:
    """A network publishing this test's zone."""
    return deployment.add_network(origin)


@pytest.fixture
def zones(tmp_path: Path) -> Path:
    """The directory daenes writes into, mounted into it from the host."""
    directory = tmp_path / "zones"
    directory.mkdir()
    return directory


@pytest.fixture
def start_daenes(
    daenes_image: str,
    docker_socket: str,
    zones: Path,
) -> Iterator[Callable[..., DockerContainer]]:
    """Start daenes over this daemon, writing into this test's directory.

    Any environment variable may be overridden by keyword, or set to None to be
    left out, which is how a test hands it an environment it cannot run on.
    """
    started: list[DockerContainer] = []

    def start(mount_socket: bool = True, **overrides: Any) -> DockerContainer:
        environment: dict[str, Any] = {
            "DNS_IP": NAMESERVER_ADDRESS,
            "SUCCESS_INTERVAL": SUCCESS_INTERVAL,
            "RETRY_INTERVAL": RETRY_INTERVAL,
            "LOG_LEVEL": "DEBUG",
        }
        container = DockerContainer(daenes_image).with_volume_mapping(
            str(zones), ZONES_MOUNT, "rw"
        )
        if mount_socket:
            container.with_volume_mapping(docker_socket, SOCKET_MOUNT, "rw")
        for name, value in (environment | overrides).items():
            if value is not None:
                container.with_env(name, str(value))
        container.start()
        started.append(container)
        return container

    yield start
    for container in started:
        # A test that stopped daenes itself, to watch it start again, left
        # nothing here to stop.
        with suppress(NotFound):
            container.stop()


def parse_records(text: str) -> dict[str, set[str]]:
    """The addresses each name answers with, read back out of a zone file.

    Read here rather than through daenes: a test parsing the file with the code
    that wrote it would only be agreeing with itself.
    """
    records: dict[str, set[str]] = {}
    for line in text.splitlines():
        match line.split():
            case [name, "IN", "A" | "AAAA", address]:
                records.setdefault(name, set()).add(address)
    return records


def parse_serial(text: str) -> int:
    """The serial out of a zone's SOA record."""
    for line in text.splitlines():
        match line.split():
            case ["@", "IN", "SOA", _, _, serial, *_]:
                return int(serial)
    raise AssertionError(f"No SOA record in:\n{text}")


@dataclass(frozen=True)
class ZoneFile:
    """The zone file daenes writes for this test's origin, if it writes one."""

    path: Path
    origin: str

    def read(self) -> str | None:
        """What the file says, or None while daenes has not written it."""
        try:
            return self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def wait(self, *, timeout: float = TIMEOUT) -> str:
        """What the file says, once daenes has written it."""
        try:
            return poll_until(self.read, timeout=timeout)
        except TimeoutError as error:
            raise AssertionError(f"daenes never wrote {self.path}") from error

    def records(self) -> dict[str, set[str]]:
        return parse_records(self.wait())

    def serial(self) -> int:
        return parse_serial(self.wait())

    def wait_for_names(
        self,
        names: set[str],
        *,
        timeout: float = TIMEOUT,
    ) -> dict[str, set[str]]:
        """The records, once the zone answers these names and no others."""

        def read() -> dict[str, set[str]] | None:
            text = self.read()
            if text is None:
                return None
            records = parse_records(text)
            return records if set(records) == names else None

        try:
            return poll_until(read, timeout=timeout)
        except TimeoutError as error:
            raise AssertionError(
                f"Zone {self.origin} never answered exactly {sorted(names)}, "
                f"last read:\n{self.read()}"
            ) from error


@pytest.fixture
def zone_for(zones: Path) -> Callable[[str], ZoneFile]:
    """Any origin's zone file, for the tests publishing more than one."""
    return lambda origin: ZoneFile(path=zones / f"{origin}.zone", origin=origin)


@pytest.fixture
def zone(zone_for: Callable[[str], ZoneFile], origin: str) -> ZoneFile:
    """The zone this test's network publishes."""
    return zone_for(origin)
