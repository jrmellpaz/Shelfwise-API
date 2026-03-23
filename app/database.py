"""
SQLAlchemy engine, session factory, and declarative Base.

Usage in route handlers:
    db: Session = Depends(get_db)
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Yield a DB session per request; auto-close when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
