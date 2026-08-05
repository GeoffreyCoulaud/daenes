"""Loading a zone file the way a real DNS server would.

Used by the zone validity suite, on zones written straight from the core, and
by the end-to-end suite, on the zones a running daenes leaves on disk.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

CHECKER = "named-checkzone"

# What BIND itself applies to a primary zone, which is stricter than what the
# tool applies when asked for nothing: check-names fails there rather than
# warns, and a name no host may bear stops the zone from loading.
CHECK_ARGUMENTS = (
    "-k", "fail",  # host names, RFC 1123
    "-n", "fail",  # NS targets
    "-m", "fail",  # MX targets
    "-M", "fail",  # MX targets that are aliases
    "-S", "fail",  # SRV targets that are aliases
    "-r", "fail",  # records repeated at one name
    "-i", "full",  # every integrity check, sibling glue included
)


def find_checker() -> str:
    """The zone checker, or a skip saying it is the one thing missing."""
    path = shutil.which(CHECKER)
    if path is None:
        pytest.skip(f"{CHECKER} is not installed, see CONTRIBUTING.md")
    return path


def check_zone(checker: str, path: Path, origin: str) -> tuple[int, str]:
    """Load a zone the way a DNS server would, and answer what it said."""
    result = subprocess.run(
        [checker, *CHECK_ARGUMENTS, origin, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, f"{result.stdout}{result.stderr}"


def assert_loads(checker: str, path: Path, origin: str) -> None:
    """Fail with what the checker said, rather than with a return code.

    A warning fails too: the flags above make an error of anything that would
    stop a server, so what is left to warn about is still worth knowing.
    """
    code, output = check_zone(checker, path, origin)
    assert code == 0, f"{CHECKER} refused the zone:\n{output}\n{path.read_text()}"
    assert "warning" not in output, f"{CHECKER} warned about the zone:\n{output}"
