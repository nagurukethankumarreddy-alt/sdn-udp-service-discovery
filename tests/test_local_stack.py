"""End-to-end localhost smoke test for registry + service server + client.

Does not require Mininet or Ryu. It validates Member 1's UDP workflow and
heartbeat timeout logic before the team runs the full SDN topology.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PYTHON = sys.executable


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until(predicate, timeout: float, description: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.15)
    raise RuntimeError(f"Timed out waiting for: {description}")


def send_registry(port: int, message: dict, timeout: float = 1.0) -> dict:
    from app.protocol import decode_message, encode_message
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(encode_message(message), ("127.0.0.1", port))
        data, _ = sock.recvfrom(65535)
        return decode_message(data)


def main() -> int:
    registry_port = free_udp_port()
    service_port = free_udp_port()
    if service_port == registry_port:
        service_port = free_udp_port()
    with tempfile.TemporaryDirectory(prefix="sdn-local-smoke-") as temp_dir:
        log_dir = Path(temp_dir)
        registry_log = open(log_dir / "registry.log", "w", encoding="utf-8")
        service_log = open(log_dir / "server.log", "w", encoding="utf-8")
        registry = service = None
        try:
            registry = subprocess.Popen(
                [PYTHON, str(ROOT / "app" / "registry_server.py"),
                 "--host", "127.0.0.1", "--port", str(registry_port),
                 "--controller-url", "", "--heartbeat-timeout", "2.5",
                 "--reaper-interval", "0.15"],
                cwd=str(ROOT), stdout=registry_log, stderr=subprocess.STDOUT,
            )
            time.sleep(0.35)
            if registry.poll() is not None:
                raise RuntimeError("Registry exited during startup; inspect registry.log")

            service = subprocess.Popen(
                [PYTHON, str(ROOT / "app" / "service_server.py"),
                 "--service", "SmokeTest", "--ip", "127.0.0.1", "--port", str(service_port),
                 "--registry-ip", "127.0.0.1", "--registry-port", str(registry_port),
                 "--heartbeat-interval", "0.5"],
                cwd=str(ROOT), stdout=service_log, stderr=subprocess.STDOUT,
            )

            def registered() -> bool:
                try:
                    result = send_registry(registry_port, {"type": "DISCOVER", "service": "SmokeTest"})
                    return result.get("status") == "OK" and len(result.get("servers", [])) == 1
                except (OSError, ValueError):
                    return False

            wait_until(registered, 5, "service registration")
            client_result = subprocess.run(
                [PYTHON, str(ROOT / "app" / "discovery_client.py"),
                 "--service", "SmokeTest", "--message", "smoke-check",
                 "--registry-ip", "127.0.0.1", "--registry-port", str(registry_port),
                 "--timeout", "1.5", "--retries", "2"],
                cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=8,
            )
            print(client_result.stdout)
            if client_result.returncode != 0 or "SERVICE_RESPONSE" not in client_result.stdout or "smoke-check" not in client_result.stdout:
                raise RuntimeError("Client did not receive expected service response")
            print("PASS: registration, discovery, and UDP service request/response")

            service.terminate()
            service.wait(timeout=3)

            def inactive() -> bool:
                try:
                    result = send_registry(registry_port, {"type": "STATUS"})
                    entries = result.get("services", {}).get("SmokeTest", [])
                    return bool(entries) and entries[0].get("status") == "INACTIVE"
                except (OSError, ValueError):
                    return False

            wait_until(inactive, 6, "heartbeat timeout marks service inactive")
            print("PASS: heartbeat timeout marks the service INACTIVE")
            return 0
        except Exception as exc:
            print(f"FAIL: {exc}")
            try:
                registry_log.flush(); service_log.flush()
                print("--- registry log ---")
                print((log_dir / "registry.log").read_text(encoding="utf-8", errors="replace"))
                print("--- service log ---")
                print((log_dir / "server.log").read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
            return 1
        finally:
            for proc in (service, registry):
                if proc is not None and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            registry_log.close()
            service_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
