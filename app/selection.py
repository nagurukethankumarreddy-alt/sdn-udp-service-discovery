"""Helpers for consulting the Ryu controller and ordering provider candidates."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from urllib.request import urlopen


def controller_select(base_url: str, service: str, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
    """Ask Ryu for its next active provider; return None if Ryu is unavailable."""
    if not base_url:
        return None
    url = base_url.rstrip("/") + "/service/select/" + quote(service, safe="")
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("status") == "OK" and isinstance(payload.get("server"), dict):
            return payload["server"]
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return None


def order_candidates(servers: List[Dict[str, Any]],
                     preferred: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Place the controller-selected endpoint first, then retain other active candidates."""
    ordered = list(servers)
    if not preferred:
        return ordered
    key = (str(preferred.get("ip")), int(preferred.get("port", 0)))
    for index, server in enumerate(ordered):
        if (str(server.get("ip")), int(server.get("port", 0))) == key:
            return [ordered[index]] + ordered[:index] + ordered[index + 1:]
    return ordered
