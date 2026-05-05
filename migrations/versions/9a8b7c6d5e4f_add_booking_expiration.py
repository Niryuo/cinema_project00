from alembic import op
import sqlalchemy as sa


revision = '9a8b7c6d5e4f'
down_revision = 'f1e2d3c4b5a6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bookings', sa.Column('expires_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('bookings', 'expires_at')