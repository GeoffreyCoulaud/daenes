"""Contract tests for the docker API daenes reads the deployment through.

Every branch in `daenes.main.docker` keys off something docker is assumed to
do. The unit tests can only restate those assumptions, since their fakes are
where the assumptions live; these check them against a real daemon, one fact
per test, so that a docker release changing its answers fails the test naming
the fact rather than surfacing in the middle of an end-to-end run.

Nothing here runs daenes, or needs its image built.
"""

from ipaddress import ip_address

import pytest
from docker.client import DockerClient
from docker.errors import DockerException

from ..external_contracts import (
    CONTAINERS_KEY,
    DNS_NAMES_KEY,
    IPV4_ADDRESS_KEY,
    IPV6_ADDRESS_KEY,
    LABELS_KEY,
    NETWORK_SETTINGS_KEY,
    NETWORKS_KEY,
    NO_ADDRESS,
)
from .conftest import IDLE_COMMAND, IDLE_IMAGE, Deployment

# Nothing here runs daenes, so CI checks these without building its image.
pytestmark = pytest.mark.contract


def get_networks(client: DockerClient, name: str):
    """One network as `networks.list()` answers it, which is how daenes finds it."""
    listed = [found for found in client.networks.list() if found.name == name]
    assert listed, f"the daemon lists no network named {name}"
    return listed[0]


def get_settings(network, name: str, container: str | None = None) -> dict:
    """What one container on a network says about being on it."""
    network.reload()
    containers = network.containers
    if container is None:
        assert len(containers) == 1, f"expected one container, got {len(containers)}"
        return containers[0].attrs[NETWORK_SETTINGS_KEY][NETWORKS_KEY][name]
    found = [one for one in containers if one.name == container]
    assert found, f"the network holds no container named {container}"
    return found[0].attrs[NETWORK_SETTINGS_KEY][NETWORKS_KEY][name]


def test_a_network_without_any_label_answers_an_empty_map(client, unique):
    """Daenes reads its label out of this map, and a missing one is a no.

    Created bare rather than through the deployment fixture, which cannot help
    labelling what it creates so that it can clean up after itself.
    """
    network = client.networks.create(unique("bare"))
    try:
        labels = get_networks(client, network.name).attrs[LABELS_KEY]
    finally:
        network.remove()

    assert labels == {}


def test_the_labels_a_network_was_created_with_are_answered_back(
    client, deployment: Deployment, origin
):
    """Which is what makes a label a way of asking daenes for anything."""
    network = deployment.add_network(origin)

    labels = get_networks(client, network.name).attrs[LABELS_KEY]

    assert labels.get("daenes.domain") == origin


def test_a_listed_network_carries_none_of_its_containers(
    client, deployment: Deployment, origin, unique
):
    """Why daenes inspects every network it publishes rather than listing once."""
    network = deployment.add_network(origin)
    deployment.add_container(network, name=unique("web"))

    listed = get_networks(client, network.name)

    assert listed.attrs.get(CONTAINERS_KEY) in (None, {})
    assert not listed.containers


def test_an_inspected_network_carries_its_containers(
    client, deployment: Deployment, origin, unique
):
    """The reload daenes does, and the whole reason it does it."""
    network = deployment.add_network(origin)
    name = unique("web")
    deployment.add_container(network, name=name)

    listed = get_networks(client, network.name)
    listed.reload()

    assert [found.name for found in listed.containers] == [name]


def test_the_containers_of_a_network_are_inspected_in_full(
    client, deployment: Deployment, origin, unique
):
    """Daenes reads their network settings straight, without inspecting again."""
    network = deployment.add_network(origin)
    deployment.add_container(network, name=unique("web"))

    settings = get_settings(get_networks(client, network.name), network.name)

    assert settings, "a container was answered without its network settings"


def test_a_containers_networks_are_keyed_by_network_name(
    client, deployment: Deployment, origin, unique
):
    """Not by identifier, which is what lets daenes look its own network up."""
    network = deployment.add_network(origin)
    deployment.add_container(network, name=unique("web"))

    listed = get_networks(client, network.name)
    listed.reload()
    networks = listed.containers[0].attrs[NETWORK_SETTINGS_KEY][NETWORKS_KEY]

    assert network.name in networks


def test_a_container_on_an_ipv4_network_answers_at_an_ipv4_address(
    client, deployment: Deployment, origin, unique
):
    network = deployment.add_network(origin)
    deployment.add_container(network, name=unique("web"))

    settings = get_settings(get_networks(client, network.name), network.name)

    assert ip_address(settings[IPV4_ADDRESS_KEY]).version == 4


def test_a_container_on_an_ipv4_network_has_no_ipv6_address(
    client, deployment: Deployment, origin, unique
):
    """Empty rather than missing, which is what daenes tells apart from an address."""
    network = deployment.add_network(origin)
    deployment.add_container(network, name=unique("web"))

    settings = get_settings(get_networks(client, network.name), network.name)

    assert settings[IPV6_ADDRESS_KEY] == NO_ADDRESS


@pytest.mark.ipv6
def test_a_container_on_a_dual_stack_network_answers_over_both_families(
    client, deployment: Deployment, origin, unique
):
    """enable_ipv6 adds a stack rather than replacing the other one."""
    network = deployment.add_network(origin, ipv6=True)
    deployment.add_container(network, name=unique("web"))

    settings = get_settings(get_networks(client, network.name), network.name)

    assert ip_address(settings[IPV4_ADDRESS_KEY]).version == 4
    assert ip_address(settings[IPV6_ADDRESS_KEY]).version == 6


