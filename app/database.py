"""Database settings and transaction boundary for the Smart CRM API."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test"
)


@dataclass(frozen=True, repr=False)
class DatabaseSettings:
    database_url: str

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        return cls(
            database_url=os.getenv("SMART_CRM_DATABASE_URL", DEFAULT_DATABASE_URL)
        )

    def __repr__(self) -> str:
        return "DatabaseSettings(database_url='<redacted>')"


class Database:
    def __init__(
        self,
        settings: DatabaseSettings | None = None,
        *,
        engine: Engine | None = None,
    ) -> None:
        self.settings = settings or DatabaseSettings.from_env()
        self.engine = engine or create_engine(
            self.settings.database_url,
            pool_pre_ping=True,
        )
        self._session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=Session,
        )
        self._open_sessions = 0
        self._session_lock = Lock()

    @property
    def open_session_count(self) -> int:
        with self._session_lock:
            return self._open_sessions

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self._session_factory()
        with self._session_lock:
            self._open_sessions += 1
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            with self._session_lock:
                self._open_sessions -= 1

    def check_database(self) -> bool:
        try:
            with self.engine.connect() as connection:
                return connection.scalar(text("SELECT 1")) == 1
        except SQLAlchemyError:
            return False

    def dispose(self) -> None:
        self.engine.dispose()


database = Database()
