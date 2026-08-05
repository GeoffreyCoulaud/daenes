"""Unit tests for daenes.main.main, the entry point and the wiring."""

import logging
from dataclasses import replace
from ipaddress import ip_address
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from docker.client import DockerClient

from daenes.main import main as main_module
from daenes.main.application import Application
from daenes.main.config import Config
from daenes.main.docker import DOMAIN_LABEL, DockerStartupError
from daenes.main.errors import ReturnCodes
from daenes.main.main import (
    build_application,
    configure_logging,
    handle_sigterm,
    main,
)

from .conftest import (
    EndOfTest,
    FakeContainer,
    FakeDockerClient,
    FakeNetwork,
    make_network_settings,
)

CONFIG = Config(
    zones_directory=Path("/zones"),
    nameserver_address=ip_address("10.0.0.53"),
    ttl=60,
    success_interval=60,
    retry_interval=10,
)


@pytest.fixture(autouse=True)
def restore_logging():
    """Put the root logger back, since configuring it is global."""
    root = logging.getLogger()
    level = root.level
    yield
    root.setLevel(level)


@pytest.mark.parametrize(
    "requested, expected",
    [("DEBUG", logging.DEBUG), ("WARNING", logging.WARNING)],
)
def test_the_log_level_is_read_from_the_environment(monkeypatch, requested, expected):
    monkeypatch.setenv("LOG_LEVEL", requested)

    configure_logging()

    assert logging.getLogger().level == expected


@pytest.mark.parametrize(
    "requested",
    [None, "VERBOSE"],
    ids=["unset", "not_a_level"],
)
def test_an_unusable_log_level_falls_back_to_info(monkeypatch, requested):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    if requested is not None:
        monkeypatch.setenv("LOG_LEVEL", requested)

    configure_logging()

    assert logging.getLogger().level == logging.INFO


def test_the_application_is_wired_from_the_configuration(tmp_path):
    """Whether the parts fit together is only shown by running them.

    Every one of them is stubbed out everywhere else, so this is the one place
    the docker adapter, the synchronizer and the zone files meet.
    """
    client = cast(
        DockerClient,
        FakeDockerClient(
            (
                FakeNetwork(
                    labels={DOMAIN_LABEL: "services.internal"},
                    containers=(
                        FakeContainer(
                            name="web",
                            networks={"compose_services": make_network_settings()},
                        ),
                    ),
                ),
            )
        ),
    )

    application = build_application(replace(CONFIG, zones_directory=tmp_path), client)
    assert isinstance(application, Application)
    application._synchronizer.synchronize()  # pylint: disable=protected-access

    written = (tmp_path / "services.internal.zone").read_text(encoding="utf-8")
    # What the zone looks like is settled elsewhere; what matters here is that
    # each part contributed what it was given.
    assert "$ORIGIN services.internal." in written  # the network's label
    assert f"$TTL {CONFIG.ttl}" in written  # the configuration
    assert "ns IN A 10.0.0.53" in written  # the configuration again
    assert "web IN A 172.20.0.2" in written  # what docker answered


def test_sigterm_shuts_down_without_an_error():
    """Docker stops a container with it, and waits out its timeout otherwise."""
    with pytest.raises(SystemExit) as raised:
        handle_sigterm()

    assert raised.value.code == 0


def make_main_run(monkeypatch, outcome: Exception | None) -> MagicMock:
    """Run main() over an application that ends the way the test decided."""
    application = MagicMock()
    application.run.side_effect = None if outcome is None else outcome
    monkeypatch.setattr(main_module, "get_configuration", lambda: CONFIG)
    monkeypatch.setattr(main_module, "connect", MagicMock())
    monkeypatch.setattr(main_module, "build_application", lambda *_: application)
    return application


def test_main_runs_the_application(monkeypatch):
    application = make_main_run(monkeypatch, outcome=None)

    main()

    application.run.assert_called_once_with()


def test_main_stops_on_a_configuration_error(monkeypatch):
    """Nothing about a wrong environment is worth retrying."""
    error = main_module.ConfigurationError(
        ReturnCodes.MISSING_ENVIRONMENT_VARIABLE, "DNS_IP is required"
    )
    monkeypatch.setattr(
        main_module, "get_configuration", MagicMock(side_effect=error)
    )

    with pytest.raises(SystemExit) as raised:
        main()

    assert raised.value.code == ReturnCodes.MISSING_ENVIRONMENT_VARIABLE


def test_main_stops_on_an_error_no_retry_could_fix(monkeypatch):
    make_main_run(monkeypatch, outcome=EndOfTest("the zones directory is read only"))

    with pytest.raises(SystemExit) as raised:
        main()

    assert raised.value.code == ReturnCodes.UNRETRYABLE_EXCEPTION_IN_LIFECYCLE


def test_main_stops_when_the_daemon_never_answered(monkeypatch):
    """The socket not being mounted is the mistake this catches, and says so."""
    monkeypatch.setattr(main_module, "get_configuration", lambda: CONFIG)
    monkeypatch.setattr(
        main_module, "connect", MagicMock(side_effect=DockerStartupError())
    )

    with pytest.raises(SystemExit) as raised:
        main()

    assert raised.value.code == ReturnCodes.DOCKER_UNREACHABLE_AT_STARTUP
