"""Unit tests for daenes.main.docker.

The fakes answer what docker's inspect endpoints answer, down to the empty
address of a container that is not running. That those answers are the ones a
daemon really gives is what end_to_end/test_contracts_docker.py checks.
"""

from ipaddress import ip_address
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from docker import client as docker_client
from docker.client import DockerClient
from docker.errors import DockerException
from requests.exceptions import ConnectionError as RequestsConnectionError

from daenes.main.docker import (
    DOMAIN_LABEL,
    ENABLED_LABEL,
    MINIMUM_API_VERSION,
    MINIMUM_DOCKER_VERSION,
    DockerDomainSource,
    DockerStartupError,
    DockerUnreachable,
    connect,
)
from daenes.main.errors import ReturnCodes
from daenes.main.model import LocalDomain

from .conftest import (
    FakeContainer,
    FakeDockerClient,
    FakeNetwork,
    make_network_settings,
)

ORIGIN = "services.internal"
NETWORK = "compose_services"


def make_source(*networks: FakeNetwork) -> DockerDomainSource:
    """The adapter over a daemon that answers what the test set up."""
    return DockerDomainSource(client=cast(DockerClient, FakeDockerClient(networks)))


def make_network(
    *containers: FakeContainer,
    labels: dict[str, str] | None = None,
    name: str = NETWORK,
) -> FakeNetwork:
    return FakeNetwork(
        name=name,
        labels={DOMAIN_LABEL: ORIGIN} if labels is None else labels,
        containers=containers,
    )


def domains_of(source: DockerDomainSource) -> list[LocalDomain]:
    """Every container the adapter reported, whichever network it was on."""
    return [
        domain
        for network in source.get_published_networks()
        for domain in network.domains
    ]


def make_container(
    name: str = "web",
    labels: dict[str, str] | None = None,
    network: str = NETWORK,
    short_id: str = "0123456789ab",
    dns_names: tuple[str, ...] | None = None,
    **settings: Any,
) -> FakeContainer:
    """A container on one network, whose settings the test spells out.

    Docker names it by its own name and its identifier unless the test says
    what else it is known by there.
    """
    return FakeContainer(
        name=name,
        labels=labels,
        short_id=short_id,
        networks={
            network: make_network_settings(
                dns_names=(name, short_id) if dns_names is None else dns_names,
                **settings,
            )
        },
    )


def names_of(source: DockerDomainSource) -> list[frozenset[str]]:
    """The names of every container the adapter reported."""
    return [domain.names for domain in domains_of(source)]


def test_a_network_naming_a_domain_is_published():
    source = make_source(make_network(make_container(name="web")))

    networks = source.get_published_networks()

    assert len(networks) == 1
    assert networks[0].origin == ORIGIN
    assert [domain.names for domain in networks[0].domains] == [frozenset({"web"})]
    assert networks[0].domains[0].addresses == (ip_address("172.20.0.2"),)


def test_a_container_is_reported_with_its_id():
    """Two containers asking for one name are told apart by nothing else."""
    source = make_source(make_network(make_container(short_id="abc123def456")))

    assert domains_of(source)[0].container == "abc123def456"


def test_a_network_everything_left_is_still_published():
    """The zone it asks for has to say so, rather than stay as it was."""
    source = make_source(make_network())

    networks = source.get_published_networks()

    assert len(networks) == 1
    assert networks[0].domains == ()


def test_a_network_naming_no_domain_is_left_alone():
    source = make_source(make_network(make_container(), labels={}))

    assert not source.get_published_networks()


def test_a_network_with_a_null_label_map_is_left_alone():
    """Today's daemon answers an empty map, an older one may answer a null.

    Go serialises a map it never allocated as null, so the tolerance costs one
    fallback and saves a crash on a daemon that does.
    """
    source = make_source(FakeNetwork(name=NETWORK, containers=(make_container(),)))

    assert not source.get_published_networks()


def test_a_network_left_with_only_the_enabled_label_of_earlier_versions(caplog):
    """It used to publish a zone, so its owner is told why it no longer does."""
    source = make_source(
        make_network(make_container(), labels={ENABLED_LABEL: "true"})
    )

    assert not source.get_published_networks()
    assert ENABLED_LABEL in caplog.text
    assert DOMAIN_LABEL in caplog.text


def test_a_container_is_published_without_being_asked_to_be():
    """Reading a deployment rather than being told about it is the whole point."""
    source = make_source(make_network(make_container(labels={})))

    assert len(domains_of(source)) == 1


def test_a_container_may_opt_out():
    source = make_source(make_network(make_container(labels={ENABLED_LABEL: "false"})))

    assert not domains_of(source)


def test_a_container_is_named_by_docker_alone():
    """Every name docker answers for it there, and no label of its own."""
    source = make_source(
        make_network(
            make_container(
                name="web",
                labels={DOMAIN_LABEL: "front"},
                dns_names=("web", "api", "0123456789ab"),
            )
        )
    )

    assert names_of(source) == [frozenset({"web", "api"})]


def test_a_container_that_left_the_network_is_ignored():
    """Between being listed and being read, a container may be gone."""
    source = make_source(make_network(make_container(network="another_network")))

    assert not domains_of(source)


