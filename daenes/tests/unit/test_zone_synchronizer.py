"""Unit tests for daenes.main.zone_synchronizer."""

from ipaddress import ip_address

import pytest

from daenes.main.dns_names import MAX_NAME_LENGTH
from daenes.main.zone_synchronizer import (
    FIRST_SERIAL,
    NAMESERVER_NAME,
    SERIAL_MODULO,
    ZoneSynchronizer,
)

from .conftest import (
    NAMESERVER_ADDRESS,
    ORIGIN,
    TTL,
    FakeNetworkSource,
    FakeZoneStore,
    addresses_of,
    alias_targets,
    make_domain,
    make_published_network,
    names_of,
)


def make_synchronizer(networks, store=None):
    """A synchronizer over a deployment and a store the test can look into."""
    source = FakeNetworkSource(tuple(networks))
    store = FakeZoneStore() if store is None else store
    synchronizer = ZoneSynchronizer(
        source=source,
        store=store,
        nameserver_address=NAMESERVER_ADDRESS,
        ttl=TTL,
    )
    return synchronizer, source, store


def synchronize(*networks, store=None):
    """Run one synchronization, and answer the zones it wrote."""
    synchronizer, _, store = make_synchronizer(networks, store)
    synchronizer.synchronize()
    return store.saved


def synchronize_one(*networks, store=None):
    """Run one synchronization that is expected to write exactly one zone."""
    saved = synchronize(*networks, store=store)
    assert len(saved) == 1
    return saved[0]


def test_a_zone_carries_its_origin_its_ttl_and_its_nameserver():
    zone = synchronize_one(make_published_network(make_domain(name="web")))

    assert zone.origin == ORIGIN
    assert zone.ttl == TTL
    assert addresses_of(zone, NAMESERVER_NAME) == (NAMESERVER_ADDRESS,)
    assert addresses_of(zone, "web") == (ip_address("172.20.0.2"),)


def test_a_network_everything_left_still_gets_a_zone():
    """Otherwise the names that used to be on it would go on resolving."""
    zone = synchronize_one(make_published_network())

    assert set(names_of(zone)) == {NAMESERVER_NAME}


def test_each_origin_becomes_its_own_zone():
    saved = synchronize(
        make_published_network(make_domain(name="web"), origin="services.internal"),
        make_published_network(make_domain(name="db"), origin="admin.internal"),
    )

    assert [zone.origin for zone in saved] == ["admin.internal", "services.internal"]


def test_two_networks_naming_one_origin_land_in_one_zone():
    """Naming the same domain twice is a deliberate way to merge two networks."""
    zone = synchronize_one(
        make_published_network(make_domain(name="web", addresses=("172.20.0.2",))),
        make_published_network(make_domain(name="db", addresses=("172.21.0.2",))),
    )

    assert addresses_of(zone, "web") == (ip_address("172.20.0.2"),)
    assert addresses_of(zone, "db") == (ip_address("172.21.0.2"),)


def test_an_origin_is_matched_without_regard_to_case():
    """RFC 4343: two spellings of one domain are one domain."""
    zone = synchronize_one(
        make_published_network(make_domain(name="web"), origin="Services.Internal"),
        make_published_network(make_domain(name="db"), origin="services.internal"),
    )

    assert zone.origin == "services.internal"
    assert set(names_of(zone)) == {NAMESERVER_NAME, "web", "db"}


def test_a_container_reachable_at_several_addresses_answers_with_all_of_them():
    """The client picks; which one it can reach is not ours to guess."""
    zone = synchronize_one(
        make_published_network(make_domain(name="web", addresses=("172.20.0.2",))),
        make_published_network(make_domain(name="web", addresses=("172.21.0.9",))),
    )

    assert addresses_of(zone, "web") == (
        ip_address("172.20.0.2"),
        ip_address("172.21.0.9"),
    )


def test_addresses_are_ordered_by_family_then_value():
    """The two families do not compare, and the output has to be stable."""
    domain = make_domain(name="web", addresses=("fd00::2", "172.20.0.9", "172.20.0.2"))

    zone = synchronize_one(make_published_network(domain))

    assert addresses_of(zone, "web") == (
        ip_address("172.20.0.2"),
        ip_address("172.20.0.9"),
        ip_address("fd00::2"),
    )


def test_an_alias_points_at_the_container_it_belongs_to():
    domain = make_domain(name="web", aliases=("www", "front"))

    zone = synchronize_one(make_published_network(domain))

    assert alias_targets(zone) == {"www": "web", "front": "web"}


def test_a_container_is_not_an_alias_of_itself():
    """Docker lists a container's own name among its aliases."""
    domain = make_domain(name="web", aliases=("web", "www"))

    zone = synchronize_one(make_published_network(domain))

    assert alias_targets(zone) == {"www": "web"}


