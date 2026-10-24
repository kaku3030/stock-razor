"""Small systemd notification helper for service readiness and watchdog pings."""

from __future__ import annotations

import os
import socket


def notify_systemd(*fields: str) -> bool:
    """Send validated fields to systemd; return False outside a notified service."""
    if not fields:
        raise ValueError("at least one systemd notification field is required")
    for field in fields:
        if not field or "\n" in field or "\x00" in field or "=" not in field:
            raise ValueError("invalid systemd notification field")

    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\x00" + address[1:]

    payload = "\n".join(fields).encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.connect(address)
        client.sendall(payload)
    return True
