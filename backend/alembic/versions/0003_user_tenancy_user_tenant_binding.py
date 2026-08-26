"""bind existing users to a tenant

Adds the tenant boundary to the legacy `users` table and backfills every
existing row into a default tenant, so no account is left tenant-less when
Zero Trust starts enforcing tenant scope.

Revision ID: 0003_user_tenancy
Revises: 0002_mo_builder
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_user_tenancy"
down_revision = "0002_mo_builder"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "tnt-default"


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("mfa_secret", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("locked_until", sa.DateTime(), nullable=True))

    # Seed the default tenant, then backfill every pre-existing user into it.
    op.execute(
        sa.text(
            "INSERT INTO mo_tenants (id, slug, name, plan, is_active, safe_mode, created_at) "
            "VALUES (:id, 'default', 'Default Tenant', 'enterprise', 1, 0, CURRENT_TIMESTAMP)"
        ).bindparams(id=DEFAULT_TENANT_ID)
    )
    op.execute(
        sa.text("UPDATE users SET tenant_id = :tid WHERE tenant_id IS NULL").bindparams(tid=DEFAULT_TENANT_ID)
    )

    with op.batch_alter_table("users") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(length=64), nullable=False)
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_users_tenant_id", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("locked_until")
        batch.drop_column("failed_login_count")
        batch.drop_column("mfa_enabled")
        batch.drop_column("mfa_secret")
        batch.drop_column("tenant_id")
    op.execute(sa.text("DELETE FROM mo_tenants WHERE id = :id").bindparams(id=DEFAULT_TENANT_ID))
