"""rename_source_to_external_url

Revision ID: b78648b1429e
Revises: e810d23d4f25
Create Date: 2026-07-17 15:00:34.958697

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b78648b1429e'
down_revision: Union[str, Sequence[str], None] = 'e810d23d4f25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('external_url', sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column('documents', 'external_url')
