from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker
from src.config import database_url


engine = create_engine(database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
metadata = MetaData()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()