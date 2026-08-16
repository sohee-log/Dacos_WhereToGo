import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL이 .env에 없습니다.")

    return psycopg.connect(database_url)
