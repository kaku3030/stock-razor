"""Read-only FREE-FIRST futures source boundary.

This module describes the four V0.1 instruments and adapts already downloaded
Yahoo Finance rows into the canonical ``ProviderEvent`` envelope.  It does
not claim realtime delivery, discover entitlement, or silently turn a vendor
continuous symbol into a research-grade continuous series.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from .live_feed_types import DeliveryMode, ProviderEvent, SemanticStreamKey
from .provider_normalization import _data_event


@dataclass(frozen=True)
class FuturesInstrumentSpec:
    root: str
    exchange: str
    vendor_continuous_symbol: str
    exchange_timezone: str
    supported_timeframes: tuple[str, ...] = ("1m", "5m", "15m", "1h", "1d")
    volume_semantics: str = "contracts"


FUTURES_INSTRUMENTS: dict[str, FuturesInstrumentSpec] = {
    "GC": FuturesInstrumentSpec("GC", "COMEX", "GC=F", "America/New_York"),
    "CL": FuturesInstrumentSpec("CL", "NYMEX", "CL=F", "America/New_York"),
    "SI": FuturesInstrumentSpec("SI", "COMEX", "SI=F", "America/New_York"),
    "HG": FuturesInstrumentSpec("HG", "COMEX", "HG=F", "America/New_York"),
}


@dataclass(frozen=True)
class ActualContinuousMapping:
    """An explicit, dated mapping; no mapping is inferred from a vendor symbol."""

    root: str
    session_date: str
    actual_contract: str
    continuous_name: str
    source: str
    evidence: str

    def __post_init__(self) -> None:
        root = self.root.upper()
        if root not in FUTURES_INSTRUMENTS:
            raise ValueError("unsupported futures root")
        if not self.actual_contract.strip() or not self.continuous_name.strip():
            raise ValueError("actual contract and continuous name are required")
        if not self.source.strip() or not self.evidence.strip():
            raise ValueError("mapping source and evidence are required")
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class RollObservation:
    """Inputs required before STOCK RAZOR may accept a contract roll."""

    current_contract: str
    next_contract: str
    current_volume: float | None
    next_volume: float | None
    current_open_interest: float | None
    next_open_interest: float | None
    consecutive_sessions: int
    contract_metadata_verified: bool


def should_roll(observation: RollObservation) -> bool:
    """Apply the conservative STOCK RAZOR roll rule.

    A roll is accepted only at a completed session boundary after explicit
    contract metadata is verified and the next contract leads both volume and
    open interest for two consecutive sessions.  Missing evidence means no
    roll; no price stitching or vendor-continuous inference is performed.
    """

    values = (
        observation.current_volume,
        observation.next_volume,
        observation.current_open_interest,
        observation.next_open_interest,
    )
    if not observation.contract_metadata_verified or observation.consecutive_sessions < 2:
        return False
    if not observation.current_contract or not observation.next_contract:
        return False
    if any(value is None or not math.isfinite(float(value)) or float(value) < 0 for value in values):
        return False
    return (
        float(observation.next_volume) > float(observation.current_volume)
        and float(observation.next_open_interest) > float(observation.current_open_interest)
    )


def _normalise_timeframe(timeframe: str) -> str:
    value = timeframe.strip().lower()
    aliases = {"1h": "1h", "60m": "1h", "d1": "1d", "day": "1d"}
    return aliases.get(value, value)


class YahooFuturesProviderBinding:
    """Normalize Yahoo futures rows without promoting their delivery mode."""

    provider_id = "yahoo_finance"

    def __init__(
        self,
        *,
        runtime_instance_id: str,
        controller_generation: int,
        sink: Callable[[ProviderEvent], None] | None = None,
    ) -> None:
        self.runtime_instance_id = runtime_instance_id
        self.controller_generation = controller_generation
        self._sink = sink

    def register_event_sink(self, sink: Callable[[ProviderEvent], None]) -> None:
        if not callable(sink):
            raise TypeError("event sink must be callable")
        self._sink = sink

    def emit_rows(
        self,
        rows: list[Mapping[str, Any]],
        *,
        key: SemanticStreamKey,
        observed_at_utc: datetime,
        observed_at_monotonic: float = 0.0,
    ) -> list[ProviderEvent]:
        if key.provider_id != self.provider_id or key.market.upper() != "US_FUTURES":
            raise ValueError("Yahoo futures binding received an invalid stream key")
        root = key.symbol.upper()
        spec = FUTURES_INSTRUMENTS.get(root)
        if spec is None:
            raise ValueError("unsupported futures root")
        timeframe = _normalise_timeframe(key.timeframe or "")
        if timeframe not in spec.supported_timeframes:
            raise ValueError("unsupported futures timeframe")
        feed = (key.feed or "").lower()
        if feed not in {"vendor_continuous", "actual_contract"}:
            raise ValueError("futures feed must identify contract semantics")

        events: list[ProviderEvent] = []
        for raw_input in rows:
            raw = dict(raw_input)
            timestamp = raw.get("provider_timestamp")
            if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
                raise ValueError("futures provider timestamp must be timezone-aware")
            timestamp = timestamp.astimezone(timezone.utc)
            if timestamp > observed_at_utc.astimezone(timezone.utc):
                raise ValueError("provider timestamp cannot be in the future")
            for field in ("open", "high", "low", "close"):
                value = raw.get(field)
                if value is None or not math.isfinite(float(value)):
                    raise ValueError(f"invalid futures {field}")
            volume = raw.get("volume")
            if volume is None or not math.isfinite(float(volume)) or float(volume) < 0:
                raise ValueError("invalid futures volume")

            raw.update(
                {
                    "provider_timestamp": timestamp,
                    "instrument_root": root,
                    "exchange": spec.exchange,
                    "volume_semantics": spec.volume_semantics,
                    "delivery_mode": DeliveryMode.UNKNOWN.value,
                    "entitlement": "UNKNOWN",
                    "continuous_semantics": (
                        "vendor_continuous_candidate"
                        if feed == "vendor_continuous"
                        else "explicit_actual_contract"
                    ),
                }
            )
            if feed == "actual_contract" and not raw.get("contract_symbol"):
                raise ValueError("actual futures rows require contract_symbol")
            event = _data_event(
                provider_id=self.provider_id,
                raw=raw,
                runtime_instance_id=self.runtime_instance_id,
                controller_generation=self.controller_generation,
                observed_at_utc=observed_at_utc,
                semantic_stream_key=key,
                provider_timestamp=timestamp,
            )
            event = replace(event, observed_at_monotonic=observed_at_monotonic)
            events.append(event)
            if self._sink is not None:
                self._sink(event)
        return events


class YahooFuturesHistoryProvider:
    """Small injectable read-only wrapper around ``yfinance.download``."""

    def __init__(
        self,
        *,
        runtime_instance_id: str,
        controller_generation: int,
        download: Callable[..., Any] | None = None,
        sink: Callable[[ProviderEvent], None] | None = None,
    ) -> None:
        self._download = download
        self._binding = YahooFuturesProviderBinding(
            runtime_instance_id=runtime_instance_id,
            controller_generation=controller_generation,
            sink=sink,
        )
    def fetch(
        self,
        root: str,
        timeframe: str,
        *,
        observed_at_utc: datetime,
        start: str | None = None,
        end: str | None = None,
        actual_contract: str | None = None,
        contract_month: str | None = None,
    ) -> list[ProviderEvent]:
        root = root.upper()
        spec = FUTURES_INSTRUMENTS.get(root)
        if spec is None:
            raise ValueError("unsupported futures root")
        normalised = _normalise_timeframe(timeframe)
        if normalised not in spec.supported_timeframes:
            raise ValueError("unsupported futures timeframe")
        if actual_contract and not contract_month:
            raise ValueError("contract_month is required for an actual contract")
        feed = "actual_contract" if actual_contract else "vendor_continuous"
        ticker = actual_contract or spec.vendor_continuous_symbol
        download = self._download
        if download is None:
            import yfinance as yf

            download = yf.download
        frame = download(
            tickers=ticker,
            start=start,
            end=end,
            interval=normalised,
            progress=False,
            auto_adjust=False,
            multi_level_index=False,
        )
        if frame is None or getattr(frame, "empty", True):
            raise ValueError("Yahoo futures returned no rows")
        rows: list[dict[str, Any]] = []
        for index, row in frame.iterrows():
            timestamp = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
            if not isinstance(timestamp, datetime):
                raise TypeError("Yahoo futures index must be datetime-like")
            if timestamp.tzinfo is None:
                raise ValueError("Yahoo futures timestamp timezone is unknown")
            record = {str(name).lower(): value for name, value in row.to_dict().items()}
            record["provider_timestamp"] = timestamp
            record["vendor_symbol"] = ticker
            if actual_contract:
                record["contract_symbol"] = actual_contract
                record["contract_month"] = contract_month
            rows.append(record)
        key = SemanticStreamKey(
            self._binding.provider_id,
            "US_FUTURES",
            root,
            "KLINE",
            timeframe=normalised,
            feed=feed,
        )
        return self._binding.emit_rows(
            rows,
            key=key,
            observed_at_utc=observed_at_utc,
        )
