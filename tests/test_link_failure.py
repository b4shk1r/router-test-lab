"""Cut the r1-r2 link, check traffic reroutes via r3, and time the recovery."""
import csv
import os
import time

import pytest

from helpers import sh, routes, can_ping, full_neighbours, wait_until

LIMIT_SECONDS = 15  # start loose; tighten to about 2x your measured median later
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "reports", "convergence.csv")


R1_R2_LINK = [("r1", "10.0.12.11"), ("r2", "10.0.12.12")]


def iface_with_ip(router, ip):
    """Find the interface name (eth0, eth1, ...) that holds this IP.

    Docker's interface names are not stable, so look it up by address,
    the same reason the OSPF config uses `network` lines instead of names.
    """
    for line in sh("docker", "exec", router, "ip", "-o", "-4", "addr", "show").splitlines():
        fields = line.split()            # "47: eth0    inet 10.0.12.11/24 brd ..."
        if fields[3].split("/")[0] == ip:
            return fields[1].split("@")[0]
    raise LookupError(f"{router} has no interface with {ip}")


def set_link(up):
    """Shut down / bring up both ends of the r1-r2 link (like `shutdown` on each port).

    We do not use `docker network disconnect/connect`: while the link is cut,
    OSPF (correctly) installs a route to 10.0.12.0/24 via r3, and Docker then
    refuses to reconnect because that subnet "conflicts with an existing route".
    """
    for router, ip in R1_R2_LINK:
        iface = iface_with_ip(router, ip)
        sh("docker", "exec", router, "ip", "link", "set", iface, "up" if up else "down")


def next_hops(router, prefix):
    return {h.get("ip") for e in routes(router, prefix) if e.get("selected")
            for h in e.get("nexthops", [])}


def back_to_normal():
    return full_neighbours("r1") == 2 and full_neighbours("r2") == 2


@pytest.fixture
def cut_r1_r2():
    start = time.monotonic()
    set_link(up=False)                      # cut the cable
    try:
        wait_until(lambda: can_ping("r1", "2.2.2.2"), timeout=60)
        yield time.monotonic() - start      # seconds until traffic flowed again
    finally:
        set_link(up=True)                   # always put the cable back, even on failure
        wait_until(back_to_normal, timeout=120)


def test_reroutes_via_r3(cut_r1_r2):
    assert next_hops("r1", "2.2.2.2/32") == {"10.0.13.13"}


def test_convergence_time(cut_r1_r2):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    with open(CSV_PATH, "a", newline="") as f:
        csv.writer(f).writerow([time.strftime("%Y-%m-%d %H:%M:%S"), f"{cut_r1_r2:.2f}"])
    assert cut_r1_r2 < LIMIT_SECONDS


def test_direct_path_back_after_restore():
    # Neighbours being Full again does not mean SPF has already re-run,
    # so poll for the direct route instead of checking once.
    wait_until(lambda: next_hops("r1", "2.2.2.2/32") == {"10.0.12.12"}, timeout=30)
