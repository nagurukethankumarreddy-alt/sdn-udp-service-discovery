"""Member 1: discover a service over UDP, then send a request to a provider."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import socket
from typing import Any, Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.protocol import DISCOVER, SERVICE_REQUEST, decode_message, encode_message
from app.selection import controller_select, order_candidates


def request_udp(address: Tuple[str, int], message: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(encode_message(message), address)
        payload, remote = sock.recvfrom(65535)
        response = decode_message(payload)
        print(f"[CLIENT] Reply from {remote[0]}:{remote[1]}")
        return response


def main() -> None:
    parser = argparse.ArgumentParser(description="UDP service discovery client")
    parser.add_argument("--service", default="Weather")
    parser.add_argument("--message", default="Hello from the discovery client")
    parser.add_argument("--registry-ip", default="10.0.0.1")
    parser.add_argument("--registry-port", type=int, default=9999)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--controller-url", default="", help="Optional Ryu REST URL, e.g. http://10.0.0.254:8080")
    args = parser.parse_args()

    response = None
    for attempt in range(max(1, args.retries)):
        try:
            response = request_udp(
                (args.registry_ip, args.registry_port),
                {"type": DISCOVER, "service": args.service},
                args.timeout,
            )
            break
        except (OSError, ValueError) as exc:
            print(f"[CLIENT] Discovery attempt {attempt + 1} failed: {exc}", flush=True)
    if not response:
        raise SystemExit("Discovery failed; no response from registry")
    if response.get("status") != "OK" or not response.get("servers"):
        print(f"[CLIENT] Service not found: {response.get('message', response)}")
        raise SystemExit(2)

    servers = response["servers"]
    print(f"[CLIENT] Discovered {len(servers)} active server(s) for {args.service}")
    for i, server in enumerate(servers, start=1):
        print(f"  {i}. {server['ip']}:{server['port']} ({server.get('status', 'ACTIVE')})")

    # Ask the SDN controller to choose an active provider (round-robin).
    # Without a controller URL, use the registry's first active provider as the baseline.
    preferred = controller_select(args.controller_url, args.service, timeout=args.timeout)
    candidates = order_candidates(servers, preferred)
    if preferred:
        print(f"[CLIENT] SDN controller selected {preferred['ip']}:{preferred['port']}")
    else:
        print("[CLIENT] Using registry-first selection (baseline/fallback)")

    service_request = {"type": SERVICE_REQUEST, "service": args.service, "message": args.message}
    service_response = None
    errors = []
    for server in candidates:
        endpoint = (server["ip"], int(server["port"]))
        try:
            print(f"[CLIENT] Trying provider {endpoint[0]}:{endpoint[1]}")
            service_response = request_udp(endpoint, service_request, args.timeout)
            print(f"[CLIENT] Provider succeeded: {endpoint[0]}:{endpoint[1]}")
            break
        except (OSError, ValueError) as exc:
            errors.append(f"{endpoint[0]}:{endpoint[1]}: {exc}")
            print(f"[CLIENT] Provider failed; trying next active provider: {exc}", flush=True)
    if service_response is None:
        raise SystemExit("All discovered providers failed: " + " | ".join(errors))
    print("[CLIENT] Service response:")
    print(service_response)


if __name__ == "__main__":
    main()
