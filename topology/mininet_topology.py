"""Member 2: two-switch Mininet topology for the Review 1 demonstration.

Hosts:
  h1  UDP Registry         10.0.0.1/24  -- connected to s1
  h2  Discovery Client     10.0.0.2/24  -- connected to s2
  h3  Weather Server 1     10.0.0.3/24  -- connected to s1
  h4  Weather Server 2     10.0.0.4/24  -- connected to s2
  h5  News Server           10.0.0.5/24  -- connected to s1
  api root-namespace API   10.0.0.254/24 -- connected to s1

Both OVS switches connect to Ryu using OpenFlow 1.3. The root-namespace
`api` interface makes the Ryu REST API reachable by Mininet hosts through
http://10.0.0.254:8080. From h1/h2/h3/h4, 127.0.0.1 refers to that host itself.

Run from the project root:
  sudo -E python3 topology/mininet_topology.py
"""
import os
import signal
import sys
import time
from pathlib import Path

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info

CONTROLLER_IP = os.environ.get("RYU_CONTROLLER_IP", "127.0.0.1")
CONTROLLER_PORT = int(os.environ.get("RYU_CONTROLLER_PORT", "6633"))
API_HOST_IP = os.environ.get("RYU_API_HOST_IP", "10.0.0.254")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROVIDER_AGENT = PROJECT_ROOT / "app" / "provider_agent.py"


class ServiceDiscoveryTopo(Topo):
    """Two OVS switches, five Mininet hosts and one root API link."""

    def build(self):
        s1 = self.addSwitch("s1", protocols="OpenFlow13")
        s2 = self.addSwitch("s2", protocols="OpenFlow13")

        # Fixed MAC/IP addresses make demonstrations and packet captures clearer.
        h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")
        h3 = self.addHost("h3", ip="10.0.0.3/24", mac="00:00:00:00:00:03")
        h4 = self.addHost("h4", ip="10.0.0.4/24", mac="00:00:00:00:00:04")
        h5 = self.addHost("h5", ip="10.0.0.5/24", mac="00:00:00:00:00:05")
        api = self.addHost(
            "api", ip=f"{API_HOST_IP}/24", mac="00:00:00:00:00:fe", inNamespace=False
        )

        self.addLink(h1, s1)       # registry
        self.addLink(h3, s1)       # server 1
        self.addLink(s1, s2)       # inter-switch link
        self.addLink(h2, s2)       # client
        self.addLink(h4, s2)       # Weather backup server
        self.addLink(h5, s1)       # News server
        self.addLink(api, s1)      # root namespace -> Ryu REST API


def run():
    net = Mininet(
        topo=ServiceDiscoveryTopo(),
        switch=OVSSwitch,
        controller=None,
        autoSetMacs=False,
        autoStaticArp=False,
    )
    net.addController(
        "c0", controller=RemoteController, ip=CONTROLLER_IP, port=CONTROLLER_PORT
    )
    provider_agents = []
    try:
        info("*** Starting SDN service-discovery topology\n")
        net.start()

        # Expose a small management API in each application host. The dashboard
        # uses these agents to start/stop real UDP service providers in that
        # host's network namespace. h2 may act as both a client and provider.
        info("*** Starting provider-management agents on h2, h3, h4 and h5\n")
        for node_name in ("h2", "h3", "h4", "h5"):
            node = net.get(node_name)
            agent_log = open(f"/tmp/cn_pro_agent_{node_name}.log", "ab", buffering=0)
            try:
                agent = node.popen(
                    [
                        sys.executable, str(PROVIDER_AGENT),
                        "--node-name", node_name,
                        "--node-ip", node.IP(),
                        "--registry-ip", "10.0.0.1",
                        "--registry-port", "9999",
                        "--project-root", str(PROJECT_ROOT),
                        "--host", "0.0.0.0",
                        "--port", "8765",
                    ],
                    cwd=str(PROJECT_ROOT),
                    stdout=agent_log,
                    stderr=agent_log,
                )
            finally:
                agent_log.close()
            provider_agents.append(agent)
        time.sleep(0.35)
        info("*** Provider agents listen on TCP port 8765 inside h2-h5\n")
        info("\n*** Host roles\n")
        info("  h1 = UDP registry      10.0.0.1 (connected to s1)\n")
        info("  h2 = discovery client  10.0.0.2 (connected to s2)\n")
        info("  h3 = Weather server 1  10.0.0.3 (connected to s1)\n")
        info("  h4 = Weather server 2  10.0.0.4 (connected to s2)\n")
        info(f"  api = root namespace   {API_HOST_IP} (Ryu REST port 8080)\n")
        info(f"  Ryu OpenFlow endpoint = {CONTROLLER_IP}:{CONTROLLER_PORT}\n")
        info("*** Try: nodes, net, dump, pingall\n")
        info("*** Flow inspection: sh ovs-ofctl -O OpenFlow13 dump-flows s1\n")
        CLI(net)
    finally:
        info("*** Stopping provider-management agents\n")
        for agent in provider_agents:
            if agent.poll() is None:
                try:
                    agent.send_signal(signal.SIGINT)
                    agent.wait(timeout=2.0)
                except Exception:
                    try:
                        agent.terminate()
                    except Exception:
                        pass
        info("*** Stopping Mininet topology\n")
        net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run()
