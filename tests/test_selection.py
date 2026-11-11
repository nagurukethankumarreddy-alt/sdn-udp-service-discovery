"""Unit tests for Ryu-assisted provider ordering."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.selection import order_candidates


def main():
    servers = [
        {"ip": "10.0.0.3", "port": 5001},
        {"ip": "10.0.0.4", "port": 5002},
    ]
    assert order_candidates(servers, None) == servers
    preferred = {"ip": "10.0.0.4", "port": 5002}
    assert order_candidates(servers, preferred) == [servers[1], servers[0]]
    assert order_candidates(servers, {"ip": "10.0.0.99", "port": 99}) == servers
    print("PASS: controller preference is placed first and fallback providers are retained")


if __name__ == "__main__":
    main()
