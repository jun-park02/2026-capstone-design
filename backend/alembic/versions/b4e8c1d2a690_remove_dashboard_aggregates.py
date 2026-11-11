"""Remove the unused dashboard aggregates table.

Revision ID: b4e8c1d2a690
Revises: 1e2f3a4b5c60
Create Date: 2026-11-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "b4e8c1d2a690"
down_revision: Union[str, Sequence[str], None] = "1e2f3a4b5c60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("dashboard_aggregates")


def downgrade() -> None:
    """Restore the schema; deleted aggregate data cannot be recovered."""
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
    op.create_index("ix_dashboard_aggregates_date", "dashboard_aggregates", ["aggregate_date"], unique=False)
    op.create_index("ix_dashboard_aggregates_metric_key", "dashboard_aggregates", ["metric_key"], unique=False)
