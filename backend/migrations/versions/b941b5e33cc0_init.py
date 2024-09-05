"""init

Revision ID: b941b5e33cc0
Revises: 7e5b5dc7342b
Create Date: 2024-09-04 18:18:13.583430

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import apps.webui.internal.db
from migrations.util import get_existing_tables


# revision identifiers, used by Alembic.
revision: str = "b941b5e33cc0"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing_tables = set(get_existing_tables())

    # ### commands auto generated by Alembic - please adjust! ###
    if "auth" not in existing_tables:
        op.create_table(
            "auth",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("email", sa.String(), nullable=True),
            sa.Column("password", sa.Text(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if "chat" not in existing_tables:
        op.create_table(
            "chat",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("chat", sa.Text(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=True),
            sa.Column("updated_at", sa.BigInteger(), nullable=True),
            sa.Column("share_id", sa.Text(), nullable=True),
            sa.Column("archived", sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("share_id"),
        )

    if "user" not in existing_tables:
        op.create_table(
            "user",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("email", sa.String(), nullable=True),
            sa.Column("role", sa.String(), nullable=True),
            sa.Column("profile_image_url", sa.Text(), nullable=True),
            sa.Column("last_active_at", sa.BigInteger(), nullable=True),
            sa.Column("updated_at", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.BigInteger(), nullable=True),
            sa.Column("api_key", sa.String(), nullable=True),
            sa.Column("settings", apps.webui.internal.db.JSONField(), nullable=True),
            sa.Column("info", apps.webui.internal.db.JSONField(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("api_key"),
        )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("user")
    op.drop_table("chat")
    op.drop_table("auth")
    # ### end Alembic commands ###
