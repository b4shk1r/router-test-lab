# Router Regression Test Lab

![router-regression](https://github.com/b4shk1r/router-test-lab/actions/workflows/tests.yml/badge.svg)

A 3-router OSPF network (FRRouting in Docker) with an automated Python/pytest regression suite that checks OSPF neighbours, routing tables, end-to-end reachability and link-failure recovery, plus a Tcl/Expect script that saves router state. It runs on every push in GitHub Actions.

## Network

Three routers in a triangle, all in OSPF area 0, one subnet per link. Every router has two paths to every other router, so cutting one link should send traffic the long way round.

```
            net12 · 10.0.12.0/24
   r1 .11 ──────────────────────── .12 r2
 1.1.1.1/32                         2.2.2.2/32
      .11 \                         / .12
 net13 ·   \                       /   net23 ·
 10.0.13.0/24\                   / 10.0.23.0/24
          .13 \                 / .13
                      r3
                  3.3.3.3/32
```

| Router | Loopback (router ID) | net12 `10.0.12.0/24` | net13 `10.0.13.0/24` | net23 `10.0.23.0/24` |
|---|---|---|---|---|
| r1 | `1.1.1.1/32` | `10.0.12.11` | `10.0.13.11` | |
| r2 | `2.2.2.2/32` | `10.0.12.12` | | `10.0.23.12` |
| r3 | `3.3.3.3/32` | | `10.0.13.13` | `10.0.23.13` |

The networks are `internal`, so there is no default route and no path to the internet. Every successful ping has to use routes OSPF built.

## How to run it

```bash
docker compose up -d                 # start r1, r2, r3 (FRR 10.7.0)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -v                  # 30 test cases, waits for OSPF to converge first
expect scripts/show_ospf.exp r1      # saves r1's neighbours + OSPF routes to reports/r1-ospf.txt
docker compose down
```

## Tests (30 cases)

| Test | What it checks | Cases |
|---|---|---|
| `test_router_running` | each router container is up | 3 |
| `test_no_default_route` | no `0.0.0.0/0`, so the only way to other routers is OSPF | 3 |
| `test_router_id` | OSPF router ID matches the loopback | 3 |
| `test_two_full_neighbours` | each router has 2 neighbours in `Full` | 3 |
| `test_ospf_route_to_loopback` | selected OSPF route to the other two loopbacks | 6 |
| `test_ospf_route_to_far_subnet` | each router learns the one link subnet it is not on | 3 |
| `test_ping_loopback` | ping works between every pair of routers | 6 |
| `test_reroutes_via_r3` | with r1–r2 cut, r1 reaches `2.2.2.2` via `10.0.13.13` (r3) | 1 |
| `test_convergence_time` | traffic flows again within the limit; logs the time to `reports/convergence.csv` | 1 |
| `test_direct_path_back_after_restore` | after the link is restored, r1 goes direct again via `10.0.12.12` | 1 |

Design choices:
- **Polling, not sleeping.** A session fixture polls until every router has 2 `Full` neighbours (max 120 s), so the suite is fast when the lab is ready and not flaky when it is slow.
- **`try/finally` around the link cut.** The link is always restored, even if a test fails halfway, so one failure does not cascade into the next tests.
- **Proved the tests can fail.** Putting r3's net23 into `area 1` makes exactly `test_two_full_neighbours[r2]` and `[r3]` fail (area mismatch, so no adjacency). Every route and ping test still passes, because OSPF correctly routes r2↔r3 traffic through r1. Only the neighbour check catches this misconfiguration.

## Re-convergence time

The test shuts down both ends of the r1–r2 link and times how long it takes until `r1` can ping `2.2.2.2` again (via r3).

**Median: 0.36 s over 7 runs (range 0.34–0.38 s)**, measured on Docker Desktop on an Apple Silicon Mac (see `reports/convergence.csv`). Ping is polled every 0.5 s, so this is an upper bound. Both ends lose the interface at once, so this covers flooding the new LSAs, re-running SPF and updating the kernel routes. No Dead-interval wait is involved.

## Packet capture

OSPF is IP protocol 89, captured from a `nicolaka/netshoot` container sharing r1's network namespace:

```bash
docker run --rm --net container:r1 -v "$PWD/captures:/captures" nicolaka/netshoot \
  tcpdump -i any -c 20 -w /captures/r1-ospf.pcap ip proto 89
```

TODO: screenshot of a decoded OSPF Hello in Wireshark (dst `224.0.0.5`, Hello 10 s / Dead 40 s, Area `0.0.0.0`, DR/BDR, active neighbours).

## Problems found while building it

1. **OSPF neighbours never formed on Docker `internal` bridge networks.** tcpdump on r2 showed only outgoing Hellos. Docker's firewall for internal bridge networks drops any packet whose destination is outside the subnet, and OSPF Hellos go to multicast `224.0.0.5` (nft counters showed the drops). Fix: use the `macvlan` driver, still `internal`, which is not filtered by the bridge firewall rules.
2. **`docker network disconnect/connect` could not restore a cut link.** While the link is down, OSPF correctly learns `10.0.12.0/24` via r3, and Docker then refuses to re-attach the container because the subnet "conflicts with an existing route". Fix: cut the link by shutting down the interface on both routers (`ip link set <iface> down`), like `shutdown` on a real router port.
3. **Tests crashed when started right after `docker compose up`.** `vtysh` errors until the FRR daemons are ready. The polling helper now treats a failed command as "not ready yet".

## What I'd test next

- **One-sided failure:** shut down only r1's end, so r2 has to wait for the 40 s Dead interval; then lower the Hello/Dead timers and compare.
- **Negative tests:** mismatched Hello timers or MTU, and assert the neighbours never reach `Full` (or get stuck in ExStart/Exchange).
- **BFD** for sub-second failure detection, and **BGP** between r1 and r3 in different AS numbers.
