# Review 2 / D2 Implementation Plan and Demonstration

## Recommendation
Extend the Review 1 project. Do not rebuild it. The existing UDP protocol, registry,
provider, client, Mininet topology and Ryu integration remain the foundation.

## Rubric-to-implementation map

| D2 rubric item | Added/required evidence | Relevant files |
|---|---|---|
| Complete application functionality (4) | Web dashboard; discover Weather/News; send a request; display provider and response; see provider states | `app/dashboard.py`, `app/registry_server.py`, `app/discovery_client.py`, `app/service_server.py` |
| Dynamic SDN functionality (6) | Ryu round-robin provider selection API; install selected-provider flow where the host port is learned; install high-priority drop flows for inactive providers; clear blocks on re-registration | `controller/sdn_controller.py`, `app/selection.py`, `app/registry_server.py` |
| Challenging scenario / robustness (4) | Provider failure via abrupt stop; heartbeat timeout; Ryu blocks inactive destination; client retries remaining providers; optional response delay / packet-drop simulation | `app/service_server.py`, `app/discovery_client.py`, `app/registry_server.py`, `controller/sdn_controller.py` |
| Performance evaluation & comparison (5) | CSV benchmark with per-request latency, success/failure, p95, throughput and provider distribution; baseline registry-first versus Ryu-assisted selection | `app/benchmark.py`, `results/` |
| Documentation, final demo & viva (6) | Architecture, runbook, scenario instructions, evaluation methodology and honest limitations | `README.md`, `RUN_COMPLETE_PROJECT.md`, this file |

## Architecture after the extension

1. Mininet emulates registry host h1, client h2, Weather providers h3/h4, News provider h5 and OVS switches s1/s2.
2. Providers register and send heartbeat datagrams to the UDP registry on h1.
3. The registry asynchronously notifies Ryu using HTTP POST `/service/register` and `/service/remove`.
4. The Ryu controller stores active provider records and exposes `/service/select/<service>`.
5. The discovery client first obtains active endpoints from the UDP registry. With `--controller-url`, it asks Ryu to select an active provider using round-robin, then tries the other registry candidates if the selected provider fails.
6. When a provider becomes inactive, Ryu removes old destination flows and installs a priority-100 drop rule for its IPv4 destination. On re-registration, the controller removes the block and reinstalls a destination forwarding rule where the provider's port is known.
7. The browser dashboard calls the same UDP registry and Ryu APIs; it does not replace the socket application.

## Installation

See `RUN_COMPLETE_PROJECT.md`. The dashboard and benchmark use Python's standard library.
Ryu remains in the dedicated Python 3.11 virtual environment because Ryu's legacy dependency
stack may not work with newer system Python versions.

## D2 demo sequence (about 8–10 minutes)

### A. Start controller and topology
Terminal 1:
```bash
cd ~/Downloads/cn_pro_full_application/cn_pro
source .venv311/bin/activate
ryu-manager --ofp-tcp-listen-port 6633 controller/sdn_controller.py
```
Terminal 2:
```bash
cd ~/Downloads/cn_pro_full_application/cn_pro
sudo -E python3 topology/mininet_topology.py
```
At `mininet>`:
```text
nodes
pingall
```

### B. Start registry and providers
At `mininet>`:
```text
h1 python3 /home/USER/Downloads/cn_pro_full_application/cn_pro/app/registry_server.py --host 10.0.0.1 --port 9999 --controller-url http://10.0.0.254:8080 &
h3 python3 /home/USER/Downloads/cn_pro_full_application/cn_pro/app/service_server.py --service Weather --ip 10.0.0.3 --port 5001 --registry-ip 10.0.0.1 --registry-port 9999 &
h4 python3 /home/USER/Downloads/cn_pro_full_application/cn_pro/app/service_server.py --service Weather --ip 10.0.0.4 --port 5002 --registry-ip 10.0.0.1 --registry-port 9999 &
h5 python3 /home/USER/Downloads/cn_pro_full_application/cn_pro/app/service_server.py --service News --ip 10.0.0.5 --port 5005 --registry-ip 10.0.0.1 --registry-port 9999 &
```
Replace `USER` with the actual Ubuntu username and update the absolute path if extraction differs.

### C. Run Weather / News with Ryu selection and fallback
```text
h2 python3 /home/USER/Downloads/cn_pro_full_application/cn_pro/app/discovery_client.py --service Weather --message "Review 2 Weather request" --registry-ip 10.0.0.1 --registry-port 9999 --controller-url http://10.0.0.254:8080
h2 python3 /home/USER/Downloads/cn_pro_full_application/cn_pro/app/discovery_client.py --service News --message "Review 2 News request" --registry-ip 10.0.0.1 --registry-port 9999 --controller-url http://10.0.0.254:8080
```
Run Weather repeatedly and show the controller's selected endpoint alternates between h3 and h4.

