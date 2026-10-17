"""Append-only PIT persistence for normalized US options observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .futu_snapshot_adapter import FutuGexNormalization, FutuRowRejection
from .gex import OptionGexObservation, OptionType


SCHEMA = "us_options_pit.v0.1"
_SAFE_SYMBOL = re.compile(r"^[A-Z0-9._-]+$")


@dataclass(frozen=True)
class OptionsPitSnapshot:
    underlying_symbol: str
    collected_at: datetime
    spot: float
    spot_asof: datetime
    spot_source: str
    provider: str
    observations: tuple[OptionGexObservation, ...]
    source_total: int
    rejected: tuple[FutuRowRejection, ...]
    research_only: bool = True
    live_trade: bool = False

    def __post_init__(self) -> None:
        symbol = self.underlying_symbol.strip().upper()
        if not symbol or not _SAFE_SYMBOL.fullmatch(symbol):
            raise ValueError("underlying_symbol contains unsupported characters")
        for field_name, value in (
            ("collected_at", self.collected_at),
            ("spot_asof", self.spot_asof),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.spot <= 0:
            raise ValueError("spot must be positive")
        if not self.spot_source.strip():
            raise ValueError("spot_source is required")
        if not self.provider.strip():
            raise ValueError("provider is required")
        if self.source_total < len(self.observations):
            raise ValueError("source_total cannot be smaller than observations")
        if self.source_total < len(self.observations) + len(self.rejected):
            raise ValueError("source_total cannot be smaller than accepted + rejected")

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "underlying_symbol": self.underlying_symbol.strip().upper(),
            "collected_at": self.collected_at.isoformat(),
            "spot": self.spot,
            "spot_asof": self.spot_asof.isoformat(),
            "spot_source": self.spot_source,
            "provider": self.provider,
            "source_total": self.source_total,
            "observations": [_observation_payload(row) for row in self.observations],
            "rejected": [
                {
                    "index": item.index,
                    "contract_symbol": item.contract_symbol,
                    "reason": item.reason,
                }
                for item in self.rejected
            ],
            "research_only": self.research_only,
            "live_trade": self.live_trade,
        }


@dataclass(frozen=True)
class OptionsPitWriteResult:
    path: Path
    payload_sha256: str
    created: bool
    raw_bytes: int
    compressed_bytes: int


def build_futu_pit_snapshot(
    normalization: FutuGexNormalization,
    *,
    underlying_symbol: str,
    collected_at: datetime,
    spot: float,
    spot_asof: datetime,
    spot_source: str,
    provider: str = "futu_opend",
) -> OptionsPitSnapshot:
    return OptionsPitSnapshot(
        underlying_symbol=underlying_symbol,
        collected_at=collected_at,
        spot=spot,
        spot_asof=spot_asof,
        spot_source=spot_source,
        provider=provider,
        observations=normalization.observations,
        source_total=normalization.total_rows,
        rejected=normalization.rejected,
    )


def _observation_payload(row: OptionGexObservation) -> dict[str, object]:
    return {
        "contract_symbol": row.contract_symbol,
        "underlying_symbol": row.underlying_symbol,
        "option_type": row.option_type.value,
        "strike": row.strike,
        "expiration": row.expiration.isoformat(),
        "open_interest": row.open_interest,
        "gamma": row.gamma,
        "contract_multiplier": row.contract_multiplier,
        "source": row.source,
        "quote_asof": row.quote_asof.isoformat() if row.quote_asof else None,
        "oi_asof": row.oi_asof.isoformat() if row.oi_asof else None,
        "implied_volatility": row.implied_volatility,
    }


def _parse_aware(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _canonical_snapshot_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _snapshot_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_snapshot_bytes(payload)).hexdigest()


def _record_from_payload(payload: object) -> OptionsPitSnapshot:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("unsupported options PIT snapshot schema")
    observations_raw = payload.get("observations")
    rejected_raw = payload.get("rejected")
    if not isinstance(observations_raw, list) or not isinstance(rejected_raw, list):
        raise ValueError("options PIT snapshot arrays are invalid")

    observations: list[OptionGexObservation] = []
    for item in observations_raw:
        if not isinstance(item, dict):
            raise ValueError("options PIT observation must be an object")
        observations.append(
            OptionGexObservation(
                contract_symbol=str(item["contract_symbol"]),
                underlying_symbol=str(item["underlying_symbol"]),
                option_type=OptionType(str(item["option_type"])),
                strike=float(item["strike"]),
                expiration=date.fromisoformat(str(item["expiration"])),
                open_interest=int(item["open_interest"]),
                gamma=float(item["gamma"]),
                contract_multiplier=float(item["contract_multiplier"]),
                source=str(item["source"]),
                quote_asof=(
                    _parse_aware(item["quote_asof"], field="quote_asof")
                    if item.get("quote_asof") is not None
                    else None
                ),
                oi_asof=(
                    _parse_aware(item["oi_asof"], field="oi_asof")
                    if item.get("oi_asof") is not None
                    else None
                ),
                implied_volatility=(
                    float(item["implied_volatility"])
                    if item.get("implied_volatility") is not None
                    else None
                ),
            )
        )

    rejected: list[FutuRowRejection] = []
    for item in rejected_raw:
        if not isinstance(item, dict):
            raise ValueError("options PIT rejection must be an object")
        rejected.append(
            FutuRowRejection(
                index=int(item["index"]),
                contract_symbol=(
                    str(item["contract_symbol"])
                    if item.get("contract_symbol") is not None
                    else None
                ),
                reason=str(item["reason"]),
            )
        )

    if payload.get("research_only") is not True or payload.get("live_trade") is not False:
        raise ValueError("options PIT safety flags are invalid")

    return OptionsPitSnapshot(
        underlying_symbol=str(payload["underlying_symbol"]),
        collected_at=_parse_aware(payload["collected_at"], field="collected_at"),
        spot=float(payload["spot"]),
        spot_asof=_parse_aware(payload["spot_asof"], field="spot_asof"),
        spot_source=str(payload["spot_source"]),
        provider=str(payload["provider"]),
        observations=tuple(observations),
        source_total=int(payload["source_total"]),
        rejected=tuple(rejected),
    )


class OptionsPitStore:
    """Append-only gzip JSON store with content-addressed filenames."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def write(self, snapshot: OptionsPitSnapshot) -> OptionsPitWriteResult:
        payload = snapshot.to_payload()
        raw = _canonical_snapshot_bytes(payload)
        digest = hashlib.sha256(raw).hexdigest()
        collected_utc = snapshot.collected_at.astimezone(timezone.utc)
        symbol = snapshot.underlying_symbol.strip().upper()
        partition = self.root / symbol / collected_utc.date().isoformat()
        partition.mkdir(parents=True, exist_ok=True)
        stamp = collected_utc.strftime("%Y%m%dT%H%M%S%fZ")
        destination = partition / f"{stamp}-{digest[:16]}.json.gz"

        if destination.exists():
            existing = self.read(destination)
            if _snapshot_digest(existing.to_payload()) != digest:
                raise ValueError("existing PIT snapshot digest mismatch")
            return OptionsPitWriteResult(
                path=destination,
                payload_sha256=digest,
                created=False,
                raw_bytes=len(raw),
                compressed_bytes=destination.stat().st_size,
            )

        wrapper = {
            "payload_sha256": digest,
            "snapshot": payload,
        }
        fd, temporary_name = tempfile.mkstemp(
            prefix=".options-pit-",
            suffix=".tmp",
            dir=partition,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as handle:
                json.dump(
                    wrapper,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

        return OptionsPitWriteResult(
            path=destination,
            payload_sha256=digest,
            created=True,
            raw_bytes=len(raw),
            compressed_bytes=destination.stat().st_size,
        )

    @staticmethod
    def read(path: str | Path) -> OptionsPitSnapshot:
        source = Path(path)
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            wrapper = json.load(handle)
        if not isinstance(wrapper, dict):
            raise ValueError("options PIT wrapper must be an object")
        payload = wrapper.get("snapshot")
        if not isinstance(payload, dict):
            raise ValueError("options PIT wrapper snapshot is invalid")
        expected = str(wrapper.get("payload_sha256") or "")
        actual = _snapshot_digest(payload)
        if expected != actual:
            raise ValueError("options PIT snapshot SHA-256 mismatch")
        return _record_from_payload(payload)
