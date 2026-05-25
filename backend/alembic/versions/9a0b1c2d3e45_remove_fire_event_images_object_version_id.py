"""remove object_version_id from fire_event_images

Revision ID: 9a0b1c2d3e45
Revises: 2d3e4f5a6b70
Create Date: 2026-05-26 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9a0b1c2d3e45"
down_revision: Union[str, Sequence[str], None] = "2d3e4f5a6b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in sa.inspect(op.get_bind()).get_columns(table_name))


def upgrade() -> None:
    if _has_table("fire_event_images") and _has_column("fire_event_images", "object_version_id"):
        op.drop_column("fire_event_images", "object_version_id")


def downgrade() -> None:
    if _has_table("fire_event_images") and not _has_column("fire_event_images", "object_version_id"):
        op.add_column(
            "fire_event_images",
            sa.Column("object_version_id", sa.String(length=255), nullable=True),
        )
