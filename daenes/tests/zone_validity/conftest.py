"""Checking what daenes writes with the checker of a real DNS server.

They prove what no test of our own could: that a zone daenes wrote is one BIND
agrees to load. Outside `testpaths`, so `uv run pytest` never needs the binary
they drive; CONTRIBUTING.md says how to install it.
"""

import shutil
import subprocess
from ipaddress import ip_address
from pathlib import Path

import pytest

from daenes.main.model import Allowances, LocalDomain, PublishedNetwork
from daenes.main.zone_files import FileSystemZoneStore
from daenes.main.zone_synchronizer import ZoneSynchronizer

CHECKER = "named-checkzone"

# What BIND itself applies to a primary zone, which is stricter than what the
# tool applies when asked for nothing: check-names fails there rather than
# warns, and a name no host may bear stops the zone from loading.
CHECK_ARGUMENTS = (
    "-k", "fail",  # host names, RFC 1123
    "-n", "fail",  # NS targets
    "-m", "fail",  # MX targets
    "-M", "fail",  # MX targets that are aliases
    "-S", "fail",  # SRV targets that are aliases
    "-r", "fail",  # records repeated at one name
    "-i", "full",  # every integrity check, sibling glue included
)

NAMESERVER_ADDRESS = ip_address("10.0.0.53")
ORIGIN = "services.internal"
TTL = 60


class FrozenNetworkSource:
    """A deployment written out by hand, standing in for docker."""

    def __init__(self, networks: tuple[PublishedNetwork, ...]) -> None:
        self._networks = networks

    def get_published_networks(self) -> list[PublishedNetwork]:
        return list(self._networks)


@pytest.fixture(name="checker", scope="session")
def fixture_checker() -> str:
    """The zone checker, or a skip saying it is the one thing missing."""
    path = shutil.which(CHECKER)
    if path is None:
        pytest.skip(f"{CHECKER} is not installed, see CONTRIBUTING.md")
    return path


def make_domain(
    name: str,
    addresses: tuple[str, ...] = ("172.20.0.2",),
    aliases: tuple[str, ...] = (),
) -> LocalDomain:
    return LocalDomain(
        container=name,
        name=name,
        addresses=tuple(ip_address(address) for address in addresses),
        aliases=frozenset(aliases),
    )


def write_zone(
    directory: Path,
    domains: tuple[LocalDomain, ...],
    origin: str = ORIGIN,
    ttl: int = TTL,
    serial: int | None = None,
) -> Path:
    """Write a zone the way a running daenes would, and answer its path."""
    store = FileSystemZoneStore(directory=directory)
    if serial is not None:
        # Start the count wherever the test wants it to end up.
        (directory / f"{origin}.zone").write_text(
            f"@ IN SOA ns admin {serial - 1} 3600 600 604800 600\n",
            encoding="utf-8",
        )
    ZoneSynchronizer(
        source=FrozenNetworkSource(
            (PublishedNetwork(name="compose_services", origin=origin, domains=domains),)
        ),
        store=store,
        nameserver_address=NAMESERVER_ADDRESS,
        ttl=ttl,
        # Everything allowed here, since that is what puts the most into a
        # zone. What a stricter deployment writes is a subset of these records.
        allowances=Allowances(
            multiple_addresses_per_name=True,
            multiple_networks_per_zone=True,
        ),
    ).synchronize()
    return directory / f"{origin}.zone"


def check_zone(checker: str, path: Path, origin: str = ORIGIN) -> tuple[int, str]:
    """Load a zone the way a DNS server would, and answer what it said."""
    result = subprocess.run(
        [checker, *CHECK_ARGUMENTS, origin, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, f"{result.stdout}{result.stderr}"


def assert_loads(checker: str, path: Path, origin: str = ORIGIN) -> None:
    """Fail with what the checker said, rather than with a return code.

    A warning fails too: the flags above make an error of anything that would
    stop a server, so what is left to warn about is still worth knowing.
    """
    code, output = check_zone(checker, path, origin)
    assert code == 0, f"{CHECKER} refused the zone:\n{output}\n{path.read_text()}"
    assert "warning" not in output, f"{CHECKER} warned about the zone:\n{output}"
