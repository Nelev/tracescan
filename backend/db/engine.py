"""How the application's tables are reached: SQLAlchemy on psycopg 3, from DATABASE_URL."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def sqlalchemy_url(database_url: str) -> str:
    """DATABASE_URL as the checkpointer takes it (postgresql://...), for SQLAlchemy on psycopg 3."""
    scheme, _, rest = database_url.partition("://")
    return f"postgresql+psycopg://{rest}" if scheme in {"postgresql", "postgres"} else database_url


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(sqlalchemy_url(database_url))
