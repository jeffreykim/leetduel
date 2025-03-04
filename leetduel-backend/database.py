from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL


engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
metadata = MetaData()