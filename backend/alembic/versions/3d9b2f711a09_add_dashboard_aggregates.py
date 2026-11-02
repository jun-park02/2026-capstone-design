"""add dashboard aggregates

Revision ID: 3d9b2f711a09
Revises: 8c9a4b7e2d31
Create Date: 2026-04-28 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "3d9b2f711a09"
down_revision: Union[str, Sequence[str], None] = "8c9a4b7e2d31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in _inspector().get_indexes(table_name))


def upgrade() -> None:
    if not _has_table("dashboard_aggregates"):
        op.create_table(
            "dashboard_aggregates",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
            sa.Column("aggregate_date", sa.Date(), nullable=False),
            sa.Column("metric_key", sa.String(length=100), nullable=False),
            sa.Column("metric_value", sa.Numeric(precision=18, scale=6), nullable=False),
            sa.Column("metric_unit", sa.String(length=32), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("extra", sa.JSON(), nullable=True),
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
            sa.UniqueConstraint("aggregate_date", "metric_key", name="uq_dashboard_aggregate_date_key"),
        )

    if not _has_index("dashboard_aggregates", "ix_dashboard_aggregates_date"):
        op.create_index(
            "ix_dashboard_aggregates_date",
            "dashboard_aggregates",
            ["aggregate_date"],
            unique=False,
        )
    if not _has_index("dashboard_aggregates", "ix_dashboard_aggregates_metric_key"):
        op.create_index(
            "ix_dashboard_aggregates_metric_key",
            "dashboard_aggregates",
            ["metric_key"],
            unique=False,
        )


def downgrade() -> None:
    if _has_table("dashboard_aggregates"):
        if _has_index("dashboard_aggregates", "ix_dashboard_aggregates_metric_key"):
            op.drop_index("ix_dashboard_aggregates_metric_key", table_name="dashboard_aggregates")
        if _has_index("dashboard_aggregates", "ix_dashboard_aggregates_date"):
            op.drop_index("ix_dashboard_aggregates_date", table_name="dashboard_aggregates")
        op.drop_table("dashboard_aggregates")
