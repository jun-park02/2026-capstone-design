"""
SQLAlchemy models package.

새 모델 파일을 이 패키지에 추가하고 이 파일에서 import 하면
Alembic autogenerate 시 metadata에 반영됩니다.
"""

from app.models.fire_event import FireEvent, FireEventImage

__all__ = ["FireEvent", "FireEventImage"]

