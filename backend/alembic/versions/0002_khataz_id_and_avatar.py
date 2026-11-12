"""Khataz ID and profile picture for users; invites by Khataz ID.

Existing users get a Khataz ID made from their email (e.g. abdul@example.com -> abdul,
or abdul2 if taken). New users choose theirs at sign-up.

Revision ID: 0002
Revises: 0001
"""
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base(email: str) -> str:
    local = re.sub(r"[^a-z0-9_.]", "", email.split("@")[0].lower()).strip(".")
    local = re.sub(r"\.{2,}", ".", local)
    if not local or not local[0].isalpha():
        local = "user" + local
    return local[:16].rstrip(".").ljust(3, "0")


def upgrade() -> None:
    op.add_column("users", sa.Column("khataz_id", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("avatar_path", sa.String(length=255), nullable=True))

    conn = op.get_bind()
    taken: set[str] = set()
    for uid, email in conn.execute(sa.text("SELECT id, email FROM users ORDER BY id")).all():
        base, n = _base(email), 1
        candidate = base
        while candidate in taken:
            n += 1
            candidate = f"{base[:20 - len(str(n))]}{n}"
        taken.add(candidate)
        conn.execute(sa.text("UPDATE users SET khataz_id = :k WHERE id = :i"), {"k": candidate, "i": uid})

    with op.batch_alter_table("users") as batch:
        batch.alter_column("khataz_id", existing_type=sa.String(length=20), nullable=False)
    op.create_index(op.f("ix_users_khataz_id"), "users", ["khataz_id"], unique=True)

    op.add_column("link_invites", sa.Column("invited_user_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_link_invites_invited_user_id"), "link_invites", ["invited_user_id"])
    with op.batch_alter_table("link_invites") as batch:
        batch.create_foreign_key("fk_link_invites_invited_user_id_users", "users",
                                 ["invited_user_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("link_invites") as batch:
        batch.drop_constraint("fk_link_invites_invited_user_id_users", type_="foreignkey")
    op.drop_index(op.f("ix_link_invites_invited_user_id"), table_name="link_invites")
    op.drop_column("link_invites", "invited_user_id")
    op.drop_index(op.f("ix_users_khataz_id"), table_name="users")
    op.drop_column("users", "avatar_path")
    op.drop_column("users", "khataz_id")
