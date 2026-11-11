"""Measure end-to-end discovery + UDP request latency for baseline and SDN modes.

Examples:
  python3 app/benchmark.py --mode baseline --iterations 30
  python3 app/benchmark.py --mode sdn --controller-url http://127.0.0.1:8080 --iterations 30

Writes one CSV row per iteration to results/ and prints aggregate metrics.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import socket
import statistics
import time
from datetime import datetime
from typing import Any, Dict, List
from urllib.error import URLError

from app.protocol import DISCOVER, SERVICE_REQUEST, decode_message, encode_message
from app.selection import controller_select, order_candidates


def udp_exchange(host: str, port: int, message: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(encode_message(message), (host, int(port)))
        payload, _ = sock.recvfrom(65535)
        return decode_message(payload)


def percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description="Baseline vs SDN service-discovery benchmark")
    parser.add_argument("--mode", choices=("baseline", "sdn"), required=True)
    parser.add_argument("--service", default="Weather")
    parser.add_argument("--registry-ip", default="10.0.0.1")
    parser.add_argument("--registry-port", type=int, default=9999)
    parser.add_argument("--controller-url", default="")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=1.5)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if args.iterations < 1 or args.timeout <= 0:
        raise SystemExit("iterations and timeout must be positive")
    if args.mode == "sdn" and not args.controller_url:
        raise SystemExit("--controller-url is required for --mode sdn")

    rows = []
    latencies = []
    successes = 0
    chosen_counts: Dict[str, int] = {}
    total_started = time.perf_counter()

    for iteration in range(1, args.iterations + 1):
        started = time.perf_counter()
        chosen = ""
        status = "ERROR"
        detail = ""
        try:
            discovery = udp_exchange(
                args.registry_ip, args.registry_port,
                {"type": DISCOVER, "service": args.service}, args.timeout
            )
            servers = discovery.get("servers", [])
            if discovery.get("status") != "OK" or not servers:
                raise RuntimeError("no active provider")
            preferred = controller_select(args.controller_url, args.service, args.timeout) if args.mode == "sdn" else None
            candidates = order_candidates(servers, preferred)
            if not candidates:
                raise RuntimeError("no candidate provider")
            # The benchmark records a single transaction per iteration. In SDN
            # mode the controller's selected endpoint is used; otherwise first provider.
            provider = candidates[0]
            chosen = f"{provider['ip']}:{provider['port']}"
            response = udp_exchange(
                provider["ip"], int(provider["port"]),
                {"type": SERVICE_REQUEST, "service": args.service,
                 "message": f"benchmark-{args.mode}-{iteration}"},
                args.timeout,
            )
            if response.get("status") != "OK":
                raise RuntimeError(f"provider returned {response}")
            status = "OK"
            successes += 1
            chosen_counts[chosen] = chosen_counts.get(chosen, 0) + 1
        except (OSError, ValueError, RuntimeError, URLError) as exc:
            detail = str(exc)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if status == "OK":
            latencies.append(elapsed_ms)
        rows.append({
            "iteration": iteration, "mode": args.mode, "service": args.service,
            "provider": chosen, "status": status, "latency_ms": round(elapsed_ms, 3),
            "detail": detail,
        })
        print(f"{iteration:03d}/{args.iterations}: {status:5s} provider={chosen or '-':18s} latency={elapsed_ms:.3f} ms")

    duration = time.perf_counter() - total_started
    output = args.output or os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "results",
        f"benchmark_{args.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print("\n=== BENCHMARK SUMMARY ===")
    print(f"Mode: {args.mode}")
    print(f"Service: {args.service}")
    print(f"Requests: {args.iterations}; successful: {successes}; failed: {args.iterations - successes}")
    print(f"Success rate: {successes / args.iterations * 100.0:.2f}%")
    if latencies:
        print(f"Average latency: {statistics.mean(latencies):.3f} ms")
        print(f"Median latency: {statistics.median(latencies):.3f} ms")
        print(f"P95 latency: {percentile(latencies, 95):.3f} ms")
        print(f"Min / max latency: {min(latencies):.3f} / {max(latencies):.3f} ms")
    print(f"Throughput: {successes / duration:.2f} successful requests/second")
    print(f"Provider distribution: {json.dumps(chosen_counts, sort_keys=True)}")
    print(f"CSV: {os.path.abspath(output)}")
    return 0 if successes == args.iterations else 2


if __name__ == "__main__":
    raise SystemExit(main())
