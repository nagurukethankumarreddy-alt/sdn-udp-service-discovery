# SDN-Integrated UDP Service Discovery System

A low-level UDP socket-based Service Discovery and Registry application integrated with an SDN controller using Ryu, Open vSwitch, and Mininet. 

The project solves the problem of hard-coded IP configurations by introducing a dynamic "phonebook" for network services. It demonstrates service registration, dynamic endpoint discovery, heartbeat-based health tracking, and controller-based OpenFlow rule management for failover scenarios.

## 1. Project Objectives

- Implement a custom UDP-based application protocol for service registration, discovery, and heartbeats.
- Run a central Service Registry and multiple Service Providers inside a Mininet network.
- Integrate the UDP application layer with a Ryu SDN controller via HTTP REST webhooks.
- Dynamically install and remove OpenFlow 1.3 rules based on provider availability.
- Handle a "Challenging Scenario" (provider crash) by detecting heartbeat timeouts, blocking the dead IP at the switch level, and seamlessly failing over to a backup provider.
- Provide a web-based Dashboard UI to manage provider processes, simulate client requests, and monitor network status.

## 2. Technologies Used

- Python 3.11
- UDP and TCP Socket Programming
- Mininet Network Emulator
- Open vSwitch (OVS)
- Ryu SDN Controller
- OpenFlow 1.3
- HTTP REST / JSON
- HTML/CSS/JS (Dashboard UI)
- Ubuntu / WSL2

## 3. Team Responsibilities

| Member | Responsibility |
|---|---|
| **Naguru Kethan Kumar Reddy** | **UDP Application Layer:** Defined UDP protocol, built the Service Registry, Service Server, and Discovery Client. Implemented the heartbeat timeout reaper and REST webhook triggers. |
| **Vedika** | **Network & SDN Layer:** Created Mininet topology with Open vSwitch, configured OpenFlow 1.3, and implemented Ryu controller functionality for dynamic flow installation and round-robin routing. |
| **Yashwant Kumar** | **Integration, Testing & Documentation:** Built the performance evaluation scripts (`benchmark.py`), tested integration, captured Wireshark UDP evidence, and prepared architecture documentation/demonstrations. |

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
Port & Protocol Mappings:

UDP 9999: Registry Server listening port.

UDP 5001, 5002, 5005: Service Provider application ports.

TCP 8080: Ryu Controller REST API.

TCP 8765: Host-local Provider Management Agents.

TCP 8000: Web Dashboard UI.

5. Repository Structure
Plaintext
sdn-udp-service-discovery/
├── app/
│   ├── benchmark.py           # Performance measurement script
│   ├── dashboard.py           # Web UI and HTTP API coordinator
│   ├── discovery_client.py    # Client discovery & fallback execution logic
│   ├── protocol.py            # JSON encode/decode & UDP message validation
│   ├── provider_agent.py      # Host namespace HTTP agent to launch providers
│   ├── registry_server.py     # Registry UDP server & heartbeat timeout reaper
│   ├── selection.py           # Ryu round-robin selection helper
│   └── service_server.py      # Provider process with background heartbeat thread
├── controller/
│   └── sdn_controller.py      # Ryu OpenFlow 1.3 Controller application
├── docs/                      # Rubrics, design documents, and checklists
├── integration/
│   └── ryu_client.py          # HTTP POST bridge from Registry to Ryu
├── scripts/                   # Setup and local test bash scripts
├── tests/                     # Automated local unit and integration tests
├── topology/
│   └── mininet_topology.py    # Emulated network with OVS and namespaces
├── .gitignore
└── README.md
6. Execution Instructions
Use separate Ubuntu terminal windows for the controller, Mininet, Dashboard, and verification.

Terminal 1: Start the Ryu Controller
Bash
source .venv311/bin/activate
ryu-manager --ofp-tcp-listen-port 6633 controller/sdn_controller.py
Terminal 2: Start Mininet & The Registry
Bash
sudo -E python3 topology/mininet_topology.py
At the mininet> prompt, verify connectivity:

Plaintext
mininet> pingall
Start the UDP Registry inside host 1 (h1):

Plaintext
mininet> h1 python3 app/registry_server.py --host 10.0.0.1 --port 9999 --controller-url [http://10.0.0.254:8080](http://10.0.0.254:8080) &
Terminal 3: Start the Web Dashboard
Run this from a normal Ubuntu terminal (outside Mininet):

Bash
python3 -m app.dashboard --registry-ip 10.0.0.1 --registry-port 9999 --controller-url [http://127.0.0.1:8080](http://127.0.0.1:8080)
Open a web browser and navigate to http://127.0.0.1:8000.

7. Testing Service Discovery & Failover
Add Providers: In the Dashboard's Service Provider tab, add a Weather service on h3 (Port 5001) and h4 (Port 5002).

Discover & Request: In the Client tab, search for Weather. Enable Ryu-assisted selection. Send a UDP request and observe the successful SERVICE_RESPONSE.

Challenging Scenario (Crash & Failover):

Manually stop the h3 provider in the UI.

Wait 8 seconds. The registry marks it INACTIVE due to missing heartbeats and notifies Ryu.

Send another Client request. The fallback loop automatically routes the request to the surviving h4 provider.

8. OpenFlow Rule Verification
At the mininet> prompt, run:

Plaintext
sh ovs-ofctl -O OpenFlow13 dump-flows s1
sh ovs-ofctl -O OpenFlow13 dump-flows s2
Expected Flow Priorities:

Priority 0: Table-miss fallback (sends to controller).

Priority 10: Standard learned IPv4 forwarding.

Priority 20: Active Provider forwarding (installed when provider registers).

Priority 100: Inactive Provider Block (drops packets destined for a dead provider IP/Port).

9. Performance Benchmark
To measure end-to-end transaction latency, success rate, and throughput, run the benchmark script in Terminal 4:

Baseline Mode (Registry-First):

Bash
python3 -m app.benchmark --mode baseline --service Weather --registry-ip 10.0.0.1 --registry-port 9999 --iterations 30
SDN Mode (Ryu Round-Robin):

Bash
python3 -m app.benchmark --mode sdn --service Weather --registry-ip 10.0.0.1 --registry-port 9999 --controller-url [http://127.0.0.1:8080](http://127.0.0.1:8080) --iterations 30
10. Limitations & Future Scope
In-Memory Registry: Service records are lost if the registry restarts. Future work includes persistent database integration (SQLite/PostgreSQL).

Selection Policy: Ryu utilizes cyclic round-robin selection. It is not currently "load-aware" regarding CPU/memory metrics.

Fixed Topology: The dashboard manages processes on fixed Mininet hosts (h2 to h5) and cannot dynamically spawn new Mininet nodes.

Best-Effort UDP: Built-in application timeouts handle failures, but UDP itself lacks transport-level reliability.
