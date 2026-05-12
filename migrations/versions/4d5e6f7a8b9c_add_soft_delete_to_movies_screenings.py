from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4d5e6f7a8b9c'
down_revision = '3c4d5e6f7a8b'
branch_labels = None
depends_on = None


def _has_column(inspector, table_name, column_name):
    return any(column['name'] == column_name for column in inspector.get_columns(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table_name in ('movies', 'screenings'):
        if not _has_column(inspector, table_name, 'is_deleted'):
            op.add_column(
                table_name,
                sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
            )
        if not _has_column(inspector, table_name, 'deleted_at'):
            op.add_column(table_name, sa.Column('deleted_at', sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table_name in ('screenings', 'movies'):
        if _has_column(inspector, table_name, 'deleted_at'):
            op.drop_column(table_name, 'deleted_at')
        if _has_column(inspector, table_name, 'is_deleted'):
            op.drop_column(table_name, 'is_deleted')
