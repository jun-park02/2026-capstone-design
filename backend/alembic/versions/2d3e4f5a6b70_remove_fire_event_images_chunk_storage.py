"""remove chunk_total and storage_provider from fire_event_images

Revision ID: 2d3e4f5a6b70
Revises: 5f6e7a8b9c01
Create Date: 2026-05-26 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "2d3e4f5a6b70"
down_revision: Union[str, Sequence[str], None] = "5f6e7a8b9c01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in sa.inspect(op.get_bind()).get_columns(table_name))


def upgrade() -> None:
    if not _has_table("fire_event_images"):
        return

    if _has_column("fire_event_images", "chunk_total"):
        op.drop_column("fire_event_images", "chunk_total")
    if _has_column("fire_event_images", "storage_provider"):
        op.drop_column("fire_event_images", "storage_provider")


def downgrade() -> None:
    if not _has_table("fire_event_images"):
        return

    if not _has_column("fire_event_images", "storage_provider"):
        op.add_column(
            "fire_event_images",
            sa.Column(
                "storage_provider",
                sa.String(length=20),
                server_default=sa.text("'s3'"),
                nullable=False,
            ),
        )
    if not _has_column("fire_event_images", "chunk_total"):
        op.add_column(
            "fire_event_images",
            sa.Column("chunk_total", mysql.INTEGER(unsigned=True), nullable=True),
        )
