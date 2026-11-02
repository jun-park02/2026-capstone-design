"""add fire confirmation email flow

Revision ID: 6f4b0fbc8a61
Revises: 4a372f37db2b
Create Date: 2026-03-24 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "6f4b0fbc8a61"
down_revision: Union[str, Sequence[str], None] = "4a372f37db2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in _inspector().get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in _inspector().get_indexes(table_name))


def _has_unique_constraint(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint["name"] == constraint_name for constraint in _inspector().get_unique_constraints(table_name)
    )


def upgrade() -> None:
    if _has_table("fire_events"):
        if not _has_column("fire_events", "user_confirmation"):
            op.add_column("fire_events", sa.Column("user_confirmation", sa.String(length=1), nullable=True))
        if not _has_column("fire_events", "user_confirmed_at"):
            op.add_column(
                "fire_events",
                sa.Column("user_confirmed_at", mysql.DATETIME(fsp=6), nullable=True),
            )
        if not _has_column("fire_events", "user_confirmed_by_email"):
            op.add_column(
                "fire_events",
                sa.Column("user_confirmed_by_email", sa.String(length=255), nullable=True),
            )

    if not _has_table("notification_recipients"):
        op.create_table(
            "notification_recipients",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=6),
                server_default=sa.text("CURRENT_TIMESTAMP(6)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                mysql.DATETIME(fsp=6),
                server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )

    if _has_table("notification_recipients") and not _has_index(
        "notification_recipients", "ix_notification_recipients_is_active"
    ):
        op.create_index(
            "ix_notification_recipients_is_active",
            "notification_recipients",
            ["is_active"],
            unique=False,
        )

    if not _has_table("fire_event_email_notifications"):
        op.create_table(
            "fire_event_email_notifications",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
            sa.Column("fire_event_id", mysql.BIGINT(unsigned=True), nullable=False),
            sa.Column("recipient_id", mysql.BIGINT(unsigned=True), nullable=True),
            sa.Column("recipient_email", sa.String(length=255), nullable=False),
            sa.Column("confirm_token_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "sent_status",
                sa.String(length=20),
                server_default=sa.text("'pending'"),
                nullable=False,
            ),
            sa.Column("send_error", sa.Text(), nullable=True),
            sa.Column("sent_at", mysql.DATETIME(fsp=6), nullable=True),
            sa.Column("decision", sa.String(length=1), nullable=True),
            sa.Column("responded_at", mysql.DATETIME(fsp=6), nullable=True),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=6),
                server_default=sa.text("CURRENT_TIMESTAMP(6)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                mysql.DATETIME(fsp=6),
                server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["fire_event_id"], ["fire_events.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["recipient_id"], ["notification_recipients.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("confirm_token_hash", name="uq_confirm_token_hash"),
            sa.UniqueConstraint(
                "fire_event_id",
                "recipient_email",
                name="uq_fire_event_recipient_email",
            ),
        )

    if _has_table("fire_event_email_notifications") and not _has_index(
        "fire_event_email_notifications",
        "ix_fire_event_email_notifications_sent_status",
    ):
        op.create_index(
            "ix_fire_event_email_notifications_sent_status",
            "fire_event_email_notifications",
            ["sent_status"],
            unique=False,
        )

    if _has_table("fire_event_email_notifications") and not _has_index(
        "fire_event_email_notifications",
        "ix_fire_event_email_notifications_decision",
    ):
        op.create_index(
            "ix_fire_event_email_notifications_decision",
            "fire_event_email_notifications",
            ["decision"],
            unique=False,
        )


def downgrade() -> None:
    if _has_table("fire_event_email_notifications"):
        if _has_index("fire_event_email_notifications", "ix_fire_event_email_notifications_decision"):
            op.drop_index(
                "ix_fire_event_email_notifications_decision",
                table_name="fire_event_email_notifications",
            )
        if _has_index("fire_event_email_notifications", "ix_fire_event_email_notifications_sent_status"):
            op.drop_index(
                "ix_fire_event_email_notifications_sent_status",
                table_name="fire_event_email_notifications",
            )
        op.drop_table("fire_event_email_notifications")

    if _has_table("notification_recipients"):
        if _has_index("notification_recipients", "ix_notification_recipients_is_active"):
            op.drop_index("ix_notification_recipients_is_active", table_name="notification_recipients")
        op.drop_table("notification_recipients")

    if _has_table("fire_events"):
        if _has_column("fire_events", "user_confirmed_by_email"):
            op.drop_column("fire_events", "user_confirmed_by_email")
        if _has_column("fire_events", "user_confirmed_at"):
            op.drop_column("fire_events", "user_confirmed_at")
        if _has_column("fire_events", "user_confirmation"):
            op.drop_column("fire_events", "user_confirmation")
