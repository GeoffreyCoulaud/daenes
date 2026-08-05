"""The name rules a zone file has to obey, each next to the RFC it comes from."""

import re

# RFC 1035 section 2.3.4. Its 255 octet limit counts a length octet per label
# and the root label, leaving 253 for the text form these rules apply to.
MAX_LABEL_LENGTH = 63
MAX_NAME_LENGTH = 253

# RFC 1123 section 2.1: letters, digits and hyphens, no hyphen at either end,
# a leading digit allowed. Names are lowercased before being matched.
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def normalize(name: str) -> str:
    """Lowercase a name and drop its root dot, if it has one.

    DNS ignores case (RFC 4343), so this only makes what we write canonical.
    """
    without_root = name[:-1] if name.endswith(".") else name
    return without_root.lower()


def is_valid_label(label: str) -> bool:
    """Whether one label may be served as part of a host name."""
    return len(label) <= MAX_LABEL_LENGTH and _LABEL.fullmatch(label) is not None


def is_valid_name(name: str) -> bool:
    """Whether a normalized name may be written into a zone as it is."""
    if len(name) > MAX_NAME_LENGTH:
        return False
    return all(is_valid_label(label) for label in name.split("."))
