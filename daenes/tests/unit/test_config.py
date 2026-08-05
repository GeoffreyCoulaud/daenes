"""Unit tests for daenes.main.config."""

from ipaddress import ip_address
from pathlib import Path

import pytest

from daenes.main.config import (
    DEFAULT_ALLOW_MULTIPLE_ADDRESSES_PER_NAME,
    DEFAULT_ALLOW_MULTIPLE_NETWORKS_PER_ZONE,
    DEFAULT_RETRY_INTERVAL,
    DEFAULT_SUCCESS_INTERVAL,
    DEFAULT_TTL,
    DEFAULT_ZONES_DIRECTORY,
    ConfigurationError,
    get_configuration,
)
from daenes.main.errors import ReturnCodes

# The one variable a deployment cannot be run without.
VALID_ENVIRONMENT = {"DNS_IP": "10.0.0.53"}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Start from an environment holding nothing daenes reads."""
    for name in (
        "DNS_IP",
        "DNS_TTL",
        "ZONES_DIR",
        "SUCCESS_INTERVAL",
        "RETRY_INTERVAL",
        "ALLOW_MULTIPLE_ADDRESSES_PER_NAME",
        "ALLOW_MULTIPLE_NETWORKS_PER_ZONE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def valid_environment(monkeypatch):
    for name, value in VALID_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


@pytest.mark.usefixtures("valid_environment")
def test_an_environment_naming_only_the_dns_server_is_enough():
    config = get_configuration()

    assert config.nameserver_address == ip_address("10.0.0.53")
    assert config.zones_directory == Path(DEFAULT_ZONES_DIRECTORY)
    assert config.ttl == DEFAULT_TTL
    assert config.success_interval == DEFAULT_SUCCESS_INTERVAL
    assert config.retry_interval == DEFAULT_RETRY_INTERVAL
    assert config.allowances.multiple_addresses_per_name == (
        DEFAULT_ALLOW_MULTIPLE_ADDRESSES_PER_NAME
    )
    assert config.allowances.multiple_networks_per_zone == (
        DEFAULT_ALLOW_MULTIPLE_NETWORKS_PER_ZONE
    )


@pytest.mark.usefixtures("valid_environment")
def test_every_setting_can_be_chosen(monkeypatch):
    monkeypatch.setenv("ZONES_DIR", "/var/lib/daenes")
    monkeypatch.setenv("DNS_TTL", "300")
    monkeypatch.setenv("SUCCESS_INTERVAL", "120")
    monkeypatch.setenv("RETRY_INTERVAL", "5")
    monkeypatch.setenv("ALLOW_MULTIPLE_ADDRESSES_PER_NAME", "true")
    monkeypatch.setenv("ALLOW_MULTIPLE_NETWORKS_PER_ZONE", "true")

    config = get_configuration()

    assert config.zones_directory == Path("/var/lib/daenes")
    assert config.ttl == 300
    assert config.success_interval == 120
    assert config.retry_interval == 5
    assert config.allowances.multiple_addresses_per_name is True
    assert config.allowances.multiple_networks_per_zone is True


def test_a_deployment_that_names_no_dns_server_stops():
    """The address goes into every zone, and nothing sensible stands in for it."""
    with pytest.raises(ConfigurationError) as raised:
        get_configuration()

    assert raised.value.return_code == ReturnCodes.MISSING_ENVIRONMENT_VARIABLE


def test_a_dns_server_that_is_not_an_address_stops(monkeypatch):
    monkeypatch.setenv("DNS_IP", "ns.example.com")

    with pytest.raises(ConfigurationError) as raised:
        get_configuration()

    assert raised.value.return_code == ReturnCodes.INVALID_ENVIRONMENT_VARIABLE


@pytest.mark.usefixtures("valid_environment")
def test_a_dns_server_may_answer_over_ipv6(monkeypatch):
    monkeypatch.setenv("DNS_IP", "fd00::53")

    assert get_configuration().nameserver_address == ip_address("fd00::53")


@pytest.mark.usefixtures("valid_environment")
@pytest.mark.parametrize(
    "name, value",
    [
        ("DNS_TTL", "a while"),
        ("DNS_TTL", "-1"),
        ("SUCCESS_INTERVAL", "1.5"),
        ("SUCCESS_INTERVAL", "0"),
        ("RETRY_INTERVAL", "0"),
    ],
    ids=["not_a_number", "negative_ttl", "not_whole", "no_wait", "no_retry_wait"],
)
def test_a_duration_that_makes_no_sense_stops(monkeypatch, name, value):
    """Retrying cannot fix it, and guessing what was meant would be worse."""
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError) as raised:
        get_configuration()

    assert raised.value.return_code == ReturnCodes.INVALID_ENVIRONMENT_VARIABLE


@pytest.mark.usefixtures("valid_environment")
def test_a_ttl_of_zero_tells_resolvers_not_to_cache(monkeypatch):
    """Zero is a legal TTL, unlike the intervals daenes itself waits out."""
    monkeypatch.setenv("DNS_TTL", "0")

    assert get_configuration().ttl == 0


@pytest.mark.usefixtures("valid_environment")
def test_sharing_is_refused_unless_asked_for():
    """Both advanced uses have to be turned on, not fallen into."""
    allowances = get_configuration().allowances

    assert allowances.multiple_addresses_per_name is False
    assert allowances.multiple_networks_per_zone is False


@pytest.mark.usefixtures("valid_environment")
@pytest.mark.parametrize(
    "value, expected",
    [("true", True), ("false", False), ("TRUE", True), (" true ", True)],
    ids=["on", "off", "shouted", "padded"],
)
def test_a_setting_is_on_or_off(monkeypatch, value, expected):
    monkeypatch.setenv("ALLOW_MULTIPLE_ADDRESSES_PER_NAME", value)

    assert get_configuration().allowances.multiple_addresses_per_name is expected


@pytest.mark.usefixtures("valid_environment")
@pytest.mark.parametrize("value", ["yes", "1", ""], ids=["yes", "one", "empty"])
def test_a_setting_that_is_neither_stops(monkeypatch, value):
    """A value that reads like a yes must not quietly mean no."""
    monkeypatch.setenv("ALLOW_MULTIPLE_ADDRESSES_PER_NAME", value)

    with pytest.raises(ConfigurationError) as raised:
        get_configuration()

    assert raised.value.return_code == ReturnCodes.INVALID_ENVIRONMENT_VARIABLE
