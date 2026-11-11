# SDN-Integrated UDP Service Discovery System

A comprehensive, low-level UDP socket-based Service Discovery and Registry application integrated with a Ryu Software-Defined Networking (SDN) Controller inside a Mininet emulated network. 

This project solves the problem of hard-coded IP configurations by introducing a dynamic "phonebook" for network services. Providers dynamically advertise their endpoints, clients discover active services by name, and an SDN controller dynamically programs the network switches to allow or block traffic based on real-time server health.

## 1. Project Objectives

- Implement a custom UDP-based application protocol for service registration, discovery, and heartbeats.
- Run a central Service Registry and multiple Service Providers inside a Mininet network.
- Integrate the UDP application layer with a Ryu SDN controller via HTTP REST webhooks.
- Dynamically install and remove OpenFlow 1.3 rules based on provider availability.
- Handle a "Challenging Scenario" (provider crash) by detecting heartbeat timeouts, blocking the dead IP at the switch level, and seamlessly failing over to a backup provider.
- Provide a web-based Dashboard UI to manage provider processes, simulate client requests, and monitor network status.

## 2. Technologies Used

- Python 3.11
- UDP & TCP Socket Programming
- Mininet Network Emulator
- Open vSwitch (OVS)
- Ryu SDN Controller
- OpenFlow 1.3
- HTTP REST / JSON
- HTML/CSS/JS (Dashboard UI)

## 3. Team Members & Responsibilities

| Team Member | GitHub Handle | Module Ownership & Responsibilities |
| :--- | :--- | :--- |
| **Naguru Kethan Kumar Reddy** | `@nagurukethankumarreddy-alt` | **UDP Service Discovery & Registry (Application Layer):** Defined UDP protocol, built the Service Registry, Service Server, and Discovery Client (`app/protocol.py`, `app/registry_server.py`, `app/service_server.py`, `app/discovery_client.py`). Implemented the heartbeat timeout reaper and REST webhook triggers[cite: 21]. |
| **Vedika** | `@vedika0303` | **Mininet + Ryu + SDN (Network Layer):** Created Mininet topology with Open vSwitch, configured OpenFlow 1.3, and implemented Ryu controller functionality (`topology/mininet_topology.py`, `controller/sdn_controller.py`) for dynamic flow installation and round-robin routing[cite: 21]. |
| **Yashwant Kumar** | `@yashja06-lgtm` | **Socket-SDN Integration, Testing & Documentation:** Built the performance evaluation scripts (`benchmark.py`), tested integration, captured Wireshark UDP evidence, and prepared architecture documentation/demonstrations[cite: 21]. |

## 4. Project Architecture

The Mininet topology contains five hosts and an API interface connected to two Open vSwitches, managed by a Ryu controller:

