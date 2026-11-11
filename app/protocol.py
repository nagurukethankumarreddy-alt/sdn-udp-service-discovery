"""Shared UDP message format for the service-discovery project.

Messages are UTF-8 JSON objects. Each message has a required `type` field.
"""
from __future__ import annotations

import json
from typing import Any, Dict

REGISTER = "REGISTER"
HEARTBEAT = "HEARTBEAT"
UNREGISTER = "UNREGISTER"
DISCOVER = "DISCOVER"
DISCOVER_RESPONSE = "DISCOVER_RESPONSE"
SERVICE_REQUEST = "SERVICE_REQUEST"
SERVICE_RESPONSE = "SERVICE_RESPONSE"
ACK = "ACK"
ERROR = "ERROR"

DEFAULT_REGISTRY_PORT = 9999
DEFAULT_SERVICE_PORT = 5001


def encode_message(message: Dict[str, Any]) -> bytes:
    """Serialize a message dictionary to UTF-8 JSON bytes."""
    if not isinstance(message, dict):
        raise TypeError("message must be a dictionary")
    if not message.get("type"):
        raise ValueError("message must have a non-empty 'type' field")
    return json.dumps(message, separators=(",", ":")).encode("utf-8")


def decode_message(payload: bytes) -> Dict[str, Any]:
    """Decode UTF-8 JSON bytes and ensure the result is an object with type."""
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON message: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError("message JSON must be an object")
    if not isinstance(decoded.get("type"), str) or not decoded["type"]:
        raise ValueError("message must have a non-empty string 'type' field")
    return decoded


def require_fields(message: Dict[str, Any], *fields: str) -> None:
    """Raise ValueError if any required field is missing or empty."""
    missing = [field for field in fields if field not in message or message[field] in (None, "")]
    if missing:
        raise ValueError("missing required field(s): " + ", ".join(missing))
