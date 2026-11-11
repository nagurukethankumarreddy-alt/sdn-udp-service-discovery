"""End-to-end local test for dashboard-managed provider lifecycle.

No Mininet or Ryu is required. It launches a UDP registry, a provider agent,
and the dashboard on free localhost ports, then adds/discovers/uses/stops a provider
through the same HTTP API used by the browser UI.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def free_port(sock_type):
    with socket.socket(socket.AF_INET, sock_type) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def call_json(url, payload=None, timeout=2.5):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def wait_for(url, timeout=6.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            return call_json(url, timeout=0.4)
        except Exception as exc:
            last = exc
            time.sleep(0.1)
    raise RuntimeError(f"service did not become ready at {url}: {last}")


def main():
    registry_port = free_port(socket.SOCK_DGRAM)
    agent_port = free_port(socket.SOCK_STREAM)
    dashboard_port = free_port(socket.SOCK_STREAM)
    service_port = free_port(socket.SOCK_DGRAM)
    processes = []
    logs = []
    temp = tempfile.TemporaryDirectory(prefix="cn_pro_dashboard_test_")

    def spawn(label, args):
        log_path = Path(temp.name) / f"{label}.log"
        handle = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            args, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        handle.close()
        processes.append(proc)
        logs.append((label, log_path))
        return proc

    try:
        spawn("registry", [
            PYTHON, str(ROOT / "app" / "registry_server.py"),
            "--host", "127.0.0.1", "--port", str(registry_port),
            "--controller-url", "", "--heartbeat-timeout", "5",
            "--reaper-interval", "0.2",
        ])
        time.sleep(0.2)
        spawn("agent", [
            PYTHON, str(ROOT / "app" / "provider_agent.py"),
            "--node-name", "testnode", "--node-ip", "127.0.0.1",
            "--registry-ip", "127.0.0.1", "--registry-port", str(registry_port),
            "--project-root", str(ROOT), "--host", "127.0.0.1",
            "--port", str(agent_port),
        ])
        wait_for(f"http://127.0.0.1:{agent_port}/health")

        spawn("dashboard", [
            PYTHON, "-m", "app.dashboard",
            "--host", "127.0.0.1", "--port", str(dashboard_port),
            "--registry-ip", "127.0.0.1", "--registry-port", str(registry_port),
            "--controller-url", "",
            "--agent-port", str(agent_port),
            "--provider-hosts", "testnode=127.0.0.1",
            "--timeout", "1.0",
        ])
        base = f"http://127.0.0.1:{dashboard_port}"
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                with urlopen(base + "/", timeout=0.5) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("dashboard did not start")

        started = call_json(base + "/api/provider/start", {
            "host": "testnode", "service": "DashboardLifecycleTest",
            "port": service_port, "response_delay_ms": 0, "drop_every": 0,
        })
        if started.get("status") != "STARTED":
            raise RuntimeError(f"provider did not start: {started}")
        print("PASS: dashboard starts a provider on the selected host")

        discovered = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                discovered = call_json(base + "/api/discover", {
                    "service": "DashboardLifecycleTest",
                })
                if discovered.get("providers"):
                    break
            except Exception:
                pass
            time.sleep(0.1)
        if not discovered or not discovered.get("providers"):
            raise RuntimeError("dashboard could not discover the provider it started")
        print("PASS: dashboard discovers the newly registered provider")

        result = call_json(base + "/api/request", {
            "service": "DashboardLifecycleTest",
            "message": "dashboard-ui-test",
            "selection_mode": "registry",
        })
        if result.get("response", {}).get("status") != "OK":
            raise RuntimeError(f"service request failed: {result}")
        print("PASS: dashboard sends UDP request and displays provider response")

        stopped = call_json(base + "/api/provider/stop", {
            "host": "testnode", "port": service_port,
        })
        if stopped.get("status") != "STOPPED":
            raise RuntimeError(f"provider did not stop cleanly: {stopped}")
        print("PASS: dashboard stops provider gracefully")

        status = call_json(base + "/api/status")
        records = status.get("services", {}).get("DashboardLifecycleTest", [])
        if not records or records[0].get("status") != "INACTIVE":
            raise RuntimeError(f"provider did not become inactive in registry: {status}")
        print("PASS: registry reports the stopped provider as INACTIVE")
        print("PASS: dashboard provider-management lifecycle")
        return 0
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGINT)
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
        temp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