def test_a_container_with_no_address_on_the_network_is_ignored():
    """A container that is not running has an empty address, not a missing one."""
    source = make_source(make_network(make_container(address=None)))

    assert not domains_of(source)


def test_a_container_on_a_dual_stack_network_answers_over_both():
    """enable_ipv6 adds a stack rather than replacing the other one."""
    source = make_source(make_network(make_container(ipv6_address="fd00::2")))

    assert domains_of(source)[0].addresses == (
        ip_address("172.20.0.2"),
        ip_address("fd00::2"),
    )


def test_a_container_on_an_ipv6_only_network_answers_over_ipv6():
    """A network created with --ipv4=false leaves IPAddress empty."""
    container = make_container(address=None, ipv6_address="fd00::2")

    source = make_source(make_network(container))

    assert domains_of(source)[0].addresses == (ip_address("fd00::2"),)


def test_an_address_docker_makes_no_sense_of_is_ignored():
    source = make_source(make_network(make_container(address="not-an-address")))

    assert not domains_of(source)


def test_the_identifier_docker_knows_a_container_by_is_not_a_name():
    """Nobody types it, and it is a new one on every redeploy.

    A container given no hostname of its own is given that identifier as one,
    so leaving it out leaves out both.
    """
    container = make_container(
        short_id="abc123def456", dns_names=("web", "abc123def456")
    )

    source = make_source(make_network(container))

    assert names_of(source) == [frozenset({"web"})]


def test_a_container_answers_to_the_hostname_it_was_given():
    """Docker resolves it, so a zone that left it out would answer for less."""
    source = make_source(
        make_network(make_container(dns_names=("web", "0123456789ab", "other-host")))
    )

    assert names_of(source) == [frozenset({"web", "other-host"})]


def test_a_container_docker_names_in_no_way_at_all_is_ignored():
    """Which no daemon speaking API 1.44 does, but an older one would."""
    source = make_source(make_network(make_container(dns_names=())))

    assert not domains_of(source)


def test_every_published_network_is_read():
    source = make_source(
        make_network(make_container(name="web", network="one"), name="one"),
        make_network(make_container(name="db", network="two"), name="two"),
    )

    assert names_of(source) == [frozenset({"web"}), frozenset({"db"})]


def test_a_network_is_inspected_before_its_containers_are_read():
    """Listing networks answers without them; only an inspect carries them."""
    network = make_network(make_container())

    make_source(network).get_published_networks()

    assert network.reloaded == 1


@pytest.mark.parametrize(
    "error",
    [DockerException("daemon is restarting"), RequestsConnectionError("socket is gone")],
    ids=["docker_error", "connection_error"],
)
def test_a_daemon_that_cannot_be_questioned_is_worth_retrying(error):
    """Docker restarting under us is not a reason to take the container down."""
    client = cast(DockerClient, FakeDockerClient(error=error))
    source = DockerDomainSource(client=client)

    with pytest.raises(DockerUnreachable) as raised:
        source.get_published_networks()

    assert raised.value.__cause__ is error


def make_daemon(monkeypatch, version: dict[str, str]) -> MagicMock:
    """A daemon answering the given /version, and nothing else."""
    client = MagicMock()
    client.version.return_value = version
    monkeypatch.setattr(docker_client.DockerClient, "from_env", lambda: client)
    return client


def test_connecting_asks_the_daemon_what_it_speaks(monkeypatch):
    """Creating a client proves nothing, so a missing socket is found here."""
    client = make_daemon(monkeypatch, {"ApiVersion": MINIMUM_API_VERSION})

    assert connect() is client
    client.version.assert_called_once_with()


def test_a_daemon_newer_than_the_minimum_is_connected_to(monkeypatch):
    """The floor is a floor, not the one version daenes was written against."""
    client = make_daemon(monkeypatch, {"ApiVersion": "1.55"})

    assert connect() is client


def test_a_daemon_too_old_to_name_its_containers_is_refused(monkeypatch):
    """It answers no DNSNames, so daenes would publish nothing and say nothing."""
    make_daemon(monkeypatch, {"ApiVersion": "1.43"})

    with pytest.raises(DockerStartupError) as raised:
        connect()

    assert raised.value.return_code == ReturnCodes.DOCKER_TOO_OLD
    assert MINIMUM_DOCKER_VERSION in str(raised.value)


def test_a_daemon_that_answers_no_version_is_not_one(monkeypatch):
    """Something is listening on that socket, but it is not a docker daemon."""
    make_daemon(monkeypatch, {})

    with pytest.raises(DockerStartupError) as raised:
        connect()

    assert raised.value.return_code == ReturnCodes.DOCKER_UNREACHABLE_AT_STARTUP


@pytest.mark.parametrize(
    "error",
    [DockerException("no such file"), RequestsConnectionError("socket is gone")],
    ids=["docker_error", "connection_error"],
)
def test_a_daemon_that_never_answered_is_not_worth_retrying(monkeypatch, error):
    """A socket that was never mounted will not appear on its own."""
    monkeypatch.setattr(
        docker_client.DockerClient, "from_env", MagicMock(side_effect=error)
    )

    with pytest.raises(DockerStartupError) as raised:
        connect()

    assert raised.value.__cause__ is error
    assert raised.value.return_code == ReturnCodes.DOCKER_UNREACHABLE_AT_STARTUP
