"""PayPal: verified sender (Log in with PayPal) and automatic payment checks.

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("paypal_user_id", sa.String(255), nullable=True))
        b.add_column(sa.Column("paypal_payer_id", sa.String(32), nullable=True))
        b.add_column(sa.Column("paypal_verified_email", sa.String(255), nullable=True))
        b.add_column(sa.Column("paypal_verified_name", sa.String(160), nullable=True))
        b.add_column(sa.Column("paypal_account_verified", sa.Boolean(), nullable=True))
        b.add_column(sa.Column("paypal_connected_at", TS, nullable=True))
        b.add_column(sa.Column("paypal_api_client_id", sa.String(255), nullable=True))
        b.add_column(sa.Column("paypal_api_secret_enc", sa.Text(), nullable=True))
        b.add_column(sa.Column("paypal_api_checked_at", TS, nullable=True))
        b.add_column(sa.Column("paypal_api_error", sa.Text(), nullable=True))
        b.create_unique_constraint("uq_users_paypal_user_id", ["paypal_user_id"])
    with op.batch_alter_table("payment_claims") as b:
        b.add_column(sa.Column("payer_paypal_email", sa.String(255), nullable=True))
        b.add_column(sa.Column("payer_paypal_id", sa.String(32), nullable=True))
        b.add_column(sa.Column("auto_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("payment_claims") as b:
        b.drop_column("auto_confirmed")
        b.drop_column("payer_paypal_id")
        b.drop_column("payer_paypal_email")
    with op.batch_alter_table("users") as b:
        b.drop_constraint("uq_users_paypal_user_id", type_="unique")
        for c in ("paypal_api_error", "paypal_api_checked_at", "paypal_api_secret_enc",
                  "paypal_api_client_id", "paypal_connected_at", "paypal_account_verified",
                  "paypal_verified_name", "paypal_verified_email", "paypal_payer_id", "paypal_user_id"):
            b.drop_column(c)
