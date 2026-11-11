"""HTTP management agent for UDP service providers inside a Mininet host.

The dashboard calls this agent to launch and stop real service_server.py
processes in the selected Mininet host namespace.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict


class ProviderManager:
    def __init__(self, node_name: str, node_ip: str, registry_ip: str,
                 registry_port: int, project_root: str):
        self.node_name = node_name
        self.node_ip = node_ip
        self.registry_ip = registry_ip
        self.registry_port = registry_port
        self.project_root = Path(project_root).resolve()
        self.service_script = self.project_root / "app" / "service_server.py"
        if not self.service_script.is_file():
            raise FileNotFoundError(f"service provider script not found: {self.service_script}")
        self._lock = threading.RLock()
        self._processes: Dict[int, Dict[str, Any]] = {}

    def list_servers(self):
        with self._lock:
            items = []
            for port, item in list(self._processes.items()):
                process = item["process"]
                if process.poll() is not None:
                    item["status"] = "STOPPED"
                else:
                    item["status"] = "RUNNING"
                items.append({
                    "host": self.node_name,
                    "ip": self.node_ip,
                    "service": item["service"],
                    "port": port,
                    "pid": process.pid,
                    "status": item["status"],
                    "started_at": item["started_at"],
                })
            return items

    def start(self, data: Dict[str, Any]):
        service = str(data.get("service", "")).strip()
        if not service or len(service) > 64 or any(ord(ch) < 32 for ch in service):
            raise ValueError("service name must contain 1–64 printable characters")
        port = int(data.get("port", 0))
        if not 1 <= port <= 65535 or port in (self.registry_port, 8765):
            raise ValueError("choose a UDP service port from 1 to 65535, excluding registry/agent ports")
        delay = int(data.get("response_delay_ms", 0))
        drop_every = int(data.get("drop_every", 0))
        workers = int(data.get("workers", 8))
        if delay < 0 or drop_every < 0 or not 1 <= workers <= 128:
            raise ValueError("delay/drop must be non-negative and workers must be 1–128")

        with self._lock:
            previous = self._processes.get(port)
            if previous and previous["process"].poll() is None:
                raise ValueError(f"UDP port {port} is already running on {self.node_name}")
            log_path = f"/tmp/cn_pro_{self.node_name}_{port}.log"
            log_handle = open(log_path, "ab", buffering=0)
            command = [
                sys.executable, str(self.service_script),
                "--service", service,
                "--ip", self.node_ip,
                "--port", str(port),
                "--registry-ip", self.registry_ip,
                "--registry-port", str(self.registry_port),
                "--workers", str(workers),
                "--response-delay-ms", str(delay),
                "--drop-every", str(drop_every),
            ]
            try:
                process = subprocess.Popen(
                    command, cwd=str(self.project_root),
                    stdin=subprocess.DEVNULL, stdout=log_handle, stderr=subprocess.STDOUT,
                    close_fds=True,
                )
            except Exception:
                log_handle.close()
                raise
            # Parent agent may exit while provider remains active; process has its own
            # stdout descriptor and does not need the parent's Python handle.
            log_handle.close()
            self._processes[port] = {
                "service": service, "process": process, "log": log_path,
                "started_at": time.time(), "status": "STARTING",
            }

        registration_seen = False
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            code = process.poll()
            if code is not None:
                with self._lock:
                    self._processes[port]["status"] = "FAILED"
                try:
                    tail = Path(log_path).read_text(errors="replace")[-1800:]
                except OSError:
                    tail = ""
                raise RuntimeError(f"provider exited during startup (code {code}). Log: {tail}")
            try:
                registration_seen = "[SERVER] Registered " in Path(log_path).read_text(errors="replace")
            except OSError:
                pass
            if registration_seen:
                break
            time.sleep(0.1)
        return {
            "status": "STARTED", "registered": registration_seen,
            "host": self.node_name, "service": service,
            "ip": self.node_ip, "port": port, "pid": process.pid, "log": log_path,
        }

    def stop(self, port: int):
        port = int(port)
        with self._lock:
            item = self._processes.get(port)
            if not item:
                raise KeyError(f"port {port} is not managed by this agent")
            process = item["process"]
            if process.poll() is None:
                # SIGINT lets service_server.py run its graceful UNREGISTER path.
                process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        with self._lock:
            item["status"] = "STOPPED"
        return {
            "status": "STOPPED", "host": self.node_name, "service": item["service"],
            "ip": self.node_ip, "port": port,
        }


def build_handler(manager: ProviderManager):
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, status: int, payload: Dict[str, Any]):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length > 8192:
                raise ValueError("request body too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def do_GET(self):
            if self.path == "/health":
                self._respond(200, {
                    "status": "OK", "host": manager.node_name,
                    "ip": manager.node_ip, "role": "provider-agent",
                })
            elif self.path == "/servers":
                self._respond(200, {"servers": manager.list_servers()})
            else:
                self._respond(404, {"error": "not found"})

        def do_POST(self):
            try:
                data = self._read_json()
                if self.path == "/start":
                    self._respond(201, manager.start(data))
                elif self.path == "/stop":
                    self._respond(200, manager.stop(int(data.get("port", 0))))
                else:
                    self._respond(404, {"error": "not found"})
            except KeyError as exc:
                self._respond(404, {"error": str(exc)})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._respond(400, {"error": str(exc)})
            except Exception as exc:
                self._respond(500, {"error": str(exc)})

        def log_message(self, fmt, *args):
            print(f"[AGENT {manager.node_name}] " + fmt % args, flush=True)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Mininet provider management agent")
    parser.add_argument("--node-name", required=True)
    parser.add_argument("--node-ip", required=True)
    parser.add_argument("--registry-ip", default="10.0.0.1")
    parser.add_argument("--registry-port", type=int, default=9999)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    manager = ProviderManager(
        args.node_name, args.node_ip, args.registry_ip, args.registry_port, args.project_root
    )
    server = ThreadingHTTPServer((args.host, args.port), build_handler(manager))
    print(
        f"[AGENT] {args.node_name} provider agent at {args.node_ip}:{args.port}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        # Stop all child providers when the topology/agent shuts down.
        for item in manager.list_servers():
            if item["status"] == "RUNNING":
                try:
                    manager.stop(item["port"])
                except Exception:
                    pass


if __name__ == "__main__":
    main()
