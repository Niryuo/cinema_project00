from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9d1e2f3a4b5'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def _has_column(inspector, table_name, column_name):
    return any(column['name'] == column_name for column in inspector.get_columns(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'movies' in inspector.get_table_names() and not _has_column(inspector, 'movies', 'poster_path'):
        op.add_column('movies', sa.Column('poster_path', sa.String(length=255), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'movies' in inspector.get_table_names() and _has_column(inspector, 'movies', 'poster_path'):
        op.drop_column('movies', 'poster_path')
