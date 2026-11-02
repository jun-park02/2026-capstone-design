"""remove checksum_sha256 from fire_event_images

Revision ID: 5f6e7a8b9c01
Revises: 0b7a6c5d9e12
Create Date: 2026-05-26 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5f6e7a8b9c01"
down_revision: Union[str, Sequence[str], None] = "0b7a6c5d9e12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in sa.inspect(op.get_bind()).get_columns(table_name))


def upgrade() -> None:
    if _has_table("fire_event_images") and _has_column("fire_event_images", "checksum_sha256"):
        op.drop_column("fire_event_images", "checksum_sha256")


def downgrade() -> None:
    if _has_table("fire_event_images") and not _has_column("fire_event_images", "checksum_sha256"):
        op.add_column(
            "fire_event_images",
            sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        )
