from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row

from .config import load


@contextmanager
def connect():
    s = load()
    with psycopg.connect(s.database_url, row_factory=dict_row) as conn:
        yield conn
