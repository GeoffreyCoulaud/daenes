"""Unit tests for daenes.main.dns_names, against the RFCs the rules come from."""

import pytest

from daenes.main.dns_names import (
    APEX,
    MAX_LABEL_LENGTH,
    MAX_NAME_LENGTH,
    is_valid_label,
    is_valid_name,
    make_relative,
    normalize,
)

ORIGIN = "services.internal"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Services.Internal", "services.internal"),
        ("services.internal", "services.internal"),
        # A name may be spelled fully qualified, and means the same thing.
        ("services.internal.", "services.internal"),
        # Only the root label goes: a name ending in an empty label is a
        # mistake, and hiding it here would let it through.
        ("services.internal..", "services.internal."),
    ],
)
def test_normalize(name, expected):
    assert normalize(name) == expected


@pytest.mark.parametrize(
    "label",
    ["web", "web-1", "web1", "1", "1web", "a" * MAX_LABEL_LENGTH],
    ids=["word", "hyphenated", "trailing_digit", "digit", "leading_digit", "longest"],
)
def test_valid_labels(label):
    """RFC 1123 section 2.1: letters, digits and hyphens, a digit may lead."""
    assert is_valid_label(label)


@pytest.mark.parametrize(
    "label",
    ["", "-web", "web-", "my_service", "wéb", "we b", "a" * (MAX_LABEL_LENGTH + 1)],
    ids=[
        "empty",
        "leading_hyphen",
        "trailing_hyphen",
        # The one that matters in practice: docker names a compose network
        # after its project, with an underscore in between.
        "underscore",
        "not_ascii",
        "space",
        "too_long",
    ],
)
def test_invalid_labels(label):
    assert not is_valid_label(label)


@pytest.mark.parametrize(
    "name",
    ["services.internal", "api.v1.services.internal", "internal"],
    ids=["two_labels", "four_labels", "one_label"],
)
def test_valid_names(name):
    assert is_valid_name(name)


@pytest.mark.parametrize(
    "name",
    ["", "services..internal", ".internal", "services.internal.", "a" * 84 + ".a" * 85],
    ids=["empty", "empty_label", "leading_dot", "trailing_dot", "too_long"],
)
def test_invalid_names(name):
    """RFC 1035 section 2.3.4 for the length, RFC 1123 for everything else."""
    assert not is_valid_name(name)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("web", "web"),
        (f"web.{ORIGIN}", "web"),
        (f"api.v1.{ORIGIN}", "api.v1"),
        (ORIGIN, APEX),
        # Another domain's name, which daenes can only serve under its own.
        ("mail.example.com", "mail.example.com"),
        # Ends in the origin's text without ending in the origin.
        (f"web-{ORIGIN}", f"web-{ORIGIN}"),
    ],
    ids=["plain", "qualified", "subdomain", "the_origin", "elsewhere", "not_a_label"],
)
def test_make_relative(name, expected):
    """A zone writes its names relative to its origin, so one already there
    would otherwise be written twice."""
    assert make_relative(name, ORIGIN) == expected


def test_the_longest_name_is_valid():
    """The limit itself is allowed, only what is past it is refused."""
    name = ".".join(["a" * 63] * 3) + "." + "a" * 61

    assert len(name) == MAX_NAME_LENGTH
    assert is_valid_name(name)
