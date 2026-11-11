"""Member 1: UDP service server with registration and heartbeat messages."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path
import socket
import signal
import threading
import time
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.protocol import (
    ACK, HEARTBEAT, REGISTER, SERVICE_REQUEST, SERVICE_RESPONSE, UNREGISTER,
    decode_message, encode_message,
)


def send_registry_message(registry_ip: str, registry_port: int, message: Dict[str, Any], timeout: float = 1.0) -> Optional[Dict[str, Any]]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(encode_message(message), (registry_ip, registry_port))
            payload, _ = sock.recvfrom(65535)
            return decode_message(payload)
    except (OSError, ValueError) as exc:
        print(f"[SERVER] Registry message failed: {exc}", flush=True)
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="UDP service provider")
    parser.add_argument("--service", default="Weather")
    parser.add_argument("--ip", required=True, help="Advertised service IP; use this host's Mininet IP")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--registry-ip", default="10.0.0.1")
    parser.add_argument("--registry-port", type=int, default=9999)
    parser.add_argument("--heartbeat-interval", type=float, default=2.0)
    parser.add_argument("--workers", type=int, default=8, help="maximum concurrent request workers")
    parser.add_argument("--response-delay-ms", type=int, default=0, help="optional simulated processing delay")
    parser.add_argument("--drop-every", type=int, default=0, help="drop every Nth request; 0 disables packet-loss simulation")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("service port must be in range 1..65535")
    if args.heartbeat_interval <= 0:
        raise SystemExit("heartbeat interval must be positive")
    if args.workers < 1 or args.response_delay_ms < 0 or args.drop_every < 0:
        raise SystemExit("workers must be >= 1; delay and drop-every must be >= 0")

    record = {"service": args.service, "ip": args.ip, "port": args.port}
    stop_event = threading.Event()

    def _shutdown_signal(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _shutdown_signal)

    # Bind first. If the service port is unavailable, do not advertise a server
    # that cannot receive traffic.
    try:
        service_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        service_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        service_sock.bind(("0.0.0.0", args.port))
        service_sock.settimeout(1.0)
    except OSError:
        try:
            service_sock.close()
        except (NameError, OSError):
            pass
        raise

    response = send_registry_message(
        args.registry_ip, args.registry_port,
        {"type": REGISTER, **record}
    )
    if response and response.get("status") == "OK":
        print(f"[SERVER] Registered {args.service} at {args.ip}:{args.port}", flush=True)
    else:
        print("[SERVER] Initial registration did not receive an OK response; heartbeats will retry registration.", flush=True)

    def heartbeat_loop() -> None:
        while not stop_event.wait(args.heartbeat_interval):
            response = send_registry_message(
                args.registry_ip, args.registry_port,
                {"type": HEARTBEAT, **record}
            )
            if response and response.get("status") == "OK":
                print("[SERVER] Heartbeat ACK", flush=True)

    thread = threading.Thread(target=heartbeat_loop, name="heartbeat", daemon=True)
    thread.start()
    print(
        f"[SERVER] {args.service} listening on 0.0.0.0:{args.port}; advertised IP={args.ip}; "
        f"workers={args.workers}; delay_ms={args.response_delay_ms}; drop_every={args.drop_every}",
        flush=True,
    )
    request_counter = 0
    counter_lock = threading.Lock()

    def process_request(payload: bytes, client_address) -> None:
        nonlocal request_counter
        try:
            message = decode_message(payload)
            if message.get("type") != SERVICE_REQUEST:
                reply = {"type": "ERROR", "status": "UNSUPPORTED", "message": "expected SERVICE_REQUEST"}
            else:
                with counter_lock:
                    request_counter += 1
                    sequence = request_counter
                request_text = str(message.get("message", "hello"))
                print(f"[SERVER] Request #{sequence} from {client_address}: {request_text}", flush=True)
                if args.drop_every and sequence % args.drop_every == 0:
                    print(f"[SERVER] Simulated packet loss for request #{sequence}", flush=True)
                    return
                if args.response_delay_ms:
                    time.sleep(args.response_delay_ms / 1000.0)
                reply = {
                    "type": SERVICE_RESPONSE,
                    "status": "OK",
                    "service": args.service,
                    "server_ip": args.ip,
                    "server_port": args.port,
                    "reply": f"{args.service} response from {args.ip}:{args.port}: received '{request_text}'",
                    "request_number": sequence,
                }
            service_sock.sendto(encode_message(reply), client_address)
        except (ValueError, TypeError) as exc:
            try:
                service_sock.sendto(
                    encode_message({"type": "ERROR", "status": "BAD_REQUEST", "message": str(exc)}),
                    client_address,
                )
            except OSError:
                pass
        except OSError as exc:
            print(f"[SERVER] Could not send response to {client_address}: {exc}", flush=True)

    pool = ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix=f"{args.service}-worker")
    try:
        while True:
            try:
                payload, client_address = service_sock.recvfrom(65535)
            except socket.timeout:
                continue
            pool.submit(process_request, payload, client_address)
    except KeyboardInterrupt:
        print("\n[SERVER] Stopping", flush=True)
    finally:
        stop_event.set()
        pool.shutdown(wait=False, cancel_futures=True)
        service_sock.close()
        # Best-effort graceful unregister. Use hard termination only when
        # explicitly demonstrating heartbeat timeout detection.
        send_registry_message(
            args.registry_ip, args.registry_port,
            {"type": UNREGISTER, **record}, timeout=0.5
        )


if __name__ == "__main__":
    main()
