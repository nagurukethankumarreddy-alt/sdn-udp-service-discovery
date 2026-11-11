"""Small HTTP client used by Member 3 to notify Ryu of service state changes."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def notify_controller(
    base_url: str,
    record: Dict[str, Any],
    active: bool,
    timeout: float = 1.0,
    retries: int = 2,
) -> Tuple[bool, str]:
    """Notify Ryu with POST /service/register or /service/remove.

    Returns (success, explanatory_message). An empty base_url deliberately
    disables the webhook, which is useful for isolated localhost unit tests.
    """
    if not base_url:
        return True, "controller notification disabled"

    endpoint = "/service/register" if active else "/service/remove"
    url = base_url.rstrip("/") + endpoint
    payload = {
        "service": str(record.get("service", "unknown")),
        "ip": str(record["ip"]),
        "port": int(record.get("port", 0)),
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    last_error = "unknown controller error"
    for attempt in range(max(1, retries + 1)):
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                if not (200 <= response.status < 300):
                    last_error = f"HTTP {response.status}: {body}"
                else:
                    return True, body or f"HTTP {response.status}"
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
        except (URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        if attempt < max(1, retries + 1) - 1:
            time.sleep(0.15 * (attempt + 1))
    return False, last_error
