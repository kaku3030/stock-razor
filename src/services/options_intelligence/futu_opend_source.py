"""Read-only Futu/OpenD source for US options-intelligence collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Mapping, Protocol
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


class QuoteContextLike(Protocol):
    def get_market_snapshot(self, codes: list[str]): ...
    def get_option_chain(self, code: str, *, start: str, end: str): ...
    def close(self) -> object: ...


@dataclass(frozen=True)
class FutuOptionsFetch:
    symbol: str
    underlying_row: Mapping[str, object]
    option_rows: tuple[Mapping[str, object], ...]
    chain_contracts: int
    snapshot_contracts: int


class FutuOpenDOptionsSource:
    """Fetch option-chain rows only; no trading context is created."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 11111,
        chain_days: int = 7,
        snapshot_batch_size: int = 200,
        quote_context_factory: Callable[..., QuoteContextLike] | None = None,
    ) -> None:
        if not str(host).strip():
            raise ValueError("host is required")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if not isinstance(chain_days, int) or isinstance(chain_days, bool) or not 0 <= chain_days <= 45:
            raise ValueError("chain_days must be between 0 and 45")
        if (
            not isinstance(snapshot_batch_size, int)
            or isinstance(snapshot_batch_size, bool)
            or not 1 <= snapshot_batch_size <= 200
        ):
            raise ValueError("snapshot_batch_size must be between 1 and 200")

        self.host = str(host).strip()
        self.port = port
        self.chain_days = chain_days
        self.snapshot_batch_size = snapshot_batch_size
        self._factory = quote_context_factory
        self._ctx: QuoteContextLike | None = None

    def __enter__(self) -> "FutuOpenDOptionsSource":
        if self._ctx is not None:
            raise RuntimeError("FutuOpenDOptionsSource is already open")
        factory = self._factory
        if factory is None:
            from futu import OpenQuoteContext
            factory = OpenQuoteContext
        self._ctx = factory(host=self.host, port=self.port)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


    def close(self) -> None:
        context = self._ctx
        self._ctx = None
        if context is not None:
            context.close()

    @staticmethod
    def _canonical_symbol(symbol: str) -> str:
        value = str(symbol or "").strip().upper()
        if not value:
            raise ValueError("symbol is required")
        return value if value.startswith("US.") else f"US.{value}"

    @staticmethod
    def _records(frame: object, *, operation: str) -> list[Mapping[str, object]]:
        if not hasattr(frame, "to_dict"):
            raise RuntimeError(f"{operation} did not return a tabular result")
        rows = frame.to_dict("records")
        if not isinstance(rows, list):
            raise RuntimeError(f"{operation} rows are invalid")
        return rows

    @staticmethod
    def _require_ok(result: object, payload: object, *, operation: str) -> None:
        try:
            code = int(result)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{operation} returned an invalid status") from exc
        if code != 0:
            raise RuntimeError(f"{operation} failed: {payload}")

    def _context(self) -> QuoteContextLike:
        if self._ctx is None:
            raise RuntimeError("FutuOpenDOptionsSource must be opened first")
        return self._ctx


    def fetch(
        self,
        symbol: str,
        *,
        evaluated_at: datetime,
    ) -> FutuOptionsFetch:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")

        canonical = self._canonical_symbol(symbol)
        context = self._context()

        ret, underlying = context.get_market_snapshot([canonical])
        self._require_ok(ret, underlying, operation="get_market_snapshot(underlying)")
        underlying_rows = self._records(
            underlying,
            operation="get_market_snapshot(underlying)",
        )
        if len(underlying_rows) != 1:
            raise RuntimeError("underlying snapshot must contain exactly one row")

        local_date = evaluated_at.astimezone(ET).date()
        end_date = local_date + timedelta(days=self.chain_days)
        ret, chain = context.get_option_chain(
            canonical,
            start=local_date.isoformat(),
            end=end_date.isoformat(),
        )
        self._require_ok(ret, chain, operation="get_option_chain")
        chain_rows = self._records(chain, operation="get_option_chain")
        codes = [
            str(row.get("code") or "").strip()
            for row in chain_rows
            if str(row.get("code") or "").strip()
        ]
        if not codes:
            raise RuntimeError("option chain returned no contract codes")

        option_rows: list[Mapping[str, object]] = []
        for offset in range(0, len(codes), self.snapshot_batch_size):
            batch = codes[offset : offset + self.snapshot_batch_size]
            ret, snapshot = context.get_market_snapshot(batch)
            self._require_ok(ret, snapshot, operation="get_market_snapshot(options)")
            option_rows.extend(
                self._records(snapshot, operation="get_market_snapshot(options)")
            )

        return FutuOptionsFetch(
            symbol=canonical,
            underlying_row=underlying_rows[0],
            option_rows=tuple(option_rows),
            chain_contracts=len(codes),
            snapshot_contracts=len(option_rows),
        )
