"""add screenings and bookings

Revision ID: a1b2c3d4e5f6
Revises: 2383336869db
Create Date: 2026-04-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '2383336869db'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'screenings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('movie_id', sa.Integer(), nullable=False),
        sa.Column('hall_name', sa.String(length=120), nullable=False),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('hall_rows', sa.Integer(), nullable=False),
        sa.Column('hall_cols', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['movie_id'], ['movies.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'bookings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('screening_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('seat_row', sa.Integer(), nullable=False),
        sa.Column('seat_col', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('cancel_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('canceled_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['screening_id'], ['screenings.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('bookings')
    op.drop_table('screenings')