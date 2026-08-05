"""Every kind of zone daenes can write, loaded by a real DNS server's checker."""

import pytest

from daenes.main.dns_names import MAX_LABEL_LENGTH, MAX_NAME_LENGTH
from daenes.main.zone_synchronizer import SERIAL_MODULO

from .conftest import CHECKER, ORIGIN, assert_loads, check_zone, make_domain, write_zone


def test_the_zone_of_a_whole_deployment_loads(checker, tmp_path):
    """The example from the README, as daenes would write it."""
    domains = (
        make_domain(name="www", addresses=("172.20.0.2",), aliases=("httpd", "web")),
        make_domain(name="db", addresses=("172.20.0.3",)),
        make_domain(name="proxy", addresses=("172.20.0.4",), aliases=("gateway",)),
    )

    assert_loads(checker, write_zone(tmp_path, domains))


def test_a_zone_nothing_asks_to_be_published_in_loads(checker, tmp_path):
    """A network everything left still answers for itself."""
    assert_loads(checker, write_zone(tmp_path, ()))


def test_a_dual_stack_zone_loads(checker, tmp_path):
    domains = (make_domain(name="web", addresses=("172.20.0.2", "fd00::2")),)

    assert_loads(checker, write_zone(tmp_path, domains))


def test_a_zone_of_containers_reachable_several_ways_loads(checker, tmp_path):
    """Several addresses on one name is an answer, not a conflict."""
    domains = (
        make_domain(name="web", addresses=("172.20.0.2",)),
        make_domain(name="web", addresses=("172.21.0.2",)),
    )

    assert_loads(checker, write_zone(tmp_path, domains))


@pytest.mark.parametrize("ttl", [0, 60, 86400], ids=["no_caching", "default", "a_day"])
def test_a_zone_loads_whatever_its_ttl(checker, tmp_path, ttl):
    """Zero is legal, and tells a resolver not to cache the answer at all."""
    domains = (make_domain(name="web"),)

    assert_loads(checker, write_zone(tmp_path, domains, ttl=ttl))


@pytest.mark.parametrize(
    "serial",
    [1, SERIAL_MODULO - 1, 0],
    ids=["first", "last_before_wrapping", "wrapped"],
)
def test_a_zone_loads_whatever_its_serial(checker, tmp_path, serial):
    """RFC 1982: the serial wraps around, and zero is a serial like any other."""
    domains = (make_domain(name="web"),)

    assert_loads(checker, write_zone(tmp_path, domains, serial=serial))


@pytest.mark.parametrize(
    "name",
    ["web", "web-1", "1", "2fa", "api.v1", "a" * MAX_LABEL_LENGTH],
    ids=["word", "hyphenated", "digit", "leading_digit", "dotted", "longest_label"],
)
def test_every_name_daenes_accepts_loads(checker, tmp_path, name):
    """What the name rules let through has to be what a server takes."""
    domains = (make_domain(name=name, aliases=(f"alias-of-{name}",)),)

    assert_loads(checker, write_zone(tmp_path, domains))


def test_the_longest_name_daenes_accepts_loads(checker, tmp_path):
    """RFC 1035 section 2.3.4, right at the limit rather than near it."""
    origin = ".".join(["a" * 60] * 4)
    name = "b" * (MAX_NAME_LENGTH - len(origin) - len("."))

    path = write_zone(tmp_path, (make_domain(name=name),), origin=origin)

    assert_loads(checker, path, origin=origin)


def test_a_zone_of_many_containers_loads(checker, tmp_path):
    """Nothing in the format depends on how few records there are."""
    domains = tuple(
        make_domain(name=f"web-{number}", addresses=(f"172.20.0.{number}",))
        for number in range(2, 200)
    )

    assert_loads(checker, write_zone(tmp_path, domains))


def test_the_checker_refuses_a_zone_that_could_not_load(checker, tmp_path):
    """Proof that the checker is checking, and the suite above worth running.

    A CNAME beside an address is what RFC 2181 section 10.1 forbids, and what
    the synchronizer drops both sides of rather than write.
    """
    path = tmp_path / f"{ORIGIN}.zone"
    path.write_text(
        "$ORIGIN services.internal.\n"
        "$TTL 60\n"
        "@ IN SOA ns admin 1 3600 600 604800 600\n"
        "@ IN NS ns\n"
        "ns IN A 10.0.0.53\n"
        "web IN A 172.20.0.2\n"
        "web IN CNAME ns\n",
        encoding="utf-8",
    )

    code, output = check_zone(checker, path)

    assert code != 0, f"{CHECKER} accepted a zone no server would load"
    assert "CNAME and other data" in output
