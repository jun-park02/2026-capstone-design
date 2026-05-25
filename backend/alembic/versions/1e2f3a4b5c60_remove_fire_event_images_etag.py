"""remove etag from fire_event_images

Revision ID: 1e2f3a4b5c60
Revises: 9a0b1c2d3e45
Create Date: 2026-05-26 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1e2f3a4b5c60"
down_revision: Union[str, Sequence[str], None] = "9a0b1c2d3e45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in sa.inspect(op.get_bind()).get_columns(table_name))


def upgrade() -> None:
    if _has_table("fire_event_images") and _has_column("fire_event_images", "etag"):
        op.drop_column("fire_event_images", "etag")


def downgrade() -> None:
    if _has_table("fire_event_images") and not _has_column("fire_event_images", "etag"):
        op.add_column(
            "fire_event_images",
            sa.Column("etag", sa.String(length=255), nullable=True),
        )
