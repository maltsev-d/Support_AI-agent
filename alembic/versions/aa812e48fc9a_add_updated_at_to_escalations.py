"""add_updated_at_to_escalations

Revision ID: aa812e48fc9a
Revises: 4c63d823cb56
Create Date: 2026-07-16 09:06:28.420448

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'aa812e48fc9a'
down_revision: Union[str, Sequence[str], None] = '4c63d823cb56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('escalations', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

def downgrade() -> None:
    op.drop_column('escalations', 'updated_at')

