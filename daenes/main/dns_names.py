"""The name rules a zone file has to obey, and nothing else.

Kept in their own module so each one can be read against the RFC it comes
from, and tested against it.
"""

import re

# RFC 1035 section 2.3.4. The 255 octet limit is on the wire form, where every
# label carries a length octet and the root label closes the name; 253 is what
# is left for the text form these rules are applied to.
MAX_LABEL_LENGTH = 63
MAX_NAME_LENGTH = 253

# RFC 1123 section 2.1, relaxing RFC 952: letters, digits and hyphens, never a
# hyphen at either end, and a leading digit is allowed. Names are lowercased
# before being matched, so the pattern does not spell the upper case out.
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def normalize(name: str) -> str:
    """Put a name in the form daenes writes and compares names in.

    DNS matches names without regard to case (RFC 4343), so lowercasing loses
    nothing and makes what we write canonical. A single trailing dot is
    dropped, since a fully qualified name and its relative spelling name the
    same thing here.
    """
    without_root = name[:-1] if name.endswith(".") else name
    return without_root.lower()


def is_valid_label(label: str) -> bool:
    """Whether one label may be served as part of a host name."""
    return len(label) <= MAX_LABEL_LENGTH and _LABEL.fullmatch(label) is not None


def is_valid_name(name: str) -> bool:
    """Whether a normalized name may be written into a zone file as it is."""
    if len(name) > MAX_NAME_LENGTH:
        return False
    return all(is_valid_label(label) for label in name.split("."))
