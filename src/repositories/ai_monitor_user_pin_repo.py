"""AI Monitor-owned durable USER_PINNED persistence.

The table is intentionally narrow and lazily self-ensured by this repository.
It does not store Radar candidate state, provider/runtime truth, Entry Permission,
or broker/execution state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError

from src.storage import Base, DatabaseManager


class AIMonitorUserPinRecord(Base):
    """One durable user-owned watch pin."""

    __tablename__ = "ai_monitor_user_pins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(String(64), nullable=False, index=True)
    market = Column(String(16), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    pinned_at = Column(DateTime, nullable=False, index=True)
    updated_at = Column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "market",
            "symbol",
            name="uix_ai_monitor_user_pin_owner_market_symbol",
        ),
    )


@dataclass(frozen=True)
class UserPin:
    owner_id: str
    market: str
    symbol: str
    pinned_at: datetime


def _owner(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("owner_id must not be empty")
    return normalized


def _market(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise ValueError("market must not be empty")
    return normalized


def _symbol(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        raise ValueError("symbol must not be empty")
    return normalized


def _utc_naive(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("pinned_at must be timezone-aware")
    return current.astimezone(timezone.utc).replace(tzinfo=None)


def _utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AIMonitorUserPinRepository:
    """Durable truth for explicit user pins only."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()
        self.ensure_schema()

    def ensure_schema(self) -> None:
        """Create only the AI Monitor user-pin table when absent."""

        with self.db.get_session() as session:
            AIMonitorUserPinRecord.__table__.create(session.get_bind(), checkfirst=True)

    def list_pins(self, *, owner_id: str) -> tuple[UserPin, ...]:
        owner = _owner(owner_id)
        with self.db.get_session() as session:
            rows = session.execute(
                select(AIMonitorUserPinRecord)
                .where(AIMonitorUserPinRecord.owner_id == owner)
                .order_by(
                    AIMonitorUserPinRecord.market.asc(),
                    AIMonitorUserPinRecord.symbol.asc(),
                )
            ).scalars().all()
            return tuple(self._to_pin(row) for row in rows)

    def pin(
        self,
        *,
        owner_id: str,
        market: str,
        symbol: str,
        pinned_at: datetime | None = None,
    ) -> UserPin:
        owner = _owner(owner_id)
        normalized_market = _market(market)
        normalized_symbol = _symbol(symbol)
        pinned_at_utc = _utc_naive(pinned_at)
        with self.db.get_session() as session:
            existing = self._find(
                session,
                owner_id=owner,
                market=normalized_market,
                symbol=normalized_symbol,
            )
            if existing is not None:
                return self._to_pin(existing)

            row = AIMonitorUserPinRecord(
                owner_id=owner,
                market=normalized_market,
                symbol=normalized_symbol,
                pinned_at=pinned_at_utc,
                updated_at=pinned_at_utc,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                # Concurrent identical pin: the unique key is authoritative.
                session.rollback()
                existing = self._find(
                    session,
                    owner_id=owner,
                    market=normalized_market,
                    symbol=normalized_symbol,
                )
                if existing is None:
                    raise
                return self._to_pin(existing)
            session.refresh(row)
            return self._to_pin(row)

    def unpin(self, *, owner_id: str, market: str, symbol: str) -> bool:
        owner = _owner(owner_id)
        normalized_market = _market(market)
        normalized_symbol = _symbol(symbol)
        with self.db.get_session() as session:
            row = self._find(
                session,
                owner_id=owner,
                market=normalized_market,
                symbol=normalized_symbol,
            )
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    @staticmethod
    def _find(session, *, owner_id: str, market: str, symbol: str):
        return session.execute(
            select(AIMonitorUserPinRecord)
            .where(
                AIMonitorUserPinRecord.owner_id == owner_id,
                AIMonitorUserPinRecord.market == market,
                AIMonitorUserPinRecord.symbol == symbol,
            )
            .limit(1)
        ).scalar_one_or_none()

    @staticmethod
    def _to_pin(row: AIMonitorUserPinRecord) -> UserPin:
        return UserPin(
            owner_id=str(row.owner_id),
            market=str(row.market),
            symbol=str(row.symbol),
            pinned_at=_utc_aware(row.pinned_at),
        )