def test_the_same_alias_reported_twice_is_one_record():
    """A container on two merged networks reports its aliases on each."""
    zone = synchronize_one(
        make_published_network(
            make_domain(name="web", addresses=("172.20.0.2",), aliases=("www",))
        ),
        make_published_network(
            make_domain(name="web", addresses=("172.21.0.2",), aliases=("www",))
        ),
    )

    assert alias_targets(zone) == {"www": "web"}


def test_a_name_that_is_both_an_address_and_an_alias_is_dropped_entirely():
    """RFC 2181 section 10.1 forbids it, and neither reading is more right."""
    zone = synchronize_one(
        make_published_network(
            make_domain(name="www", addresses=("172.20.0.3",)),
            make_domain(name="web", addresses=("172.20.0.2",), aliases=("www",)),
        )
    )

    assert alias_targets(zone) == {}
    assert addresses_of(zone, "www") is None
    assert addresses_of(zone, "web") == (ip_address("172.20.0.2"),)


def test_an_alias_pointing_at_two_containers_is_dropped_entirely():
    zone = synchronize_one(
        make_published_network(
            make_domain(name="web", aliases=("www",)),
            make_domain(name="proxy", aliases=("www",)),
        )
    )

    assert alias_targets(zone) == {}
    assert set(names_of(zone)) == {NAMESERVER_NAME, "web", "proxy"}


@pytest.mark.parametrize(
    "domain",
    [make_domain(name=NAMESERVER_NAME), make_domain(aliases=(NAMESERVER_NAME,))],
    ids=["as_a_container", "as_an_alias"],
)
def test_the_nameserver_name_belongs_to_the_zone_alone(domain):
    """Handing it to a container would leave the zone's NS record lying."""
    zone = synchronize_one(make_published_network(domain))

    assert addresses_of(zone, NAMESERVER_NAME) == (NAMESERVER_ADDRESS,)
    assert alias_targets(zone) == {}


@pytest.mark.parametrize(
    "name",
    ["my_service", "-web", ""],
    ids=["underscore", "leading_hyphen", "empty"],
)
def test_a_container_that_cannot_be_named_in_dns_is_ignored(name):
    zone = synchronize_one(
        make_published_network(make_domain(name=name), make_domain(name="web"))
    )

    assert set(names_of(zone)) == {NAMESERVER_NAME, "web"}


def test_an_alias_that_cannot_be_named_in_dns_is_ignored():
    domain = make_domain(name="web", aliases=("my_alias", "www"))

    zone = synchronize_one(make_published_network(domain))

    assert alias_targets(zone) == {"www": "web"}


def test_a_name_too_long_for_its_zone_is_ignored():
    """The limit is on the whole name, so a long zone leaves less room."""
    origin = ".".join(["a" * 60] * 4)
    room_left = MAX_NAME_LENGTH - len(origin) - len(".")

    zone = synchronize_one(
        make_published_network(
            make_domain(name="b" * room_left),
            make_domain(name="c" * (room_left + 1)),
            origin=origin,
        )
    )

    assert set(names_of(zone)) == {NAMESERVER_NAME, "b" * room_left}


@pytest.mark.parametrize(
    "origin",
    ["compose_services.internal", "services"],
    ids=["not_a_domain", "single_label"],
)
def test_a_zone_nobody_could_serve_is_not_written(origin):
    """A compose network is named after its project, underscore included."""
    saved = synchronize(
        make_published_network(make_domain(), origin=origin),
        make_published_network(make_domain(), origin="services.internal"),
    )

    assert [zone.origin for zone in saved] == ["services.internal"]


def test_the_first_serial_of_a_zone_is_one():
    zone = synchronize_one(make_published_network(make_domain()))

    assert zone.serial == FIRST_SERIAL


def test_a_serial_carries_on_from_the_zone_already_on_disk():
    """Going back in time would leave every secondary server on the old zone."""
    store = FakeZoneStore({ORIGIN: 41})

    zone = synchronize_one(make_published_network(make_domain()), store=store)

    assert zone.serial == 42


def test_a_serial_wraps_around():
    """RFC 1982: the serial is unsigned 32 bit arithmetic."""
    store = FakeZoneStore({ORIGIN: SERIAL_MODULO - 1})

    zone = synchronize_one(make_published_network(make_domain()), store=store)

    assert zone.serial == 0


def test_an_unchanged_zone_is_left_alone():
    """Rewriting it would bump the serial, which every secondary takes for news."""
    synchronizer, _, store = make_synchronizer(
        [make_published_network(make_domain())]
    )

    synchronizer.synchronize()
    synchronizer.synchronize()

    assert len(store.saved) == 1


def test_a_changed_zone_is_written_again_with_a_new_serial():
    synchronizer, source, store = make_synchronizer(
        [make_published_network(make_domain(name="web"))]
    )

    synchronizer.synchronize()
    source.networks.append(make_published_network(make_domain(name="db")))
    synchronizer.synchronize()

    assert [zone.serial for zone in store.saved] == [1, 2]
    assert set(names_of(store.saved[-1])) == {NAMESERVER_NAME, "web", "db"}
