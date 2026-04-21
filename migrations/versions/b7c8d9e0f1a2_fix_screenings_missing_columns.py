"""fix screenings missing columns

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-04-15 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c8d9e0f1a2'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def _has_column(inspector, table_name, column_name):
    return any(column['name'] == column_name for column in inspector.get_columns(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'screenings' not in inspector.get_table_names():
        op.create_table(
            'screenings',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('movie_id', sa.Integer(), nullable=False),
            sa.Column('hall_name', sa.String(length=120), nullable=False),
            sa.Column('start_time', sa.DateTime(), nullable=False),
            sa.Column('hall_rows', sa.Integer(), nullable=False, server_default='5'),
            sa.Column('hall_cols', sa.Integer(), nullable=False, server_default='10'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['movie_id'], ['movies.id']),
            sa.PrimaryKeyConstraint('id'),
        )
    else:
        if not _has_column(inspector, 'screenings', 'hall_name'):
            op.add_column('screenings', sa.Column('hall_name', sa.String(length=120), nullable=True))
            op.execute("UPDATE screenings SET hall_name = 'Зал 1' WHERE hall_name IS NULL")
            op.alter_column('screenings', 'hall_name', nullable=False)

        if not _has_column(inspector, 'screenings', 'start_time'):
            op.add_column('screenings', sa.Column('start_time', sa.DateTime(), nullable=True))
            op.execute("UPDATE screenings SET start_time = now() WHERE start_time IS NULL")
            op.alter_column('screenings', 'start_time', nullable=False)

        if not _has_column(inspector, 'screenings', 'hall_rows'):
            op.add_column('screenings', sa.Column('hall_rows', sa.Integer(), nullable=True))
            op.execute("UPDATE screenings SET hall_rows = 5 WHERE hall_rows IS NULL")
            op.alter_column('screenings', 'hall_rows', nullable=False)

        if not _has_column(inspector, 'screenings', 'hall_cols'):
            op.add_column('screenings', sa.Column('hall_cols', sa.Integer(), nullable=True))
            op.execute("UPDATE screenings SET hall_cols = 10 WHERE hall_cols IS NULL")
            op.alter_column('screenings', 'hall_cols', nullable=False)

        if not _has_column(inspector, 'screenings', 'created_at'):
            op.add_column('screenings', sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True))


def downgrade():
    # Безопасный downgrade:для проверки удаляем только добавленные в этой ревизии поля, если таблица существует.
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'screenings' not in inspector.get_table_names():
        return

    for column in ['created_at', 'hall_cols', 'hall_rows', 'start_time', 'hall_name']:
        if _has_column(inspector, 'screenings', column):
            op.drop_column('screenings', column)