"""화재 감지 이벤트, 이미지 메타 데이터 테이블 생성

Revision ID: 4a372f37db2b
Revises: aab00f10d81f
Create Date: 2026-03-19 08:20:21.197897
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = '4a372f37db2b'
down_revision: Union[str, Sequence[str], None] = 'aab00f10d81f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table("fire_events"):
        op.create_table(
            'fire_events',
            sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
            sa.Column('event_id', sa.String(length=64), nullable=False),
            sa.Column('redis_stream_id', sa.String(length=32), nullable=True),
            sa.Column('received_at', mysql.DATETIME(fsp=6), nullable=False),
            sa.Column('captured_at', mysql.DATETIME(fsp=6), nullable=True),
            sa.Column('lat', sa.Numeric(precision=10, scale=7), nullable=True),
            sa.Column('lon', sa.Numeric(precision=10, scale=7), nullable=True),
            sa.Column('alt', sa.Numeric(precision=8, scale=2), nullable=True),
            sa.Column('confidence', sa.Numeric(precision=5, scale=4), nullable=True),
            sa.Column('src_ip', sa.String(length=45), nullable=True),
            sa.Column('src_port', mysql.INTEGER(unsigned=True), nullable=True),
            sa.Column('dst_port', mysql.INTEGER(unsigned=True), nullable=True),
            sa.Column('raw_payload', sa.JSON(), nullable=False),
            sa.Column('created_at', mysql.DATETIME(fsp=6), server_default=sa.text('CURRENT_TIMESTAMP(6)'), nullable=False),
            sa.Column('updated_at', mysql.DATETIME(fsp=6), server_default=sa.text('CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('event_id'),
            sa.UniqueConstraint('redis_stream_id')
        )

    if not _has_index("fire_events", "ix_fire_events_captured_at"):
        op.create_index('ix_fire_events_captured_at', 'fire_events', ['captured_at'], unique=False)
    if not _has_index("fire_events", "ix_fire_events_received_at"):
        op.create_index('ix_fire_events_received_at', 'fire_events', ['received_at'], unique=False)

    if not _has_table("fire_event_images"):
        op.create_table(
            'fire_event_images',
            sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
            sa.Column('fire_event_id', mysql.BIGINT(unsigned=True), nullable=False),
            sa.Column('image_uid', sa.String(length=64), nullable=False),
            sa.Column('original_filename', sa.String(length=255), nullable=False),
            sa.Column('source_local_path', sa.String(length=1024), nullable=True),
            sa.Column('file_ext', sa.String(length=16), nullable=True),
            sa.Column('content_type', sa.String(length=100), nullable=True),
            sa.Column('file_size_bytes', mysql.BIGINT(unsigned=True), nullable=True),
            sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
            sa.Column('chunk_total', mysql.INTEGER(unsigned=True), nullable=True),
            sa.Column('storage_provider', sa.String(length=20), server_default=sa.text("'s3'"), nullable=False),
            sa.Column('bucket', sa.String(length=63), nullable=True),
            sa.Column('object_key', sa.String(length=512), nullable=True),
            sa.Column('object_version_id', sa.String(length=255), nullable=True),
            sa.Column('etag', sa.String(length=255), nullable=True),
            sa.Column('upload_status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
            sa.Column('upload_error', sa.Text(), nullable=True),
            sa.Column('uploaded_at', mysql.DATETIME(fsp=6), nullable=True),
            sa.Column('created_at', mysql.DATETIME(fsp=6), server_default=sa.text('CURRENT_TIMESTAMP(6)'), nullable=False),
            sa.Column('updated_at', mysql.DATETIME(fsp=6), server_default=sa.text('CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)'), nullable=False),
            sa.ForeignKeyConstraint(['fire_event_id'], ['fire_events.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('bucket', 'object_key', name='uq_bucket_key'),
            sa.UniqueConstraint('fire_event_id', 'image_uid', name='uq_event_image')
        )

    if not _has_index("fire_event_images", "ix_fire_event_images_upload_status"):
        op.create_index('ix_fire_event_images_upload_status', 'fire_event_images', ['upload_status'], unique=False)
    if not _has_index("fire_event_images", "ix_fire_event_images_uploaded_at"):
        op.create_index('ix_fire_event_images_uploaded_at', 'fire_event_images', ['uploaded_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    if _has_table("fire_event_images"):
        if _has_index("fire_event_images", "ix_fire_event_images_uploaded_at"):
            op.drop_index('ix_fire_event_images_uploaded_at', table_name='fire_event_images')
        if _has_index("fire_event_images", "ix_fire_event_images_upload_status"):
            op.drop_index('ix_fire_event_images_upload_status', table_name='fire_event_images')
        op.drop_table('fire_event_images')

    if _has_table("fire_events"):
        if _has_index("fire_events", "ix_fire_events_received_at"):
            op.drop_index('ix_fire_events_received_at', table_name='fire_events')
        if _has_index("fire_events", "ix_fire_events_captured_at"):
            op.drop_index('ix_fire_events_captured_at', table_name='fire_events')
        op.drop_table('fire_events')
