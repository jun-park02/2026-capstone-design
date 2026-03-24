from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class FireEvent(Base):
    """Fire event metadata."""

    __tablename__ = "fire_events"
    __table_args__ = (
        Index("ix_fire_events_received_at", "received_at"),
        Index("ix_fire_events_captured_at", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    redis_stream_id: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    received_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    lon: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    alt: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    src_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    src_port: Mapped[int | None] = mapped_column(INTEGER(unsigned=True), nullable=True)
    dst_port: Mapped[int | None] = mapped_column(INTEGER(unsigned=True), nullable=True)
    user_confirmation: Mapped[str | None] = mapped_column(String(1), nullable=True)
    user_confirmed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    user_confirmed_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
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

    images: Mapped[list["FireEventImage"]] = relationship(
        back_populates="fire_event",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    email_notifications: Mapped[list["FireEventEmailNotification"]] = relationship(
        back_populates="fire_event",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class FireEventImage(Base):
    """Image metadata stored for a fire event."""

    __tablename__ = "fire_event_images"
    __table_args__ = (
        UniqueConstraint("fire_event_id", "image_uid", name="uq_event_image"),
        UniqueConstraint("bucket", "object_key", name="uq_bucket_key"),
        Index("ix_fire_event_images_upload_status", "upload_status"),
        Index("ix_fire_event_images_uploaded_at", "uploaded_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    fire_event_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("fire_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_ext: Mapped[str | None] = mapped_column(String(16), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunk_total: Mapped[int | None] = mapped_column(INTEGER(unsigned=True), nullable=True)
    storage_provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'s3'"),
    )
    bucket: Mapped[str | None] = mapped_column(String(63), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    object_version_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    upload_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'pending'"),
    )
    upload_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
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

    fire_event: Mapped["FireEvent"] = relationship(back_populates="images")


class NotificationRecipient(Base):
    """Email recipient for fire confirmation requests."""

    __tablename__ = "notification_recipients"
    __table_args__ = (Index("ix_notification_recipients_is_active", "is_active"),)

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
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

    email_notifications: Mapped[list["FireEventEmailNotification"]] = relationship(
        back_populates="recipient",
    )


class FireEventEmailNotification(Base):
    """Email delivery and confirmation state per recipient."""

    __tablename__ = "fire_event_email_notifications"
    __table_args__ = (
        UniqueConstraint("fire_event_id", "recipient_email", name="uq_fire_event_recipient_email"),
        UniqueConstraint("confirm_token_hash", name="uq_confirm_token_hash"),
        Index("ix_fire_event_email_notifications_sent_status", "sent_status"),
        Index("ix_fire_event_email_notifications_decision", "decision"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    fire_event_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("fire_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("notification_recipients.id", ondelete="SET NULL"),
        nullable=True,
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    confirm_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sent_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'pending'"),
    )
    send_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(1), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
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

    fire_event: Mapped["FireEvent"] = relationship(back_populates="email_notifications")
    recipient: Mapped["NotificationRecipient | None"] = relationship(back_populates="email_notifications")
