"""add worlds

Revision ID: 72d7f061a69c
Revises:
Create Date: 2026-10-28 19:52:51.195889

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "72d7f061a69c"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "worlds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("generator_version", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("spec_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seed", "generator_version", "spec_hash"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("worlds")
