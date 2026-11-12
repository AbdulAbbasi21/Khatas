"""Owner's own ID for each contact (unique per business).

Existing contacts get an ID like P007 (from their number), which the owner can rename.

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("local_id", sa.String(length=30), nullable=True))
    op.add_column("contacts", sa.Column("local_key", sa.String(length=30), nullable=True))
    conn = op.get_bind()
    for (cid,) in conn.execute(sa.text("SELECT id FROM contacts")).all():
        lid = f"P{cid:03d}"
        conn.execute(sa.text("UPDATE contacts SET local_id = :l, local_key = :k WHERE id = :i"),
                     {"l": lid, "k": lid.lower(), "i": cid})
    with op.batch_alter_table("contacts") as batch:
        batch.create_unique_constraint("uq_contact_local_id", ["business_id", "local_key"])


def downgrade() -> None:
    with op.batch_alter_table("contacts") as batch:
        batch.drop_constraint("uq_contact_local_id", type_="unique")
    op.drop_column("contacts", "local_key")
    op.drop_column("contacts", "local_id")
