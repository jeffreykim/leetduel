import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=os.path.join(basedir, ".env.local"))

d = os.getenv("DATABASE_URL")
if not d:
    raise ValueError("DATABASE_URL environment variable is not set")

database_url = d

port = os.getenv("PORT") or 8000

code_execution_url = os.getenv("CODE_EXECUTION_URL") or ""