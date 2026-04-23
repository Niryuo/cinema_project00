from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1f2a3b4c5d6'
down_revision = '44a64ff80c52'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('loyalty_card_number', sa.String(length=32), nullable=True))
    op.add_column('users', sa.Column('loyalty_points', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('cashback_balance', sa.Float(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('loyalty_status', sa.String(length=20), nullable=False, server_default='guest'))
    op.create_unique_constraint('uq_users_loyalty_card_number', 'users', ['loyalty_card_number'])


def downgrade():
    op.drop_constraint('uq_users_loyalty_card_number', 'users', type_='unique')
    op.drop_column('users', 'loyalty_status')
    op.drop_column('users', 'cashback_balance')
    op.drop_column('users', 'loyalty_points')
    op.drop_column('users', 'loyalty_card_number')