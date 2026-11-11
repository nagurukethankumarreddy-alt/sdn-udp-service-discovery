# File map and ownership

## Member 1 — UDP application

- `app/protocol.py`: shared message types and JSON helpers.
- `app/registry_server.py`: UDP registry, thread-safe-by-single-loop state handling, heartbeat timeout reaper and controller event queue.
- `app/service_server.py`: service registration, heartbeat, service request responses and graceful unregister.
- `app/discovery_client.py`: discovery request and service request/response.

## Member 2 — SDN and topology

- `controller/sdn_controller.py`: Ryu application, OpenFlow 1.3, switch state tracking, table-miss rule, MAC learning, basic flow installation, REST register/remove/status endpoints.
- `topology/mininet_topology.py`: two OVS switches, four Mininet hosts, inter-switch link, and `api` interface to make REST accessible from Mininet hosts.

## Member 3 — integration and tests

- `integration/ryu_client.py`: sends HTTP REST register/remove notifications with bounded retries.
- `tests/test_local_stack.py`: starts local registry and service subprocesses, verifies discovery/request-response and heartbeat timeout.
- `docs/`: review scope, file ownership and Git workflow.

## Shared boundary

Member 1 owns UDP message shapes; Member 3 should coordinate any protocol change with Member 1. Member 2 owns OpenFlow/controller code and topology. Any changes to REST endpoint names or payload fields must be coordinated between `app/registry_server.py`, `integration/ryu_client.py`, and `controller/sdn_controller.py`.


## Review 2 files

- `app/selection.py`: queries Ryu for the preferred provider and orders fallback candidates.
- `app/dashboard.py`: local web dashboard over the registry UDP API and Ryu REST API.
- `app/benchmark.py`: baseline-vs-SDN transaction benchmark; writes raw CSV results.
- `tests/test_selection.py`: unit tests for controller-selected provider ordering.
- `docs/REVIEW2_PLAN_AND_DEMO.md`: maps the D2 rubric to features and demo evidence.

- `tests/test_failover_local.py`: verifies fallback to a healthy provider when the first drops requests.