```text
                    Ryu SDN Controller
                         (TCP 6633)
                             |
                        OpenFlow 1.3
                             |
            +----------------+----------------+
            |                                 |
      +----------+                      +----------+
      |    s1    |----------------------|    s2    |
      |   OVS    |                      |   OVS    |
      +----------+                      +----------+
      /    |     \                        /      \
     /     |      \                      /        \
   h1      h3      h5                  h2          h4
Registry Provider Provider           Client      Provider
10.0.0.1 10.0.0.3 10.0.0.5          10.0.0.2    10.0.0.4
(UDP 9999) (Weather) (News)        (Dashboard)  (Weather)
Port & Protocol Mappings:UDP 9999: Registry Server listening port.   UDP 5001, 5002, 5005: Service Provider application ports.   TCP 8080: Ryu Controller REST API.   TCP 8765: Host-local Provider Management Agents.   TCP 8000: Web Dashboard UI.   5. Repository StructurePlaintextsdn-udp-service-discovery/
├── app/
│   ├── protocol.py            # JSON encode/decode & UDP message validation
│   ├── registry_server.py     # Registry UDP server & heartbeat timeout reaper
│   ├── service_server.py      # Provider process with background heartbeat thread
│   ├── discovery_client.py    # Client discovery & fallback execution logic
│   ├── dashboard.py           # Web UI and HTTP API coordinator
│   ├── provider_agent.py      # Host namespace HTTP agent to launch providers
│   ├── selection.py           # Ryu round-robin selection helper
│   └── benchmark.py           # Performance measurement script
├── controller/
│   └── sdn_controller.py      # Ryu OpenFlow 1.3 Controller application
├── integration/
│   └── ryu_client.py          # HTTP POST bridge from Registry to Ryu
├── topology/
│   └── mininet_topology.py    # Emulated network with OVS and namespaces
├── tests/                     # Automated local unit and integration tests
├── docs/                      # Rubrics, design documents, and checklists
└── scripts/                   # Setup and local test bash scripts
6. Execution InstructionsUse separate Ubuntu terminal windows for the controller, Mininet, Dashboard, and verification.   Terminal 1: Start the Ryu ControllerBashsource .venv311/bin/activate
ryu-manager --ofp-tcp-listen-port 6633 controller/sdn_controller.py
Keep this running. Wait for switch connection logs.   Terminal 2: Start Mininet & The RegistryBashsudo -E python3 topology/mininet_topology.py
At the mininet> prompt, verify connectivity:Plaintextmininet> pingall
Start the UDP Registry inside host 1 (h1):Plaintextmininet> h1 python3 app/registry_server.py --host 10.0.0.1 --port 9999 --controller-url [http://10.0.0.254:8080](http://10.0.0.254:8080) &
Terminal 3: Start the Web DashboardRun this from a normal Ubuntu terminal (outside Mininet):Bashpython3 -m app.dashboard --registry-ip 10.0.0.1 --registry-port 9999 --controller-url [http://127.0.0.1:8080](http://127.0.0.1:8080)
Open http://127.0.0.1:8000 in your web browser.   7. Testing & Core WorkflowsAdd Providers: In the Dashboard's Service Provider tab, add a Weather service on h3 (Port 5001) and h4 (Port 5002).   Discover & Request: In the Client tab, search for Weather[cite: 20]. Use Ryu-assisted selection. Send a UDP request and observe the successful SERVICE_RESPONSE[cite: 20].Challenging Scenario (Crash & Failover):Manually stop the h3 provider in the UI[cite: 20].Wait 8 seconds. The registry will mark it INACTIVE due to missing heartbeats and notify Ryu[cite: 20].Ryu will install a priority-100 blocking rule[cite: 20].Send another Client request. The application fallback loop will automatically route the request to the surviving h4 provider[cite: 20].8. OpenFlow Rule VerificationIn Terminal 4 (or inside the Mininet CLI), dump the flow tables to verify SDN dynamic routing:Bashsh ovs-ofctl -O OpenFlow13 dump-flows s1
sh ovs-ofctl -O OpenFlow13 dump-flows s2
Expected Flow Priorities[cite: 20]:priority=0: Table-miss fallback (sends to controller)[cite: 20].priority=10: Standard learned IPv4 forwarding[cite: 20].priority=20: Active Provider forwarding (installed when provider registers)[cite: 20].priority=100: Inactive Provider Block (drops packets destined for a dead provider IP/Port)[cite: 20].Check Ryu's internal REST state:Bashcurl -s [http://127.0.0.1:8080/service/status](http://127.0.0.1:8080/service/status) | python3 -m json.tool
9. Performance BenchmarkTo measure end-to-end transaction latency, success rate, and throughput, run the benchmark script in Terminal 4[cite: 20]:Baseline Mode (Registry-First):Bashpython3 -m app.benchmark --mode baseline --service Weather --registry-ip 10.0.0.1 --registry-port 9999 --iterations 30
SDN Mode (Ryu Round-Robin):Bashpython3 -m app.benchmark --mode sdn --service Weather --registry-ip 10.0.0.1 --registry-port 9999 --controller-url [http://127.0.0.1:8080](http://127.0.0.1:8080) --iterations 30
Note: SDN mode includes an additional HTTP REST request to the controller, which intentionally increases measured control-plane latency[cite: 20]. The benefit of SDN lies in centralized policy and dynamic blocking, not raw speed[cite: 20].10. Limitations & Future ScopeIn-Memory Registry: Service records are lost if the registry restarts. Future work includes persistent database integration (SQLite/PostgreSQL)[cite: 20].Selection Policy: Ryu utilizes cyclic round-robin selection. It is not currently "load-aware" regarding CPU/memory metrics[cite: 20].Fixed Topology: The dashboard manages processes on fixed Mininet hosts (h2 to h5) and cannot dynamically spawn new Mininet nodes[cite: 20].Best-Effort UDP: Built-in application timeouts handle failures, but UDP itself lacks transport-level reliability[cite: 20].
