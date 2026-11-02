from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class FireEvent(Base):
    """화재 감지 이벤트의 기본 메타데이터를 저장하는 모델."""

    __tablename__ = "fire_events"
    __table_args__ = (
        # 수신 시각 기준 이벤트 목록 조회에 사용
        Index("ix_fire_events_received_at", "received_at"),
        # 촬영 시각 기준 이벤트 검색에 사용
        Index("ix_fire_events_captured_at", "captured_at"),
    )

    # 테이블 내부 기본 키
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    # 외부 시스템에서 전달한 화재 이벤트 ID
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Redis fire_detect Stream 메시지 ID
    redis_stream_id: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    # 업로드 서버가 이벤트를 수신한 시각
    received_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    # 이미지가 실제 촬영된 시각
    captured_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    # 화재 감지 위치 위도
    lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    # 화재 감지 위치 경도
    lon: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    # 화재 감지 위치 고도
    alt: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    # AI 또는 감지 시스템이 계산한 화재 신뢰도
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    # 이미지를 업로드한 클라이언트 IP
    src_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    # 사용자의 화재 여부 확인 결과
    user_confirmation: Mapped[str | None] = mapped_column(String(1), nullable=True)
    # 사용자가 확인 결과를 남긴 시각
    user_confirmed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    # 확인 결과를 남긴 사용자 이메일
    user_confirmed_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Redis payload와 S3/DB 처리 결과를 보존하는 JSON 필드
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
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

    # 이 화재 이벤트에 연결된 이미지 메타데이터 목록
    images: Mapped[list["FireEventImage"]] = relationship(
        back_populates="fire_event",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    # 이 화재 이벤트에 대해 발송된 확인 메일 상태 목록
    email_notifications: Mapped[list["FireEventEmailNotification"]] = relationship(
        back_populates="fire_event",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class FireEventImage(Base):
    """화재 이벤트에 연결된 이미지 파일과 S3 저장 정보를 저장하는 모델."""

    __tablename__ = "fire_event_images"
    __table_args__ = (
        # 같은 이벤트 안에서 같은 이미지 ID가 중복 저장되지 않도록 막는다.
        UniqueConstraint("fire_event_id", "image_uid", name="uq_event_image"),
        # 같은 S3 객체가 중복 등록되지 않도록 막는다.
        UniqueConstraint("bucket", "object_key", name="uq_bucket_key"),
        # 업로드 상태별 조회에 사용한다.
        Index("ix_fire_event_images_upload_status", "upload_status"),
        # 업로드 완료 시각 기준 조회에 사용한다.
        Index("ix_fire_event_images_uploaded_at", "uploaded_at"),
    )

    # 테이블 내부 기본 키
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    # 부모 화재 이벤트 ID
    fire_event_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("fire_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 외부 시스템에서 전달한 이미지 ID
    image_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    # 저장에 사용하는 이미지 파일명
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # S3 업로드 전 공유 볼륨에 저장된 로컬 파일 경로
    source_local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # 이미지 파일 확장자
    file_ext: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 이미지 MIME 타입
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 이미지 파일 크기
    file_size_bytes: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    # S3 버킷 이름
    bucket: Mapped[str | None] = mapped_column(String(63), nullable=True)
    # S3 객체 키
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # S3 업로드 상태
    upload_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'pending'"),
    )
    # S3 업로드 실패 시 에러 메시지
    upload_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # S3 업로드 완료 시각
    uploaded_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
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

    # 이 이미지가 속한 부모 화재 이벤트
    fire_event: Mapped["FireEvent"] = relationship(back_populates="images")


class NotificationRecipient(Base):
    """화재 확인 메일을 받을 수신자 정보를 저장하는 모델."""

    __tablename__ = "notification_recipients"
    __table_args__ = (Index("ix_notification_recipients_is_active", "is_active"),)

    # 테이블 내부 기본 키
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    # 확인 메일을 받을 이메일 주소
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # 메일 발송 대상 포함 여부
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
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

    # 이 수신자에게 발송된 화재 확인 메일 상태 목록
    email_notifications: Mapped[list["FireEventEmailNotification"]] = relationship(
        back_populates="recipient",
    )


class FireEventEmailNotification(Base):
    """화재 이벤트별 확인 메일 발송 상태와 사용자 응답을 저장하는 모델."""

    __tablename__ = "fire_event_email_notifications"
    __table_args__ = (
        # 같은 이벤트에 같은 이메일로 중복 발송 레코드가 생기지 않도록 막는다.
        UniqueConstraint("fire_event_id", "recipient_email", name="uq_fire_event_recipient_email"),
        # 확인 링크 토큰 해시가 중복되지 않도록 막는다.
        UniqueConstraint("confirm_token_hash", name="uq_confirm_token_hash"),
        # 메일 발송 상태별 조회에 사용한다.
        Index("ix_fire_event_email_notifications_sent_status", "sent_status"),
        # 사용자 응답 결과별 조회에 사용한다.
        Index("ix_fire_event_email_notifications_decision", "decision"),
    )

    # 테이블 내부 기본 키
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    # 확인 메일이 연결된 화재 이벤트 ID
    fire_event_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("fire_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 등록된 수신자 ID
    recipient_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("notification_recipients.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 메일을 보낸 실제 수신자 주소
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    # 확인 링크 검증에 사용하는 토큰 해시
    confirm_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 메일 발송 상태
    sent_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'pending'"),
    )
    # 메일 발송 실패 시 에러 메시지
    send_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 메일 발송 완료 시각
    sent_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    # 사용자의 확인 응답
    decision: Mapped[str | None] = mapped_column(String(1), nullable=True)
    # 사용자가 확인 링크에 응답한 시각
    responded_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
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

    # 이 메일 상태가 연결된 화재 이벤트
    fire_event: Mapped["FireEvent"] = relationship(back_populates="email_notifications")
    # 이 메일 상태가 연결된 수신자
    recipient: Mapped["NotificationRecipient | None"] = relationship(back_populates="email_notifications")
