from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, Index, JSON, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DashboardAggregate(Base):
    """대시보드 API에서 사용할 일별 집계 값을 저장하는 모델."""

    __tablename__ = "dashboard_aggregates"
    __table_args__ = (
        # 같은 날짜에 같은 집계 지표가 중복 저장되지 않도록 막는다.
        UniqueConstraint("aggregate_date", "metric_key", name="uq_dashboard_aggregate_date_key"),
        # 날짜 기준 집계 조회에 사용한다.
        Index("ix_dashboard_aggregates_date", "aggregate_date"),
        # 지표 이름 기준 조회에 사용한다.
        Index("ix_dashboard_aggregates_metric_key", "metric_key"),
    )

    # 테이블 내부 기본 키
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    # 집계 기준 날짜
    aggregate_date: Mapped[date] = mapped_column(Date, nullable=False)
    # 집계 지표 이름
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # 집계 지표 값
    metric_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    # 지표 단위
    metric_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 지표 설명
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 추가 메타데이터를 저장하는 JSON 필드
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # DB 레코드 생성 시각
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    # DB 레코드 마지막 수정 시각
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
    )
