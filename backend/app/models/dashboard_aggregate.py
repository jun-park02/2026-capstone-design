from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, Index, JSON, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DashboardAggregate(Base):
    """Daily aggregate metric for dashboard APIs."""

    __tablename__ = "dashboard_aggregates"
    __table_args__ = (
        UniqueConstraint("aggregate_date", "metric_key", name="uq_dashboard_aggregate_date_key"),
        Index("ix_dashboard_aggregates_date", "aggregate_date"),
        Index("ix_dashboard_aggregates_metric_key", "metric_key"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    aggregate_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    metric_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
    )
