"""화재 감지 이벤트, 이미지 메타 데이터 테이블 생성

Revision ID: ed9d83c50f81
Revises: 
Create Date: 2026-03-19 08:14:35.047597
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed9d83c50f81'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
