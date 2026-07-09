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


def get_db() -> Iterator[Connection]:
    ensure_pool_open()
    with pool.connection() as connection:
        yield connection
