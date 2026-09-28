"""The platform migration creates every table the ORM declares, with tenant scoping."""

from sqlalchemy import inspect

from app.mo.db import AUTHORITY_TABLES, PLATFORM_TABLES


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


def test_authority_tables_exist_and_are_tenant_scoped(engine):
    insp = inspect(engine)
    assert set(AUTHORITY_TABLES) <= set(insp.get_table_names())
    for table in AUTHORITY_TABLES:
        cols = {c["name"] for c in insp.get_columns(table)}
        assert "tenant_id" in cols, table


def test_grant_store_holds_only_a_token_hash_and_receipts_are_idempotency_unique(engine):
    insp = inspect(engine)
    assert "token_hash" in {c["name"] for c in insp.get_columns("mo_capability_grants")}
    assert "token" not in {c["name"] for c in insp.get_columns("mo_capability_grants")}
    uniques = [set(u["column_names"]) for u in insp.get_unique_constraints("mo_receipts")]
    assert {"tenant_id", "idempotency_key"} in uniques
