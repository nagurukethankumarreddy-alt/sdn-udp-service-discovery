# Review 1: Scope, implementation and demo

## What Review 1 should prove

Prioritize a small, reproducible foundation over advanced features:

1. **UDP application works locally:** registration, discovery, service request/response and heartbeat timeout.
2. **Mininet topology exists:** two OpenFlow 1.3 switches, registry, client, two service hosts and a root-namespace interface for controller REST.
3. **Controller can connect:** Ryu starts and both switches connect using OpenFlow 1.3.
4. **Basic forwarding works:** `pingall` succeeds and flow tables can be inspected.
5. **Registry/controller integration works:** register/remove events appear in registry/controller logs and `/service/status` reflects service state.
6. **Evidence is captured:** terminal screenshots, logs, flow table output, and actual test results.

Follow the exact rubric from your instructor if it lists different review deliverables.

## Demonstration order

1. Show architecture and host roles.
2. Run syntax compilation and `tests/test_local_stack.py`.
3. Show the Ryu startup log and switch connection messages, if the Ryu environment is working.
4. Show Mininet `nodes`, `net`, and `pingall`.
5. Start registry and both service instances; show registration/heartbeat logs.
6. Run the client and show a real service response.
7. Show controller REST status and `ovs-ofctl` flow tables.
8. Stop one service process, wait past heartbeat timeout, and show it becomes inactive. Repeat discovery to verify the remaining service can respond.

## How to explain the components

- **UDP registry:** service directory; keeps service name, IP, port and status in memory.
- **Heartbeat/reaper:** updates liveness timestamps and marks stale service records inactive.
- **Discovery client:** asks registry which endpoints are active and sends a request to one.
- **Ryu controller:** handles OpenFlow events and sends rules to OVS switches; exposes REST endpoints for service state updates.
- **Mininet:** creates a repeatable virtual network with hosts, links and switches.
- **Open vSwitch:** programmable switch that enforces OpenFlow rules.
- **REST webhook:** carries registry registration/removal events to the controller.

## Do not overclaim

- The local UDP smoke test does not test Ryu, OVS or Mininet.
- `pingall` does not prove the UDP service-discovery application works.
- A REST notification does not by itself prove packets reroute or fail over. Verify the behavior and flow tables.
- The baseline client chooses the first active endpoint; it is not a load-balancing algorithm.
