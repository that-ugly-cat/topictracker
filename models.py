"""
Database models for TopicTracker.

ORM: SQLAlchemy with SQLite (./data/tt.db, persisted via Docker volume).

User model: email + password, is_admin flag (no complex permission tree needed).
Run model: tracks a single pipeline execution (search → analyse → viz → network).
  status: pending | downloading | done_download | analysing | done | error
  Steps are gated by status: Step 2 requires done_download, Step 3/4 require done.
"""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

DATABASE_URL = "sqlite:///./data/tt.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True)
    email         = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name          = Column(String)
    is_active     = Column(Boolean, default=True)
    is_admin      = Column(Boolean, default=False)
    created_at    = Column(DateTime, default=datetime.utcnow)

    runs = relationship("Run", back_populates="user")


class Run(Base):
    __tablename__ = "runs"
    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    title       = Column(String, nullable=False)
    query       = Column(String, nullable=False)
    year_from   = Column(Integer, nullable=False)
    year_to     = Column(Integer, nullable=False)
    status      = Column(String, default="pending")   # pending | downloading | done_download | analysing | done | error
    error_msg   = Column(Text, nullable=True)
    export_dir  = Column(String, nullable=True)       # relative path under export/
    paper_count = Column(Integer, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="runs")


def init_db():
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import text
    with engine.connect() as conn:
        for stmt in [
            "ALTER TABLE runs ADD COLUMN error_msg TEXT",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
