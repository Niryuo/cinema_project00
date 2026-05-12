from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3c4d5e6f7a8b'
down_revision = '2a3b4c5d6e7f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'favorite_screenings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('screening_id', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['screening_id'], ['screenings.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'screening_id', name='uq_favorite_screenings_user_screening'),
    )


def downgrade():
    op.drop_table('favorite_screenings')

