"""notified_events unique subscription dedup_key

Revision ID: 42ca2c03846a
Revises: a2b987c27d10
Create Date: 2026-10-27 12:11:13.765467

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "42ca2c03846a"
down_revision: Union[str, Sequence[str], None] = "a2b987c27d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Tiene una sola riga per (subscription_id, dedup_key) prima del vincolo.
    op.execute(
        "DELETE FROM notified_events WHERE id NOT IN "
        "(SELECT MIN(id) FROM notified_events GROUP BY subscription_id, dedup_key)"
    )
    with op.batch_alter_table("notified_events", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_notified_events_sub_key", ["subscription_id", "dedup_key"]
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("notified_events", schema=None) as batch_op:
        batch_op.drop_constraint("uq_notified_events_sub_key", type_="unique")
