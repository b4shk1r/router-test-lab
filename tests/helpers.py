"""Small functions every test reuses. They talk to the routers via `docker exec`."""
import json
import subprocess
import time

ROUTERS = ["r1", "r2", "r3"]
LOOPBACKS = {"r1": "1.1.1.1", "r2": "2.2.2.2", "r3": "3.3.3.3"}
# The one link subnet each router is NOT directly attached to (it must learn it via OSPF).
FAR_SUBNET = {"r1": "10.0.23.0/24", "r2": "10.0.13.0/24", "r3": "10.0.12.0/24"}


def sh(*args):
    """Run a command and return its stdout; raise (with its stderr) if it fails."""
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args, result.stdout,
                                            result.stderr)
    return result.stdout


def vtysh_json(router, command):
    """Run a FRR show command with `json` appended and parse the result."""
    return json.loads(sh("docker", "exec", router, "vtysh", "-c", f"{command} json"))


def routes(router, prefix):
    """All route entries for one prefix, or [] if the router has no route to it."""
    return vtysh_json(router, "show ip route").get(prefix, [])


def full_neighbours(router):
    """How many OSPF neighbours of this router are in the Full state."""
    data = vtysh_json(router, "show ip ospf neighbor")
    # FRR has used both field names across versions, so accept either.
    states = [n.get("nbrState") or n.get("state", "")
              for entries in data.get("neighbors", {}).values() for n in entries]
    return sum(s.startswith("Full") for s in states)


def can_ping(router, ip):
    result = subprocess.run(["docker", "exec", router, "ping", "-c", "1", "-W", "1", ip],
                            capture_output=True)
    return result.returncode == 0


def wait_until(check, timeout=60, step=0.5):
    """Poll until check() is true; return the seconds it took.

    A check that raises (e.g. vtysh not ready yet right after start-up) counts
    as "not yet", so we keep polling instead of crashing.
    """
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            if check():
                return time.monotonic() - start
        except (subprocess.CalledProcessError, ValueError, KeyError):
            pass
        time.sleep(step)
    raise TimeoutError(f"not true after {timeout} s")
