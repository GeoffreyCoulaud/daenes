"""What a deployment ends up answering, once daenes has looked at it.

A real daenes, over a real daemon, and the zone files read off the disk it
wrote them to.
"""

import pytest

from ..external_contracts import IPV4_ADDRESS_KEY, IPV6_ADDRESS_KEY
from ..zone_checker import assert_loads, find_checker
from .conftest import (
    APEX_NAME,
    ENABLED_LABEL,
    NAMESERVER_ADDRESS,
    NAMESERVER_NAME,
    get_address,
)


def test_a_container_answers_at_its_name(network, deployment, start_daenes, zone, unique):
    """The plainest case there is, and the one every deployment starts from."""
    web = unique("web")
    deployment.add_container(network, name=web)

    start_daenes()

    assert zone.wait_for_names({NAMESERVER_NAME, web})


def test_a_container_answers_at_the_address_docker_gave_it(
    network, deployment, start_daenes, zone, unique
):
    """A name is only worth publishing if it takes a client where it meant to go."""
    web = unique("web")
    container = deployment.add_container(network, name=web)

    start_daenes()

    records = zone.wait_for_names({NAMESERVER_NAME, web})
    assert records[web] == {get_address(container, network, IPV4_ADDRESS_KEY)}


def test_a_container_answers_at_its_aliases_too(
    network, deployment, start_daenes, zone, unique
):
    """Compose gives every service one, so most names in a zone are these."""
    web, api, front = unique("web"), unique("api"), unique("front")
    deployment.add_container(network, name=web, aliases=(api, front))

    start_daenes()

    records = zone.wait_for_names({NAMESERVER_NAME, web, api, front})
    assert records[api] == records[web] == records[front]


def test_a_container_answers_at_the_hostname_it_was_given(
    network, deployment, start_daenes, zone, unique
):
    """Docker resolves it, so a zone leaving it out would answer for less."""
    web, host = unique("web"), unique("other-host")
    deployment.add_container(network, name=web, hostname=host)

    start_daenes()

    records = zone.wait_for_names({NAMESERVER_NAME, web, host})
    assert records[host] == records[web]


def test_the_identifier_docker_knows_a_container_by_is_not_published(
    network, deployment, start_daenes, zone, unique
):
    """Nobody types it, and a redeploy would hand out a new one every time."""
    web = unique("web")
    container = deployment.add_container(network, name=web)

    start_daenes()

    records = zone.wait_for_names({NAMESERVER_NAME, web})
    assert container.get_wrapped_container().short_id not in records


def test_a_name_already_ending_in_the_zones_domain_is_not_repeated(
    network, deployment, start_daenes, zone, unique
):
    """The natural thing to write, and it would answer for name.origin.origin."""
    holder, web = unique("holder"), unique("web")
    deployment.add_container(network, name=holder, hostname=f"{web}.{zone.origin}")

    start_daenes()

    assert zone.wait_for_names({NAMESERVER_NAME, holder, web})


def test_a_container_named_after_the_zone_answers_for_the_domain(
    network, deployment, start_daenes, zone, unique
):
    """A deployment saying this container is what the domain is for."""
    web = unique("web")
    container = deployment.add_container(network, name=web, hostname=zone.origin)

    start_daenes()

    records = zone.wait_for_names({NAMESERVER_NAME, web, APEX_NAME})
    assert records[APEX_NAME] == {get_address(container, network, IPV4_ADDRESS_KEY)}


def test_the_zone_names_the_dns_server_that_serves_it(
    network, deployment, start_daenes, zone, unique
):
    """DNS_IP, which is the one thing daenes cannot read off the daemon."""
    deployment.add_container(network, name=unique("web"))

    start_daenes()

    zone.wait()
    assert zone.records()[NAMESERVER_NAME] == {NAMESERVER_ADDRESS}


def test_a_network_naming_no_domain_publishes_nothing(
    network, deployment, start_daenes, zone, unique
):
    """Every other network on the daemon is somebody else's business.

    The published network is the clock here: daenes reads them all in one pass,
    so a zone written for it is a pass the other one went through as well. Every
    zone in the directory is read, other tests' included, since a name nobody
    else can hold is being looked for rather than a zone.
    """
    private = deployment.add_network()
    hidden = unique("hidden")
    deployment.add_container(private, name=hidden)
    deployment.add_container(network, name=unique("web"))

    start_daenes()

    zone.wait()
    written = "\n".join(path.read_text() for path in zone.path.parent.glob("*.zone"))
    assert hidden not in written


def test_a_container_may_opt_out(network, deployment, start_daenes, zone, unique):
    """Containers on a published network are in unless they say otherwise."""
    web = unique("web")
    deployment.add_container(network, name=web)
    deployment.add_container(network, name=unique("private"), **{ENABLED_LABEL: "false"})

    start_daenes()

    assert zone.wait_for_names({NAMESERVER_NAME, web})


def test_a_container_on_two_published_networks_lands_in_both_zones(
    deployment, start_daenes, zone_for, origin, unique
):
    """With the address it has on each, which is not the same address."""
    other_origin = f"{unique('other')}.internal"
    first = deployment.add_network(origin)
    second = deployment.add_network(other_origin)
    web = unique("web")
    container = deployment.add_container(first, name=web)
    second.connect(container.get_wrapped_container().id)

    start_daenes()

    here = zone_for(origin).wait_for_names({NAMESERVER_NAME, web})
    there = zone_for(other_origin).wait_for_names({NAMESERVER_NAME, web})
    assert here[web] == {get_address(container, first, IPV4_ADDRESS_KEY)}
    assert there[web] == {get_address(container, second, IPV4_ADDRESS_KEY)}


@pytest.mark.usefixtures("network")
def test_an_emptied_network_keeps_a_zone_of_its_own(start_daenes, zone):
    """So that a server has something to answer with, rather than the last thing."""
    start_daenes()

    assert zone.wait_for_names({NAMESERVER_NAME})


@pytest.mark.ipv6
def test_a_container_on_a_dual_stack_network_answers_over_both_families(
    deployment, start_daenes, zone, origin, unique
):
    """One host over two protocols, which is one name with two records."""
    network = deployment.add_network(origin, ipv6=True)
    web = unique("web")
    container = deployment.add_container(network, name=web)

    start_daenes()

    records = zone.wait_for_names({NAMESERVER_NAME, web})
    assert records[web] == {
        get_address(container, network, IPV4_ADDRESS_KEY),
        get_address(container, network, IPV6_ADDRESS_KEY),
    }


def test_the_zone_a_deployment_produces_loads_in_a_dns_server(
    network, deployment, start_daenes, zone, unique
):
    """The whole point, and the one thing only a DNS server can be asked.

    The zone validity suite loads what the core writes; this loads what a
    running daenes left on the disk of a machine it read for itself.
    """
    checker = find_checker()
    web, api = unique("web"), unique("api")
    deployment.add_container(network, name=web, aliases=(api,))
    deployment.add_container(network, name=unique("db"))

    start_daenes()

    zone.wait_for_names({NAMESERVER_NAME, web, api, unique("db")})
    assert_loads(checker, zone.path, zone.origin)
