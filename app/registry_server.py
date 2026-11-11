"""Member 1: UDP service registry with heartbeats and Member 3 Ryu webhook.

Example inside Mininet's h1:
  python3 app/registry_server.py --host 10.0.0.1 --port 9999 \
      --controller-url http://10.0.0.254:8080

The registry keeps service state even if the controller webhook is temporarily
unavailable; webhook errors are logged and do not crash the UDP registry.
"""
from __future__ import annotations

import argparse
import os
import queue
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.protocol import (  # noqa: E402
    ACK, DISCOVER, DISCOVER_RESPONSE, ERROR, HEARTBEAT, REGISTER, UNREGISTER,
    decode_message, encode_message, require_fields,
)
from integration.ryu_client import notify_controller  # noqa: E402


ServerKey = Tuple[str, str, int]


class Registry:
    def __init__(self, controller_url: str, heartbeat_timeout: float):
        self.controller_url = controller_url
        self.heartbeat_timeout = heartbeat_timeout
        self.services: Dict[str, Dict[ServerKey, Dict[str, Any]]] = {}
        # Keep webhook HTTP latency out of the UDP receive loop. A single worker
        # preserves event order (REGISTER followed by REMOVE, for example).
        self._notification_queue: queue.Queue[Tuple[Dict[str, Any], bool]] = queue.Queue()
        self._notification_thread = threading.Thread(
            target=self._notification_worker, name="ryu-webhook-worker", daemon=True
        )
        self._notification_thread.start()

    @staticmethod
    def _key(record: Dict[str, Any]) -> ServerKey:
        return (str(record["service"]), str(record["ip"]), int(record["port"]))

    def _controller_event(self, record: Dict[str, Any], active: bool) -> None:
        self._notification_queue.put((dict(record), active))
        label = "REGISTER" if active else "REMOVE"
        print(f"[INTEGRATION] Queued Ryu {label} event for {record['service']} {record['ip']}:{record['port']}", flush=True)

    def _notification_worker(self) -> None:
        while True:
            record, active = self._notification_queue.get()
            label = "REGISTER" if active else "REMOVE"
            try:
                ok, details = notify_controller(self.controller_url, record, active)
                if ok:
                    print(f"[INTEGRATION] Ryu {label} notification: {record['service']} {record['ip']}:{record['port']} ({details})", flush=True)
                else:
                    print(f"[WARN] Ryu {label} notification failed for {record['ip']}: {details}", flush=True)
            finally:
                self._notification_queue.task_done()

    def register(self, message: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
        require_fields(message, "service", "ip", "port")
        port = int(message["port"])
        if not 1 <= port <= 65535:
            raise ValueError("port must be in range 1..65535")
        record = {
            "service": str(message["service"]),
            "ip": str(message["ip"]),
            "port": port,
            "status": "ACTIVE",
            "last_seen": float(time.time() if now is None else now),
        }
        key = self._key(record)
        self.services.setdefault(record["service"], {})[key] = record
        self._controller_event(record, active=True)
        print(f"[REGISTRY] ACTIVE {record['service']} at {record['ip']}:{record['port']}", flush=True)
        return record

    def heartbeat(self, message: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
        require_fields(message, "service", "ip", "port")
        service, ip, port = str(message["service"]), str(message["ip"]), int(message["port"])
        key = (service, ip, port)
        group = self.services.setdefault(service, {})
        existing = group.get(key)
        if existing is None or existing.get("status") != "ACTIVE":
            # A heartbeat can restore a process after the registry restarted or
            # after a stale entry was removed. It carries the full endpoint.
            return self.register(message, now=now)
        existing["last_seen"] = float(time.time() if now is None else now)
        return existing

    def unregister(self, message: Dict[str, Any]) -> Dict[str, Any]:
        require_fields(message, "service", "ip", "port")
        key = (str(message["service"]), str(message["ip"]), int(message["port"]))
        record = self.services.get(key[0], {}).get(key)
        if record is None:
            return {"type": ERROR, "status": "NOT_FOUND", "message": "server is not registered"}
        record["status"] = "INACTIVE"
        self._controller_event(record, active=False)
        print(f"[REGISTRY] INACTIVE (unregistered) {key[0]} at {key[1]}:{key[2]}", flush=True)
        return {"type": ACK, "status": "OK", "message": "server unregistered"}

    def discover(self, message: Dict[str, Any]) -> Dict[str, Any]:
        require_fields(message, "service")
        service = str(message["service"])
        records = self.services.get(service, {})
        active = [
            {"service": r["service"], "ip": r["ip"], "port": r["port"], "status": r["status"]}
            for r in records.values() if r.get("status") == "ACTIVE"
        ]
        active.sort(key=lambda r: (r["ip"], r["port"]))
        return {
            "type": DISCOVER_RESPONSE,
            "status": "OK" if active else "NOT_FOUND",
            "service": service,
            "servers": active,
            "message": "active servers returned" if active else "no active server found",
        }

    def mark_timeouts(self, now: Optional[float] = None) -> int:
        current = float(time.time() if now is None else now)
        changed = 0
        for group in self.services.values():
            for record in group.values():
                if record.get("status") == "ACTIVE" and current - float(record["last_seen"]) > self.heartbeat_timeout:
                    record["status"] = "INACTIVE"
                    self._controller_event(record, active=False)
                    print(f"[REGISTRY] INACTIVE (heartbeat timeout) {record['service']} at {record['ip']}:{record['port']}", flush=True)
                    changed += 1
        return changed

    def snapshot(self) -> Dict[str, Any]:
        return {
            service: [dict(record) for record in entries.values()]
            for service, entries in self.services.items()
        }


def handle_message(registry: Registry, message: Dict[str, Any]) -> Dict[str, Any]:
    msg_type = message.get("type")
    if msg_type == REGISTER:
        record = registry.register(message)
        return {"type": ACK, "status": "OK", "message": "registered", "server": record}
    if msg_type == HEARTBEAT:
        registry.heartbeat(message)
        return {"type": ACK, "status": "OK", "message": "heartbeat accepted"}
    if msg_type == UNREGISTER:
        return registry.unregister(message)
    if msg_type == DISCOVER:
        return registry.discover(message)
    if msg_type == "STATUS":
        return {"type": "STATUS_RESPONSE", "status": "OK", "services": registry.snapshot()}
    return {"type": ERROR, "status": "UNKNOWN_MESSAGE", "message": f"unsupported type: {msg_type}"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UDP service registry")
    parser.add_argument("--host", default="0.0.0.0", help="UDP bind address")
    parser.add_argument("--port", type=int, default=9999, help="UDP registry port")
    parser.add_argument("--controller-url", default=os.environ.get("RYU_REST_URL", "http://10.0.0.254:8080"),
                        help="Ryu REST base URL; set empty string to disable webhook")
    parser.add_argument("--heartbeat-timeout", type=float, default=8.0, help="seconds before a server is inactive")
    parser.add_argument("--reaper-interval", type=float, default=0.5, help="timeout check interval in seconds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be in range 1..65535")
    if args.heartbeat_timeout <= 0 or args.reaper_interval <= 0:
        raise SystemExit("heartbeat timeout and reaper interval must be positive")

    registry = Registry(args.controller_url, args.heartbeat_timeout)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((args.host, args.port))
        sock.settimeout(min(args.reaper_interval, 1.0))
        print(f"[REGISTRY] Listening on {args.host}:{args.port}; heartbeat timeout={args.heartbeat_timeout}s", flush=True)
        print(f"[REGISTRY] Ryu callback URL: {args.controller_url or '(disabled)'}", flush=True)
        while True:
            try:
                payload, client_address = sock.recvfrom(65535)
                try:
                    message = decode_message(payload)
                    response = handle_message(registry, message)
                except (ValueError, TypeError, KeyError) as exc:
                    response = {"type": ERROR, "status": "BAD_REQUEST", "message": str(exc)}
                try:
                    sock.sendto(encode_message(response), client_address)
                except OSError as exc:
                    print(f"[WARN] Could not send UDP reply to {client_address}: {exc}", flush=True)
            except socket.timeout:
                pass
            except KeyboardInterrupt:
                print("\n[REGISTRY] Stopping", flush=True)
                break
            except OSError as exc:
                print(f"[ERROR] Registry socket error: {exc}", flush=True)
                time.sleep(0.2)
            registry.mark_timeouts()


if __name__ == "__main__":
    main()
