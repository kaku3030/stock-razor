"""Compatibility export for the shared stdlib-only systemd primitive."""

from src.utils.systemd_notify import notify_systemd

__all__ = ["notify_systemd"]
