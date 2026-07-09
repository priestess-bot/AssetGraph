from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.core import database


class FakePool:
    def __init__(self) -> None:
        self.is_open = False
        self.open_calls = 0
        self.close_calls = 0
        self.connection_calls = 0

    @property
    def closed(self) -> bool:
        return not self.is_open

    def open(self, *, wait: bool = False) -> None:
        assert wait is True
        self.open_calls += 1
        self.is_open = True

    def close(self) -> None:
        self.close_calls += 1
        self.is_open = False

    @contextmanager
    def connection(self):
        self.connection_calls += 1
        if not self.is_open:
            raise RuntimeError("the pool is not open yet")
        yield "connection"


def test_get_db_opens_pool_before_yielding_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pool = FakePool()
    monkeypatch.setattr(database, "pool", fake_pool)

    generator = database.get_db()
    try:
        assert next(generator) == "connection"
    finally:
        with pytest.raises(StopIteration):
            next(generator)

    assert fake_pool.open_calls == 1
    assert fake_pool.connection_calls == 1


def test_get_db_reuses_already_open_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pool = FakePool()
    fake_pool.open(wait=True)
    monkeypatch.setattr(database, "pool", fake_pool)

    generator = database.get_db()
    try:
        assert next(generator) == "connection"
    finally:
        with pytest.raises(StopIteration):
            next(generator)

    assert fake_pool.open_calls == 1
    assert fake_pool.connection_calls == 1
