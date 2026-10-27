"""devices secret_hash

Revision ID: 83b48563f3aa
Revises: 42ca2c03846a
Create Date: 2026-10-27 12:14:12.366492

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '83b48563f3aa'
down_revision: Union[str, Sequence[str], None] = '42ca2c03846a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('secret_hash', sa.String(length=64), nullable=True))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_column('secret_hash')

