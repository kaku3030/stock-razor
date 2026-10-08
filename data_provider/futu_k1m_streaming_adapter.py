# -*- coding: utf-8 -*-
"""Minimal Futu/OpenD K_1M streaming adapter.

This slice transports provider evidence only. It deliberately does not claim
REALTIME delivery, bar closure, or LIVE qualification.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from .live_feed_types import (
    DeliveryMode,
    ProviderEvent,
    ProviderEventKind,
    SemanticStreamKey,
    freeze_normalized_payload,
)


OPEND_SYNC_CONTEXT_CONNECTED_EVIDENCE = "OPEND_SYNC_CONTEXT_CONSTRUCTION_RETURNED"


class FutuK1MStreamingAdapter:
    """OpenD K_1M push adapter for the provider-neutral Live Feed boundary."""

    def __init__(
        self,
        quote_context: object,
        futu_module: object,
        *,
        runtime_instance_id: str,
        controller_generation: Callable[[], int],
        now_utc: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
        transport_connected_evidence: str | None = None,
    ) -> None:
        self._ctx = quote_context
        self._ft = futu_module
        self._runtime_instance_id = runtime_instance_id
        self._controller_generation = controller_generation
        self._now_utc = now_utc
        self._monotonic = monotonic
        supplied_transport_evidence = (
            str(transport_connected_evidence).strip() if transport_connected_evidence else None
        )
        if supplied_transport_evidence not in (None, OPEND_SYNC_CONTEXT_CONNECTED_EVIDENCE):
            raise ValueError("unsupported transport connected evidence")
        self._transport_connected_evidence = supplied_transport_evidence
        self._transport_evidence_emitted = False
        self._context_id = uuid.uuid4().hex
        self._sink: Callable[[ProviderEvent], None] | None = None
        self._handler = None
        self._started = False
        self._handler_callback_count = 0
        self._row_count = 0
        self._sink_emit_count = 0
        self._callback_latency_ms_last: float | None = None
        self._callback_latency_ms_max: float | None = None
        self._callback_latency_ms_sum = 0.0
        self._callback_latency_sample_count = 0
        self._last_subscribe_result = None

    def register_event_sink(self, sink: Callable[[ProviderEvent], None]) -> None:
        if not callable(sink):
            raise TypeError("event sink must be callable")
        self._sink = sink

    def start(self) -> None:
        if self._started:
            return
        if self._sink is None:
            raise RuntimeError("event sink must be registered before start")
        adapter = self

        class KlineHandler(self._ft.CurKlineHandlerBase):
            def on_recv_rsp(self, rsp_pb):
                callback_started = adapter._monotonic()
                adapter._handler_callback_count += 1
                try:
                    ret, data = super().on_recv_rsp(rsp_pb)
                    if ret != adapter._ft.RET_OK:
                        adapter._emit_error(str(data))
                        return ret, data
                    if not hasattr(data, "to_dict"):
                        adapter._emit_error("K_1M payload is not tabular")
                        return ret, data
                    for row in data.to_dict("records"):
                        adapter._row_count += 1
                        adapter._emit_row(row)
                    return ret, data
                finally:
                    adapter._record_callback_latency(callback_started)

        handler = KlineHandler()
        # Retain the handler independently of the provider context.  Some
        # SDK/context implementations only retain the registered callback for
        # dispatch, so the adapter owns its lifecycle explicitly.
        self._handler = handler
        self._started = True
        try:
            registration_result = self._ctx.set_handler(handler)
            if registration_result not in (None, self._ft.RET_OK):
                raise RuntimeError("OpenD K_1M handler registration rejected: " + str(registration_result)[:300])
        except Exception:
            self._started = False
            self._handler = None
            raise
        if self._transport_connected_evidence and not self._transport_evidence_emitted:
            self._emit(
                ProviderEvent(
                    runtime_instance_id=self._runtime_instance_id,
                    provider_id="futu",
                    controller_generation=int(self._controller_generation()),
                    observed_at_utc=self._now_utc(),
                    observed_at_monotonic=self._monotonic(),
                    event_kind=ProviderEventKind.CONNECTED,
                    provider_context_id=self._context_id,
                    delivery_mode=DeliveryMode.UNKNOWN,
                    provenance="CALLER_VERIFIED_TRANSPORT",
                    diagnostic_fields=freeze_normalized_payload(
                        {
                            "transport_evidence": self._transport_connected_evidence,
                            "delivery_qualification": "UNPROVEN",
                        }
                    ),
                )
            )
            self._transport_evidence_emitted = True

    def stop(self) -> None:
        # Context ownership belongs to the runtime, not this adapter. Avoid
        # closing a shared OpenQuoteContext here.
        self._started = False

    @staticmethod
    def _validate_key(key: SemanticStreamKey) -> None:
        if key.provider_id != "futu" or key.market != "us":
            raise ValueError("Futu K_1M adapter requires provider=futu, market=us")
        if key.stream_type != "K_1M" or key.timeframe != "1m":
            raise ValueError("only K_1M / 1m is supported in this slice")
        if not key.symbol.startswith("US."):
            raise ValueError("US OpenD symbols must use canonical US.* form")

    def subscribe_stream(self, key: SemanticStreamKey) -> None:
        self.subscribe_streams((key,))

    def subscribe_streams(self, keys) -> None:
        unique = tuple(dict.fromkeys(keys))
        if not unique:
            raise ValueError("at least one K_1M stream is required")
        for key in unique:
            self._validate_key(key)
        ret, data = self._ctx.subscribe(
            [key.symbol for key in unique],
            [self._ft.SubType.K_1M],
            subscribe_push=True,
        )
        self._last_subscribe_result = {"ret": ret, "data": str(data)[:300]}
        if self._transport_connected_evidence:
            accepted = ret == self._ft.RET_OK
            for key in unique:
                self._emit(
                    ProviderEvent(
                        runtime_instance_id=self._runtime_instance_id,
                        provider_id="futu",
                        controller_generation=int(self._controller_generation()),
                        observed_at_utc=self._now_utc(),
                        observed_at_monotonic=self._monotonic(),
                        event_kind=ProviderEventKind.SUBSCRIPTION_RESULT,
                        semantic_stream_key=key,
                        provider_context_id=self._context_id,
                        payload=freeze_normalized_payload({"accepted": accepted}),
                        delivery_mode=DeliveryMode.UNKNOWN,
                        provenance="OPEND_SUBSCRIBE_RETURN",
                        diagnostic_fields=freeze_normalized_payload(
                            {
                                "administrative_only": True,
                                "subscribe_ret": ret,
                                "detail": str(data)[:300],
                            }
                        ),
                    )
                )
        if ret != self._ft.RET_OK:
            raise RuntimeError("OpenD K_1M subscribe rejected: " + str(data)[:300])

    def diagnostics(self) -> dict:
        mean_latency = (
            self._callback_latency_ms_sum / self._callback_latency_sample_count
            if self._callback_latency_sample_count
            else None
        )
        return {
            "handler_callback_count": self._handler_callback_count,
            "row_count": self._row_count,
            "sink_emit_count": self._sink_emit_count,
            "provider_callback_latency_ms_last": self._callback_latency_ms_last,
            "provider_callback_latency_ms_max": self._callback_latency_ms_max,
            "provider_callback_latency_ms_mean": (
                round(mean_latency, 3) if mean_latency is not None else None
            ),
            "provider_callback_latency_sample_count": self._callback_latency_sample_count,
            "last_subscribe_result": self._last_subscribe_result,
        }

    def _record_callback_latency(self, started_at: float) -> None:
        latency_ms = max(0.0, (self._monotonic() - started_at) * 1000)
        latency_ms = round(latency_ms, 3)
        self._callback_latency_ms_last = latency_ms
        self._callback_latency_ms_max = (
            latency_ms
            if self._callback_latency_ms_max is None
            else max(self._callback_latency_ms_max, latency_ms)
        )
        self._callback_latency_ms_sum += latency_ms
        self._callback_latency_sample_count += 1

    def unsubscribe_stream(self, key: SemanticStreamKey) -> None:
        self._validate_key(key)
        ret, data = self._ctx.unsubscribe([key.symbol], [self._ft.SubType.K_1M])
        if ret != self._ft.RET_OK:
            raise RuntimeError("OpenD K_1M unsubscribe rejected: " + str(data)[:300])

    def _emit_row(self, row: dict) -> None:
        symbol = str(row.get("code") or "").strip()
        raw_time = str(row.get("time_key") or "").strip() or None
        if not symbol.startswith("US."):
            self._emit_error("unexpected non-US K_1M symbol")
            return
        key = SemanticStreamKey(
            provider_id="futu",
            market="us",
            symbol=symbol,
            stream_type="K_1M",
            timeframe="1m",
        )
        # US time_key progress semantics are intentionally NOT promoted from
        # the older HK evidence set. Preserve the raw value as evidence only.
        payload = freeze_normalized_payload(
            {
                name: row.get(name)
                for name in ("code", "time_key", "open", "close", "high", "low", "volume", "turnover")
                if name in row
            }
        )
        self._emit(
            ProviderEvent(
                runtime_instance_id=self._runtime_instance_id,
                provider_id="futu",
                controller_generation=int(self._controller_generation()),
                observed_at_utc=self._now_utc(),
                observed_at_monotonic=self._monotonic(),
                event_kind=ProviderEventKind.DATA,
                semantic_stream_key=key,
                provider_context_id=self._context_id,
                payload=payload,
                provider_timestamp_raw=raw_time,
                delivery_mode=DeliveryMode.UNKNOWN,
                progress_identity_candidate=None,
                provenance="PUSH",
                diagnostic_fields=freeze_normalized_payload(
                    {"semantic_scope": "US_K1M_PUSH", "bar_state": "FORMING_OR_UNKNOWN", "bar_closure": "UNPROVEN", "same_time_key_may_update": True}
                ),
            )
        )

    def _emit_error(self, message: str) -> None:
        self._emit(
            ProviderEvent(
                runtime_instance_id=self._runtime_instance_id,
                provider_id="futu",
                controller_generation=int(self._controller_generation()),
                observed_at_utc=self._now_utc(),
                observed_at_monotonic=self._monotonic(),
                event_kind=ProviderEventKind.ERROR,
                provider_context_id=self._context_id,
                delivery_mode=DeliveryMode.UNKNOWN,
                provenance="PUSH",
                diagnostic_fields=freeze_normalized_payload({"error": message[:300]}),
            )
        )

    def _emit(self, event: ProviderEvent) -> None:
        if self._sink is not None and self._started:
            self._sink_emit_count += 1
            self._sink(event)
