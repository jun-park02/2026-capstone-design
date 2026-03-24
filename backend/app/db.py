import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def get_database_url() -> str:
    user = os.getenv("MYSQL_USER", "user")
    password = os.getenv("MYSQL_PASSWORD", "password")
    # 기본값은 "호스트에서 Alembic/스크립트를 실행"하는 경우를 기준으로 둔다.
    # Docker Compose 안의 backend 컨테이너에서는 환경변수로 mysql:3306 이 주입된다.
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = os.getenv("MYSQL_PORT", "23306")
    db = os.getenv("MYSQL_DATABASE", "mydb")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}"


DATABASE_URL = os.getenv("DATABASE_URL", get_database_url())

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