@pytest.mark.ipv6
def test_a_container_on_an_ipv6_only_network_has_no_ipv4_address(
    client, deployment: Deployment, origin, unique
):
    """A network created with --ipv4=false leaves the other key empty."""
    network = deployment.add_network(origin, ipv6=True, ipv4=False)
    deployment.add_container(network, name=unique("web"))

    settings = get_settings(get_networks(client, network.name), network.name)

    assert settings[IPV4_ADDRESS_KEY] == NO_ADDRESS
    assert ip_address(settings[IPV6_ADDRESS_KEY]).version == 6


def test_a_container_is_one_of_its_own_dns_names(
    client, deployment: Deployment, origin, unique
):
    """The name docker gives it is the one daenes publishes most of the time."""
    network = deployment.add_network(origin)
    name = unique("web")
    deployment.add_container(network, name=name)

    settings = get_settings(get_networks(client, network.name), network.name)

    assert name in settings[DNS_NAMES_KEY]


def test_the_aliases_a_container_was_connected_with_are_dns_names(
    client, deployment: Deployment, origin, unique
):
    """Compose puts the service name in here, which is how daenes publishes it."""
    network = deployment.add_network(origin)
    aliases = (unique("api"), unique("front"))
    deployment.add_container(network, name=unique("web"), aliases=aliases)

    settings = get_settings(get_networks(client, network.name), network.name)

    assert set(aliases) <= set(settings[DNS_NAMES_KEY])


def test_the_hostname_a_container_was_given_is_a_dns_name(
    client, deployment: Deployment, origin, unique
):
    """Reading DNSNames rather than composing a list is what catches this one.

    A container's hostname is nowhere near its name or its aliases, and docker
    answers for it all the same.
    """
    network = deployment.add_network(origin)
    hostname = unique("other-host")
    deployment.add_container(network, name=unique("web"), hostname=hostname)

    settings = get_settings(get_networks(client, network.name), network.name)

    assert hostname in settings[DNS_NAMES_KEY]


def test_a_containers_identifier_is_one_of_its_dns_names(
    client, deployment: Deployment, origin, unique
):
    """The one name in there daenes leaves out, so this is why it has to."""
    network = deployment.add_network(origin)
    container = deployment.add_container(network, name=unique("web"))

    settings = get_settings(get_networks(client, network.name), network.name)

    assert container.get_wrapped_container().short_id in settings[DNS_NAMES_KEY]


def test_docker_answers_at_every_name_it_calls_a_dns_name(
    client, deployment: Deployment, origin, unique
):
    """The fact the whole design rests on, asked of the resolver itself.

    Publishing DNSNames is only right if DNSNames is what docker resolves, and
    nothing short of its own resolver can say so.
    """
    network = deployment.add_network(origin)
    web = unique("web")
    deployment.add_container(
        network,
        name=web,
        aliases=(unique("api"),),
        hostname=unique("other-host"),
    )
    asker = deployment.add_container(network, name=unique("asker"))

    settings = get_settings(get_networks(client, network.name), network.name, web)

    for name in settings[DNS_NAMES_KEY]:
        result = asker.exec(["nslookup", name])
        assert result.exit_code == 0, (
            f"docker calls {name!r} a DNS name and does not resolve it:\n"
            f"{result.output.decode(errors='replace')}"
        )


def test_a_container_without_any_label_answers_an_empty_map(
    client, deployment: Deployment, origin, unique
):
    """Daenes reads the opt-out label off this map, and a missing one is a yes.

    Created bare, and for the same reason as the network above.
    """
    network = deployment.add_network(origin)
    container = client.containers.run(
        IDLE_IMAGE,
        IDLE_COMMAND,
        detach=True,
        network=network.name,
        name=unique("bare"),
    )
    try:
        listed = get_networks(client, network.name)
        listed.reload()
        labels = listed.containers[0].labels
    finally:
        container.remove(force=True)

    assert labels == {}


def test_a_container_is_named_without_a_leading_slash(
    client, deployment: Deployment, origin, unique
):
    """The API answers "/web" for a container named "web"; the model does not."""
    network = deployment.add_network(origin)
    name = unique("web")
    deployment.add_container(network, name=name)

    listed = get_networks(client, network.name)
    listed.reload()

    assert listed.containers[0].name == name


def test_a_container_that_stopped_has_left_the_network(
    client, deployment: Deployment, origin, unique
):
    """What makes a name stop resolving, without daenes being told anything."""
    network = deployment.add_network(origin)
    container = deployment.add_container(network, name=unique("web"))

    deployment.remove(container)

    listed = get_networks(client, network.name)
    listed.reload()
    assert not listed.containers


def test_a_daemon_that_is_not_there_cannot_be_pinged(tmp_path, monkeypatch):
    """The failure daenes reports at startup rather than retrying forever.

    Building a client raises nothing on its own, so nothing but the ping tells
    a mounted socket from a forgotten one.
    """
    monkeypatch.setenv("DOCKER_HOST", f"unix://{tmp_path / 'docker.sock'}")

    with pytest.raises(DockerException):
        DockerClient.from_env().ping()
