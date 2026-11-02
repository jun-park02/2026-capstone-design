"""remove src_port from fire_events

Revision ID: 7c2e8f9a1b34
Revises: 3d9b2f711a09
Create Date: 2026-05-26 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "7c2e8f9a1b34"
down_revision: Union[str, Sequence[str], None] = "3d9b2f711a09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in sa.inspect(op.get_bind()).get_columns(table_name))


def upgrade() -> None:
    if _has_table("fire_events") and _has_column("fire_events", "src_port"):
        op.drop_column("fire_events", "src_port")


def downgrade() -> None:
    if _has_table("fire_events") and not _has_column("fire_events", "src_port"):
        op.add_column(
            "fire_events",
            sa.Column("src_port", mysql.INTEGER(unsigned=True), nullable=True),
        )
