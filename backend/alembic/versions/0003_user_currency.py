"""Default currency chosen at sign-up.

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # existing users get USD; they can change it in Settings
    op.add_column("users", sa.Column("default_currency", sa.String(length=3), nullable=False,
                                     server_default="USD"))


def downgrade() -> None:
    op.drop_column("users", "default_currency")
