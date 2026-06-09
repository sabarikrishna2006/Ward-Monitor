from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base
import os

# DB lives inside backend/data/ — works both locally and on server
_HERE = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = f"sqlite:///{os.path.join(_HERE, 'data', 'ward_careos.db')}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