### D. Launch the application dashboard
In a normal Ubuntu terminal (not at the Mininet prompt):
```bash
cd ~/Downloads/cn_pro_full_application/cn_pro
python3 -m app.dashboard --registry-ip 10.0.0.1 --registry-port 9999 --controller-url http://127.0.0.1:8080
```
Open `http://127.0.0.1:8000` in the Ubuntu browser. Show provider status, discovery, request and reply.

### E. Demonstrate a provider failure and SDN block
At `mininet>` abruptly kill h4 so it does not gracefully unregister:
```text
sh pkill -f 'service_server.py --service Weather --ip 10.0.0.4'
```
Wait 10–12 seconds. Inspect:
```bash
curl -s http://127.0.0.1:8080/service/status
```
Then inspect the flow table:
```text
sh ovs-ofctl -O OpenFlow13 dump-flows s1
sh ovs-ofctl -O OpenFlow13 dump-flows s2
```
Look for a priority-100 rule matching IPv4 destination `10.0.0.4`. Repeat Weather discovery/request. The registry should no longer return h4 as active; the controller should no longer select it; the client should use h3.

To demonstrate recovery, restart h4 with its original command and wait for re-registration. Ryu should mark it active and remove its drop rule. Confirm with REST status and a new discovery.

### F. Performance comparison
Run each benchmark from a normal terminal while both Weather providers are healthy:
```bash
python3 app/benchmark.py --mode baseline --service Weather --registry-ip 10.0.0.1 --registry-port 9999 --iterations 30
python3 app/benchmark.py --mode sdn --service Weather --registry-ip 10.0.0.1 --registry-port 9999 --controller-url http://127.0.0.1:8080 --iterations 30
```
Each run saves a CSV under `results/`. Record average/median/p95 latency, success rate, throughput and provider distribution. The SDN mode includes an HTTP selection call, so it can have extra control-plane latency; do not claim it is faster unless your measured results prove that. The key comparison is baseline first-provider selection versus controller-assisted round-robin and provider distribution.

Repeat with one provider stopped to compare success/failure behaviour, but label those results as a failure-condition experiment rather than a normal-performance comparison.

## Performance methodology

- Warm up services before measuring.
- Use the same Mininet topology, service, request text size, iteration count and timeout in both modes.
- Run baseline and SDN modes multiple times and report mean/median/p95, success rate and completed requests per second.
- Save the raw CSV files. Calculate percentage difference only from measured values:
  `((baseline - SDN) / baseline) * 100`.
- Explain the trade-off: SDN selection may add REST overhead but provides controller-coordinated provider choice and a central place for dynamic policy.
- Avoid presenting one run as conclusive; use at least three runs per mode for the final report.

## Important limitations to disclose

- The registry is in-memory; restarting it clears registrations until providers register/heartbeat again.
- Round-robin selection is performed by the Ryu controller's REST API. It is not weighted or load-aware yet.
- The priority-100 drop rule blocks traffic to an inactive provider IP. Existing requests are not migrated mid-flight. The client can fail over only while trying the candidates returned by the registry.
- The dashboard binds to localhost by default and has no authentication. Keep it local for the academic demo.
- The benchmark measures application transaction latency (registry discovery + optional controller selection + provider UDP response); it is not a hardware line-rate benchmark.
- The local smoke test does not exercise Ryu or Mininet. The integrated demonstration and flow-table inspection are separate checks.

## Local regression test for fallback

`tests/test_failover_local.py` runs a registry and two providers on localhost. The first provider drops every service datagram; the test checks that the client times out and successfully uses the second provider.


## Full interactive web application

`app/dashboard.py` now provides two operational roles:
- Client: enter any service name, discover active UDP providers, inspect provider endpoints, select via Ryu/manual/registry policy, send a UDP request and view the reply.
- Service Provider: add a provider process to one of the existing Mininet hosts (h2–h5), select service name and UDP port, start it through a host-local management agent, and stop/unregister it from the UI.

`app/provider_agent.py` is launched automatically by the updated Mininet topology inside h2–h5. These agents are necessary because a dashboard running in the Ubuntu root namespace cannot directly launch a process inside a Mininet host namespace using an ordinary local subprocess.

The new `tests/test_dashboard_lifecycle.py` verifies the dashboard can start a provider, discover it, send a UDP request, stop it and observe registry unregistration on localhost (no Mininet/Ryu required).
