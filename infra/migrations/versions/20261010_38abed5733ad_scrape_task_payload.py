"""scrape task payload

Revision ID: 38abed5733ad
Revises: f393d06f58ab
Create Date: 2026-10-10 21:14:08.504738
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "38abed5733ad"
down_revision: str | None = "f393d06f58ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # FK на account добавляется после создания обеих таблиц (use_alter)
    op.create_foreign_key(
        "brand_shop_user_pk_fkey", "brand", "account", ["shop_user_pk"], ["user_pk"]
    )
    op.add_column(
        "scrape_task",
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("scrape_task", "payload")
    op.drop_constraint("brand_shop_user_pk_fkey", "brand", type_="foreignkey")
