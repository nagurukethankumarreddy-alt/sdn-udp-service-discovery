# SDN-Integrated UDP Service Discovery System (Review 1)

A low-level UDP socket-based Service Discovery and Registry application integrated with a basic Ryu SDN Controller inside a Mininet network topology. This repository contains the Deliverable 1 (Review 1) implementation.

## 1. Team Members & Module Ownership

| Team Member | GitHub Handle | Assigned Module & Responsibilities |
| :--- | :--- | :--- |
| **Naguru Kethan Kumar Reddy** | `@nagurukethankumarreddy-alt` | **UDP Service Discovery & Registry (Application Layer):** Define UDP protocol, build the Service Registry, Service Server, and Discovery Client (`app/protocol.py`, `app/registry_server.py`, `app/service_server.py`, `app/discovery_client.py`). |
| **Vedika** | `@vedika0303` | **Mininet + Ryu + SDN (Network Layer):** Create Mininet topology with Open vSwitch, configure OpenFlow 1.3, and implement Ryu controller functionality (`topology/mininet_topology.py`, `controller/sdn_controller.py`). |
| **Yashwant Kumar** | `@yashja06-lgtm` | **Socket-SDN Integration, Testing & Documentation:** Connect the Registry to the Ryu controller via REST, verify pingall/flows, capture Wireshark UDP evidence, and prepare the architecture presentation[cite: 8]. |

---

## 2. Review 1 Target Objectives
For Review 1, the immediate goal is to build and demonstrate the first working end-to-end version of the project[cite: 8]:
- **UDP protocol + Registry:** Implemented `REGISTER`, `DISCOVER`, and `HEARTBEAT` functionality[cite: 8].
- **Service Client/Server:** Actual UDP request and response payloads exchanged between nodes[cite: 8].
- **Mininet topology:** Network topology creation with successful `pingall` verification[cite: 8].
- **Ryu/OpenFlow:** Controller connection to switches with basic flow installation and controller logs[cite: 8].
- **Socket–SDN integration:** Registry events (like `REGISTER` or timeouts) trigger notifications to the Ryu controller via REST[cite: 8].
- **Wireshark/Testing:** UDP packet capture on port 5000 and 8001 demonstrating evidence of protocol execution[cite: 8].

---

## 3. System Architecture & Integration Flow

```mermaid
sequenceDiagram
    participant SP as Service Server (h2)
    participant REG as UDP Registry (h1)
    participant SDN as Ryu SDN Controller
    participant CL as Discovery Client (h3)

    Note over SP, SDN: 1. Service Registration & SDN Notification
    SP->>REG: UDP REGISTER {"service": "compute", "ip": "10.0.0.2", "port": 8001}
    REG-->>SP: UDP REGISTER_ACK
    REG->>SDN: REST POST /sdn/service/register
    SDN->>SDN: Install OpenFlow rules (Allow traffic)

    Note over SP, REG: 2. Periodic Heartbeats
    SP->>REG: UDP HEARTBEAT (every 2s)

    Note over CL, SP: 3. Service Discovery & Execution
    CL->>REG: UDP DISCOVER {"service": "compute"}
    REG-->>CL: UDP DISCOVER_RESP {"ip": "10.0.0.2", "port": 8001}
    CL->>SP: UDP SERVICE_REQUEST {"payload": "Client Data"}
    SP-->>CL: UDP SERVICE_RESPONSE {"data": "Processed Data successfully"}
