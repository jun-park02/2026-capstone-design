from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Index, JSON, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DroneTelemetry(Base):
    """Redis Stream에서 소비한 드론 텔레메트리를 MySQL에 저장하는 모델."""

    __tablename__ = "drone_telemetry"
    __table_args__ = (
        # 같은 Redis Stream 메시지가 중복 저장되지 않도록 막는다.
        UniqueConstraint("redis_stream_id", name="uq_drone_telemetry_redis_stream_id"),
        # 드론별 시간순 조회에 사용한다.
        Index("ix_drone_telemetry_system_time", "system_id", "telemetry_at"),
        # 메시지 타입별 시간순 조회에 사용한다.
        Index("ix_drone_telemetry_message_time", "message_type", "telemetry_at"),
        # 전체 텔레메트리 시간순 조회에 사용한다.
        Index("ix_drone_telemetry_telemetry_at", "telemetry_at"),
    )

    # 테이블 내부 기본 키
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    # Redis Stream 메시지 ID
    redis_stream_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # MAVLink 호환 메시지 타입
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # 드론 ID
    system_id: Mapped[int | None] = mapped_column(INTEGER(unsigned=True), nullable=True)
    # MAVLink 호환용 컴포넌트 ID
    component_id: Mapped[int | None] = mapped_column(INTEGER(unsigned=True), nullable=True)
    # 텔레메트리가 수신되거나 기록된 시각
    telemetry_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    # 위도
    lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    # 경도
    lon: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    # 고도
    alt: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # 기준 위치 대비 상대고도
    relative_alt: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # 기체 heading 값
    heading: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    # 드론 부팅 이후 경과 시간
    time_boot_ms: Mapped[int | None] = mapped_column(INTEGER(unsigned=True), nullable=True)
    # Redis payload 원본을 보존하는 JSON 필드
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # DB 레코드 생성 시각
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
