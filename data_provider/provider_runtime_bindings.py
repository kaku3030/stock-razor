"""Small read-only bridges from observed provider payloads to ProviderEvent.

These bindings do not open connections, subscribe, or infer entitlement.  The
OpenD handler factory only wraps the SDK callback classes already used by the
repository's observation tools; the Eastmoney binding accepts rows returned by
the existing polling paths.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .live_feed_types import ProviderEvent, SemanticStreamKey
from .provider_normalization import normalize_eastmoney_quote, normalize_opend_callback


def _timestamp(raw: Mapping[str, Any], *, default_zone: str, not_after: datetime) -> datetime:
    value = next(
        (raw.get(name) for name in ("provider_timestamp", "time_key", "data_time", "update_time", "timestamp", "f86", "date") if raw.get(name) is not None),
        None,
    )
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise ValueError("provider timestamp must be finite")
        parsed = datetime.fromtimestamp(float(value), timezone.utc)
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("provider timestamp is required")
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(default_zone))
    parsed = parsed.astimezone(timezone.utc)
    observed = not_after.astimezone(timezone.utc)
    if parsed > observed:
        raise ValueError("provider timestamp cannot be in the future")
    return parsed


def _rows(data: Any) -> list[dict[str, Any]]:
    try:
        records = data.to_dict(orient="records")
    except AttributeError:
        records = data if isinstance(data, list) else [data]
    if not isinstance(records, list) or not all(isinstance(row, Mapping) for row in records):
        raise TypeError("provider callback rows must be mappings")
    return [dict(row) for row in records]


class OpenDProviderBinding:
    """Normalize rows delivered by an already-created Futu/OpenD callback."""

    provider_id = "moomoo_opend"

    def __init__(self, *, runtime_instance_id: str, controller_generation: int, sink: Callable[[ProviderEvent], None] | None = None, provider_timezone: str = "America/New_York") -> None:
        self.runtime_instance_id = runtime_instance_id
        self.controller_generation = controller_generation
        self.provider_timezone = provider_timezone
        self._sink = sink

    def register_event_sink(self, sink: Callable[[ProviderEvent], None]) -> None:
        if not callable(sink):
            raise TypeError("event sink must be callable")
        self._sink = sink

    def emit_rows(self, data: Any, *, key: SemanticStreamKey, observed_at_utc: datetime, observed_at_monotonic: float | None = None) -> list[ProviderEvent]:
        if key.provider_id != self.provider_id or key.market.upper() != "US":
            raise ValueError("OpenD binding received a non-US OpenD stream key")
        events: list[ProviderEvent] = []
        for raw in _rows(data):
            symbol = str(raw.get("code") or raw.get("symbol") or "").strip().upper()
            if symbol != key.symbol.upper():
                raise ValueError("OpenD row/provider identity mismatch")
            row = dict(raw)
            row["provider_timestamp"] = _timestamp(
                row, default_zone=self.provider_timezone, not_after=observed_at_utc
            )
            row["observed_at_monotonic"] = time.monotonic() if observed_at_monotonic is None else observed_at_monotonic
            event = normalize_opend_callback(raw=row, runtime_instance_id=self.runtime_instance_id, controller_generation=self.controller_generation, observed_at_utc=observed_at_utc, semantic_stream_key=key)
            if (
                key.stream_type.upper() == "QUOTE"
                and row.get("sequence") is None
                and row.get("tie_breaker") is None
                and row.get("progress_identity") is None
            ):
                event = replace(event, progress_identity_candidate=None)
            events.append(event)
            if self._sink is not None:
                self._sink(event)
        return events

    def handler_factories(self, futu_module: Any, *, key: SemanticStreamKey, observed_at: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> tuple[Any, Any]:
        binding = self

        class QuoteHandler(futu_module.StockQuoteHandlerBase):
            def on_recv_rsp(self, rsp_pb: Any) -> tuple[Any, Any]:
                ret_code, data = super().on_recv_rsp(rsp_pb)
                if ret_code == futu_module.RET_OK:
                    binding.emit_rows(data, key=key, observed_at_utc=observed_at())
                return ret_code, data

        class KlineHandler(futu_module.CurKlineHandlerBase):
            def on_recv_rsp(self, rsp_pb: Any) -> tuple[Any, Any]:
                ret_code, data = super().on_recv_rsp(rsp_pb)
                if ret_code == futu_module.RET_OK:
                    binding.emit_rows(data, key=key, observed_at_utc=observed_at())
                return ret_code, data

        return QuoteHandler(), KlineHandler()


class EastmoneyProviderBinding:
    """Normalize rows/events returned by existing Eastmoney paths."""

    provider_id = "eastmoney"

    def __init__(self, *, runtime_instance_id: str, controller_generation: int, sink: Callable[[ProviderEvent], None] | None = None, provider_timezone: str = "Asia/Shanghai") -> None:
        self.runtime_instance_id = runtime_instance_id
        self.controller_generation = controller_generation
        self.provider_timezone = provider_timezone
        self._sink = sink

    def register_event_sink(self, sink: Callable[[ProviderEvent], None]) -> None:
        if not callable(sink):
            raise TypeError("event sink must be callable")
        self._sink = sink

    def emit_row(self, raw: Mapping[str, Any], *, key: SemanticStreamKey, observed_at_utc: datetime, observed_at_monotonic: float | None = None) -> ProviderEvent:
        if key.provider_id != self.provider_id or key.market.upper() != "CN":
            raise ValueError("Eastmoney binding received a non-CN Eastmoney stream key")
        row = dict(raw)
        symbol = str(row.get("symbol") or row.get("code") or row.get("f57") or "").strip()
        if not symbol or symbol not in {key.symbol, key.symbol.removeprefix("CN.")}:  # preserve provider identity, reject cross-symbol rows
            raise ValueError("Eastmoney row/provider identity mismatch")
        row["provider_timestamp"] = _timestamp(
            row, default_zone=self.provider_timezone, not_after=observed_at_utc
        )
        row["observed_at_monotonic"] = time.monotonic() if observed_at_monotonic is None else observed_at_monotonic
        event = normalize_eastmoney_quote(raw=row, runtime_instance_id=self.runtime_instance_id, controller_generation=self.controller_generation, observed_at_utc=observed_at_utc, semantic_stream_key=key)
        if self._sink is not None:
            self._sink(event)
        return event
