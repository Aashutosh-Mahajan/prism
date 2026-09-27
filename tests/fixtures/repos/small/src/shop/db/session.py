"""Database session management."""

import sqlalchemy

from shop.config import DATABASE_URL


def get_engine():
    return sqlalchemy.create_engine(DATABASE_URL)


def session_scope():
    engine = get_engine()
    return engine.connect()
