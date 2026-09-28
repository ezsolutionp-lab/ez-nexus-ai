"""The platform migration creates every table the ORM declares, with tenant scoping."""

from sqlalchemy import inspect

from app.mo.db import PLATFORM_TABLES


def test_platform_tables_exist_after_migration(engine):
    existing = set(inspect(engine).get_table_names())
    assert set(PLATFORM_TABLES) <= existing


def test_platform_tables_are_tenant_scoped(engine):
    insp = inspect(engine)
    for table in PLATFORM_TABLES:
        cols = {c["name"] for c in insp.get_columns(table)}
        assert "tenant_id" in cols, f"{table} has no tenant_id"
        assert any("tenant_id" in ix["column_names"] for ix in insp.get_indexes(table)), \
            f"{table} has no index covering tenant_id"
