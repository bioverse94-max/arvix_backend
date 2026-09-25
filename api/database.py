import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sih_user:sih_password@localhost:5432/fraud_db")

# Fix for SQLAlchemy 1.4+ not accepting 'postgres://' prefix
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Supabase (Postgres) recommended settings
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,       # Check connection health before using
        pool_size=10,             # Keep a reasonable pool size
        max_overflow=20           # Allow temporary burst
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
