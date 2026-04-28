from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Index, JSON, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DroneTelemetry(Base):
    """Persisted MAVLink telemetry received from Redis Streams."""

    __tablename__ = "drone_telemetry"
    __table_args__ = (
        UniqueConstraint("redis_stream_id", name="uq_drone_telemetry_redis_stream_id"),
        Index("ix_drone_telemetry_system_time", "system_id", "telemetry_at"),
        Index("ix_drone_telemetry_message_time", "message_type", "telemetry_at"),
        Index("ix_drone_telemetry_telemetry_at", "telemetry_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    redis_stream_id: Mapped[str] = mapped_column(String(32), nullable=False)
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    system_id: Mapped[int | None] = mapped_column(INTEGER(unsigned=True), nullable=True)
    component_id: Mapped[int | None] = mapped_column(INTEGER(unsigned=True), nullable=True)
    telemetry_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    lon: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    alt: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    relative_alt: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    heading: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    time_boot_ms: Mapped[int | None] = mapped_column(INTEGER(unsigned=True), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
