"""Minimal additive schema migrations.

`Base.metadata.create_all` creates missing *tables* but never adds a column to a table that
already exists, so an installed database silently keeps the old shape and every query for a
new column fails. Until Alembic is introduced (recorded as a known gap in
docs/ARCHITECTURE.md), this closes that hole for the only kind of change made so far:
adding a nullable column.

Deliberate limits — this is not a migration framework and should not grow into one:

*   additive only: no drops, renames, type changes or data rewrites
*   nullable columns only, so existing rows stay valid without a backfill
*   idempotent: it inspects the live schema and does nothing when the column is present

Anything beyond that is Alembic's job. The moment a change needs a data migration or a
non-null default, stop extending this file and add Alembic.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

#: (table, column, SQL type, default literal or None)
#:
#: Types are written in a dialect-neutral subset that SQLite and Postgres both accept.
#: JSON is spelled TEXT on purpose: SQLite stores JSON as text anyway, and SQLAlchemy's
#: JSON type serialises through it, so TEXT works on both without a dialect branch.
ADDITIVE_COLUMNS: tuple[tuple[str, str, str, str | None], ...] = (
    ("sectors", "provider_symbols", "TEXT", None),
    ("sectors", "index_type", "VARCHAR(32)", None),
    ("sectors", "benchmark_allowed", "BOOLEAN", "0"),
    ("sectors", "sector_analysis_allowed", "BOOLEAN", "1"),
    ("benchmarks", "provider_symbols", "TEXT", None),
    ("benchmarks", "index_type", "VARCHAR(32)", None),
)


def apply_additive_migrations(engine: Engine) -> list[str]:
    """Add any missing nullable columns. Returns what was changed, for logging."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    applied: list[str] = []

    for table, column, sql_type, default in ADDITIVE_COLUMNS:
        if table not in existing_tables:
            # Fresh install: create_all will build the table complete from the models.
            continue

        columns = {c["name"] for c in inspector.get_columns(table)}
        if column in columns:
            continue

        clause = f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
        if default is not None:
            clause += f" DEFAULT {default}"

        with engine.begin() as connection:
            connection.execute(text(clause))
        applied.append(f"{table}.{column}")
        logger.info("migration: added %s.%s", table, column)

    return applied
