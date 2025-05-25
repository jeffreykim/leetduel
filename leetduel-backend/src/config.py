import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=os.path.join(basedir, ".env.local"))

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise ValueError("DATABASE_URL environment variable is not set")

port = os.getenv("PORT") or 8000

code_execution_url = os.getenv("CODE_EXECUTION_URL") or ""

judge0 = os.getenv("JUDGE0_KEY") or ""