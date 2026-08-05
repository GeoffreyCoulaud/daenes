"""Unit tests for daenes.main.docker.

What these fakes answer is what docker's own inspect endpoints answer, down to
the null labels and the empty address of a container that is not running.
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
    DockerDomainSource,
    DockerStartupError,
    DockerUnreachable,
    connect,
)
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
    **settings: Any,
) -> FakeContainer:
    """A container on one network, whose settings the test spells out."""
    return FakeContainer(
        name=name,
        labels=labels,
        short_id=short_id,
        networks={network: make_network_settings(**settings)},
    )


def test_a_network_naming_a_domain_is_published():
    source = make_source(make_network(make_container(name="web")))

    networks = source.get_published_networks()

    assert len(networks) == 1
    assert networks[0].origin == ORIGIN
    assert [domain.name for domain in networks[0].domains] == ["web"]
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


def test_a_network_with_no_label_at_all_is_left_alone():
    """Docker answers a null rather than an empty map for those."""
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


def test_a_container_may_name_the_domain_it_wants():
    source = make_source(
        make_network(make_container(name="web", labels={DOMAIN_LABEL: "front"}))
    )

    assert domains_of(source)[0].name == "front"


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


def test_the_aliases_of_a_container_on_the_network_are_reported():
    source = make_source(make_network(make_container(aliases=("www", "front"))))

    assert domains_of(source)[0].aliases == frozenset({"www", "front"})


def test_a_container_with_no_alias_is_reported_without_any():
    """Docker answers a null there too."""
    source = make_source(make_network(make_container(aliases=None)))

    assert domains_of(source)[0].aliases == frozenset()


def test_every_published_network_is_read():
    source = make_source(
        make_network(make_container(name="web", network="one"), name="one"),
        make_network(make_container(name="db", network="two"), name="two"),
    )

    assert [domain.name for domain in domains_of(source)] == ["web", "db"]


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


def test_connecting_pings_the_daemon(monkeypatch):
    """Creating a client proves nothing, so a missing socket is found here."""
    client = MagicMock()
    monkeypatch.setattr(docker_client.DockerClient, "from_env", lambda: client)

    assert connect() is client
    client.ping.assert_called_once_with()


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
