"""화재 감지 이벤트, 이미지 메타 데이터 테이블 생성

Revision ID: aab00f10d81f
Revises: ed9d83c50f81
Create Date: 2026-03-19 08:15:33.448882
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aab00f10d81f'
down_revision: Union[str, Sequence[str], None] = 'ed9d83c50f81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
