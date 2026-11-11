"""Member 2: Review-1 Ryu controller for the SDN-integrated UDP service project.

Implements:
- OpenFlow 1.3 switch support
- table-miss rule (send unknown packets to controller)
- MAC learning and basic L2 forwarding
- short-lived IPv4 destination forwarding flows
- REST endpoints for registration/removal notifications from the registry
- optional status endpoint for demonstration

Run from project root:
    ryu-manager --verbose controller/sdn_controller.py

Default ports: OpenFlow TCP 6633, REST/WSGI HTTP 8080.
"""

import json

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER,
    MAIN_DISPATCHER,
    DEAD_DISPATCHER,
    set_ev_cls,
)
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4, udp
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from webob import Response


WSGI_INSTANCE_NAME = "sdn_service_discovery_api"


class ServiceDiscoveryController(app_manager.RyuApp):
    """Learning-switch controller plus small service-state REST API."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}       # dpid -> {mac: port}
        self.ip_to_port = {}        # (dpid, ip) -> port
        self.ip_to_mac = {}         # (dpid, ip) -> mac
        self.datapaths = {}         # dpid -> datapath
        self.service_state = {}     # (service, IP, UDP port) -> record + active flag
        self.selection_counters = {}  # service -> next round-robin index
        self.selection_events = 0

        wsgi = kwargs["wsgi"]
        wsgi.register(ServiceAPI, {WSGI_INSTANCE_NAME: self})
        self.logger.info("SDN Service Discovery Controller started (OpenFlow 1.3)")

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(datapath.id, None)
            self.logger.info("Switch %s disconnected", datapath.id)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.datapaths[datapath.id] = datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Table-miss: forward unmatched packets to the controller.
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, priority=0, match=match, actions=actions)
        self.logger.info("Switch %s connected; table-miss rule installed", datapath.id)

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        instructions = [
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)
        ]
        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions,
            idle_timeout=idle_timeout,
        )
        datapath.send_msg(flow_mod)

    @staticmethod
    def service_key(record):
        return (str(record["service"]), str(record["ip"]), int(record["port"]))

    def delete_provider_flows(self, datapath, ip_addr, port):
        """Delete the UDP destination flow for one service endpoint."""
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch(
            eth_type=0x0800, ip_proto=17, ipv4_dst=ip_addr, udp_dst=int(port)
        )
        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match,
        )
        datapath.send_msg(flow_mod)

    def install_service_flow(self, ip_addr, port, priority=20):
        """Install a UDP destination rule wherever the provider IP port is learned."""
        installed = 0
        for (dpid, learned_ip), out_port in list(self.ip_to_port.items()):
            if learned_ip != ip_addr:
                continue
            datapath = self.datapaths.get(dpid)
            if datapath is None:
                continue
            parser = datapath.ofproto_parser
            match = parser.OFPMatch(
                eth_type=0x0800, ip_proto=17, ipv4_dst=ip_addr, udp_dst=int(port)
            )
            self.add_flow(
                datapath, priority=priority, match=match,
                actions=[parser.OFPActionOutput(out_port)], idle_timeout=0
            )
            installed += 1
            self.logger.info(
                "Installed dynamic service flow: switch=%s dst=%s udp_port=%s out_port=%s priority=%s",
                dpid, ip_addr, port, out_port, priority
            )
        return installed

    def install_block_flow(self, datapath, ip_addr, port):
        """Install a high-priority drop rule for one inactive UDP service endpoint."""
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(
            eth_type=0x0800, ip_proto=17, ipv4_dst=ip_addr, udp_dst=int(port)
        )
        # An empty action list intentionally drops matching packets.
        self.add_flow(datapath, priority=100, match=match, actions=[], idle_timeout=0)
        self.logger.warning(
            "Installed provider-block rule: switch=%s dst=%s udp_port=%s",
            datapath.id, ip_addr, port
        )

    def select_service(self, service):
        """Return the next active provider using round-robin selection."""
        active = [
            record for record in self.service_state.values()
            if record.get("service") == service and record.get("active", False)
        ]
        active.sort(key=lambda item: (str(item.get("ip")), int(item.get("port", 0))))
        if not active:
            return None
        index = self.selection_counters.get(service, 0) % len(active)
        selected = active[index]
        self.selection_counters[service] = (index + 1) % len(active)
        self.selection_events += 1
        # Prioritise a destination-specific forwarding entry for the chosen provider.
        self.install_service_flow(str(selected["ip"]), int(selected["port"]), priority=30)
        self.logger.info(
            "ROUND-ROBIN SELECT: service=%s provider=%s:%s",
            service, selected["ip"], selected["port"]
        )
        return selected

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        in_port = msg.match.get("in_port")

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return

        src_mac = eth.src
        dst_mac = eth.dst
        self.mac_to_port.setdefault(dpid, {})[src_mac] = in_port

        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt:
            self.ip_to_port[(dpid, arp_pkt.src_ip)] = in_port
            self.ip_to_mac[(dpid, arp_pkt.src_ip)] = src_mac

        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            self.ip_to_port[(dpid, ip_pkt.src)] = in_port
            self.ip_to_mac[(dpid, ip_pkt.src)] = src_mac
            udp_pkt = pkt.get_protocol(udp.udp)
            if udp_pkt:
                inactive = next((
                    record for record in self.service_state.values()
                    if record.get("ip") == ip_pkt.dst
                    and int(record.get("port", 0)) == int(udp_pkt.dst_port)
                    and not record.get("active", False)
                ), None)
                if inactive:
                    self.logger.warning(
                        "Dropping packet to inactive service endpoint %s:%s",
                        ip_pkt.dst, udp_pkt.dst_port
                    )
                    return

        # Learning-switch forwarding: use a known destination port, else flood.
        out_port = self.mac_to_port[dpid].get(dst_mac, ofproto.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]

        # Install a short-lived flow for known IPv4 unicast destinations.
        # Service-specific static rules installed by register_service use a higher priority.
        if ip_pkt and out_port != ofproto.OFPP_FLOOD:
            udp_pkt = pkt.get_protocol(udp.udp)
            if udp_pkt:
                match = parser.OFPMatch(
                    eth_type=0x0800, ip_proto=17,
                    ipv4_dst=ip_pkt.dst, udp_dst=int(udp_pkt.dst_port)
                )
            else:
                match = parser.OFPMatch(eth_type=0x0800, ipv4_dst=ip_pkt.dst)
            self.add_flow(
                datapath,
                priority=10,
                match=match,
                actions=[parser.OFPActionOutput(out_port)],
                idle_timeout=30,
            )

        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        packet_out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data,
        )
        datapath.send_msg(packet_out)

    def register_service(self, record):
        required = ("service", "ip", "port")
        if any(key not in record for key in required):
            raise ValueError("record must contain service, ip and port")
        normalized = dict(record)
        normalized["ip"] = str(normalized["ip"])
        normalized["port"] = int(normalized["port"])
        normalized["active"] = True
        key = self.service_key(normalized)
        self.service_state[key] = normalized
        self.logger.info(
            "SERVICE REGISTERED/RECOVERED: %s -> %s:%s",
            normalized["service"], normalized["ip"], normalized["port"]
        )

        # Remove a previous block for this exact UDP endpoint, then restore forwarding.
        for datapath in list(self.datapaths.values()):
            self.delete_provider_flows(datapath, normalized["ip"], normalized["port"])
        self.install_service_flow(normalized["ip"], normalized["port"], priority=20)

    def remove_service(self, record):
        required = ("service", "ip", "port")
        if any(key not in record for key in required):
            raise ValueError("record must contain service, ip and port")
        normalized = dict(record)
        normalized["service"] = str(normalized["service"])
        normalized["ip"] = str(normalized["ip"])
        normalized["port"] = int(normalized["port"])
        key = self.service_key(normalized)
        existing = self.service_state.get(key, {})
        merged = dict(existing)
        merged.update(normalized)
        merged["active"] = False
        self.service_state[key] = merged
        self.logger.warning(
            "SERVICE MARKED INACTIVE: %s (%s:%s)",
            merged.get("service", "unknown service"), merged["ip"], merged["port"]
        )
        # Remove stale destination rules and block only this UDP port, not every service on the host.
        for datapath in list(self.datapaths.values()):
            self.delete_provider_flows(datapath, merged["ip"], merged["port"])
            self.install_block_flow(datapath, merged["ip"], merged["port"])

    def status(self):
        return {
            "switches": sorted(self.datapaths.keys()),
            "services": list(self.service_state.values()),
            "blocked_services": sorted(
                f"{record['ip']}:{record['port']}"
                for record in self.service_state.values()
                if not record.get("active", False)
            ),
            "selection_policy": "round-robin",
            "selection_events": self.selection_events,
        }


class ServiceAPI(ControllerBase):
    """HTTP endpoints called by the registry/integration module."""

    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self.controller = data[WSGI_INSTANCE_NAME]

    @route("service_register", "/service/register", methods=["POST"])
    def register(self, req, **kwargs):
        try:
            body = json.loads(req.body.decode("utf-8"))
            self.controller.register_service(body)
            payload = {"ok": True, "action": "register", "ip": body.get("ip")}
            return Response(content_type="application/json",
                            body=json.dumps(payload).encode("utf-8"))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return Response(status=400, content_type="application/json",
                            body=json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))

    @route("service_remove", "/service/remove", methods=["POST"])
    def remove(self, req, **kwargs):
        try:
            body = json.loads(req.body.decode("utf-8"))
            self.controller.remove_service(body)
            payload = {"ok": True, "action": "remove", "ip": body.get("ip")}
            return Response(content_type="application/json",
                            body=json.dumps(payload).encode("utf-8"))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return Response(status=400, content_type="application/json",
                            body=json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))

    @route("service_select", "/service/select/{service}", methods=["GET"])
    def select(self, req, **kwargs):
        service = str(kwargs.get("service", "")).strip()
        if not service:
            return Response(status=400, content_type="application/json",
                            body=json.dumps({"status": "ERROR", "message": "service is required"}).encode("utf-8"))
        selected = self.controller.select_service(service)
        if selected is None:
            payload = {"status": "NOT_FOUND", "service": service, "message": "no active provider known to controller"}
            return Response(status=404, content_type="application/json",
                            body=json.dumps(payload).encode("utf-8"))
        payload = {
            "status": "OK",
            "service": service,
            "policy": "round-robin",
            "server": {
                "service": selected.get("service"),
                "ip": selected.get("ip"),
                "port": selected.get("port"),
                "status": "ACTIVE",
            },
        }
        return Response(content_type="application/json",
                        body=json.dumps(payload).encode("utf-8"))

    @route("service_status", "/service/status", methods=["GET"])
    def status(self, req, **kwargs):
        payload = self.controller.status()
        return Response(content_type="application/json",
                        body=json.dumps(payload).encode("utf-8"))
