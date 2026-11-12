"""Alembic environment: migrates the tables of db.models in the DATABASE_URL database.

Synchronous on purpose (psycopg 3 does both), so it also runs from inside a test's event loop.
The same database holds LangGraph's checkpoint tables, which the checkpointer creates and owns:
`include_name` keeps autogenerate from proposing to drop them, and the healthy-span store's
(langchain_pg_*, created by langchain-postgres; see runs/healthy.py).
"""

import os
from collections.abc import MutableMapping
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import create_engine

from db.engine import sqlalchemy_url
from db.models import Base

config = context.config
# A caller that drives Alembic from code (the tests) passes no ini file, and keeps its logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: MutableMapping[Any, Any]) -> bool:
    return type_ != "table" or name in target_metadata.tables


def run_migrations() -> None:
    engine = create_engine(sqlalchemy_url(os.environ["DATABASE_URL"]))
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_name=include_name
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline mode is not set up: run against a database (DATABASE_URL)")
run_migrations()
