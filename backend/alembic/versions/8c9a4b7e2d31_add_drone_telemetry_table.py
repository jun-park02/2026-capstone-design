"""add drone telemetry table

Revision ID: 8c9a4b7e2d31
Revises: 6f4b0fbc8a61
Create Date: 2026-04-28 11:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "8c9a4b7e2d31"
down_revision: Union[str, Sequence[str], None] = "6f4b0fbc8a61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in _inspector().get_indexes(table_name))


def upgrade() -> None:
    if not _has_table("drone_telemetry"):
        op.create_table(
            "drone_telemetry",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
            sa.Column("redis_stream_id", sa.String(length=32), nullable=False),
            sa.Column("message_type", sa.String(length=64), nullable=False),
            sa.Column("system_id", mysql.INTEGER(unsigned=True), nullable=True),
            sa.Column("component_id", mysql.INTEGER(unsigned=True), nullable=True),
            sa.Column("telemetry_at", mysql.DATETIME(fsp=6), nullable=False),
            sa.Column("lat", sa.Numeric(precision=10, scale=7), nullable=True),
            sa.Column("lon", sa.Numeric(precision=10, scale=7), nullable=True),
            sa.Column("alt", sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column("relative_alt", sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column("heading", sa.Numeric(precision=8, scale=2), nullable=True),
            sa.Column("time_boot_ms", mysql.INTEGER(unsigned=True), nullable=True),
            sa.Column("raw_payload", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=6),
                server_default=sa.text("CURRENT_TIMESTAMP(6)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("redis_stream_id", name="uq_drone_telemetry_redis_stream_id"),
        )

    if not _has_index("drone_telemetry", "ix_drone_telemetry_system_time"):
        op.create_index(
            "ix_drone_telemetry_system_time",
            "drone_telemetry",
            ["system_id", "telemetry_at"],
            unique=False,
        )
    if not _has_index("drone_telemetry", "ix_drone_telemetry_message_time"):
        op.create_index(
            "ix_drone_telemetry_message_time",
            "drone_telemetry",
            ["message_type", "telemetry_at"],
            unique=False,
        )
    if not _has_index("drone_telemetry", "ix_drone_telemetry_telemetry_at"):
        op.create_index(
            "ix_drone_telemetry_telemetry_at",
            "drone_telemetry",
            ["telemetry_at"],
            unique=False,
        )


def downgrade() -> None:
    if _has_table("drone_telemetry"):
        if _has_index("drone_telemetry", "ix_drone_telemetry_telemetry_at"):
            op.drop_index("ix_drone_telemetry_telemetry_at", table_name="drone_telemetry")
        if _has_index("drone_telemetry", "ix_drone_telemetry_message_time"):
            op.drop_index("ix_drone_telemetry_message_time", table_name="drone_telemetry")
        if _has_index("drone_telemetry", "ix_drone_telemetry_system_time"):
            op.drop_index("ix_drone_telemetry_system_time", table_name="drone_telemetry")
        op.drop_table("drone_telemetry")
