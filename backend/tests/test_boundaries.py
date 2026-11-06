"""The graph reaches traces only through the MCP server, never through the reader or the DB."""

import ast
from pathlib import Path

AGENT_DIR = Path(__file__).parent.parent / "agent"
ALLOWED_TRACE_STORE_MODULE = "trace_store.models"  # shared contracts, used for typing
DB_DRIVERS = {"psycopg", "psycopg2", "asyncpg", "sqlalchemy"}
# Postgres persistence is wired in the backend/main.py lifespan and handed to build_graph.
POSTGRES_PERSISTENCE = ("langgraph.checkpoint.postgres", "langgraph.store.postgres")


def imported_names(path: Path):
    """Yield every dotted name a file imports; `from a import b` yields `a.b`."""
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield from (f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def test_agent_package_only_imports_trace_store_models_and_no_db_drivers():
    for path in AGENT_DIR.rglob("*.py"):
        for name in imported_names(path):
            top = name.split(".")[0]
            if top == "trace_store":
                allowed = name == ALLOWED_TRACE_STORE_MODULE or name.startswith(
                    ALLOWED_TRACE_STORE_MODULE + "."
                )
                assert allowed, f"{path.name} imports {name}"
            assert top not in DB_DRIVERS, f"{path.name} imports {name}"
            assert not name.startswith(POSTGRES_PERSISTENCE), f"{path.name} imports {name}"
