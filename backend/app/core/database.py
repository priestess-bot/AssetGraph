from contextlib import contextmanager
from collections.abc import Iterator

from psycopg import Connection
from psycopg_pool import ConnectionPool

from app.core.config import settings

pool = ConnectionPool(conninfo=settings.postgres_dsn, open=False)


def open_pool() -> None:
    pool.open(wait=True)


def close_pool() -> None:
    pool.close()


def ensure_pool_open() -> None:
    if pool.closed:
        open_pool()


@contextmanager
def database_connection() -> Iterator[Connection]:
    ensure_pool_open()
    with pool.connection() as connection:
        yield connection


def get_db() -> Iterator[Connection]:
    with database_connection() as connection:
        yield connection
