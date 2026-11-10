"""Steady-state regression checks: 27 cases across 7 tests."""
import pytest

from helpers import ROUTERS, LOOPBACKS, FAR_SUBNET, sh, vtysh_json, routes, full_neighbours, can_ping

PAIRS = [(a, b) for a in ROUTERS for b in ROUTERS if a != b]


@pytest.mark.parametrize("router", ROUTERS)
def test_router_running(router):
    assert sh("docker", "inspect", "-f", "{{.State.Running}}", router).strip() == "true"


@pytest.mark.parametrize("router", ROUTERS)
def test_no_default_route(router):
    # No way out except OSPF routes, so a passing ping really proves OSPF works.
    assert "0.0.0.0/0" not in vtysh_json(router, "show ip route")


@pytest.mark.parametrize("router", ROUTERS)
def test_router_id(router):
    assert vtysh_json(router, "show ip ospf")["routerId"] == LOOPBACKS[router]


@pytest.mark.parametrize("router", ROUTERS)
def test_two_full_neighbours(router):
    assert full_neighbours(router) == 2


@pytest.mark.parametrize("src,dst", PAIRS)
def test_ospf_route_to_loopback(src, dst):
    entries = routes(src, f"{LOOPBACKS[dst]}/32")
    assert any(e["protocol"] == "ospf" and e.get("selected") for e in entries)


@pytest.mark.parametrize("router", ROUTERS)
def test_ospf_route_to_far_subnet(router):
    entries = routes(router, FAR_SUBNET[router])
    assert any(e["protocol"] == "ospf" and e.get("selected") for e in entries)


@pytest.mark.parametrize("src,dst", PAIRS)
def test_ping_loopback(src, dst):
    assert can_ping(src, LOOPBACKS[dst])
