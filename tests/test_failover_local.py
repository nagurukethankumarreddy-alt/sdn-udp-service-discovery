"""Local integration test: if first provider drops packets, client tries the next provider."""
from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def registry_request(port, message, timeout=0.4):
    from app.protocol import decode_message, encode_message
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(encode_message(message), ("127.0.0.1", port))
        data, _ = sock.recvfrom(65535)
        return decode_message(data)


def main():
    registry_port = free_port()
    p1, p2 = sorted((free_port(), free_port()))
    while len({registry_port, p1, p2}) != 3:
        p1, p2 = sorted((free_port(), free_port()))
    service = "FailoverTest"
    processes = []
    try:
        registry = subprocess.Popen(
            [PYTHON, str(ROOT / "app" / "registry_server.py"),
             "--host", "127.0.0.1", "--port", str(registry_port),
             "--controller-url", "", "--heartbeat-timeout", "2.5",
             "--reaper-interval", "0.1"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        processes.append(registry)
        time.sleep(0.25)
        dropping = subprocess.Popen(
            [PYTHON, str(ROOT / "app" / "service_server.py"),
             "--service", service, "--ip", "127.0.0.1", "--port", str(p1),
             "--registry-ip", "127.0.0.1", "--registry-port", str(registry_port),
             "--heartbeat-interval", "0.5", "--drop-every", "1"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        processes.append(dropping)
        healthy = subprocess.Popen(
            [PYTHON, str(ROOT / "app" / "service_server.py"),
             "--service", service, "--ip", "127.0.0.1", "--port", str(p2),
             "--registry-ip", "127.0.0.1", "--registry-port", str(registry_port),
             "--heartbeat-interval", "0.5"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        processes.append(healthy)

        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                response = registry_request(
                    registry_port, {"type": "DISCOVER", "service": service}
                )
                if len(response.get("servers", [])) == 2:
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("both providers did not register")

        result = subprocess.run(
            [PYTHON, str(ROOT / "app" / "discovery_client.py"),
             "--service", service, "--message", "check-fallback",
             "--registry-ip", "127.0.0.1", "--registry-port", str(registry_port),
             "--timeout", "0.35", "--retries", "1"],
            cwd=ROOT, capture_output=True, text=True, timeout=8,
        )
        print(result.stdout)
        if result.returncode != 0:
            raise RuntimeError("client did not recover using second provider")
        if f"Provider succeeded: 127.0.0.1:{p2}" not in result.stdout:
            raise RuntimeError("client did not use the expected healthy fallback provider")
        print("PASS: client falls back when the first provider drops its UDP response")
        return 0
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
