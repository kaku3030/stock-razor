"""Fail-closed, opt-in TickFlow Premium credential ingress helpers.

This module validates a reference only. The caller owns the AWS SDK/CLI read
and must keep the returned secret in memory and process environment only.
"""

from __future__ import annotations

import re


SECRET_ARN = re.compile(
    r"^arn:aws:secretsmanager:ap-northeast-1:888425712426:secret:"
    r"stock-razor/tickflow/premium-[A-Za-z0-9+=,.@_-]{6,}$"
)


def premium_ingress_enabled(value: str | None) -> bool:
    """Return true only for the exact explicit enable value."""
    return value == "true"


def validate_secret_arn(secret_arn: str | None) -> str:
    """Validate the one-purpose Tokyo Premium secret namespace."""
    if not secret_arn or not SECRET_ARN.fullmatch(secret_arn):
        raise ValueError("invalid TickFlow Premium secret reference")
    return secret_arn


def validate_secret_document(document: object) -> str:
    """Extract one API key from a secret document without logging it."""
    if not isinstance(document, dict) or set(document) != {"api_key"}:
        raise ValueError("secret document must contain only api_key")
    value = document.get("api_key")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("secret api_key is missing")
    return value
