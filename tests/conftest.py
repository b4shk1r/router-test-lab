import pytest

from helpers import ROUTERS, full_neighbours, wait_until


@pytest.fixture(scope="session", autouse=True)
def lab_converged():
    """Wait for OSPF to settle before any test runs.

    Polling (instead of a fixed sleep) keeps the suite fast when the lab is
    already up, and not flaky when it is slow to converge.
    """
    try:
        wait_until(lambda: all(full_neighbours(r) == 2 for r in ROUTERS), timeout=120)
    except TimeoutError:
        pass  # don't block: let the tests themselves report what is broken
